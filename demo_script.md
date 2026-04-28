# SwarmGen demo video script (target ~7 minutes)

Tone: matter-of-fact, technical, casual. No em dashes anywhere. No reading the slides word for word.

## Setup before recording

- All three workers running. Verify with: `curl http://192.168.1.16:8002/health`, ditto pc and pi.
- `python ui.py --workers clip@192.168.1.39:8001,unet@192.168.1.16:8002,vae@192.168.1.185:8003` open in a browser tab on loq.
- A second terminal showing the live coordinator log.
- Architecture figure ready (paper/figs).
- Result PNGs ready (paper/figs).

## 0:00 - 0:45  Motivation and pitch

> "SwarmGen is a final project for CIS 589 at UM-Dearborn. The idea: take a diffusion model, Stable Diffusion Turbo specifically, and split it across three edge devices so each one only hosts the part it can fit. Why bother? Because a Raspberry Pi 4B with 1.8 gigabytes of RAM cannot run the full SD-Turbo pipeline. Peak working set is 2.3 gigabytes. The Pi physically cannot do this on its own. SwarmGen lets it participate."

Show the architecture figure: CLIP on the CPU laptop, UNet on the GPU laptop, VAE on the Pi. Coordinator on the GPU laptop too.

## 0:45 - 1:30  What we are not doing

> "I want to be honest up front. We are not trying to beat a single GPU on per-image latency. Putting a Pi in the pipeline adds 140 seconds of VAE decode that the GPU would have done in a quarter of a second. The point of this paper is memory partitioning and fault tolerance, not speed."

Show the latency comparison plot.

## 1:30 - 3:30  Live single-image demo

Switch to the Gradio UI. Camera on the screen, voice describing what is happening.

> "Here is the system running. The status panel at the bottom shows three workers, alive, with current and peak memory. CLIP on the CPU laptop, UNet on the RTX 5060, VAE on the Pi."

Type a prompt: `a watercolor painting of a lighthouse at dusk`. Click Generate.

> "Watch the per-stage timing as the image renders. CLIP runs on the CPU laptop in about half a second. UNet runs four denoising steps on the GPU in about 230 milliseconds. The VAE on the Pi takes about 140 seconds. That is the bottleneck. We will see what to do about it in a minute."

Wait for the image. Show the result.

## 3:30 - 5:00  Fault tolerance demo

> "Now the fun one. We declared loq's GPU as a fallback worker for VAE: it has the VAE model loaded already, takes about 165 megabytes of VRAM, and advertises VAE in its supported stages."

In the UI, set the fault-injection dropdown to `vae`. Submit a fresh prompt.

> "The coordinator schedules a kill of the Pi worker one second into the run. CLIP runs, UNet runs, then the coordinator goes to call VAE on the Pi and the connection is closed. The transport-level error marks the Pi dead immediately, and the VAE call retries on loq's GPU. Total time: about five and a half seconds. The Pi died, the image still rendered."

Show the fault-recovery timeline figure.

> "On the worker health table you can see the Pi is now showing alive=false. We can bring it back by SSHing in and restarting the worker, but for the purposes of this demo we have moved on."

## 5:00 - 6:00  Batch throughput

> "The other thing we measured is batch throughput with pipeline parallelism. Three async tasks, one per stage, with bounded queues between them. While CLIP is encoding prompt three, UNet is denoising prompt two, VAE is decoding prompt one."

Show the throughput plot.

> "When loq's GPU runs VAE, batch throughput is 87 images per minute. When the Pi runs VAE, batch throughput is 0.41 images per minute. Pipeline parallelism cannot save us here because steady-state throughput is bounded by the slowest stage, and the Pi is two orders of magnitude slower than the GPU."

## 6:00 - 6:45  Memory reduction story

Show the memory plot.

> "But the memory story is real. The single-device baseline peaks at 2358 megabytes. The Pi's peak in the swarm is 1225 megabytes, comfortably within its 1.8 gigabyte total. The dashed red line is the Pi's physical RAM. The single-device peak is above it. The Pi cannot run the full pipeline alone. The swarm makes the Pi a participant. That is the headline."

## 6:45 - 7:00  Wrap-up

> "Source code, paper, and result CSVs are at github dot com slash sudarshan-sridhar slash swarmgen. Approximately 1500 lines of Python. FastAPI, asyncio, zeroconf, no Docker, no Kubernetes, no Ray. Thanks for watching."

## Backup notes

- If a worker is unresponsive at recording time, restart in this order: pc CLIP, then pi VAE, then loq UNet.
- If mDNS is flaky, the UI was launched with `--workers` so it does not depend on discovery for the run.
- The "kill VAE" button sends `/admin/die` regardless of the fault-injection dropdown — useful for ad-hoc demos.
