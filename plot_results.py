"""
Render the paper figures from results/*.csv and the JSON batch sidecars.

Outputs PNGs to paper/figs/.
Run:
    python plot_results.py
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


RESULTS = Path("results")
FIGS = Path("paper/figs")
OUTPUTS = Path("outputs")
FIGS.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "figure.dpi": 130,
})


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(x: str) -> float:
    try:
        return float(x)
    except (ValueError, TypeError):
        return float("nan")


# -----------------------------------------------------------------------------
# 1. latency comparison
# -----------------------------------------------------------------------------
def plot_latency() -> None:
    rows_baseline = _read_csv(RESULTS / "baseline_latency.csv")
    rows_loq = _read_csv(RESULTS / "latency_3dev_loq_vae.csv")
    rows_pi = _read_csv(RESULTS / "latency_3dev_pi.csv")

    def mean_total(rows: List[Dict[str, str]], key: str = "total_ms") -> tuple[float, float]:
        vals = [_f(r[key]) for r in rows if _f(r.get(key, "nan")) == _f(r.get(key, "nan"))]
        # skip first (warm-up) for baseline
        if not vals: return float("nan"), float("nan")
        if len(vals) > 3:
            vals = vals[1:]
        return float(np.mean(vals)), float(np.std(vals))

    configs = []
    means = []
    stds = []
    if rows_baseline:
        m, s = mean_total(rows_baseline, "total_ms")
        configs.append("1-dev baseline\n(loq, full pipeline)"); means.append(m); stds.append(s)
    if rows_loq:
        m, s = mean_total(rows_loq, "total_ms")
        configs.append("3-dev swarm\n(VAE on loq GPU)"); means.append(m); stds.append(s)
    if rows_pi:
        m, s = mean_total(rows_pi, "total_ms")
        configs.append("3-dev swarm\n(VAE on Pi CPU)"); means.append(m); stds.append(s)

    if not configs:
        print("plot_latency: no data, skipping")
        return

    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ["#3a78c2", "#56a366", "#c2562d"][: len(configs)]
    x = np.arange(len(configs))
    bars = ax.bar(x, means, yerr=stds, capsize=4, color=colors, edgecolor="black", linewidth=0.5)
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, m, f"{m:,.0f} ms",
                ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(configs)
    ax.set_ylabel("end-to-end latency per image (ms, log scale)")
    ax.set_yscale("log")
    ax.set_title("Single-image latency by configuration (4-step SD-Turbo, 512x512)")
    ax.grid(True, axis="y", alpha=0.3, which="both")
    fig.tight_layout()
    out = FIGS / "latency_comparison.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"wrote {out}")


# -----------------------------------------------------------------------------
# 2. memory per device per config
# -----------------------------------------------------------------------------
def plot_memory() -> None:
    # 1-device peak from baseline
    rows_baseline = _read_csv(RESULTS / "baseline_latency.csv")
    baseline_peak = max((_f(r.get("rss_mb_after", "nan")) for r in rows_baseline), default=0.0)

    # 3-device-with-pi peaks from memory_3dev_pi.csv
    rows_mem = _read_csv(RESULTS / "memory_3dev_pi.csv")
    per_role: Dict[str, float] = {}
    for r in rows_mem:
        role = r["role"]
        peak = _f(r.get("peak_mb", "nan"))
        if not math.isnan(peak):
            per_role[role] = max(per_role.get(role, 0.0), peak)

    fig, ax = plt.subplots(figsize=(7, 4))
    labels = ["1-dev baseline\n(loq alone)", "3-dev swarm — loq UNet",
              "3-dev swarm — pc CLIP", "3-dev swarm — pi VAE"]
    values = [
        baseline_peak,
        per_role.get("unet", 0.0),
        per_role.get("clip", 0.0),
        per_role.get("vae", 0.0),
    ]
    pi_total = 1845  # approx Pi 4B 2GB total RAM
    colors = ["#666666", "#3a78c2", "#56a366", "#c2562d"]

    x = np.arange(len(labels))
    bars = ax.bar(x, values, color=colors, edgecolor="black", linewidth=0.5)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v, f"{v:,.0f} MB",
                ha="center", va="bottom", fontsize=9)
    ax.axhline(pi_total, color="red", linestyle="--", alpha=0.6,
               label=f"Pi 4B physical RAM ({pi_total} MB)")
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("peak RSS during one generation (MB)")
    ax.set_title("Per-device peak memory: single-device vs heterogeneous swarm")
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    out = FIGS / "memory_per_device.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"wrote {out}")


# -----------------------------------------------------------------------------
# 3. batch throughput
# -----------------------------------------------------------------------------
def plot_throughput() -> None:
    # Pull from JSON sidecars where possible; fall back to log values.
    points = []
    p1 = OUTPUTS / "batch_with_pi" / "batch_summary.json"
    p2 = OUTPUTS / "batch_no_pi" / "batch_summary.json"
    for p, label, color in [
        (p1, "3-dev swarm (Pi VAE)", "#c2562d"),
        (p2, "3-dev swarm (loq VAE fallback)", "#56a366"),
    ]:
        if p.exists():
            d = json.loads(p.read_text())
            points.append((label, d["n_completed"], d["throughput_imgs_per_min"], color))

    if not points:
        print("plot_throughput: no data, skipping")
        return

    fig, ax = plt.subplots(figsize=(7, 4))
    labels = [pt[0] for pt in points]
    vals = [pt[2] for pt in points]
    colors = [pt[3] for pt in points]
    bars = ax.bar(np.arange(len(labels)), vals, color=colors, edgecolor="black", linewidth=0.5)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, v, f"{v:.2f}",
                ha="center", va="bottom", fontsize=9)
    ax.set_xticks(np.arange(len(labels))); ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("throughput (images / minute)")
    ax.set_yscale("log")
    ax.set_title("Batch throughput (4 prompts, pipeline-parallel)")
    ax.grid(True, axis="y", alpha=0.3, which="both")
    fig.tight_layout()
    out = FIGS / "throughput_scaling.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"wrote {out}")


# -----------------------------------------------------------------------------
# 4. fault recovery
# -----------------------------------------------------------------------------
def plot_fault() -> None:
    """
    Pull a fault-injected sidecar (saved by the coordinator with __fault- suffix).
    Show the per-stage timeline and which worker handled VAE.
    """
    candidates = list(OUTPUTS.glob("*__fault-vae.json"))
    if not candidates:
        print("plot_fault: no fault sidecar found, skipping")
        return
    d = json.loads(candidates[0].read_text())
    t = d["timings_ms"]
    stages = ["clip", "unet", "vae"]
    durations = [t.get(s, 0) for s in stages]
    workers = [d["workers_used"][s].split("@")[1] for s in stages]

    fig, ax = plt.subplots(figsize=(8, 3.2))
    starts = [0]
    for x in durations[:-1]:
        starts.append(starts[-1] + x)
    colors = ["#3a78c2", "#56a366", "#c2562d"]
    for i, (st, dur, who) in enumerate(zip(stages, durations, workers)):
        ax.barh(0, dur, left=starts[i], color=colors[i], edgecolor="black", linewidth=0.5,
                label=f"{st}  via {who}")
        ax.text(starts[i] + dur / 2, 0, f"{st}\n{dur:.0f} ms",
                ha="center", va="center", fontsize=9, color="white", fontweight="bold")
    fault_at = 1000  # ms (fault_delay = 1.0s)
    ax.axvline(fault_at, color="red", linestyle="--", linewidth=2)
    ax.text(fault_at, 0.45, "kill Pi VAE worker", color="red", ha="center",
            fontsize=9, fontweight="bold")
    ax.set_yticks([])
    ax.set_xlabel("ms since generation start")
    total = sum(durations)
    ax.set_title(f"Fault recovery timeline (Pi VAE killed at t=1000 ms; total = {total:.0f} ms)")
    ax.set_xlim(0, total * 1.05)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    out = FIGS / "fault_recovery.png"
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print(f"wrote {out}")


def main() -> None:
    plot_latency()
    plot_memory()
    plot_throughput()
    plot_fault()


if __name__ == "__main__":
    main()
