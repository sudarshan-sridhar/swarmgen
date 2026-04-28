"""
SwarmGen HTTP API server. Backs the static frontend in `static/`.

Run on loq:
    python api.py --workers clip@192.168.1.39:8001,unet@192.168.1.16:8002,vae@192.168.1.185:8003

Serves:
    GET  /                       static/index.html
    GET  /static/...             static asset files
    GET  /outputs/...             rendered images
    GET  /api/workers            live health snapshot for all workers
    POST /api/generate           body {prompt, seed, steps, fault?}
    POST /api/admin/kill-vae     send /admin/die to the primary VAE worker
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import coordinator as C


log = logging.getLogger("swarmgen.api")

REGISTRY: List[C.Worker] = []
ROOT = Path(__file__).parent.resolve()
STATIC_DIR = ROOT / "static"
OUTPUTS_DIR = ROOT / "outputs" / "ui"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


class GenerateReq(BaseModel):
    prompt: str
    seed: int = 42
    steps: int = Field(default=4, ge=1, le=8)
    height: int = 512
    width: int = 512
    fault: Optional[str] = None  # "vae" | None


class GenerateResp(BaseModel):
    image_url: str
    total_ms: float
    timings_ms: Dict[str, float]
    bytes_per_stage: Dict[str, int]
    workers_used: Dict[str, str]
    retries: Dict[str, int]
    fault_injected: Optional[str] = None


def make_app() -> FastAPI:
    app = FastAPI(title="swarmgen-api")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/outputs", StaticFiles(directory=str(ROOT / "outputs")), name="outputs")

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        idx = STATIC_DIR / "index.html"
        if not idx.exists():
            raise HTTPException(status_code=404, detail="static/index.html not found")
        return FileResponse(str(idx))

    @app.get("/api/workers")
    async def workers_endpoint() -> JSONResponse:
        timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
        rows: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=timeout) as client:
            for w in REGISTRY:
                row: Dict[str, Any] = {
                    "role": w.role,
                    "host": w.host,
                    "port": w.port,
                    "alive": False,
                    "current_mb": None,
                    "peak_mb": None,
                    "device": w.capabilities.get("device", "?"),
                    "dtype": w.capabilities.get("dtype", "?"),
                    "supports": w.supported_stages,
                    "gpu_name": w.capabilities.get("gpu_name"),
                }
                try:
                    r = await client.get(f"{w.url}/health", timeout=1.5)
                    if r.status_code == 200:
                        d = r.json()
                        row["alive"] = True
                        row["current_mb"] = round(d.get("current_memory_mb", 0), 1)
                        row["peak_mb"] = round(d.get("peak_memory_mb", 0), 1)
                        w.alive = True
                except Exception:
                    w.alive = False
                rows.append(row)
        return JSONResponse(rows)

    @app.post("/api/generate", response_model=GenerateResp)
    async def generate_endpoint(req: GenerateReq) -> GenerateResp:
        if not req.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt is empty")
        fault_stage = req.fault if req.fault and req.fault != "none" else None
        try:
            res = await C.generate(
                REGISTRY, req.prompt,
                out_dir=OUTPUTS_DIR,
                steps=req.steps, seed=req.seed,
                height=req.height, width=req.width,
                fault_stage=fault_stage, fault_delay_s=1.0,
            )
        except Exception as e:
            log.exception("generate failed")
            raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

        image_url = f"/outputs/ui/{Path(res.image_path).name}"
        return GenerateResp(
            image_url=image_url,
            total_ms=round(res.total_ms, 2),
            timings_ms={k: round(v, 2) for k, v in res.timings_ms.items()},
            bytes_per_stage=res.bytes_per_stage,
            workers_used=res.workers_used,
            retries={k: len(v) for k, v in res.retries.items()},
            fault_injected=fault_stage,
        )

    @app.post("/api/admin/kill-vae")
    async def kill_vae_endpoint() -> JSONResponse:
        target = next((w for w in REGISTRY if w.role == "vae"), None)
        if target is None:
            raise HTTPException(status_code=404, detail="no VAE worker registered")
        timeout = httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                await client.post(f"{target.url}/admin/die")
            except Exception:
                pass  # process death is the success case
        return JSONResponse({
            "killed": f"{target.host}:{target.port}",
            "role": target.role,
        })

    return app


async def hydrate() -> None:
    timeout = httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for w in REGISTRY:
            try:
                await C.fetch_capabilities(client, w)
            except Exception:
                w.alive = False


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", required=True,
                   help="comma-separated list of role@host:port")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    global REGISTRY
    REGISTRY = [C.parse_worker_spec(s) for s in args.workers.split(",") if s.strip()]
    asyncio.run(hydrate())
    log.info("hydrated %d workers", len(REGISTRY))

    app = make_app()
    print(f"\nSwarmGen UI ready at  http://localhost:{args.port}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
