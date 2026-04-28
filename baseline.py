"""
Single-device SD-Turbo baseline.
Runs the full pipeline locally on whichever device is available, for the latency comparison.

Usage:
    python baseline.py --prompt "..." --runs 10 --csv results/baseline_latency.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path

import psutil
import torch


log = logging.getLogger("swarmgen.baseline")


def main() -> int:
    p = argparse.ArgumentParser(description="Single-device SD-Turbo baseline.")
    p.add_argument("--prompt", default="a photo of a red fox in a snowy forest")
    p.add_argument("--prompts-file", type=Path, default=None,
                   help="optional file: one prompt per line; cycles per run")
    p.add_argument("--runs", type=int, default=1, help="number of generations to time")
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--height", type=int, default=512)
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--out-dir", type=Path, default=Path("outputs/baseline"))
    p.add_argument("--csv", type=Path, default=Path("results/baseline_latency.csv"))
    p.add_argument("--device", default=None, help="cuda or cpu (auto-detect by default)")
    p.add_argument("--dtype", default=None, choices=[None, "fp16", "fp32"])
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s | %(message)s")

    if args.device is None:
        args.device = "cuda" if torch.cuda.is_available() else "cpu"
    if args.dtype is None:
        args.dtype = "fp16" if args.device == "cuda" else "fp32"
    dtype = torch.float16 if args.dtype == "fp16" else torch.float32

    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.csv.parent.mkdir(parents=True, exist_ok=True)

    log.info("device=%s dtype=%s steps=%d runs=%d", args.device, dtype, args.steps, args.runs)

    from diffusers import StableDiffusionPipeline

    log.info("loading pipeline (this is a 1-device baseline; needs full model)")
    t_load_0 = time.perf_counter()
    pipe = StableDiffusionPipeline.from_pretrained(
        "stabilityai/sd-turbo", torch_dtype=dtype, safety_checker=None
    ).to(args.device)
    pipe.set_progress_bar_config(disable=True)
    load_ms = (time.perf_counter() - t_load_0) * 1000
    log.info("model load: %.0f ms", load_ms)

    if args.prompts_file:
        prompts = [ln.strip() for ln in args.prompts_file.read_text(encoding="utf-8").splitlines()
                   if ln.strip() and not ln.strip().startswith("#")]
        if not prompts:
            log.error("no prompts in file")
            return 2
    else:
        prompts = [args.prompt]

    rows = []
    proc = psutil.Process()
    peak_rss_mb = proc.memory_info().rss / (1024 * 1024)
    for i in range(args.runs):
        prompt = prompts[i % len(prompts)]
        seed = args.seed + i
        g = torch.Generator(device=args.device).manual_seed(seed)
        torch.cuda.synchronize() if args.device == "cuda" else None
        t0 = time.perf_counter()
        img = pipe(
            prompt,
            num_inference_steps=args.steps,
            guidance_scale=0.0,
            height=args.height, width=args.width,
            generator=g,
        ).images[0]
        if args.device == "cuda":
            torch.cuda.synchronize()
        ms = (time.perf_counter() - t0) * 1000
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        peak_rss_mb = max(peak_rss_mb, rss_mb)
        out_path = args.out_dir / f"baseline-{i:02d}.png"
        img.save(out_path)
        log.info("[%d/%d] '%s' -> %.0f ms, rss=%.1f MB", i + 1, args.runs, prompt[:50], ms, rss_mb)
        rows.append({
            "run_idx": i, "prompt": prompt, "seed": seed,
            "total_ms": round(ms, 2),
            "rss_mb_after": round(rss_mb, 1),
            "device": args.device, "dtype": args.dtype,
            "steps": args.steps, "height": args.height, "width": args.width,
            "image": str(out_path),
        })

    with args.csv.open("w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    log.info("wrote %s (%d rows). peak RSS during runs: %.1f MB", args.csv, len(rows), peak_rss_mb)
    print(f"\nbaseline summary: device={args.device} dtype={args.dtype} steps={args.steps}")
    print(f"  runs={args.runs}  mean={sum(r['total_ms'] for r in rows)/len(rows):.0f} ms  "
          f"peak_rss={peak_rss_mb:.0f} MB  csv={args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
