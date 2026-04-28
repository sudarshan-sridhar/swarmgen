"""
SwarmGen coordinator.

Phase 3 capability: discovery (mDNS + manual fallback), single-image orchestration,
heartbeat monitor, and stage retry on a fallback worker if a primary dies.

CLI:
    # Happy path. mDNS or direct workers.
    python coordinator.py --prompt "..." \
        --workers clip@192.168.1.39:8001,unet@192.168.1.16:8002,vae@192.168.1.185:8003

    # Fault-injection demo: kill the VAE worker 1 second in, recover automatically.
    python coordinator.py --prompt "..." --fault vae --workers ...

A worker can advertise `supported_stages` beyond its primary role. The coordinator
prefers a worker whose primary == stage, then falls back to any other live worker
that lists the stage in supported_stages.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

import protocol


log = logging.getLogger("swarmgen.coordinator")


# -----------------------------------------------------------------------------
# Worker registry
# -----------------------------------------------------------------------------
@dataclass
class Worker:
    role: str            # primary role advertised
    host: str
    port: int
    capabilities: Dict[str, Any] = field(default_factory=dict)
    alive: bool = True
    last_heartbeat_ts: float = 0.0
    consecutive_misses: int = 0

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def supported_stages(self) -> List[str]:
        st = self.capabilities.get("supported_stages")
        if isinstance(st, list) and st:
            return list(st)
        return [self.role]

    def __repr__(self) -> str:
        return f"Worker({self.role}@{self.host}:{self.port}, alive={self.alive})"


def parse_worker_spec(spec: str) -> Worker:
    try:
        role, hostport = spec.split("@", 1)
        host, port = hostport.rsplit(":", 1)
        return Worker(role=role.strip(), host=host.strip(), port=int(port))
    except Exception as e:
        raise ValueError(f"bad --workers spec {spec!r}: {e}")


async def fetch_capabilities(client: httpx.AsyncClient, w: Worker) -> Worker:
    r = await client.get(f"{w.url}/capabilities", timeout=5.0)
    r.raise_for_status()
    w.capabilities = r.json()
    log.info("capabilities role=%s host=%s -> device=%s dtype=%s supported=%s gpu=%s",
             w.role, w.host,
             w.capabilities.get("device"), w.capabilities.get("dtype"),
             w.supported_stages, w.capabilities.get("gpu_name"))
    return w


# -----------------------------------------------------------------------------
# mDNS discovery
# -----------------------------------------------------------------------------
async def discover_workers(timeout: float = 4.0) -> List[Worker]:
    from zeroconf import IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

    found: Dict[str, Worker] = {}
    azc = AsyncZeroconf(ip_version=IPVersion.V4Only)

    def on_state_change(zc, service_type, name, state_change):
        if state_change is not ServiceStateChange.Added:
            return
        asyncio.create_task(_resolve(zc, service_type, name))

    async def _resolve(zc, service_type, name):
        try:
            info = AsyncServiceInfo(service_type, name)
            ok = await info.async_request(azc.zeroconf, 3000)
            if not ok:
                return
            props = {k.decode(): v.decode() for k, v in (info.properties or {}).items()}
            role = props.get("role", "?")
            addrs = info.parsed_scoped_addresses()
            host = addrs[0] if addrs else None
            if not host:
                return
            w = Worker(role=role, host=host, port=info.port or 0)
            found[name] = w
            log.info("mDNS found %s -> %s:%d (role=%s)", name, w.host, w.port, role)
        except Exception:
            log.exception("mDNS resolve failed for %s", name)

    browser = AsyncServiceBrowser(
        azc.zeroconf, "_swarmgen._tcp.local.", handlers=[on_state_change]
    )
    log.info("mDNS browsing for _swarmgen._tcp.local. (%.1fs)", timeout)
    await asyncio.sleep(timeout)
    await browser.async_cancel()
    await azc.async_close()
    return list(found.values())


# -----------------------------------------------------------------------------
# Heartbeat monitor
# -----------------------------------------------------------------------------
class HeartbeatMonitor:
    """Polls /heartbeat on each worker every `interval` seconds.
    Marks a worker dead after `max_misses` consecutive failures.
    """
    def __init__(self, workers: List[Worker], *, interval: float = 1.0, max_misses: int = 3):
        self.workers = workers
        self.interval = interval
        self.max_misses = max_misses
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def _ping_one(self, client: httpx.AsyncClient, w: Worker) -> None:
        try:
            r = await client.get(f"{w.url}/heartbeat", timeout=1.0)
            r.raise_for_status()
            w.last_heartbeat_ts = time.time()
            w.consecutive_misses = 0
            if not w.alive:
                log.warning("worker recovered: %s", w)
                w.alive = True
        except Exception as e:
            w.consecutive_misses += 1
            if w.alive and w.consecutive_misses >= self.max_misses:
                w.alive = False
                log.error("worker DEAD after %d misses: %s (last err: %s)",
                          w.consecutive_misses, w, type(e).__name__)

    async def _run(self) -> None:
        timeout = httpx.Timeout(connect=1.0, read=1.0, write=1.0, pool=1.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            while not self._stop.is_set():
                await asyncio.gather(*(self._ping_one(client, w) for w in self.workers),
                                     return_exceptions=True)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
                except asyncio.TimeoutError:
                    pass

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            log.info("heartbeat monitor started (interval=%.1fs, max_misses=%d)",
                     self.interval, self.max_misses)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:
                pass
            self._task = None


# -----------------------------------------------------------------------------
# Worker selection (primary preferred, then any worker with the stage in supported)
# -----------------------------------------------------------------------------
def select_workers_for(stage: str, registry: List[Worker]) -> List[Worker]:
    """Return live workers ordered: primary-role match first, then fallbacks."""
    primary = [w for w in registry if w.alive and w.role == stage]
    fallback = [w for w in registry if w.alive and w.role != stage and stage in w.supported_stages]
    return primary + fallback


# -----------------------------------------------------------------------------
# Stage call with retry-on-failure
# -----------------------------------------------------------------------------
async def call_stage(
    client: httpx.AsyncClient,
    registry: List[Worker],
    stage: str,
    body: bytes,
    params: Dict[str, Any],
    *,
    expect: str = "tensor",   # "tensor" | "png"
    read_timeout: float = 240.0,
) -> Tuple[bytes, float, Worker, List[str]]:
    """Try the stage on each candidate worker until one succeeds.
    Returns (response bytes, wall-clock ms, winning worker, [retry log lines]).
    """
    candidates = select_workers_for(stage, registry)
    if not candidates:
        raise RuntimeError(f"no live worker supports stage={stage!r}")

    retries: List[str] = []
    last_exc: Optional[BaseException] = None

    # Always include the stage name so multi-role workers know what to run.
    full_params = dict(params)
    full_params["stage"] = stage
    headers = {"X-SwarmGen-Params": json.dumps(full_params)}

    for w in candidates:
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{w.url}/run_stage",
                headers=headers,
                content=body,
                timeout=httpx.Timeout(connect=3.0, read=read_timeout, write=30.0, pool=3.0),
            )
            r.raise_for_status()
            ms = (time.perf_counter() - t0) * 1000
            server_ms = r.headers.get("X-SwarmGen-Stage-Ms", "?")
            log.info("stage=%s OK on %s in %.1f ms (server %s ms, %d B)",
                     stage, w, ms, server_ms, len(r.content))
            return r.content, ms, w, retries
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            msg = f"{type(e).__name__}: {e}"
            log.warning("stage=%s FAILED on %s after %.1f ms: %s", stage, w, ms, msg)
            retries.append(f"{w.role}@{w.host}:{w.port} -> {msg}")
            last_exc = e
            # Mark this worker as suspect — the heartbeat task will confirm dead.
            w.consecutive_misses += 1
            if w.consecutive_misses >= 1 and not isinstance(e, httpx.HTTPStatusError):
                # transport-level failure: treat as dead immediately so we don't loop on it
                w.alive = False
                log.error("marking %s dead immediately (transport error)", w)
            continue

    raise RuntimeError(
        f"all candidates failed for stage={stage}: tried={[c.role+'@'+c.host for c in candidates]}; "
        f"last={last_exc!r}"
    )


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------
@dataclass
class GenResult:
    prompt: str
    image_path: Path
    timings_ms: Dict[str, float]
    bytes_per_stage: Dict[str, int]
    total_ms: float
    workers_used: Dict[str, str]
    retries: Dict[str, List[str]]


async def generate(
    registry: List[Worker],
    prompt: str,
    *,
    out_dir: Path,
    steps: int = 4,
    seed: int = 42,
    height: int = 512,
    width: int = 512,
    fault_stage: Optional[str] = None,
    fault_delay_s: float = 1.0,
) -> GenResult:
    """Single-image generation: CLIP -> UNet -> VAE.
    If fault_stage is set, schedules a /admin/die on that stage's primary worker
    after fault_delay_s seconds, to demonstrate recovery.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    timings: Dict[str, float] = {}
    sizes: Dict[str, int] = {}
    workers_used: Dict[str, str] = {}
    retries: Dict[str, List[str]] = {}
    t_start = time.perf_counter()

    timeout = httpx.Timeout(connect=5.0, read=240.0, write=60.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:

        # Schedule the fault, if requested.
        fault_task: Optional[asyncio.Task] = None
        if fault_stage:
            target = next((w for w in registry if w.alive and w.role == fault_stage), None)
            if target is None:
                raise RuntimeError(f"--fault {fault_stage}: no primary worker with that role to kill")
            fault_task = asyncio.create_task(
                _inject_fault(client, target, fault_delay_s)
            )

        try:
            # CLIP
            enc_bytes, t_clip, w_clip, r_clip = await call_stage(
                client, registry, "clip", b"", {"prompt": prompt}, read_timeout=60.0,
            )
            timings["clip"] = t_clip; sizes["clip"] = len(enc_bytes)
            workers_used["clip"] = f"{w_clip.role}@{w_clip.host}:{w_clip.port}"
            retries["clip"] = r_clip

            # UNet
            latent_bytes, t_unet, w_unet, r_unet = await call_stage(
                client, registry, "unet", enc_bytes,
                {"steps": steps, "seed": seed, "height": height, "width": width},
                read_timeout=180.0,
            )
            timings["unet"] = t_unet; sizes["unet"] = len(latent_bytes)
            workers_used["unet"] = f"{w_unet.role}@{w_unet.host}:{w_unet.port}"
            retries["unet"] = r_unet

            # VAE
            png_bytes, t_vae, w_vae, r_vae = await call_stage(
                client, registry, "vae", latent_bytes, {},
                expect="png", read_timeout=300.0,
            )
            timings["vae"] = t_vae; sizes["vae"] = len(png_bytes)
            workers_used["vae"] = f"{w_vae.role}@{w_vae.host}:{w_vae.port}"
            retries["vae"] = r_vae

        finally:
            if fault_task:
                if not fault_task.done():
                    fault_task.cancel()
                with contextlib_suppress():
                    await fault_task

    total_ms = (time.perf_counter() - t_start) * 1000
    slug = _slugify(prompt) or "gen"
    if fault_stage:
        slug = f"{slug}__fault-{fault_stage}"
    image_path = out_dir / f"{slug}.png"
    image_path.write_bytes(png_bytes)
    sidecar = out_dir / f"{slug}.json"
    sidecar.write_text(json.dumps({
        "prompt": prompt,
        "seed": seed, "steps": steps, "height": height, "width": width,
        "timings_ms": timings,
        "bytes_per_stage": sizes,
        "total_ms": total_ms,
        "workers_used": workers_used,
        "retries": retries,
        "fault_injected": fault_stage,
    }, indent=2))
    log.info("wrote %s (total %.0f ms)", image_path, total_ms)
    return GenResult(prompt=prompt, image_path=image_path, timings_ms=timings,
                     bytes_per_stage=sizes, total_ms=total_ms,
                     workers_used=workers_used, retries=retries)


class contextlib_suppress:
    def __aenter__(self): return self
    async def __aexit__(self, *a): return True
    def __enter__(self): return self
    def __exit__(self, *a): return True


async def _inject_fault(client: httpx.AsyncClient, target: Worker, delay_s: float) -> None:
    log.warning("fault injection scheduled: kill %s in %.1fs", target, delay_s)
    try:
        await asyncio.sleep(delay_s)
        log.warning("fault injection: POST /admin/die to %s", target)
        try:
            await client.post(f"{target.url}/admin/die", timeout=2.0)
        except Exception as e:
            # The worker dies before responding cleanly — that's expected.
            log.info("admin/die response error (expected): %s", e)
        # Help the rest of the pipeline notice fast.
        target.alive = False
        target.consecutive_misses = 99
    except asyncio.CancelledError:
        log.info("fault task cancelled before firing")


def _slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen]


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SwarmGen coordinator (single-image, fault-aware).")
    p.add_argument("--prompt", required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--height", type=int, default=512)
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--out-dir", type=Path, default=Path("outputs"))
    p.add_argument("--workers", default=None,
                   help="comma-separated list of role@host:port (skips mDNS)")
    p.add_argument("--discover", action="store_true")
    p.add_argument("--discover-timeout", type=float, default=4.0)
    p.add_argument("--fault", choices=["clip", "unet", "vae"],
                   help="kill this stage's primary worker mid-generation to test recovery")
    p.add_argument("--fault-delay", type=float, default=1.0)
    p.add_argument("--no-heartbeat", action="store_true",
                   help="disable the background heartbeat monitor")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)-5s %(name)s | %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stdout, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("zeroconf").setLevel(logging.WARNING)


