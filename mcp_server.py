"""MCP server exposing Xiaomi-OCR-0 as local tools for agent use.

Design goals (agent-first):
  * The text it returns is what lands in the model's context, so results are
    compact by default (`detail="brief"`) and never silently truncated.
  * Resolution is chosen automatically from a vision-token budget, so callers
    pass a path and nothing else.
  * Identical work is cached on disk (per file hash + task), so re-reading the
    same screenshot in a later session costs ~0s instead of ~40s.
  * Tables come back as Markdown, not OTSL tags.
  * VRAM is held only while busy: idle eviction + explicit release.

Tools: ocr_image, ocr_text, kie_image, vqa_image, ocr_pdf, ocr_batch,
       model_status, model_release
Run:   python mcp_server.py            (stdio, what DSH/Harness expects)
       python mcp_server.py --http     (streamable-http on :8765/mcp)
"""
from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
from typing import Any

from mcp.server.mcpserver import MCPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.environ.get("XIAOMI_OCR_MODEL_PATH", os.path.join(ROOT, "model"))
DEVICE = os.environ.get("XIAOMI_OCR_DEVICE", "cuda")
MAX_SIDE_CAP = int(os.environ.get("XIAOMI_OCR_MAX_SIDE", "1536"))
TOKEN_BUDGET = int(os.environ.get("XIAOMI_OCR_TOKEN_BUDGET", "1200"))
IDLE_UNLOAD_S = int(os.environ.get("XIAOMI_OCR_IDLE_UNLOAD_S", "120"))
HOLD_S = int(os.environ.get("XIAOMI_OCR_HOLD_S", "600"))
SINGLE_RELEASE = os.environ.get("XIAOMI_OCR_SINGLE_RELEASE", "1") == "1"
# Unloading frees VRAM but not the process's ~3-5 GB of host memory (torch arenas + CUDA
# context). When set, an idle process exits and the MCP client respawns it on demand.
EXIT_IDLE_S = int(os.environ.get("XIAOMI_OCR_EXIT_IDLE_S", "600"))
BRIEF_CHARS = int(os.environ.get("XIAOMI_OCR_BRIEF_CHARS", "6000"))
CACHE_DIR = os.path.join(ROOT, "tmp", "cache")
CACHE_VERSION = "v2"

PROMPT_MARKDOWN = (
    "Extract all information from the main body of the document image and represent it "
    "in markdown format, ignoring headers and footers. Tables should be expressed in OTSL "
    "format, formulas in the document should be represented using LATEX format, and the "
    "parsing should be organized according to the reading order."
)
PROMPT_TEXT = "Extract the text in the image."
PROMPT_TABLE = "Parse the table in the image into OTSL."
PROMPT_FORMULA = "Identify the formula in the image and represent it using LATEX format."
PROMPTS = {"markdown": PROMPT_MARKDOWN, "text": PROMPT_TEXT, "table": PROMPT_TABLE, "formula": PROMPT_FORMULA}

mcp = MCPServer(
    "xiaomi-ocr",
    instructions=(
        "Local Xiaomi-OCR-0 document OCR (no network, no API cost). Use these tools instead of "
        "guessing about image content. Defaults are tuned for agent use: results are compact, "
        "resolution is chosen automatically, repeat reads hit a disk cache. Ask detail='full' "
        "only when you need every character."
    ),
)

_lock = threading.Lock()
_STARTED_AT = time.monotonic()
_state: dict[str, Any] = {
    "model": None,
    "processor": None,
    "device": DEVICE,
    "last_used": 0.0,
    "loaded_at": 0.0,
    "loads": 0,
    "pins": 0,          # >0 while a multi-image job is running
    "keep_until": 0.0,   # declared hold deadline for multi-page work
    "policy": "idle",    # human-readable retention state
    "unloaded_at": 0.0,  # when the model last left VRAM (for EXIT_IDLE_S)
}


