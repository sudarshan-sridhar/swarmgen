"""
SwarmGen Gradio demo UI.

Run on loq:
    python ui.py --workers clip@192.168.1.39:8001,unet@192.168.1.16:8002,vae@192.168.1.185:8003

Open http://localhost:7860.

Design spec lives in DESIGN.md. Key choices:
    - Geist + Geist Mono via Google Fonts.
    - Zinc neutrals with a single Live Emerald accent.
    - Failure Crimson reserved for the kill button and DEAD status only.
    - Workers table and per-stage timing rendered as styled HTML for density control.
    - Two-column split: controls 2fr, output 3fr. Workers table full width below.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import logging
from pathlib import Path
from typing import List, Tuple

import gradio as gr
import httpx

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
    background_fill_primary="#ffffff",
    border_color_primary="#e4e4e7",
    block_border_width="1px",
    block_radius="14px",
    block_shadow="none",
    button_primary_background_fill="#18181b",
    button_primary_background_fill_hover="#27272a",
    button_primary_text_color="#ffffff",
    button_secondary_background_fill="#ffffff",
    button_secondary_text_color="#18181b",
    button_secondary_border_color="#e4e4e7",
    input_background_fill="#ffffff",
    input_border_color="#e4e4e7",
    input_border_color_focus="#10b981",
)


CUSTOM_CSS = r"""
:root {
    --ink: #18181b;
    --steel: #52525b;
    --whisper: #71717a;
    --border: #e4e4e7;
    --canvas: #fafafa;
    --emerald: #10b981;
    --crimson: #b91c1c;
    --crimson-bg: #fee2e2;
    --code-wash: #f4f4f5;
}

footer { display: none !important; }

.gradio-container {
    max-width: 1280px !important;
    margin: 0 auto !important;
    padding: 32px 24px 64px !important;
    background: var(--canvas) !important;
}

/* hero */
#sg-hero { padding: 0 !important; border: none !important; background: transparent !important; }
#sg-hero h1 {
    font-size: 30px;
    letter-spacing: -0.025em;
    font-weight: 600;
    color: var(--ink);
    margin: 0 0 6px 0;
    line-height: 1.05;
}
#sg-hero p {
    color: var(--steel);
    font-size: 14px;
    line-height: 1.55;
    max-width: 65ch;
    margin: 0;
}

/* eyebrow labels */
.sg-eyebrow {
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--whisper);
    font-weight: 500;
    margin: 0 0 8px 2px;
}

/* tighten all gradio blocks */
.gradio-container .block {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}

/* form controls -- white surface, zinc border, emerald focus */
.gradio-container textarea,
.gradio-container input[type="text"],
.gradio-container input[type="number"],
.gradio-container .wrap-inner input {
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--ink) !important;
    font-size: 14px !important;
    line-height: 1.5 !important;
}
.gradio-container textarea:focus,
.gradio-container input:focus {
    border-color: var(--emerald) !important;
    box-shadow: 0 0 0 2px rgba(16,185,129,0.15) !important;
    outline: none !important;
}
.gradio-container label > .label-wrap > span,
.gradio-container .label > span {
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    color: var(--whisper) !important;
    font-weight: 500 !important;
}

/* primary button -- charcoal ink, tactile press */
.gradio-container button.primary,
#sg-generate-btn button {
    background: var(--ink) !important;
    color: #ffffff !important;
    border: 1px solid var(--ink) !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    padding: 10px 18px !important;
    transition: transform 0.06s ease, background 0.15s ease;
}
.gradio-container button.primary:hover { background: #27272a !important; }
.gradio-container button.primary:active { transform: translateY(1px); }

/* kill button -- crimson, restrained */
#sg-kill-btn button {
    background: #ffffff !important;
    color: var(--crimson) !important;
    border: 1px solid #fecaca !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    padding: 10px 14px !important;
    transition: background 0.15s ease, transform 0.06s ease;
}
#sg-kill-btn button:hover { background: var(--crimson-bg) !important; }
#sg-kill-btn button:active { transform: translateY(1px); }

/* image frame */
#sg-image, #sg-image .image-container {
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    overflow: hidden;
}
#sg-image .empty {
    color: var(--whisper) !important;
    font-size: 13px !important;
}

/* summary line */
#sg-summary {
    font-size: 13.5px;
    color: var(--ink);
    min-height: 22px;
    margin-top: 4px;
}
#sg-summary code {
    font-family: var(--font-mono);
    font-size: 12px;
    background: var(--code-wash);
    padding: 1px 6px;
    border-radius: 4px;
    color: var(--ink);
}
#sg-summary strong { font-weight: 600; }

/* per-stage timing (HTML rendered) */
.sg-stage-tbl {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: 12.5px;
    font-variant-numeric: tabular-nums;
    background: #ffffff;
}
.sg-stage-tbl th {
    text-align: left;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 10px;
    font-weight: 500;
    color: var(--whisper);
    padding: 8px 12px;
    background: #fafafa;
    border-bottom: 1px solid var(--border);
}
.sg-stage-tbl td {
    padding: 9px 12px;
    border-top: 1px solid var(--border);
    color: var(--ink);
}
.sg-stage-tbl td.num { text-align: right; font-weight: 500; }
.sg-stage-tbl td.host { color: var(--whisper); font-size: 11.5px; }
.sg-stage-tbl tr:first-child td { border-top: none; }

