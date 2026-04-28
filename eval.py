"""
SwarmGen evaluation harness.

Subcommands:
    latency   N runs of single-image gen across configs (1-dev, 2-dev, 3-dev). Records timings.
    memory    Sample /health every 100 ms during generation; record peak RSS per worker.
    network   Per-stage byte counts (already in coordinator sidecar — this aggregates).
    batch     Batch sizes 1, 4, 8 across configs; records throughput.
    fault     N fault-injection runs; records recovery time.

Each subcommand writes results/<name>.csv. Plotting is done by plot_results.py.

Usage examples:
    python eval.py latency --workers 3dev "clip@.39:8001,unet@.16:8002,vae@.185:8003" --runs 5
    python eval.py memory  --workers 3dev "..." --prompt "..."
    python eval.py fault   --workers 3dev "..." --runs 3
    python eval.py batch   --workers 3dev "..." --sizes 1,4,8
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

# Re-use coordinator internals.
import coordinator as C


log = logging.getLogger("swarmgen.eval")


# -----------------------------------------------------------------------------
# Common helpers
# -----------------------------------------------------------------------------
def parse_workers(spec: str) -> List[C.Worker]:
    return [C.parse_worker_spec(s) for s in spec.split(",") if s.strip()]


async def hydrate_capabilities(workers: List[C.Worker]) -> None:
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for w in workers:
            try:
                await C.fetch_capabilities(client, w)
            except Exception:
                log.exception("could not hydrate %s", w)
                w.alive = False


PROMPTS_DEFAULT = [
    "a photo of a red fox in a snowy forest",
    "a watercolor painting of a lighthouse at dusk",
    "a steampunk airship over Venice canals",
    "a cyberpunk city skyline at night, neon reflections",
    "an oil painting of a cottage in a wheat field",
]


# -----------------------------------------------------------------------------
# Memory sampler (background task)
# -----------------------------------------------------------------------------
class MemorySampler:
    """Polls /health on each worker every `interval` and records the peak."""
    def __init__(self, workers: List[C.Worker], interval: float = 0.1):
        self.workers = workers
        self.interval = interval
        self.samples: List[Dict[str, Any]] = []  # rows: ts, host, role, current_mb, peak_mb
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def _run(self) -> None:
        timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            while not self._stop.is_set():
                ts = time.time()
                async def _one(w):
                    try:
                        r = await client.get(f"{w.url}/health", timeout=1.0)
                        if r.status_code == 200:
                            d = r.json()
                            self.samples.append({
                                "ts": ts, "host": w.host, "port": w.port, "role": w.role,
                                "current_mb": d.get("current_memory_mb"),
                                "peak_mb": d.get("peak_memory_mb"),
                            })
                    except Exception:
                        pass
                await asyncio.gather(*(_one(w) for w in self.workers))
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
                except asyncio.TimeoutError:
                    pass

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task


# -----------------------------------------------------------------------------
# latency
# -----------------------------------------------------------------------------
async def cmd_latency(args: argparse.Namespace) -> int:
    workers = parse_workers(args.workers)
    await hydrate_capabilities(workers)
    if not all(w.alive for w in workers):
        log.error("some workers unreachable; aborting")
        return 2

    prompts = PROMPTS_DEFAULT if not args.prompts_file else \
              [ln.strip() for ln in Path(args.prompts_file).read_text().splitlines()
               if ln.strip() and not ln.startswith("#")]

    out_csv = Path(args.csv) if args.csv else Path("results") / f"latency_{args.config_name}.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []

    monitor = C.HeartbeatMonitor(workers) if not args.no_heartbeat else None
    if monitor:
        monitor.start()
    try:
        for run_idx in range(args.runs):
            prompt = prompts[run_idx % len(prompts)]
            seed = args.seed + run_idx
            log.info("run %d/%d: %r (seed=%d)", run_idx + 1, args.runs, prompt[:60], seed)
            try:
                t0 = time.perf_counter()
                res = await C.generate(
                    workers, prompt,
                    out_dir=Path("outputs") / f"latency_{args.config_name}",
                    steps=args.steps, seed=seed, height=args.height, width=args.width,
                )
                wall = (time.perf_counter() - t0) * 1000
                rows.append({
                    "config": args.config_name, "run_idx": run_idx, "prompt": prompt, "seed": seed,
                    "total_ms": round(res.total_ms, 2),
                    "wall_ms": round(wall, 2),
                    "clip_ms": round(res.timings_ms.get("clip", float("nan")), 2),
                    "unet_ms": round(res.timings_ms.get("unet", float("nan")), 2),
                    "vae_ms": round(res.timings_ms.get("vae", float("nan")), 2),
                    "clip_bytes": res.bytes_per_stage.get("clip", 0),
                    "unet_bytes": res.bytes_per_stage.get("unet", 0),
                    "vae_bytes": res.bytes_per_stage.get("vae", 0),
                    "clip_worker": res.workers_used.get("clip", ""),
                    "unet_worker": res.workers_used.get("unet", ""),
                    "vae_worker": res.workers_used.get("vae", ""),
                })
            except Exception as e:
                log.exception("run %d failed", run_idx)
                rows.append({"config": args.config_name, "run_idx": run_idx, "prompt": prompt,
                             "error": f"{type(e).__name__}: {e}"})
    finally:
        if monitor:
            await monitor.stop()

    _write_csv(out_csv, rows)
    succ = [r for r in rows if "error" not in r]
    if succ:
        mean = sum(r["total_ms"] for r in succ) / len(succ)
        log.info("latency [%s]: %d runs, mean=%.0f ms, csv=%s", args.config_name, len(succ), mean, out_csv)
    return 0


# -----------------------------------------------------------------------------
# memory
# -----------------------------------------------------------------------------
async def cmd_memory(args: argparse.Namespace) -> int:
    workers = parse_workers(args.workers)
    await hydrate_capabilities(workers)

    sampler = MemorySampler(workers, interval=0.1)
    sampler.start()
    try:
        log.info("running 1 generation while sampling /health every 100 ms")
        await C.generate(workers, args.prompt,
                         out_dir=Path("outputs") / "memory",
                         steps=args.steps, seed=args.seed,
                         height=args.height, width=args.width)
    finally:
        await sampler.stop()

    out_csv = Path(args.csv) if args.csv else Path("results") / f"memory_{args.config_name}.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(out_csv, sampler.samples)
    # summary per worker
    summary: Dict[str, Dict[str, float]] = {}
    for s in sampler.samples:
        h = f"{s['role']}@{s['host']}"
        cur = summary.setdefault(h, {"min": 1e18, "peak": 0.0})
        if s["current_mb"] is not None:
            cur["min"] = min(cur["min"], s["current_mb"])
        if s["peak_mb"] is not None:
            cur["peak"] = max(cur["peak"], s["peak_mb"])
    log.info("memory peaks per worker:")
    for h, st in summary.items():
        log.info("  %-25s peak=%6.1f MB  min=%6.1f MB", h, st["peak"], st["min"])
    log.info("wrote %s (%d samples)", out_csv, len(sampler.samples))
    return 0


# -----------------------------------------------------------------------------
# network — aggregates per-stage bytes from latency rows (or runs them)
# -----------------------------------------------------------------------------
async def cmd_network(args: argparse.Namespace) -> int:
    # Reuse latency runner; the network bytes are recorded there.
    out_csv = Path(args.csv) if args.csv else Path("results") / f"network_{args.config_name}.csv"
    args.csv = str(out_csv)  # piggyback on latency
    return await cmd_latency(args)


# -----------------------------------------------------------------------------
# batch
# -----------------------------------------------------------------------------
async def cmd_batch(args: argparse.Namespace) -> int:
    workers = parse_workers(args.workers)
    await hydrate_capabilities(workers)
    if not all(w.alive for w in workers):
        log.error("some workers unreachable; aborting")
        return 2

    prompts_all = PROMPTS_DEFAULT * 3 if not args.prompts_file else \
                  [ln.strip() for ln in Path(args.prompts_file).read_text().splitlines()
                   if ln.strip() and not ln.startswith("#")]
    sizes = [int(s) for s in args.sizes.split(",")]
    out_csv = Path(args.csv) if args.csv else Path("results") / f"batch_{args.config_name}.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []

    monitor = C.HeartbeatMonitor(workers)
    monitor.start()
    try:
        for size in sizes:
            prompts = prompts_all[:size]
            log.info("batch size=%d (%d prompts)", size, len(prompts))
            t0 = time.perf_counter()
            br = await C.generate_batch(
                workers, prompts,
                out_dir=Path("outputs") / f"eval_batch_{args.config_name}_n{size}",
                steps=args.steps, seed_base=args.seed,
                height=args.height, width=args.width,
            )
            wall_ms = (time.perf_counter() - t0) * 1000
            done = sum(1 for r in br.items if r.image_path is not None)
            rows.append({
                "config": args.config_name,
                "batch_size": size,
                "completed": done,
                "wall_ms": round(wall_ms, 2),
                "throughput_imgs_per_min": round(br.throughput_imgs_per_min, 3),
                "mean_per_image_ms": round(wall_ms / max(done, 1), 2),
            })
            log.info("batch %d: %d done in %.0f ms (%.2f img/min)", size, done, wall_ms, br.throughput_imgs_per_min)
    finally:
        await monitor.stop()

    _write_csv(out_csv, rows)
    log.info("wrote %s", out_csv)
    return 0


# -----------------------------------------------------------------------------
# fault
# -----------------------------------------------------------------------------
async def cmd_fault(args: argparse.Namespace) -> int:
    workers = parse_workers(args.workers)
    await hydrate_capabilities(workers)
    if not all(w.alive for w in workers):
        log.error("some workers unreachable; aborting")
        return 2

    out_csv = Path(args.csv) if args.csv else Path("results") / f"fault_{args.config_name}.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []

    for run_idx in range(args.runs):
        # Re-hydrate alive flags before each fault run because we just killed something last time.
        for w in workers:
            w.alive = True
            w.consecutive_misses = 0
        # Also: the killed worker needs to have been restarted between fault runs.
        # We don't restart it programmatically; the operator does. So we skip retry
        # if a previously killed worker is unreachable.
        await hydrate_capabilities(workers)
        if not all(w.alive for w in workers):
            log.warning("worker(s) unreachable before fault run %d — did you restart them? skipping",
                        run_idx + 1)
            rows.append({"config": args.config_name, "run_idx": run_idx,
                         "error": "precheck-failed (some workers unreachable)"})
            continue

        prompt = PROMPTS_DEFAULT[run_idx % len(PROMPTS_DEFAULT)]
        log.info("fault run %d/%d (target=%s, prompt=%r)",
                 run_idx + 1, args.runs, args.target, prompt[:50])
        monitor = C.HeartbeatMonitor(workers)
        monitor.start()
        try:
            t0 = time.perf_counter()
            res = await C.generate(
                workers, prompt,
                out_dir=Path("outputs") / f"fault_{args.config_name}",
                steps=args.steps, seed=args.seed + run_idx,
                fault_stage=args.target, fault_delay_s=args.fault_delay,
            )
            wall = (time.perf_counter() - t0) * 1000
            rows.append({
                "config": args.config_name, "run_idx": run_idx, "prompt": prompt,
                "fault_target": args.target, "fault_delay_s": args.fault_delay,
                "wall_ms": round(wall, 2), "total_ms": round(res.total_ms, 2),
                "vae_ms": round(res.timings_ms.get("vae", float('nan')), 2),
                "vae_worker": res.workers_used.get("vae", ""),
                "retries_total": sum(len(v) for v in res.retries.values()),
                "image": str(res.image_path),
            })
            log.info("fault run %d ok: total=%.0f ms, vae via %s",
                     run_idx + 1, res.total_ms, res.workers_used.get("vae"))
        except Exception as e:
            log.exception("fault run %d failed", run_idx + 1)
            rows.append({"config": args.config_name, "run_idx": run_idx, "prompt": prompt,
                         "fault_target": args.target,
                         "error": f"{type(e).__name__}: {e}"})
        finally:
            await monitor.stop()
        # Pause so the operator can restart the killed worker before the next run.
        if run_idx + 1 < args.runs:
            log.warning("paused 8s for the killed %s worker to be restarted manually",
                        args.target)
            await asyncio.sleep(8)

    _write_csv(out_csv, rows)
    log.info("wrote %s", out_csv)
    return 0


# -----------------------------------------------------------------------------
# CSV writer
# -----------------------------------------------------------------------------
def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    keys: List[str] = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                keys.append(k)
                seen.add(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workers", required=True, help="role@host:port,role@host:port,...")
    p.add_argument("--config-name", required=True, help="label for the CSV (e.g. 1dev, 3dev_pi, 3dev_loq_vae)")
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--height", type=int, default=512)
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--csv", default=None)
    p.add_argument("--no-heartbeat", action="store_true")


def main() -> int:
    p = argparse.ArgumentParser(description="SwarmGen evaluation harness.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("latency"); add_common(pl)
    pl.add_argument("--runs", type=int, default=5)
    pl.add_argument("--prompts-file", type=Path, default=None)

    pm = sub.add_parser("memory"); add_common(pm)
    pm.add_argument("--prompt", default=PROMPTS_DEFAULT[0])

    pn = sub.add_parser("network"); add_common(pn)
    pn.add_argument("--runs", type=int, default=3)
    pn.add_argument("--prompts-file", type=Path, default=None)

    pb = sub.add_parser("batch"); add_common(pb)
    pb.add_argument("--sizes", default="1,4,8")
    pb.add_argument("--prompts-file", type=Path, default=None)

    pf = sub.add_parser("fault"); add_common(pf)
    pf.add_argument("--runs", type=int, default=3)
    pf.add_argument("--target", default="vae", choices=["clip", "unet", "vae"])
    pf.add_argument("--fault-delay", type=float, default=1.0)

    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    fn = {"latency": cmd_latency, "memory": cmd_memory, "network": cmd_network,
          "batch": cmd_batch, "fault": cmd_fault}[args.cmd]
    try:
        return asyncio.run(fn(args))
    except KeyboardInterrupt:
        return 130
    except Exception:
        log.error("eval failed:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
