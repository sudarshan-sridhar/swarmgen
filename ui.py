"""
SwarmGen Gradio demo UI.

Run on loq:
    python ui.py --workers clip@192.168.1.39:8001,unet@192.168.1.16:8002,vae@192.168.1.185:8003

Then open http://localhost:7860 in a browser.

Features:
    - prompt -> image
    - live worker health panel (refresh every 2s)
    - kill VAE worker on demand to demonstrate fault recovery
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


# -----------------------------------------------------------------------------
# Theme + CSS
# -----------------------------------------------------------------------------
THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.emerald,
    neutral_hue=gr.themes.colors.zinc,
    font=[gr.themes.GoogleFont("Geist"), "ui-sans-serif", "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("Geist Mono"), "ui-monospace", "Menlo", "Consolas", "monospace"],
).set(
    body_background_fill="#fafafa",
    body_background_fill_dark="#0a0a0a",
    background_fill_primary="#ffffff",
    background_fill_primary_dark="#101010",
    border_color_primary="#e4e4e7",
    border_color_primary_dark="#27272a",
    block_border_width="1px",
    block_radius="14px",
    block_shadow="none",
    button_primary_background_fill="#18181b",
    button_primary_background_fill_dark="#fafafa",
    button_primary_background_fill_hover="#27272a",
    button_primary_text_color="#fafafa",
    button_primary_text_color_dark="#18181b",
    button_secondary_background_fill="#ffffff",
    button_secondary_background_fill_dark="#171717",
    button_secondary_text_color="#18181b",
    button_secondary_border_color="#e4e4e7",
)


CUSTOM_CSS = """
/* tighten the page; cap width like a real dashboard */
.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
    padding: 24px 24px 64px !important;
}

/* header block */
#sg-hero h1 {
    font-size: 28px;
    letter-spacing: -0.02em;
    font-weight: 600;
    margin: 0 0 4px 0;
}
#sg-hero p {
    color: #52525b;
    font-size: 14px;
    line-height: 1.55;
    max-width: 65ch;
    margin: 0;
}

/* eyebrow label above sections */
.sg-eyebrow {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #71717a;
    margin: 0 0 8px 2px;
    font-weight: 500;
}

/* monospace numbers in stats / tables */
.sg-mono, .sg-mono * { font-variant-numeric: tabular-nums; font-family: var(--font-mono) !important; }