/* workers table (HTML rendered) */
.sg-workers {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    font-family: var(--font-mono);
    font-size: 12.5px;
    font-variant-numeric: tabular-nums;
    background: #ffffff;
}
.sg-workers th {
    text-align: left;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 10px;
    font-weight: 500;
    color: var(--whisper);
    padding: 9px 14px;
    background: #fafafa;
    border-bottom: 1px solid var(--border);
}
.sg-workers td {
    padding: 11px 14px;
    border-top: 1px solid var(--border);
    color: var(--ink);
}
.sg-workers tr:first-child td { border-top: none; }
.sg-workers td.num { text-align: right; }
.sg-workers .role { font-weight: 600; letter-spacing: 0.04em; }
.sg-workers .host { color: var(--whisper); font-size: 11.5px; }

/* alive/dead pills */
.sg-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 3px 8px;
    border-radius: 999px;
    font-family: var(--font-mono);
}
.sg-pill.alive { background: rgba(16,185,129,0.10); color: #047857; }
.sg-pill.alive::before {
    content: "";
    width: 6px; height: 6px;
    border-radius: 999px;
    background: var(--emerald);
    box-shadow: 0 0 0 0 rgba(16,185,129,0.5);
    animation: sg-pulse 2.4s ease-out infinite;
}
.sg-pill.dead { background: rgba(185,28,28,0.08); color: var(--crimson); }
.sg-pill.dead::before {
    content: "";
    width: 6px; height: 6px;
    border-radius: 999px;
    background: var(--crimson);
}

@keyframes sg-pulse {
    0%   { box-shadow: 0 0 0 0 rgba(16,185,129,0.5); }
    70%  { box-shadow: 0 0 0 6px rgba(16,185,129,0); }
    100% { box-shadow: 0 0 0 0 rgba(16,185,129,0); }
}

/* slider tweaks */
.gradio-container input[type="range"] { accent-color: var(--emerald); }

/* Markdown body */
.gradio-container .prose, .gradio-container .markdown { color: var(--ink); }
"""


# -----------------------------------------------------------------------------
# HTML renderers (we render tables ourselves for full styling control)
# -----------------------------------------------------------------------------
def _esc(x) -> str:
    return html.escape(str(x), quote=True)


def _empty_stage_html() -> str:
    rows = "".join(
        f"<tr><td class='role'>{s}</td>"
        f"<td class='num'>—</td><td class='num'>—</td>"
        f"<td class='host'>—</td><td class='num'>0</td></tr>"
        for s in ("CLIP", "UNET", "VAE")
    )
    return (
        "<table class='sg-stage-tbl'>"
        "<thead><tr><th>stage</th><th style='text-align:right'>ms</th>"
        "<th style='text-align:right'>bytes</th><th>via</th>"
        "<th style='text-align:right'>retries</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _render_stage_html(timings_ms: dict, sizes: dict, used: dict, retries: dict) -> str:
    rows = []
    for st in ("clip", "unet", "vae"):
        ms = timings_ms.get(st, float("nan"))
        ms_s = f"{ms:,.0f}" if ms == ms else "—"
        bytes_s = f"{sizes.get(st, 0):,}"
        via = used.get(st, "—")
        if "@" in via:
            via = via.split("@", 1)[1]
        n_retries = len(retries.get(st, []))
        rows.append(
            f"<tr><td class='role'>{st.upper()}</td>"
            f"<td class='num'>{_esc(ms_s)}</td>"
            f"<td class='num'>{_esc(bytes_s)}</td>"
            f"<td class='host'>{_esc(via)}</td>"
            f"<td class='num'>{n_retries}</td></tr>"
        )
    return (
        "<table class='sg-stage-tbl'>"
        "<thead><tr><th>stage</th><th style='text-align:right'>ms</th>"
        "<th style='text-align:right'>bytes</th><th>via</th>"
        "<th style='text-align:right'>retries</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


async def _workers_html() -> str:
    timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
    rows = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for w in REGISTRY:
            alive = False
            cur_mb = "—"
            peak_mb = "—"
            try:
                r = await client.get(f"{w.url}/health", timeout=1.5)
                if r.status_code == 200:
                    d = r.json()
                    alive = True
                    cur_mb = f"{d.get('current_memory_mb', 0):.0f}"
                    peak_mb = f"{d.get('peak_memory_mb', 0):.0f}"
                    w.alive = True
            except Exception:
                w.alive = False

            pill = (
                "<span class='sg-pill alive'>alive</span>"
                if alive
                else "<span class='sg-pill dead'>dead</span>"
            )
            device = w.capabilities.get("device", "—")
            supports = ",".join(w.supported_stages)
            rows.append(
                "<tr>"
                f"<td class='role'>{_esc(w.role.upper())}</td>"
                f"<td>{_esc(device)}</td>"
                f"<td class='host'>{_esc(w.host)}:{_esc(w.port)}</td>"
                f"<td>{pill}</td>"
                f"<td class='num'>{_esc(cur_mb)}</td>"
                f"<td class='num'>{_esc(peak_mb)}</td>"
                f"<td class='host'>{_esc(supports)}</td>"
                "</tr>"
            )
    return (
        "<table class='sg-workers'>"
        "<thead><tr><th>role</th><th>device</th><th>host</th>"
        "<th>status</th><th style='text-align:right'>RSS MB</th>"
        "<th style='text-align:right'>peak MB</th><th>supports</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def workers_html_sync() -> str:
    return asyncio.run(_workers_html())


# -----------------------------------------------------------------------------
# Generate / kill
# -----------------------------------------------------------------------------
async def _hydrate() -> None:
    timeout = httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for w in REGISTRY:
            try:
                await C.fetch_capabilities(client, w)
            except Exception:
                w.alive = False


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
        msg = f"<strong>Failed</strong> &nbsp;<code>{_esc(type(e).__name__)}: {_esc(str(e))}</code>"
        return None, _empty_stage_html(), msg

    stage_html = _render_stage_html(res.timings_ms, res.bytes_per_stage,
                                    res.workers_used, res.retries)
    fault_note = f" &nbsp;<code>fault on {_esc(fault_stage)} at t=1s</code>" if fault_stage else ""
    summary = f"<strong>Total</strong> &nbsp;<code>{res.total_ms:,.0f} ms</code>{fault_note}"
    return str(res.image_path), stage_html, summary


def generate_sync(prompt: str, seed: int, steps: int, fault: str):
    if not prompt or not prompt.strip():
        return None, _empty_stage_html(), "<strong>Failed</strong> &nbsp;<code>enter a prompt first</code>"
    return asyncio.run(_generate(prompt, seed, steps, fault))


async def _kill_vae() -> str:
    timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
    target = next((w for w in REGISTRY if w.role == "vae"), None)
    if target is None:
        return "<strong>No VAE worker registered.</strong>"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            await client.post(f"{target.url}/admin/die")
        except Exception:
            pass
    return (
        f"<strong>Sent</strong> &nbsp;<code>POST /admin/die</code>&nbsp;to&nbsp;"
        f"<code>{_esc(target.host)}:{_esc(target.port)}</code>"
        " &nbsp;— generate again to watch the fallback take over."
    )


def kill_vae_sync() -> str:
    return asyncio.run(_kill_vae())


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="SwarmGen", theme=THEME, css=CUSTOM_CSS) as ui:

        with gr.Row(elem_id="sg-hero"):
            gr.HTML(
                """
                <div>
                  <h1>SwarmGen</h1>
                  <p>Stable Diffusion Turbo, partitioned across three heterogeneous edge
                  devices. CLIP runs on a CPU laptop, UNet on an RTX 5060, VAE on a
                  Raspberry Pi 4B. Heartbeat-driven fault tolerance reroutes the VAE
                  stage to the GPU when the Pi dies mid-flight.</p>
                </div>
                """
            )

        with gr.Row(equal_height=False):
            # ---------- left: controls ----------
            with gr.Column(scale=2, min_width=380):
                gr.HTML('<div class="sg-eyebrow">prompt</div>')
                prompt = gr.Textbox(
                    show_label=False, lines=3, container=False,
                    value="a watercolor painting of a lighthouse at dusk",
                    placeholder="describe the image...",
                )

                with gr.Row():
                    seed = gr.Number(label="seed", value=42, precision=0,
                                     minimum=0, maximum=2**31 - 1, container=True)
                    steps = gr.Slider(label="steps", minimum=1, maximum=8, step=1,
                                      value=4, container=True)
                    fault = gr.Dropdown(
                        label="fault inject",
                        choices=["none", "vae"], value="none", container=True,
                    )

                with gr.Row():
                    btn = gr.Button("generate", variant="primary",
                                    elem_id="sg-generate-btn", scale=2)
                    kill_btn = gr.Button("kill Pi VAE worker",
                                         elem_id="sg-kill-btn", scale=1)

                summary = gr.HTML(elem_id="sg-summary")

                gr.HTML('<div class="sg-eyebrow" style="margin-top:24px">per-stage timing</div>')
                stages = gr.HTML(value=_empty_stage_html())

            # ---------- right: image ----------
            with gr.Column(scale=3, min_width=420):
                gr.HTML('<div class="sg-eyebrow">output</div>')
                image = gr.Image(
                    show_label=False, type="filepath",
                    height=512, elem_id="sg-image", container=False,
                )

        # ---------- workers ----------
        gr.HTML('<div class="sg-eyebrow" style="margin-top:32px">workers — refreshes every 2 s</div>')
        workers = gr.HTML(value=workers_html_sync())
        timer = gr.Timer(value=2.0, active=True)
        timer.tick(fn=workers_html_sync, outputs=[workers])

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
