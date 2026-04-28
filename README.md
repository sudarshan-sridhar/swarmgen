# SwarmGen

Distributed Stable Diffusion Turbo across 3 heterogeneous edge devices, for CIS 589 final project.

Pipeline split:

```
prompt -> CLIP (CPU laptop, :8001)
       -> UNet x4 (RTX 5060 box, :8002)
       -> VAE (Pi 4B, :8003)
       -> image
```

## Run order (3 terminals, one per device)

### 1. GPU box (Windows 11, conda env `ml`)

```
conda activate ml
pip install -r requirements-gpu.txt
python protocol.py            # round-trip check
python worker.py --role unet --port 8002
```

In a second terminal on the same box:

```
python coordinator.py --prompt "a cat astronaut riding a horse"
```

### 2. Second laptop (CPU only)

```
bash setup_laptop.sh
source .venv/bin/activate
python worker.py --role clip --port 8001
```

### 3. Raspberry Pi 4B

```
bash setup_pi.sh
source .venv/bin/activate
python worker.py --role vae --port 8003
```

## Files

- `protocol.py` shared tensor wire format (JSON header + raw bytes, no pickle)
- `worker.py` role-flagged FastAPI service, runs on all 3 devices
- `coordinator.py` mDNS browser, async orchestration, heartbeat, fault recovery, batch
- `baseline.py` single-device SD-Turbo for the latency comparison
- `eval.py` measurement harness, writes CSVs to `results/`
- `plot_results.py` produces the paper figures
- `ui.py` Gradio demo
- `paper/paper.tex` IEEE template

## Notes

- No em dashes anywhere in human-facing text. That's the house style.
- Pi cannot run the full pipeline alone. That is the point of the paper, not a bug.
- Every script supports `--help`.
