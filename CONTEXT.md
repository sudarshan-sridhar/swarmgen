# SwarmGen — Project Context for Claude Code

You are helping me build **SwarmGen**, my final project for CIS 589 (Edge Computing) at the University of Michigan-Dearborn. This document is the single source of truth. Read it fully before doing anything.

---

## Who I am, what I'm doing

- I'm Sudarshan Sridhar, MS CIS student, working with my teammate Varun Patel.
- This is the final project. Paper + working system + video demo are due **April 28** (tomorrow).
- We submitted a proposal already. Some things in the proposal are being cut intentionally — see the "Scope changes from proposal" section below. Do not try to re-add the cut features.
- I'm solo-driving the implementation. Varun is hands-off on code.
- I am away from home tonight with all three target devices on the same Wi-Fi. I cannot physically touch any of the machines if something goes wrong — everything has to be reachable over SSH or remote desktop. **Fail loudly, log everything, and never silently swallow exceptions.**

---

## The actual research question

The proposal frames it as "cloud GPUs are expensive, can edge devices collaborate?" That framing is fine for marketing but the real research question that the paper has to defend is sharper:

> **Can a diffusion pipeline be partitioned across heterogeneous edge devices such that (a) the system runs end-to-end, (b) peak per-device memory drops below what any single device would need, (c) the system degrades gracefully when a device fails, and (d) batch throughput scales with swarm size?**

We are NOT trying to beat a single GPU on single-image latency. We will lose that fight and the paper says so honestly. We ARE trying to show that the swarm enables generation on a hardware mix where no single device could run the full model (the Pi can't fit SD-Turbo in 4GB RAM), and that fault tolerance + batch throughput are real wins.

This framing matters. Every design decision should serve this story.

---

## Hardware (locked, do not assume otherwise)

| Role | Device | Specs | Notes |
|------|--------|-------|-------|
| Coordinator + UNet worker | My main laptop, Windows 11 | RTX 5060 Laptop GPU, 8GB VRAM, conda env `ml`, Python 3.11.14, PyTorch 2.5.1 + CUDA 12.1 | The GPU box. Runs orchestrator and the heaviest pipeline stage. |
| CLIP worker | My second laptop | CPU only, on the same Wi-Fi | Runs the text encoder. Lightweight stage. |
| VAE worker | Raspberry Pi 4B | ~4GB RAM, Python 3.9+, SSH access confirmed | Runs the VAE decoder only. Slow but bounded. **Cannot fit the full SD-Turbo model in RAM** — this is the headline of the paper. |

All three devices on the same local Wi-Fi. mDNS works (the Pi sees `.local` hostnames; verified).

---

(Full context is in the Downloads copy; this file is the in-repo reference. See README.md for run order.)
