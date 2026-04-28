# SwarmGen

Distributed Stable Diffusion Turbo across three heterogeneous edge devices.

CIS 589 Edge Computing · Final Project · Spring 2026 · UM-Dearborn
Sudarshan Sridhar · Varun Patel
github.com/sudarshan-sridhar/swarmgen

---

## The problem

A Raspberry Pi 4B cannot run Stable Diffusion Turbo on its own. The full SD-Turbo pipeline has a peak working set of about **2358 MB**. The Pi has **1845 MB** of physical RAM. That is a hard ceiling, not a software issue.

The interesting question is whether a swarm of unequal devices, each holding only a piece of the model, can do something none of them could do alone, and whether that swarm degrades gracefully when a device fails.

We are not trying to beat a single GPU on per-image latency. We will lose that fight by two orders of magnitude. The honest claim is memory partitioning, end-to-end correctness on the Pi, and fault tolerance.

---

## The solution

Split SD-Turbo into its three components and place each one on the device best suited to host it.

- **CLIP text encoder** runs on a CPU laptop. ~120 M parameters, one forward pass per prompt.
- **UNet denoiser** runs on an RTX 5060 laptop. ~865 M parameters, four forward passes per image.
- **VAE decoder** runs on a Raspberry Pi 4B. ~80 M parameters, one forward pass per image. Slow but bounded.

Putting UNet on the GPU is not a cheat. The claim is per-device memory reduction, not GPU offload. The Pi physically cannot hold the 2.4 GB working set; the swarm makes it a participant.

---

## Architecture

A coordinator on the GPU laptop (`loq`) orchestrates the pipeline over async HTTP. Workers announce themselves with mDNS under `_swarmgen._tcp.local.` and fall back to an explicit `--workers role@host:port` flag for predictability during the demo.

- Tensors travel over `application/octet-stream`. 4-byte length prefix + JSON header + raw bytes. No pickle.
- Each worker exposes `/health`, `/heartbeat`, `/capabilities`, `/run_stage`, and `/admin/die`.
- The coordinator runs an async heartbeat task that polls every worker once per second and marks it dead after three misses.
- The GPU laptop also loads the VAE as a fallback role (`--fallback-roles vae`). When the Pi dies, the next VAE call retries on the GPU in about 250 ms.
- PyTorch inference runs in `asyncio.to_thread` so heavy decodes never pin the FastAPI event loop.

---

## The three devices

| short | role | hardware | RAM | Wi-Fi IP | port |
|-------|------|----------|-----|----------|------|
| **loq** | UNet (+VAE fallback) | Win 11, RTX 5060 Laptop, 8 GB VRAM | 32 GB | 192.168.1.16 | 8002 |
| **pc**  | CLIP                 | Win 11, Intel i5-1035G1, no GPU    | 12 GB | 192.168.1.39 | 8001 |
| **pi**  | VAE                  | Pi 4B, ARM Cortex-A72, Debian 13   | **1.8 GB** | 192.168.1.185 | 8003 |

All three sit on the same home Wi-Fi. `loq` also runs the coordinator and the web UI.

---

## Single-image latency

| configuration | mean per image |
|---|---|
| 1-device baseline (loq, full pipeline)   | **380 ms** |
| 3-device swarm with VAE on loq fallback  | 1097 ms |
| 3-device swarm with VAE on the Pi        | **147 615 ms (~2.5 min)** |

The Pi VAE decode dominates. We don't beat the single-device baseline. We said we wouldn't. The point of the swarm isn't speed.

---

## Per-device memory: the headline

| where the model runs | peak RSS |
|---|---|
| 1-device baseline · loq full pipeline | **2358 MB** |
| 3-device swarm · loq UNet + VAE fp16  | 2080 MB |
| 3-device swarm · pc CLIP              | 1398 MB |
| 3-device swarm · **pi VAE**           | **1226 MB** |

**Pi physical RAM ceiling: 1845 MB.**

