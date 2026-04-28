"""
SwarmGen worker. One file, role-flagged.

Run examples:
    python worker.py --role clip --port 8001
    python worker.py --role unet --port 8002
    python worker.py --role vae  --port 8003

Endpoints (FastAPI on 0.0.0.0:port):
    GET  /health        -> JSON {status, role, ...memory stats..., last_heartbeat}
    GET  /capabilities  -> JSON device + model facts (set on startup)
    GET  /heartbeat     -> JSON {ts, role}
    POST /run_stage     -> stage-specific. Tensor I/O is octet-stream + JSON header
                           via protocol.pack_tensor / unpack_tensor.
    POST /admin/die     -> kills the process (used by fault-injection eval)

Wire format for /run_stage:
    Request:
        Header X-SwarmGen-Params: JSON dict of stage-specific params (optional)
        Body:  empty, OR a packed tensor (for unet/vae inputs)
    Response:
        Header X-SwarmGen-Stage-Ms: float ms spent in the model
        Body:  packed tensor (clip/unet) OR PNG bytes (vae)

mDNS:
    Service _swarmgen._tcp.local.
    Name    swarmgen-{role}-{hostname}._swarmgen._tcp.local.
    TXT     role={role}

No silent failures. Every exception logs full traceback. Verbose startup banner.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import socket
import sys
import threading
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

import psutil
import torch
# Ensure safetensors.torch submodule is registered before diffusers imports it.
# Some safetensors+diffusers combos don't auto-register the .torch attribute,
# which leads to "module 'safetensors' has no attribute 'torch'" deep in load_state_dict.
import safetensors  # noqa: F401
import safetensors.torch  # noqa: F401
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from PIL import Image
from zeroconf import IPVersion, ServiceInfo, Zeroconf

import protocol

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
log = logging.getLogger("swarmgen.worker")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)-5s %(name)s | %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stdout, force=True)
    # Quiet noisy libraries on the Pi where stdout costs.
    logging.getLogger("zeroconf").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# -----------------------------------------------------------------------------
# Memory tracking
# -----------------------------------------------------------------------------
@dataclass
class MemStats:
    current_mb: float = 0.0
    peak_mb: float = 0.0
    last_heartbeat_ts: float = 0.0

    def sample(self) -> None:
        rss = psutil.Process().memory_info().rss / (1024 * 1024)
        self.current_mb = rss
        if rss > self.peak_mb:
            self.peak_mb = rss


MEM = MemStats()


# -----------------------------------------------------------------------------
# Model holder. Each role only loads its piece.
# -----------------------------------------------------------------------------
MODEL_ID = "stabilityai/sd-turbo"


@dataclass
class ModelBundle:
    role: str
    device: torch.device
    dtype: torch.dtype
    # CLIP
    tokenizer: Any = None
    text_encoder: Any = None
    # UNet
    unet: Any = None
    scheduler: Any = None
    # VAE
    vae: Any = None
    # Static info
    capabilities: Dict[str, Any] = field(default_factory=dict)


def _pick_device_dtype(role: str) -> tuple[torch.device, torch.dtype]:
    if role == "unet" and torch.cuda.is_available():
        return torch.device("cuda"), torch.float16
    if role == "vae":
        # CPU FP32 for the Pi. Slow but deterministic, fits in RAM.
        return torch.device("cpu"), torch.float32
    # CLIP on CPU laptop. FP32 is fine; CLIP is small.
    return torch.device("cpu"), torch.float32


def _load_models(role: str) -> ModelBundle:
    device, dtype = _pick_device_dtype(role)
    log.info("loading models: role=%s device=%s dtype=%s", role, device, dtype)
    bundle = ModelBundle(role=role, device=device, dtype=dtype)

    if role == "clip":
        from transformers import CLIPTextModel, CLIPTokenizer

        log.info("loading CLIP tokenizer + text_encoder from %s", MODEL_ID)
        bundle.tokenizer = CLIPTokenizer.from_pretrained(MODEL_ID, subfolder="tokenizer")
        bundle.text_encoder = CLIPTextModel.from_pretrained(
            MODEL_ID, subfolder="text_encoder", torch_dtype=dtype
        ).to(device)
        bundle.text_encoder.eval()

    elif role == "unet":
        from diffusers import EulerDiscreteScheduler, UNet2DConditionModel

        log.info("loading UNet from %s", MODEL_ID)
        try:
            bundle.unet = UNet2DConditionModel.from_pretrained(
                MODEL_ID, subfolder="unet", torch_dtype=dtype, variant="fp16"
            ).to(device)
        except Exception:
            log.warning("fp16 variant not available, falling back to default weights")
            bundle.unet = UNet2DConditionModel.from_pretrained(
                MODEL_ID, subfolder="unet", torch_dtype=dtype
            ).to(device)
        bundle.unet.eval()
        bundle.scheduler = EulerDiscreteScheduler.from_pretrained(
            MODEL_ID, subfolder="scheduler"
        )

    elif role == "vae":
        from diffusers import AutoencoderKL

        log.info("loading VAE from %s", MODEL_ID)
        bundle.vae = AutoencoderKL.from_pretrained(
            MODEL_ID, subfolder="vae", torch_dtype=dtype
        ).to(device)
        bundle.vae.eval()

    else:
        raise ValueError(f"unknown role: {role}")

    return bundle


def _build_capabilities(role: str, port: int, bundle: ModelBundle) -> Dict[str, Any]:
    caps: Dict[str, Any] = {
        "role": role,
        "hostname": socket.gethostname(),
        "port": port,
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "torch_version": torch.__version__,
        "cpu_count": psutil.cpu_count(logical=True),
        "ram_total_mb": round(psutil.virtual_memory().total / (1024 * 1024), 1),
        "gpu_present": torch.cuda.is_available(),
        "device": str(bundle.device),
        "dtype": str(bundle.dtype).removeprefix("torch."),
        "model_id": MODEL_ID,
        "supported_stages": [role],
        "fallback_for": [],  # filled below for the GPU box
    }
    if torch.cuda.is_available():
        try:
            props = torch.cuda.get_device_properties(0)
            caps["gpu_name"] = torch.cuda.get_device_name(0)
            caps["gpu_vram_mb"] = round(props.total_memory / (1024 * 1024), 1)
            caps["fallback_for"] = ["clip", "vae"]  # GPU box can stand in if a worker dies
        except Exception:
            log.exception("failed to inspect GPU")
    return caps


# -----------------------------------------------------------------------------
# Stage runners
# -----------------------------------------------------------------------------
@torch.inference_mode()
def run_clip(bundle: ModelBundle, prompt: str) -> torch.Tensor:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("clip stage requires non-empty 'prompt' param")
    tok = bundle.tokenizer(
        prompt,
        padding="max_length",
        max_length=bundle.tokenizer.model_max_length,
        truncation=True,
        return_tensors="pt",
    ).to(bundle.device)
    out = bundle.text_encoder(input_ids=tok.input_ids)
    enc = out.last_hidden_state  # (1, 77, hidden)
    log.info("clip: prompt=%r -> encoder_hidden_states shape=%s dtype=%s",
             prompt[:60], tuple(enc.shape), enc.dtype)
    return enc


@torch.inference_mode()
def run_unet(
    bundle: ModelBundle,
    encoder_hidden_states: torch.Tensor,
    *,
    steps: int = 4,
    seed: int = 42,
    height: int = 512,
    width: int = 512,
) -> torch.Tensor:
    """SD-Turbo: 4 Euler steps, no CFG."""
    device = bundle.device
    dtype = bundle.dtype
    enc = encoder_hidden_states.to(device=device, dtype=dtype)

    bundle.scheduler.set_timesteps(steps, device=device)
    timesteps = bundle.scheduler.timesteps
    latent_h = height // 8
    latent_w = width // 8
    g = torch.Generator(device=device).manual_seed(int(seed))
    latents = torch.randn((1, 4, latent_h, latent_w), generator=g, device=device, dtype=dtype)
    latents = latents * bundle.scheduler.init_noise_sigma

    for i, t in enumerate(timesteps):
        latent_in = bundle.scheduler.scale_model_input(latents, t)
        noise_pred = bundle.unet(latent_in, t, encoder_hidden_states=enc).sample
        latents = bundle.scheduler.step(noise_pred, t, latents).prev_sample
        log.debug("unet step %d/%d (t=%s)", i + 1, len(timesteps), t.item())

    log.info("unet: %d steps -> latent shape=%s dtype=%s",
             len(timesteps), tuple(latents.shape), latents.dtype)
    # Move to CPU FP32 for transport — VAE wants float, downstream is CPU.
    return latents.detach().to(device="cpu", dtype=torch.float32)


@torch.inference_mode()
def run_vae(bundle: ModelBundle, latents: torch.Tensor) -> bytes:
    device = bundle.device
    dtype = bundle.dtype
    z = latents.to(device=device, dtype=dtype)
    scaling = float(getattr(bundle.vae.config, "scaling_factor", 0.18215))
    image = bundle.vae.decode(z / scaling).sample  # (1, 3, H, W) in [-1, 1]
    image = (image / 2 + 0.5).clamp(0, 1)
    image = (image[0].permute(1, 2, 0).cpu().float().numpy() * 255).round().astype("uint8")
    pil = Image.fromarray(image)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    log.info("vae: latent shape=%s -> PNG %d bytes", tuple(latents.shape), buf.tell())
    return buf.getvalue()


# -----------------------------------------------------------------------------
# Local IP discovery for mDNS announcement
# -----------------------------------------------------------------------------
def _detect_local_ip() -> str:
    """Return the IPv4 used to reach the default gateway. Fallback to 127.0.0.1."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets actually sent — just resolves the routing decision.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
