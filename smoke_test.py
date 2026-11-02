"""Standalone smoke test: load the local weights and OCR one example image.

Run after install:  .venv\\Scripts\\python.exe smoke_test.py
Exit code 0 means the model, tokenizer and GPU path all work.
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "model")
IMAGE = os.path.join(MODEL_DIR, "example_pics", "receipt.jpg")
FIELDS = ["date", "seller_name", "total_amount", "total_tax"]


def main() -> int:
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor

    if not os.path.exists(os.path.join(MODEL_DIR, "model.safetensors")):
        print(f"ERROR: weights missing at {MODEL_DIR}; run install again", file=sys.stderr)
        return 2
    if not os.path.exists(IMAGE):
        print(f"ERROR: sample image missing at {IMAGE}", file=sys.stderr)
        return 2

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.bfloat16
    print(f"[1/3] loading model on {device}/{dtype} ...", file=sys.stderr)
    t0 = time.time()
    processor = AutoProcessor.from_pretrained(MODEL_DIR)
    model = AutoModelForImageTextToText.from_pretrained(MODEL_DIR, dtype=dtype).to(device).eval()
    print(f"      loaded in {time.time() - t0:.1f}s", file=sys.stderr)

    img = Image.open(IMAGE).convert("RGB")
    if max(img.size) > 1024:
        scale = 1024 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)

    schema = json.dumps({f: "" for f in FIELDS}, ensure_ascii=False, indent=4)
    prompt = ("Extract key information in the image\n\n"
              "Please output the key information in JSON format according to the following schema:\n" + schema)

    print("[2/3] running inference ...", file=sys.stderr)
    t0 = time.time()
    inputs = processor.apply_chat_template(
        [{"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": prompt}]}],
        tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt",
    ).to(device)
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=256, do_sample=False)
    text = processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
    dt = time.time() - t0

    print("[3/3] result:\n", file=sys.stderr)
    print(text.strip())
    print(f"\n[{dt:.1f}s, {device}]", file=sys.stderr)
    if "2017-10-18" not in text:
        print("WARNING: expected the receipt date 2017-10-18 in the output", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