async def main_async(args: argparse.Namespace) -> int:
    workers: List[Worker] = []

    if args.workers:
        workers = [parse_worker_spec(s) for s in args.workers.split(",") if s.strip()]
        log.info("using %d workers from --workers", len(workers))

    if args.discover or not workers:
        discovered = await discover_workers(timeout=args.discover_timeout)
        log.info("mDNS discovered %d workers", len(discovered))
        existing = {(w.host, w.port) for w in workers}
        for w in discovered:
            if (w.host, w.port) not in existing:
                workers.append(w)

    if not workers:
        log.error("no workers found (try --workers role@host:port,... or fix mDNS)")
        return 2

    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for w in workers:
            try:
                await fetch_capabilities(client, w)
            except Exception:
                log.exception("could not fetch capabilities for %s", w)
                w.alive = False

    monitor: Optional[HeartbeatMonitor] = None
    if not args.no_heartbeat:
        monitor = HeartbeatMonitor(workers, interval=1.0, max_misses=3)
        monitor.start()

    try:
        res = await generate(
            workers, args.prompt,
            out_dir=args.out_dir,
            steps=args.steps, seed=args.seed,
            height=args.height, width=args.width,
            fault_stage=args.fault,
            fault_delay_s=args.fault_delay,
        )
    finally:
        if monitor:
            await monitor.stop()

    print()
    print("=" * 72)
    print(f"prompt:     {res.prompt}")
    print(f"image:      {res.image_path}")
    print(f"total:      {res.total_ms:.0f} ms")
    for stage in ("clip", "unet", "vae"):
        ms = res.timings_ms.get(stage, float('nan'))
        b = res.bytes_per_stage.get(stage, 0)
        used = res.workers_used.get(stage, "?")
        retries = res.retries.get(stage, [])
        retry_note = f"  [retried {len(retries)}x]" if retries else ""
        print(f"  {stage:<5}  {ms:7.1f} ms  {b:>10} B   via {used}{retry_note}")
    if args.fault:
        print(f"fault:      injected on stage={args.fault} after {args.fault_delay:.1f}s")
    print("=" * 72)
    return 0


def main() -> int:
    args = parse_args()
    _setup_logging(args.verbose)
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 130
    except Exception:
        log.error("coordinator failed:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
