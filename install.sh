#!/usr/bin/env bash
# Install the local Xiaomi-OCR-0 MCP plugin for DeepSeek Harness.
#
#   bash install.sh            # CUDA build (falls back to CPU)
#   bash install.sh --cpu      # CPU only
#   bash install.sh --skip-model --render-only
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
VENVPY="$VENV/bin/python"
TMPDIR_LOCAL="$ROOT/tmp"
mkdir -p "$TMPDIR_LOCAL"
export TMPDIR="$TMPDIR_LOCAL"

CPU=0
SKIP_MODEL=0
RENDER_ONLY=0
MODEL_MIRROR="${HF_ENDPOINT:-https://hf-mirror.com}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpu) CPU=1 ;;
    --skip-model) SKIP_MODEL=1 ;;
    --render-only) RENDER_ONLY=1 ;;
    --mirror) MODEL_MIRROR="$2"; shift ;;
    -h|--help) sed -n '1,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done

step() { printf '\n==> %s\n' "$1"; }
ok()   { printf '    %s\n' "$1"; }
warn() { printf '    ! %s\n' "$1"; }

step "Locating Python 3.10+"
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
[[ -n "$PY" ]] || { echo "Python 3.10+ not found"; exit 1; }
VER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
"$PY" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)' || {
  echo "Python $VER is too old; 3.10+ required"; exit 1; }
ok "Python $VER at $PY"

if [[ $RENDER_ONLY -eq 0 ]]; then
  step "Creating .venv"
  [[ -x "$VENVPY" ]] || "$PY" -m venv "$VENV"
  ok "$VENV"

  step "Installing Python dependencies (this downloads ~2-3 GB on first run)"
  "$VENVPY" -m pip install --upgrade pip --quiet
  if [[ $CPU -eq 1 ]]; then
    "$VENVPY" -m pip install "torch==2.14.0" "torchvision==0.29.0"
  else
    ok "installing CUDA build from download.pytorch.org/whl/cu130"
    "$VENVPY" -m pip install --index-url https://download.pytorch.org/whl/cu130 \
      "torch==2.14.0+cu130" "torchvision==0.29.0+cu130" || {
        warn "CUDA wheels unavailable; falling back to CPU torch"
        "$VENVPY" -m pip install "torch==2.14.0" "torchvision==0.29.0"
      }
  fi
  "$VENVPY" -m pip install "transformers==5.17.0" pillow accelerate mcp pymupdf
  ok "dependencies installed"

  if [[ $SKIP_MODEL -eq 0 ]]; then
    step "Downloading Xiaomi-OCR-0 weights (~1.7 GB) from $MODEL_MIRROR"
    HF_ENDPOINT="$MODEL_MIRROR" "$VENVPY" "$ROOT/fetch_model.py"
  else
    warn "skipped model download (--skip-model)"
  fi
fi

step "Rendering plugin/cordis.patch.yml"
TPL="$ROOT/plugin/cordis.patch.yml.template"
OUT="$ROOT/plugin/cordis.patch.yml"
python3 - "$TPL" "$OUT" "$VENVPY" "$ROOT/mcp_server.py" "$ROOT" "$CPU" <<'PY'
import sys, pathlib
tpl, out, venvpy, server, root, cpu = sys.argv[1:7]
text = pathlib.Path(tpl).read_text(encoding="utf-8")
text = text.replace("{{PYTHON}}", venvpy).replace("{{SERVER}}", server).replace("{{ROOT}}", root)
if cpu == "1":
    text = text.replace("XIAOMI_OCR_DEVICE: cuda", "XIAOMI_OCR_DEVICE: cpu")
pathlib.Path(out).write_text(text, encoding="utf-8")
print("    wrote", out)
PY

cat <<EOF

============================================================
Next steps
============================================================
1. Restart DeepSeek Harness.
2. Sidebar -> Plugins -> Add plugin -> paste:

   $ROOT/plugin

3. The card "Local OCR (Xiaomi-OCR-0)" appears, switched on.

Optional smoke test before wiring Harness:

   $VENVPY $ROOT/smoke_test.py
EOF
