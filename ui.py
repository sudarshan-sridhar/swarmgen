"""
SwarmGen Gradio demo UI.

Run on loq:
    python ui.py --workers clip@192.168.1.39:8001,unet@192.168.1.16:8002,vae@192.168.1.185:8003

Then open http://localhost:7860 in a browser.

Features:
    - prompt -> image
    - live worker health panel (refresh every 2s)
    - "kill VAE worker" button to demo fault recovery on camera
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path
from typing import List, Tuple

import gradio as gr
import httpx
import pandas as pd

import coordinator as C


log = logging.getLogger("swarmgen.ui")


REGISTRY: List[C.Worker] = []
HEARTBEAT: C.HeartbeatMonitor = None  # type: ignore


async def _hydrate() -> None:
    timeout = httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for w in REGISTRY:
            try:
                await C.fetch_capabilities(client, w)
            except Exception:
                w.alive = False


async def _health_table() -> pd.DataFrame:
    timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
    rows = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for w in REGISTRY:
            row = {
                "role": w.role,
                "host": w.host,
                "port": w.port,
                "device": w.capabilities.get("device", "?"),
                "dtype": w.capabilities.get("dtype", "?"),
                "alive": False,
                "current_mb": "",
                "peak_mb": "",
                "supports": ",".join(w.supported_stages),
            }
            try:
                r = await client.get(f"{w.url}/health", timeout=1.5)
                if r.status_code == 200:
                    d = r.json()
                    row["alive"] = True
                    row["current_mb"] = f"{d.get('current_memory_mb', 0):.0f}"
                    row["peak_mb"] = f"{d.get('peak_memory_mb', 0):.0f}"
                    w.alive = True
            except Exception:
                w.alive = False
            rows.append(row)
    return pd.DataFrame(rows)


def health_table_sync() -> pd.DataFrame:
    return asyncio.run(_health_table())


async def _generate(prompt: str, seed: int, steps: int, fault: str) -> Tuple[str, pd.DataFrame, str]:
    fault_stage = fault if fault and fault != "none" else None
    res = await C.generate(
        REGISTRY, prompt,
        out_dir=Path("outputs") / "ui",
        steps=steps, seed=seed,
        fault_stage=fault_stage, fault_delay_s=1.0,
    )
    rows = []
    for st in ("clip", "unet", "vae"):
        rows.append({
            "stage": st,
            "ms": f"{res.timings_ms.get(st, float('nan')):.0f}",
            "bytes": res.bytes_per_stage.get(st, 0),
            "worker": res.workers_used.get(st, "?"),
            "retries": len(res.retries.get(st, [])),
        })
    df = pd.DataFrame(rows)
    summary = (
        f"**Total**: {res.total_ms:.0f} ms"
        + (f"  |  fault injected on {fault_stage}" if fault_stage else "")
    )
    return str(res.image_path), df, summary


def generate_sync(prompt: str, seed: int, steps: int, fault: str):
    return asyncio.run(_generate(prompt, seed, steps, fault))


async def _kill_vae() -> str:
    timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
    target = next((w for w in REGISTRY if w.role == "vae"), None)
    if target is None:
        return "no VAE worker in registry"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            await client.post(f"{target.url}/admin/die")
        except Exception as e:
            return f"sent /admin/die to {target}: {e}"
    return f"sent /admin/die to {target}"


def kill_vae_sync() -> str:
    return asyncio.run(_kill_vae())


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="SwarmGen — distributed SD-Turbo demo", theme=gr.themes.Soft()) as ui:
        gr.Markdown(
            """
            # SwarmGen
            **Distributed Stable Diffusion Turbo across 3 heterogeneous edge devices.**
            CLIP on a CPU laptop, UNet on an RTX 5060 box, VAE on a Raspberry Pi 4B.
            Heartbeat monitor + fallback workers means a device can die mid-generation
            and the image still completes.
            """
        )
        with gr.Row():
            with gr.Column(scale=2):
                prompt = gr.Textbox(label="prompt", value="a photo of a red fox in a snowy forest", lines=2)
                with gr.Row():
                    seed = gr.Slider(label="seed", minimum=0, maximum=2**31 - 1, step=1, value=42)
                    steps = gr.Slider(label="denoising steps", minimum=1, maximum=8, step=1, value=4)
                fault = gr.Dropdown(label="fault inject (kills the worker 1 s into the run)",
                                    choices=["none", "vae", "unet", "clip"], value="none")
                with gr.Row():
                    btn = gr.Button("generate", variant="primary")
                    kill_btn = gr.Button("kill VAE worker now (manual)", variant="stop")
                summary = gr.Markdown()
                stages = gr.Dataframe(label="per-stage timing", headers=["stage","ms","bytes","worker","retries"])
            with gr.Column(scale=3):
                image = gr.Image(label="generated image", type="filepath")

        with gr.Accordion("worker health (refresh every 2 s)", open=True):
            health = gr.Dataframe(value=health_table_sync(),
                                  headers=["role","host","port","device","dtype","alive","current_mb","peak_mb","supports"])
            timer = gr.Timer(value=2.0, active=True)
            timer.tick(fn=health_table_sync, outputs=[health])

        btn.click(generate_sync, inputs=[prompt, seed, steps, fault],
                  outputs=[image, stages, summary])
        kill_btn.click(kill_vae_sync, outputs=[summary])

    return ui


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", required=True,
                   help="comma-separated list of role@host:port")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--share", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s")

    global REGISTRY
    REGISTRY = [C.parse_worker_spec(s) for s in args.workers.split(",") if s.strip()]
    asyncio.run(_hydrate())
    log.info("hydrated %d workers", len(REGISTRY))

    ui = build_ui()
    ui.launch(server_name="0.0.0.0", server_port=args.port, share=args.share, inbrowser=False)


if __name__ == "__main__":
    main()
