"""Download Xiaomi-OCR-0 weights from an HF mirror into ./model (no huggingface_hub needed)."""
import os
import sys
import time
import urllib.request

REPO = "xiaomi-research/Xiaomi-OCR-0"
BASE = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
ROOT = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(ROOT, "model")

FILES = [
    "model.safetensors",
    "config.json",
    "chat_template.jinja",
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "example_pics/qianziwen.jpeg",
    "example_pics/receipt.jpg",
    "example_pics/dense-equations.jpg",
]


def fetch(rel):
    url = f"{BASE}/{REPO}/resolve/main/{rel}"
    out = os.path.join(DEST, rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part"
    if os.path.exists(out) and os.path.getsize(out) > 0:
        print(f"skip {rel} ({os.path.getsize(out)} bytes)", flush=True)
        return
    for attempt in range(1, 6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                t0 = time.time()
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if total and done % (64 << 20) < (1 << 20):
                        pct = 100 * done / total
                        rate = done / max(time.time() - t0, 0.1) / 1e6
                        print(f"  {rel}: {pct:5.1f}% {done/1e6:7.1f}MB {rate:5.1f}MB/s", flush=True)
            os.replace(tmp, out)
            print(f"ok   {rel} {os.path.getsize(out)} bytes", flush=True)
            return
        except Exception as e:  # noqa: BLE001
            print(f"retry {rel} ({attempt}/5): {type(e).__name__}: {e}", flush=True)
            time.sleep(2 * attempt)
    raise SystemExit(f"FAILED: {rel}")


if __name__ == "__main__":
    wanted = sys.argv[1:] or FILES
    os.makedirs(DEST, exist_ok=True)
    for rel in wanted:
        fetch(rel)
    print("done ->", DEST)