The 2358 MB single-device pipeline does not fit on the Pi. The 1226 MB VAE-only working set does. The swarm makes the impossible run.

---

## Fault tolerance

We kill the Pi VAE worker exactly one second into a generation, on purpose, with `POST /admin/die`. Then we measure what happens.

- Coordinator's next call to VAE fails at the transport layer.
- The dead worker is dropped from the candidate pool immediately.
- The VAE retry routes to `loq`'s GPU (which has the VAE preloaded as a fallback role).
- The image still completes.

| metric | value |
|---|---|
| Total time with fault recovery | **5.6 s** |
| VAE on loq (fp16 GPU fallback) | **250 ms** |
| Without fallback (Pi alone)    | 147 s |

Heartbeat-based liveness + transport-level retry + a preloaded fallback role. No magic.

---

## Batch throughput

The coordinator's batch mode uses three async tasks with bounded queues between them. While CLIP encodes prompt N+1, UNet denoises prompt N, and VAE decodes prompt N-1.

| configuration | throughput |
|---|---|
| 3-device swarm · VAE on loq GPU | **87.6 img/min** |
| 3-device swarm · VAE on the Pi  | **0.41 img/min** |

Steady-state throughput is bounded by the slowest stage. Pi VAE is **about 850× slower** than the GPU VAE, so pipeline parallelism cannot save us when a stage is that unbalanced. Heterogeneous swarms enable workloads on hardware that could not otherwise run them; they do not automatically accelerate batch throughput.

---

## The UI

A single static HTML file. Tailwind from CDN, vanilla JS, no build step. Served by `api.py` (FastAPI) which fronts the coordinator with a small JSON API.

- Dark theme. Bricolage Grotesque + JetBrains Mono.
- Numbered sections: 01 control, 02 pipeline, 03 output, 04 swarm.
- Live worker telemetry table polls `/api/workers` every two seconds. Pulsing green dot for alive, red for dead.
- Per-stage timing fills in after each generation, with a small heat bar showing relative stage cost.
- The output frame has a shimmer overlay during generation and an empty state that shows the pipeline as ASCII.
- A `kill Pi VAE worker` button issues `/admin/die` on demand for live fault demos.

---

## Implementation

About **1500 lines of Python** plus the static frontend. Same code runs unmodified on Linux ARM, Windows CPU, and Windows CUDA.

| file | what it does |
|---|---|
| `worker.py`         | Single role-flagged FastAPI worker. Loads only its assigned model component plus any fallback roles. |
| `coordinator.py`    | Async orchestrator. mDNS + explicit workers. Single-image and batch with pipeline parallelism. Heartbeat monitor and retry-on-fallback. |
| `protocol.py`       | Tensor wire format. 4-byte length prefix + JSON header + raw bytes. No pickle. |
| `api.py`            | FastAPI server in front of the coordinator. Serves the static UI plus `/api/workers`, `/api/generate`, `/api/admin/kill-vae`. |
| `static/index.html` | The UI. One file, no build step. |
| `eval.py`, `baseline.py`, `plot_results.py` | Eval harness, single-device baseline, and the script that turns the result CSVs into the four paper figures. |

No Docker. No Kubernetes. No Ray. Plain venvs, FastAPI, asyncio, zeroconf, httpx.

---

## Conclusion

**Heterogeneous edge swarms are best framed as enablers, not accelerators.**

- **Memory partitioning works.** Pi peaks at 1226 MB during the VAE decode, comfortably under its 1.8 GB ceiling. The 2358 MB single-device peak does not fit. The swarm lets a Pi participate in a workload it cannot host alone.
- **Fault recovery is fast and demonstrable.** Heartbeat plus transport-level retry routes the failed stage to a preloaded fallback in about 250 ms. The image still completes.
- **Throughput is gated by the slowest stage.** Pipeline parallelism does not deliver an order-of-magnitude speedup when one stage is 850× slower. Honest finding, mentioned in the paper.

Source code, paper, and result CSVs at **github.com/sudarshan-sridhar/swarmgen**.
