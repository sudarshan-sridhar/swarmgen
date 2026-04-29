# SwarmGen

Distributed Stable Diffusion Turbo across three heterogeneous edge devices.
Final project for CIS 589 (Edge Computing), University of Michigan-Dearborn.

The diffusion pipeline is partitioned by stage and each stage runs on the
device best suited to it:

```
prompt -> CLIP   (CPU laptop,        :8001)
       -> UNet   (RTX 5060 desktop,  :8002)
       -> VAE    (Raspberry Pi 4B,   :8003)
       -> image
```

## Research question

Can a diffusion pipeline be partitioned across heterogeneous edge devices
such that (a) the system runs end to end, (b) peak per-device memory drops
below what any single device would need, (c) the system degrades gracefully
when a device fails, and (d) batch throughput scales with swarm size?

The Pi cannot fit SD-Turbo in 4 GB of RAM on its own, so a single-device
baseline is not feasible there. The swarm makes the pipeline reachable on
that hardware mix, recovers automatically if a worker dies, and amortizes
single-image latency over a batch via pipeline parallelism.

## Repository layout

| Path | Purpose |
| --- | --- |
| `protocol.py`      | Tensor wire format. JSON header plus raw bytes, no pickle. |
| `worker.py`        | Role-flagged FastAPI worker. Same binary on every device. |
| `coordinator.py`   | mDNS discovery, async orchestration, heartbeats, fault recovery, batch. |
| `baseline.py`      | Single-device SD-Turbo for the latency comparison. |
| `eval.py`          | Measurement harness. Writes CSVs to `results/`. |
| `plot_results.py`  | Builds the figures used in the paper. |
| `api.py`           | FastAPI server backing the web UI. |
| `static/`          | Tailwind frontend served by `api.py`. |
| `ui.py`            | Older Gradio demo, kept for reference. |
| `paper/`           | IEEE-format paper sources and figures. |
| `requirements-*.txt`, `setup_*.sh` | Per-device dependencies and bootstrap scripts. |

## Running the swarm

Three terminals, one per device.

### 1. GPU desktop (Windows 11, conda env `ml`)

```
conda activate ml
pip install -r requirements-gpu.txt
python protocol.py                          # tensor round-trip self-check
python worker.py --role unet --port 8002
```

### 2. CPU laptop

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

### 4. Coordinator (any device on the LAN)

Single image:

```
python coordinator.py --prompt "a cat astronaut riding a horse"
```

Web UI:

```
python api.py --workers clip@<laptop-ip>:8001,unet@<gpu-ip>:8002,vae@<pi-ip>:8003
# open http://localhost:7860
```

Every script supports `--help`.

## Reproducing the paper results

```
python eval.py --suite all          # writes results/*.csv
python plot_results.py              # writes paper/figs/*.png
```

## Conventions

- No `pickle` on the wire. Tensors travel as JSON header plus raw bytes
  (see `protocol.py`).
- Workers fail loudly. Heartbeats and structured logs are the only way
  the coordinator learns about failures.
- The Pi cannot run the full pipeline alone. That is the premise, not a bug.

## Authors

Sudarshan Sridhar and Varun Patel. CIS 589, Winter 2026.