# --------------------------------------------------------------------------- model lifecycle
def _load() -> tuple[Any, Any, str]:
    if _state["model"] is not None:
        _state["last_used"] = time.monotonic()
        return _state["model"], _state["processor"], _state["device"]

    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    device = DEVICE
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    dtype = torch.float16 if device == "cuda" else torch.bfloat16

    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_DIR)
    model = AutoModelForImageTextToText.from_pretrained(MODEL_DIR, dtype=dtype).to(device).eval()
    print(f"[xiaomi-ocr] loaded on {device}/{dtype} in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)

    now = time.monotonic()
    _state.update(model=model, processor=processor, device=device,
                  last_used=now, loaded_at=now, loads=_state["loads"] + 1)
    return model, processor, device


def _unload(reason: str) -> bool:
    """Drop the model and give the VRAM back. Caller must hold _lock."""
    model = _state["model"]
    if model is None:
        return False
    _state.update(model=None, processor=None, unloaded_at=time.monotonic())
    try:
        del model
        gc.collect()
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        trim_host_memory()
        if torch.cuda.is_available():
            free = torch.cuda.mem_get_info()[0] / 2**30
            print(f"[xiaomi-ocr] unloaded ({reason}), {free:.2f} GiB VRAM free, "
                  f"rss {_rss_mib()} MiB", file=sys.stderr, flush=True)
        else:
            print(f"[xiaomi-ocr] unloaded ({reason}), rss {_rss_mib()} MiB", file=sys.stderr, flush=True)
    except Exception as exc:  # noqa: BLE001 - unloading must never raise into a tool call
        print(f"[xiaomi-ocr] unload warning: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    return True


def _rss_mib() -> int:
    """Resident set size of this process, in MiB."""
    try:
        import psutil

        return int(psutil.Process().memory_info().rss / (1024 * 1024))
    except Exception:  # noqa: BLE001 - diagnostics only
        return -1


def trim_host_memory() -> None:
    """Hand freed heap pages back to the OS (torch keeps host arenas alive otherwise)."""
    try:
        import ctypes

        if sys.platform == "win32":
            ctypes.CDLL("msvcrt")._heapmin()
        else:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001 - best effort
        pass


def _watchdog() -> None:
    """Backstop eviction + optional idle exit (releases host memory, not just VRAM)."""
    if IDLE_UNLOAD_S <= 0 and HOLD_S <= 0:
        print("[xiaomi-ocr] idle unload disabled", file=sys.stderr, flush=True)
    while True:
        time.sleep(2)
        if EXIT_IDLE_S > 0 and _state["model"] is None and _state["pins"] == 0:
            since = _state["unloaded_at"] or _STARTED_AT
            if time.monotonic() - since > EXIT_IDLE_S:
                print(f"[xiaomi-ocr] exiting after {EXIT_IDLE_S}s idle "
                      f"(rss was {_rss_mib()} MiB), client will respawn on next call",
                      file=sys.stderr, flush=True)
                sys.stderr.flush()
                os._exit(0)
        if _state["model"] is None:
            continue
        now = time.monotonic()
        if now < _state["keep_until"]:
            continue  # a multi-image job asked us to stay resident
        if now - _state["last_used"] < IDLE_UNLOAD_S:
            continue
        if _state["pins"] > 0:
            continue  # a job is in flight
        if not _lock.acquire(blocking=False):
            continue  # a call is running
        try:
            if _state["model"] is not None and time.monotonic() - _state["last_used"] >= IDLE_UNLOAD_S:
                _unload(f"idle > {IDLE_UNLOAD_S}s")
        finally:
            _lock.release()


# --------------------------------------------------------------------------- image plumbing
def _settle(hold: bool) -> str:
    """Decide what happens to the model right after a tool call finished.

    hold=True  -> a multi-image job said more is coming: keep it for HOLD_S.
    hold=False -> a one-shot call: release VRAM immediately.
    """
    if _lock.acquire(timeout=10):
        try:
            if _state["model"] is None:
                _state["policy"] = "not loaded"
                return _state["policy"]
            now = time.monotonic()
            if hold:
                _state["keep_until"] = now + HOLD_S
                _state["policy"] = f"held {HOLD_S}s after last call"
            elif _state["pins"] > 0:
                _state["policy"] = "kept: job still running"
            elif SINGLE_RELEASE:
                _state["keep_until"] = 0.0
                _unload("single-shot call finished")
                _state["policy"] = "released (single-shot)"
            else:
                _state["keep_until"] = now + IDLE_UNLOAD_S
                _state["policy"] = f"idle timer {IDLE_UNLOAD_S}s"
            return _state["policy"]
        finally:
            _lock.release()
    return "busy"


def _resolve(path: str) -> str:
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(p):
        raise FileNotFoundError(f"image not found: {path} (resolved: {p})")
    return p


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _vision_tokens(w: int, h: int) -> int:
    """Qwen3.5-VL: 16px patches, 2x2 merge."""
    return math.ceil(w / 16) * math.ceil(h / 16) // 4


def _auto_side(w: int, h: int, budget: int) -> int:
    """Largest long edge that keeps vision tokens under `budget` (cap: MAX_SIDE_CAP)."""
    long_edge = max(w, h)
    if _vision_tokens(w, h) <= budget:
        return long_edge
    scale = math.sqrt(budget * 4 * 16 * 16 / (w * h))
    return max(256, min(MAX_SIDE_CAP, int(long_edge * scale)))


def _prepare(path: str, max_side: int, detail: str) -> tuple[Any, int, int, int]:
    from PIL import Image

    img = Image.open(_resolve(path)).convert("RGB")
    w0, h0 = img.size
    budget = TOKEN_BUDGET if detail != "full" else TOKEN_BUDGET * 2
    side = max_side or _auto_side(w0, h0, budget)
    side = min(side, MAX_SIDE_CAP) if max_side else side
    if max(w0, h0) > side:
        scale = side / max(w0, h0)
        img = img.resize((max(1, round(w0 * scale)), max(1, round(h0 * scale))), Image.LANCZOS)
    return img, side, w0, h0


# --------------------------------------------------------------------------- post-processing
def otsl_to_markdown(text: str) -> str:
    """Convert OTSL tags (fcel/ecel/lcel/ucel/xcel/nl) into a Markdown table."""
    if "<fcel>" not in text and "<ecel>" not in text:
        return text
    rows: list[list[str]] = []
    for block in re.split(r"<nl>", text):
        cells: list[str] = []
        for m in re.finditer(r"<(fcel|ecel|lcel|ucel|xcel|ched|rhed)>(.*?)(?=<(?:fcel|ecel|lcel|ucel|xcel|ched|rhed)>|<nl>|$)",
                             block, re.S):
            tag, val = m.group(1), m.group(2).strip()
            if tag == "lcel":
                val = cells[-1] if cells else ""  # horizontal merge: repeat left content
            elif tag in ("ucel", "xcel"):
                val = ""
            cells.append(val)
        if cells:
            rows.append(cells)
    if not rows:
        return text
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]

    def esc(c: str) -> str:
        return c.replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(esc(c) for c in rows[0]) + " |",
           "| " + " | ".join("---" for _ in rows[0]) + " |"]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^(here is|以下是|图片中的文字[:：]?).{0,20}\n", "", text, flags=re.I)
    return text.strip()


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def _cache_get(key: str) -> dict[str, Any] | None:
    try:
        with open(_cache_path(key), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 - a broken cache entry is just a miss
        return None


def _cache_put(key: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - caching is best-effort
        pass


# --------------------------------------------------------------------------- inference core
def _run(image: Any, prompt: str, max_new_tokens: int) -> tuple[str, dict[str, Any]]:
    import torch

    with _lock:
        model, processor, device = _load()
        t0 = time.time()
        inputs = processor.apply_chat_template(
            [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}],
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(device)
        n_in = inputs["input_ids"].shape[1]
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        new_tokens = output[:, n_in:]
        text = processor.batch_decode(new_tokens, skip_special_tokens=True)[0]

        eos = model.generation_config.eos_token_id
        eos_ids = set(eos if isinstance(eos, (list, tuple)) else [eos])
        truncated = bool(new_tokens.shape[1] >= max_new_tokens and new_tokens[0, -1].item() not in eos_ids)

        meta = {
            "input_tokens": int(n_in),
            "output_tokens": int(new_tokens.shape[1]),
            "seconds": round(time.time() - t0, 1),
            "device": device,
            "image_size": list(image.size),
            "truncated": truncated,
        }
        _state["last_used"] = time.monotonic()
    return text.strip(), meta


def _task(path: str, prompt: str, detail: str, max_side: int, max_new_tokens: int,
          post: str | None = None) -> tuple[str, dict[str, Any]]:
    """Cached, post-processed single-image run. `post` selects the output shape."""
    src = _resolve(path)
    digest = _sha256(src)
    budget = TOKEN_BUDGET if detail != "full" else TOKEN_BUDGET * 2
    img, side, w0, h0 = _prepare(src, max_side, detail)
    key = hashlib.sha256(
        f"{CACHE_VERSION}|{digest}|{prompt[:64]}|{side}|{max_new_tokens}|{detail}|{post}".encode()
    ).hexdigest()[:32]

    hit = _cache_get(key)
    if hit is not None:
        meta = dict(hit["meta"], cache="hit", age_seconds=round(time.time() - hit["ts"], 1))
        text = hit["text"]
    else:
        t0 = time.time()
        text, meta = _run(img, prompt, max_new_tokens)
        meta["cache"] = "miss"
        meta["wall_seconds"] = round(time.time() - t0, 1)
        text = _tidy(text)
        if post == "otsl":
            text = otsl_to_markdown(text)
        _cache_put(key, {"text": text, "meta": {k: v for k, v in meta.items() if k != "cache"}, "ts": time.time()})

    text = _tidy(text) if post != "otsl" else text
    if detail != "full" and len(text) > BRIEF_CHARS:
        text = text[:BRIEF_CHARS] + f"\n\n…[cut at {BRIEF_CHARS} chars; re-run with detail='full' for the rest]"
        meta["brief_cut"] = True

    meta.update({"source_pixels": [w0, h0], "used_side": side, "text_chars": len(text)})
    return text, meta


def _schema_prompt(fields: list[str]) -> str:
    schema = json.dumps({f: "" for f in fields}, ensure_ascii=False, indent=4)
    return ("Extract key information in the image\n\n"
            "Please output the key information in JSON format according to the following schema:\n" + schema)


def _fmt(text: str, meta: dict[str, Any]) -> str:
    return f"{text}\n\n<!-- {json.dumps(meta, ensure_ascii=False)} -->"


# --------------------------------------------------------------------------- tools
@mcp.tool()
def ocr_image(image_path: str, intent: str = "markdown", detail: str = "brief",
              max_side: int = 0, max_new_tokens: int = 0, hold: bool = False) -> str:
    """Parse a document page image. Returns Markdown with tables (Markdown) and formulas (LaTeX).

    Args:
        image_path: path to the image
        intent: markdown (whole page), text (plain), table (one table), formula (one formula)
        detail: brief (compact, default) or full (every character, bigger context cost)
        max_side: force the long edge in px (0 = auto from a vision-token budget)
        max_new_tokens: output budget (0 = auto: 1024 brief / 2560 full)
        hold: true when more pages are coming right after this call (keeps the model warm for
              XIAOMI_OCR_HOLD_S); false releases VRAM as soon as the call returns
    """
    intent = intent if intent in PROMPTS else "markdown"
    budget = max_new_tokens or (1024 if detail != "full" else 2560)
    text, meta = _task(image_path, PROMPTS[intent], detail, max_side, budget,
                       post="otsl" if intent in ("table", "markdown") else None)
    meta["retention"] = _settle(hold)
    return _fmt(text, meta)


@mcp.tool()
def ocr_text(image_path: str, detail: str = "brief", max_side: int = 0,
             max_new_tokens: int = 0, hold: bool = False) -> str:
    """Extract plain text from an image (screenshots, receipts, signs, short documents).

    Args:
        hold: true when more images follow immediately; false releases VRAM right away
    """
    budget = max_new_tokens or (768 if detail != "full" else 2048)
    text, meta = _task(image_path, PROMPT_TEXT, detail, max_side, budget)
    meta["retention"] = _settle(hold)
    return _fmt(text, meta)


@mcp.tool()
def kie_image(image_path: str, fields: str, detail: str = "brief",
              max_side: int = 0, max_new_tokens: int = 0, hold: bool = False) -> str:
    """Extract key fields from invoices/receipts/cards/forms and return JSON.

    Args:
        image_path: path to the image
        fields: comma- or space-separated field names, e.g. "date seller_name total_amount"
        hold: true when more images follow immediately; false releases VRAM right away
    """
    names = [f.strip() for f in fields.replace(",", " ").split() if f.strip()]
    if not names:
        return "ERROR: fields is empty; pass the keys you want extracted."
    budget = max_new_tokens or 384
    text, meta = _task(image_path, _schema_prompt(names), detail, max_side, budget)
    meta["retention"] = _settle(hold)
    return _fmt(text, meta)


@mcp.tool()
def vqa_image(image_path: str, question: str, detail: str = "brief",
              max_side: int = 0, max_new_tokens: int = 0, hold: bool = False) -> str:
    """Answer a short question about a document image (values, totals, dates, chart readings).

    Args:
        hold: true when more questions/images follow immediately; false releases VRAM right away
    """
    if not question.strip():
        return "ERROR: question is empty."
    budget = max_new_tokens or 192
    text, meta = _task(image_path, question.strip(), detail, max_side, budget)
    meta["retention"] = _settle(hold)
    return _fmt(text, meta)


@mcp.tool()
def ocr_batch(paths: list[str], intent: str = "text", detail: str = "brief", hold: bool = False) -> str:
    """OCR several images in one call (serial, cached). Returns one section per file.

    Args:
        paths: list of absolute or project-relative image paths
        intent: text (default), markdown, table or formula
        hold: keep the model resident for XIAOMI_OCR_HOLD_S after the batch. Default false —
              the whole batch already runs inside this one call, so VRAM is released when it
              returns. Pass true only when you know more calls follow immediately.
    """
    intent = intent if intent in PROMPTS else "text"
    out: list[str] = []
    with _lock:
        _state["pins"] += 1
    try:
        for i, p in enumerate(paths, 1):
            try:
                text, meta = _task(p, PROMPTS[intent], detail, 0, 768 if detail != "full" else 2048,
                                   post="otsl" if intent in ("table", "markdown") else None)
                out.append(f"### [{i}] {os.path.basename(p)}\n\n{text}\n\n<!-- {json.dumps(meta, ensure_ascii=False)} -->")
            except Exception as exc:  # noqa: BLE001 - one bad file must not kill the batch
                out.append(f"### [{i}] {os.path.basename(p)}\n\nERROR: {type(exc).__name__}: {exc}")
    finally:
        with _lock:
            _state["pins"] -= 1
    retention = _settle(hold)
    return "\n\n".join(out) + f"\n\n<!-- retention: {retention} -->"


@mcp.tool()
def ocr_pdf(pdf_path: str, pages: str = "", detail: str = "brief", dpi: int = 150,
            max_pages: int = 5, hold: bool = False) -> str:
    """Parse a PDF page by page. Defaults to the first 5 pages — ask for more explicitly.

    Args:
        pdf_path: path to the PDF
        pages: 1-based selection like "1", "1-3", "2,4" (empty = first max_pages pages)
        detail: brief / full
        dpi: render resolution (150 is enough for 1280px long edge)
        max_pages: hard cap when pages is empty
        hold: keep the model resident after this job; default false because all pages are
              processed inside this call, so VRAM is released on return
    """
    try:
        import pypdfium2 as pdfium  # BSD-3-Clause / Apache-2.0 (PDFium); avoids AGPL PyMuPDF
    except ImportError:
        return ("ERROR: pypdfium2 is not installed. Install it with "
                "`pip install pypdfium2`, or OCR page images individually with ocr_image.")

    src = _resolve(pdf_path)
    doc = pdfium.PdfDocument(src)
    total = len(doc)
    wanted: list[int] = []
    if pages.strip():
        for part in pages.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                wanted.extend(range(int(a), int(b) + 1))
            else:
                wanted.append(int(part))
    else:
        wanted = list(range(1, min(total, max_pages) + 1))

    out: list[str] = []
    with _lock:
        _state["pins"] += 1
    try:
        for num in wanted:
            if num < 1 or num > total:
                continue
            page = doc[num - 1]
            bitmap = page.render(scale=dpi / 72)
            image = bitmap.to_pil().convert("RGB")
            tmp = os.path.join(ROOT, "tmp", f"_page_{num}.png")
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            image.save(tmp)
            text, meta = _task(tmp, PROMPT_MARKDOWN, detail, 0, 1024 if detail != "full" else 2560, post="otsl")
            out.append(f"## Page {num}\n\n{text}\n\n<!-- {json.dumps(meta, ensure_ascii=False)} -->")
    finally:
        with _lock:
            _state["pins"] -= 1
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass
    retention = _settle(hold)
    head = f"<!-- {total} pages total; parsed {len(out)}; retention: {retention} -->\n\n" if out else ""
    return head + "\n\n".join(out) if out else "ERROR: no pages selected."


@mcp.tool()
def model_status() -> str:
    """Report whether the OCR model is resident, its VRAM use, and how long it has been idle."""
    import torch

    loaded = _state["model"] is not None
    now = time.monotonic()
    info: dict[str, Any] = {
        "loaded": loaded,
        "device": _state["device"],
        "retention": _state["policy"],
        "held_seconds_left": max(0, round(_state["keep_until"] - now, 1)) if loaded else None,
        "running_jobs": _state["pins"],
        "hold_seconds": HOLD_S,
        "single_shot_release": SINGLE_RELEASE,
        "idle_seconds": round(now - _state["last_used"], 1) if loaded else None,
        "idle_unload_seconds": IDLE_UNLOAD_S,
        "loads_this_process": _state["loads"],
        "token_budget": TOKEN_BUDGET,
        "exit_idle_seconds": EXIT_IDLE_S,
        "rss_mib": _rss_mib(),
        "cache_entries": len(os.listdir(CACHE_DIR)) if os.path.isdir(CACHE_DIR) else 0,
    }
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        info["vram"] = {
            "free_gib": round(free / 2**30, 2),
            "total_gib": round(total / 2**30, 2),
            "torch_reserved_gib": round(torch.cuda.memory_reserved() / 2**30, 2),
        }
    return json.dumps(info, ensure_ascii=False)


@mcp.tool()
def model_release() -> str:
    """Free the OCR model's VRAM immediately (the next OCR call reloads it in ~7s)."""
    if not _lock.acquire(timeout=1.0):
        return "BUSY: an OCR call is running; release skipped."
    try:
        _state["keep_until"] = 0.0
        freed = _unload("manual release")
        _state["policy"] = "released (manual)"
    finally:
        _lock.release()
    return "released" if freed else "already unloaded"


if __name__ == "__main__":
    threading.Thread(target=_watchdog, name="idle-unload", daemon=True).start()
    if "--http" in sys.argv:
        mcp.run(
            transport="streamable-http",
            host=os.environ.get("XIAOMI_OCR_HOST", "127.0.0.1"),
            port=int(os.environ.get("XIAOMI_OCR_PORT", "8765")),
            streamable_http_path="/mcp",
        )
    else:
        mcp.run()  # stdio: spawned by the client
