#!/usr/bin/env bash
# One-shot bootstrap for the Raspberry Pi 4B (VAE worker).
# Paste this over SSH after copying the repo to ~/swarmgen.
# Fails loudly. Run from the repo root.
set -euo pipefail

echo "== SwarmGen Pi setup =="
echo "Host: $(hostname)   Arch: $(uname -m)   Python: $(python3 --version)"

# System packages the Pi typically needs for torch + Pillow.
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip libjpeg-dev zlib1g-dev libopenblas-dev

# Venv keeps us out of system Python.
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip wheel

echo "== Installing torch (CPU, aarch64) =="
# Pi 4B is aarch64. PyPI ships aarch64 wheels for torch >= 2.6 on modern Python.
# We don't pin tightly because the protocol uses raw numpy bytes, so torch version
# skew across devices is harmless.
pip install "torch>=2.6,<2.10"

echo "== Installing Pi requirements (no transformers — VAE-only) =="
pip install -r requirements-pi.txt

echo "== Sanity: torch + diffusers import =="
python - <<'PY'
import torch, diffusers, fastapi, zeroconf, psutil
print("python", __import__('sys').version.split()[0])
print("torch", torch.__version__, "cuda?", torch.cuda.is_available())
print("diffusers", diffusers.__version__)
print("fastapi", fastapi.__version__)
print("zeroconf OK, psutil OK")
PY

echo "== Sanity: protocol round-trip =="
python protocol.py

echo "== Pi setup done =="
echo "Next: python worker.py --role vae --port 8003"
