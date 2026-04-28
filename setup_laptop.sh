#!/usr/bin/env bash
# One-shot bootstrap for the second laptop (CLIP worker, CPU only).
# Run from the repo root.
set -euo pipefail

echo "== SwarmGen second-laptop setup =="
echo "Host: $(hostname)   Arch: $(uname -m)   Python: $(python3 --version)"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip wheel

echo "== Installing torch (CPU wheel) =="
pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

echo "== Installing CPU requirements =="
pip install -r requirements-cpu.txt

echo "== Sanity: imports =="
python - <<'PY'
import torch, diffusers, transformers, fastapi, zeroconf, psutil
print("torch", torch.__version__, "cuda?", torch.cuda.is_available())
print("diffusers", diffusers.__version__)
print("transformers", transformers.__version__)
print("fastapi", fastapi.__version__)
print("zeroconf OK, psutil OK")
PY

echo "== Sanity: protocol round-trip =="
python protocol.py

echo "== Laptop setup done =="
echo "Next: python worker.py --role clip --port 8001"