/* status table tweaks */
.sg-status table { font-size: 12.5px; }
.sg-status table th { font-weight: 500; color: #71717a; text-transform: uppercase; letter-spacing: 0.05em; font-size: 10.5px; }
.sg-status table td { padding: 8px 10px !important; }
.sg-status .alive-true { color: #10b981; font-weight: 600; }
.sg-status .alive-false { color: #ef4444; font-weight: 600; }

/* per-stage timing table */
.sg-stages table td:nth-child(2) { text-align: right; font-variant-numeric: tabular-nums; }
.sg-stages table td:nth-child(3) { text-align: right; font-variant-numeric: tabular-nums; color: #71717a; }
.sg-stages table td:nth-child(4) { font-family: var(--font-mono); font-size: 11.5px; color: #71717a; }

/* tactile button press */
button:active { transform: translateY(1px); }

/* danger button (kill VAE) restraint */
#sg-kill-btn {
    background: #ffffff;
    color: #b91c1c;
    border: 1px solid #fecaca !important;
}
#sg-kill-btn:hover { background: #fee2e2; }

/* primary generate button — make it the obvious action */
#sg-generate-btn { font-weight: 600; }

/* result image frame */
#sg-image .image-container { border-radius: 12px; overflow: hidden; }

/* summary line */
#sg-summary { font-size: 13.5px; color: #3f3f46; min-height: 22px; }
#sg-summary code { font-family: var(--font-mono); font-size: 12.5px; background: #f4f4f5; padding: 1px 6px; border-radius: 4px; }
"""


# -----------------------------------------------------------------------------
# Async helpers
# -----------------------------------------------------------------------------
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
                "role": w.role.upper(),
                "device": w.capabilities.get("device", "?"),
                "host": f"{w.host}:{w.port}",
                "status": "DEAD",
                "current MB": "—",
                "peak MB": "—",
                "supports": ",".join(w.supported_stages),
            }
            try:
                r = await client.get(f"{w.url}/health", timeout=1.5)
                if r.status_code == 200:
                    d = r.json()
                    row["status"] = "ALIVE"
                    row["current MB"] = f"{d.get('current_memory_mb', 0):.0f}"
                    row["peak MB"] = f"{d.get('peak_memory_mb', 0):.0f}"
                    w.alive = True
            except Exception:
                w.alive = False
            rows.append(row)
    return pd.DataFrame(rows)


def health_table_sync() -> pd.DataFrame:
    return asyncio.run(_health_table())


_EMPTY_STAGES = pd.DataFrame([
    {"stage": "CLIP", "ms": "—", "bytes": "—", "via": "—", "retries": 0},
    {"stage": "UNET", "ms": "—", "bytes": "—", "via": "—", "retries": 0},
    {"stage": "VAE",  "ms": "—", "bytes": "—", "via": "—", "retries": 0},
])


async def _generate(prompt: str, seed: int, steps: int, fault: str):
    fault_stage = fault if fault and fault != "none" else None
    try:
        res = await C.generate(
            REGISTRY, prompt,
            out_dir=Path("outputs") / "ui",
            steps=steps, seed=seed,
            fault_stage=fault_stage, fault_delay_s=1.0,
        )
    except Exception as e:
        log.exception("generate failed")
        msg = f"**Failed** `{type(e).__name__}: {e}`"
        return None, _EMPTY_STAGES.copy(), msg

    rows = []
    for st in ("clip", "unet", "vae"):
        ms = res.timings_ms.get(st, float("nan"))
        rows.append({
            "stage": st.upper(),
            "ms": f"{ms:,.0f}" if ms == ms else "—",
            "bytes": f"{res.bytes_per_stage.get(st, 0):,}",
            "via": res.workers_used.get(st, "?").split("@", 1)[-1],
            "retries": len(res.retries.get(st, [])),
        })
    df = pd.DataFrame(rows)
    fault_note = f" — fault on **{fault_stage}** at t=1s" if fault_stage else ""
    summary = f"**Total** `{res.total_ms:,.0f} ms`{fault_note}"
    return str(res.image_path), df, summary


def generate_sync(prompt: str, seed: int, steps: int, fault: str):
    if not prompt or not prompt.strip():
        return None, _EMPTY_STAGES.copy(), "**Failed** `enter a prompt first`"
    return asyncio.run(_generate(prompt, seed, steps, fault))


async def _kill_vae() -> str:
    timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
    target = next((w for w in REGISTRY if w.role == "vae"), None)
    if target is None:
        return "_no VAE worker in registry_"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            await client.post(f"{target.url}/admin/die")
        except Exception:
            pass
    return f"sent `/admin/die` to **{target.host}:{target.port}** — generate again to see fallback take over"


def kill_vae_sync() -> str:
    return asyncio.run(_kill_vae())


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="SwarmGen — distributed SD-Turbo demo", theme=THEME, css=CUSTOM_CSS) as ui:

        with gr.Row(elem_id="sg-hero"):
            gr.Markdown(
                """
                # SwarmGen
                Stable Diffusion Turbo, partitioned across three heterogeneous edge devices.
                CLIP runs on a CPU laptop, UNet on an RTX 5060, VAE on a Raspberry Pi 4B.
                Heartbeat-driven fault tolerance reroutes the VAE stage to the GPU when the Pi dies mid-flight.
                """
            )

        with gr.Row(equal_height=False):
            # ---------- left column: controls ----------
            with gr.Column(scale=2, min_width=380):
                gr.HTML('<div class="sg-eyebrow">prompt</div>')
                prompt = gr.Textbox(
                    show_label=False, lines=3,
                    value="a watercolor painting of a lighthouse at dusk",
                    placeholder="describe the image...",
                )

                with gr.Row():
                    seed = gr.Number(label="seed", value=42, precision=0, minimum=0, maximum=2**31 - 1)
                    steps = gr.Slider(label="steps", minimum=1, maximum=8, step=1, value=4)
                    fault = gr.Dropdown(
                        label="fault inject",
                        info="kills this worker 1 s into the run",
                        choices=["none", "vae"], value="none",
                    )

                with gr.Row():
                    btn = gr.Button("generate", variant="primary", elem_id="sg-generate-btn", scale=2)
                    kill_btn = gr.Button("kill Pi VAE worker", variant="secondary", elem_id="sg-kill-btn", scale=1)

                summary = gr.Markdown(elem_id="sg-summary")

                gr.HTML('<div class="sg-eyebrow" style="margin-top:18px">per-stage timing</div>')
                stages = gr.Dataframe(
                    headers=["stage", "ms", "bytes", "via", "retries"],
                    datatype=["str", "str", "str", "str", "number"],
                    interactive=False, show_label=False,
                    elem_classes=["sg-stages", "sg-mono"],
                    value=pd.DataFrame([
                        {"stage": "CLIP", "ms": "—", "bytes": "—", "via": "—", "retries": 0},
                        {"stage": "UNET", "ms": "—", "bytes": "—", "via": "—", "retries": 0},
                        {"stage": "VAE",  "ms": "—", "bytes": "—", "via": "—", "retries": 0},
                    ]),
                )

            # ---------- right column: image ----------
            with gr.Column(scale=3, min_width=400):
                gr.HTML('<div class="sg-eyebrow">output</div>')
                image = gr.Image(
                    show_label=False, type="filepath",
                    height=512, elem_id="sg-image",
                )

        # ---------- worker health (full width) ----------
        gr.HTML('<div class="sg-eyebrow" style="margin-top:24px">workers (refreshes every 2 s)</div>')
        health = gr.Dataframe(
            value=health_table_sync(),
            headers=["role", "device", "host", "status", "current MB", "peak MB", "supports"],
            interactive=False, show_label=False,
            elem_classes=["sg-status", "sg-mono"],
        )
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
