"""
SwarmGen coordinator.

Phase 2: discovery (mDNS + manual fallback) and single-image orchestration.
Pipeline: prompt -> CLIP -> UNet -> VAE -> PNG.

CLI:
    python coordinator.py --prompt "a cat astronaut" \
        --workers clip@192.168.1.39:8001,unet@192.168.1.16:8002,vae@192.168.1.185:8003

    # Or, if mDNS is working, just:
    python coordinator.py --prompt "a cat astronaut" --discover

Output: PNG written to outputs/<slug>.png plus a JSON sidecar with timings.
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
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

import protocol


log = logging.getLogger("swarmgen.coordinator")


# -----------------------------------------------------------------------------
# Worker registry
# -----------------------------------------------------------------------------
@dataclass
class Worker:
    role: str
    host: str
    port: int
    capabilities: Dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def parse_worker_spec(spec: str) -> Worker:
    """`role@host:port` -> Worker."""
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
    log.info("capabilities role=%s host=%s -> %s",
             w.role, w.host,
             {k: w.capabilities.get(k) for k in ("device", "dtype", "ram_total_mb", "gpu_name", "torch_version")})
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
        # We resolve in a separate task to avoid blocking the listener.
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
        azc.zeroconf,
        "_swarmgen._tcp.local.",
        handlers=[on_state_change],
    )
    log.info("mDNS browsing for _swarmgen._tcp.local. (%.1fs)", timeout)
    await asyncio.sleep(timeout)
    await browser.async_cancel()
    await azc.async_close()
    return list(found.values())


# -----------------------------------------------------------------------------
# Pipeline planner: pick one worker per role
# -----------------------------------------------------------------------------
def plan_pipeline(workers: List[Worker]) -> Dict[str, Worker]:
    by_role: Dict[str, Worker] = {}
    for w in workers:
        if w.role not in by_role:
            by_role[w.role] = w
    missing = [r for r in ("clip", "unet", "vae") if r not in by_role]
    if missing:
        raise RuntimeError(f"missing required worker roles: {missing}. found={[w.role for w in workers]}")
    log.info("pipeline plan: clip=%s unet=%s vae=%s",
             by_role["clip"].host, by_role["unet"].host, by_role["vae"].host)
    return by_role


# -----------------------------------------------------------------------------
# Stage calls
# -----------------------------------------------------------------------------
async def call_clip(client: httpx.AsyncClient, w: Worker, prompt: str) -> tuple[bytes, float]:
    t0 = time.perf_counter()
    r = await client.post(
        f"{w.url}/run_stage",
        headers={"X-SwarmGen-Params": json.dumps({"prompt": prompt})},
        content=b"",
        timeout=60.0,
    )
    r.raise_for_status()
    ms = (time.perf_counter() - t0) * 1000
    server_ms = float(r.headers.get("X-SwarmGen-Stage-Ms", "nan"))
    log.info("clip stage: %.1f ms wall (server %.1f ms), %d B", ms, server_ms, len(r.content))
    return r.content, ms


async def call_unet(
    client: httpx.AsyncClient, w: Worker, enc_packed: bytes,
    *, steps: int = 4, seed: int = 42, height: int = 512, width: int = 512,
) -> tuple[bytes, float]:
    t0 = time.perf_counter()
    params = {"steps": steps, "seed": seed, "height": height, "width": width}
    r = await client.post(
        f"{w.url}/run_stage",
        headers={"X-SwarmGen-Params": json.dumps(params)},
        content=enc_packed,
        timeout=180.0,
    )
    r.raise_for_status()
    ms = (time.perf_counter() - t0) * 1000
    server_ms = float(r.headers.get("X-SwarmGen-Stage-Ms", "nan"))
    log.info("unet stage: %.1f ms wall (server %.1f ms), %d B", ms, server_ms, len(r.content))
    return r.content, ms


async def call_vae(client: httpx.AsyncClient, w: Worker, latent_packed: bytes) -> tuple[bytes, float]:
    t0 = time.perf_counter()
    r = await client.post(
        f"{w.url}/run_stage",
        content=latent_packed,
        timeout=240.0,
    )
    r.raise_for_status()
    ms = (time.perf_counter() - t0) * 1000
    server_ms = float(r.headers.get("X-SwarmGen-Stage-Ms", "nan"))
    log.info("vae stage: %.1f ms wall (server %.1f ms), %d PNG B", ms, server_ms, len(r.content))
    return r.content, ms


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


async def generate(
    plan: Dict[str, Worker],
    prompt: str,
    *,
    out_dir: Path,
    steps: int = 4,
    seed: int = 42,
    height: int = 512,
    width: int = 512,
) -> GenResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(connect=5.0, read=240.0, write=60.0, pool=5.0)
    timings: Dict[str, float] = {}
    sizes: Dict[str, int] = {}
    t_start = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout) as client:
        enc_bytes, t_clip = await call_clip(client, plan["clip"], prompt)
        timings["clip"] = t_clip
        sizes["clip"] = len(enc_bytes)

        latent_bytes, t_unet = await call_unet(
            client, plan["unet"], enc_bytes,
            steps=steps, seed=seed, height=height, width=width,
        )
        timings["unet"] = t_unet
        sizes["unet"] = len(latent_bytes)

        png_bytes, t_vae = await call_vae(client, plan["vae"], latent_bytes)
        timings["vae"] = t_vae
        sizes["vae"] = len(png_bytes)

    total_ms = (time.perf_counter() - t_start) * 1000
    slug = _slugify(prompt) or "gen"
    image_path = out_dir / f"{slug}.png"
    image_path.write_bytes(png_bytes)
    sidecar = out_dir / f"{slug}.json"
    sidecar.write_text(json.dumps({
        "prompt": prompt,
        "seed": seed,
        "steps": steps,
        "height": height,
        "width": width,
        "timings_ms": timings,
        "bytes_per_stage": sizes,
        "total_ms": total_ms,
        "plan": {role: {"host": w.host, "port": w.port} for role, w in plan.items()},
    }, indent=2))
    log.info("wrote %s (total %.0f ms)", image_path, total_ms)
    return GenResult(prompt=prompt, image_path=image_path, timings_ms=timings,
                     bytes_per_stage=sizes, total_ms=total_ms)


def _slugify(s: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:maxlen]


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SwarmGen coordinator (single-image).")
    p.add_argument("--prompt", required=True, help="text prompt to generate")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--height", type=int, default=512)
    p.add_argument("--width", type=int, default=512)
    p.add_argument("--out-dir", type=Path, default=Path("outputs"))
    p.add_argument("--workers", default=None,
                   help="comma-separated list of role@host:port (skips mDNS)")
    p.add_argument("--discover", action="store_true",
                   help="use mDNS to find workers")
    p.add_argument("--discover-timeout", type=float, default=4.0)
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
        # Manual entries take priority; mDNS fills any gaps.
        existing_roles = {w.role for w in workers}
        for w in discovered:
            if w.role not in existing_roles:
                workers.append(w)

    if not workers:
        log.error("no workers found via --workers or mDNS")
        return 2

    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for w in workers:
            try:
                await fetch_capabilities(client, w)
            except Exception:
                log.exception("could not fetch capabilities for %s @ %s:%d", w.role, w.host, w.port)

    plan = plan_pipeline(workers)

    res = await generate(
        plan, args.prompt,
        out_dir=args.out_dir,
        steps=args.steps, seed=args.seed,
        height=args.height, width=args.width,
    )

    print()
    print("=" * 72)
    print(f"prompt:     {res.prompt}")
    print(f"image:      {res.image_path}")
    print(f"total:      {res.total_ms:.0f} ms")
    for stage in ("clip", "unet", "vae"):
        ms = res.timings_ms.get(stage, float('nan'))
        b = res.bytes_per_stage.get(stage, 0)
        print(f"  {stage:<5}     {ms:7.1f} ms   {b:>10} B")
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