def make_app(role: str, port: int) -> FastAPI:
    bundle: ModelBundle = _load_models(role)
    MEM.sample()
    log.info("models loaded. RSS=%.1f MB", MEM.current_mb)

    capabilities = _build_capabilities(role, port, bundle)
    log.info("capabilities=%s", json.dumps(capabilities))

    zc_state: Dict[str, Any] = {"zc": None, "info": None}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Register mDNS on startup.
        local_ip = _detect_local_ip()
        host = socket.gethostname().split(".")[0].lower()
        service_name = f"swarmgen-{role}-{host}._swarmgen._tcp.local."
        try:
            info = ServiceInfo(
                type_="_swarmgen._tcp.local.",
                name=service_name,
                addresses=[socket.inet_aton(local_ip)],
                port=port,
                properties={
                    "role": role,
                    "hostname": host,
                    "version": "0.1",
                },
                server=f"{host}.local.",
            )
            zc = Zeroconf(ip_version=IPVersion.V4Only)
            zc.register_service(info)
            zc_state["zc"] = zc
            zc_state["info"] = info
            log.info("mDNS announced %s @ %s:%d", service_name, local_ip, port)
        except Exception:
            log.exception("mDNS announce failed (continuing without)")

        # Banner.
        log.info("=" * 72)
        log.info("SwarmGen worker UP  role=%s port=%d device=%s dtype=%s",
                 role, port, bundle.device, str(bundle.dtype).removeprefix("torch."))
        log.info("hostname=%s  local_ip=%s  pid=%d", host, local_ip, os.getpid())
        log.info("RSS=%.1f MB peak=%.1f MB", MEM.current_mb, MEM.peak_mb)
        log.info("=" * 72)

        yield

        # Shutdown.
        if zc_state["zc"] is not None:
            try:
                zc_state["zc"].unregister_service(zc_state["info"])
                zc_state["zc"].close()
                log.info("mDNS unregistered")
            except Exception:
                log.exception("mDNS unregister failed")

    app = FastAPI(title=f"swarmgen-{role}", lifespan=lifespan)

    # ----- Endpoints -----------------------------------------------------------
    @app.get("/health")
    def health() -> Dict[str, Any]:
        MEM.sample()
        return {
            "status": "ok",
            "role": role,
            "current_memory_mb": round(MEM.current_mb, 1),
            "peak_memory_mb": round(MEM.peak_mb, 1),
            "last_heartbeat": MEM.last_heartbeat_ts,
            "ts": time.time(),
        }

    @app.get("/capabilities")
    def caps() -> Dict[str, Any]:
        return capabilities

    @app.get("/heartbeat")
    def heartbeat() -> Dict[str, Any]:
        MEM.last_heartbeat_ts = time.time()
        return {"ts": MEM.last_heartbeat_ts, "role": role}

    @app.post("/admin/die")
    def die(delay_ms: int = 50) -> Response:
        log.warning("/admin/die received — exiting in %d ms", delay_ms)

        def _kill() -> None:
            time.sleep(delay_ms / 1000.0)
            log.warning("worker process exiting now")
            os._exit(137)

        threading.Thread(target=_kill, daemon=True).start()
        return Response(status_code=202, content=b"dying")

    @app.post("/run_stage")
    async def run_stage(request: Request) -> Response:
        params_header = request.headers.get("X-SwarmGen-Params") or "{}"
        try:
            params = json.loads(params_header)
        except Exception as e:
            log.exception("bad X-SwarmGen-Params header")
            raise HTTPException(status_code=400, detail=f"bad params header: {e}")

        body = await request.body()
        log.info("run_stage role=%s params=%s body=%dB",
                 role, json.dumps(params)[:120], len(body))

        t0 = time.perf_counter()
        try:
            if role == "clip":
                prompt = params.get("prompt")
                out_t = run_clip(bundle, prompt=prompt)
                payload = protocol.pack_tensor(out_t)
                content_type = "application/octet-stream"

            elif role == "unet":
                if not body:
                    raise HTTPException(status_code=400, detail="unet stage requires packed encoder_hidden_states in body")
                enc = protocol.unpack_tensor(body)
                out_t = run_unet(
                    bundle,
                    enc,
                    steps=int(params.get("steps", 4)),
                    seed=int(params.get("seed", 42)),
                    height=int(params.get("height", 512)),
                    width=int(params.get("width", 512)),
                )
                payload = protocol.pack_tensor(out_t)
                content_type = "application/octet-stream"

            elif role == "vae":
                if not body:
                    raise HTTPException(status_code=400, detail="vae stage requires packed latents in body")
                latents = protocol.unpack_tensor(body)
                payload = run_vae(bundle, latents)
                content_type = "image/png"

            else:
                raise HTTPException(status_code=500, detail=f"unsupported role: {role}")

        except HTTPException:
            raise
        except Exception as e:
            log.error("run_stage failed:\n%s", traceback.format_exc())
            raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

        ms = (time.perf_counter() - t0) * 1000
        MEM.sample()
        log.info("run_stage done role=%s in %.1f ms (out=%dB) RSS=%.1f peak=%.1f",
                 role, ms, len(payload), MEM.current_mb, MEM.peak_mb)
        return Response(
            content=payload,
            media_type=content_type,
            headers={
                "X-SwarmGen-Stage-Ms": f"{ms:.2f}",
                "X-SwarmGen-Role": role,
                "X-SwarmGen-Peak-MB": f"{MEM.peak_mb:.1f}",
            },
        )

    # 500 handler that always logs the traceback.
    @app.exception_handler(Exception)
    async def _all_exceptions(request: Request, exc: Exception):
        log.error("unhandled exception:\n%s", traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"error": type(exc).__name__, "detail": str(exc)},
        )

    return app


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SwarmGen worker (one of clip|unet|vae).")
    p.add_argument("--role", required=True, choices=["clip", "unet", "vae"])
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    p.add_argument("--verbose", action="store_true", help="DEBUG logging")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    _setup_logging(args.verbose)
    log.info("starting SwarmGen worker role=%s port=%d host=%s pid=%d",
             args.role, args.port, args.host, os.getpid())

    app = make_app(args.role, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
