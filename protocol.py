"""
SwarmGen wire protocol for tensors.

Format: [4-byte big-endian header length][JSON header bytes][raw tensor bytes]

JSON header fields:
    shape:  list[int]
    dtype:  str   (e.g. "float16", "float32", "int64")

No pickle. Trivial to debug, version-stable, fast.

Run this file directly to round-trip a random tensor and assert equality:
    python protocol.py
"""
from __future__ import annotations

import io
import json
import struct
from typing import Tuple

import torch

_HEADER_LEN_STRUCT = struct.Struct(">I")  # 4-byte unsigned big-endian


def _torch_dtype_to_str(dtype: torch.dtype) -> str:
    return str(dtype).removeprefix("torch.")


def _str_to_torch_dtype(name: str) -> torch.dtype:
    dt = getattr(torch, name, None)
    if not isinstance(dt, torch.dtype):
        raise ValueError(f"unknown torch dtype: {name!r}")
    return dt


def pack_tensor(t: torch.Tensor) -> bytes:
    """Serialize a torch.Tensor to bytes (CPU contiguous + JSON header + raw)."""
    if not isinstance(t, torch.Tensor):
        raise TypeError(f"pack_tensor expected torch.Tensor, got {type(t)}")
    cpu = t.detach().to("cpu").contiguous()
    header = {
        "shape": list(cpu.shape),
        "dtype": _torch_dtype_to_str(cpu.dtype),
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    raw = cpu.numpy().tobytes() if cpu.numel() > 0 else b""
    return _HEADER_LEN_STRUCT.pack(len(header_bytes)) + header_bytes + raw


def unpack_tensor(b: bytes) -> torch.Tensor:
    """Inverse of pack_tensor."""
    if len(b) < 4:
        raise ValueError("payload too short for header length prefix")
    (hlen,) = _HEADER_LEN_STRUCT.unpack(b[:4])
    if len(b) < 4 + hlen:
        raise ValueError("payload too short for declared header")
    header = json.loads(b[4 : 4 + hlen].decode("utf-8"))
    raw = b[4 + hlen :]
    dtype = _str_to_torch_dtype(header["dtype"])
    shape = tuple(int(x) for x in header["shape"])
    if all(s > 0 for s in shape) or len(shape) == 0:
        # Use frombuffer for zero-copy from a bytes object, then reshape.
        # Note: torch.frombuffer requires writable buffer for some dtypes; use a copy via tensor() to be safe.
        import numpy as np

        np_dtype_map = {
            "float16": "float16",
            "float32": "float32",
            "float64": "float64",
            "bfloat16": None,  # numpy lacks bf16; handle separately
            "int8": "int8",
            "int16": "int16",
            "int32": "int32",
            "int64": "int64",
            "uint8": "uint8",
            "bool": "bool",
        }
        np_name = np_dtype_map.get(header["dtype"])
        if np_name is None and header["dtype"] == "bfloat16":
            # Round-trip bf16 via uint16 view.
            arr = np.frombuffer(raw, dtype="uint16").reshape(shape).copy()
            t = torch.from_numpy(arr).view(torch.bfloat16)
        else:
            if np_name is None:
                raise ValueError(f"unsupported dtype for unpack: {header['dtype']}")
            arr = np.frombuffer(raw, dtype=np_name).reshape(shape).copy()
            t = torch.from_numpy(arr)
        return t
    # Empty tensor
    return torch.empty(shape, dtype=dtype)


def header_only(b: bytes) -> Tuple[dict, int]:
    """Return (header_dict, total_header_size_in_bytes_including_length_prefix)."""
    (hlen,) = _HEADER_LEN_STRUCT.unpack(b[:4])
    return json.loads(b[4 : 4 + hlen].decode("utf-8")), 4 + hlen


def _roundtrip_check() -> None:
    import numpy as np

    cases = [
        torch.randn(2, 3, 4, dtype=torch.float32),
        torch.randn(1, 4, 64, 64, dtype=torch.float16),
        torch.randint(0, 1000, (1, 77), dtype=torch.int64),
        torch.zeros((), dtype=torch.float32),
    ]
    for i, t in enumerate(cases):
        b = pack_tensor(t)
        t2 = unpack_tensor(b)
        assert t.shape == t2.shape, f"case {i} shape mismatch"
        assert t.dtype == t2.dtype, f"case {i} dtype mismatch {t.dtype} vs {t2.dtype}"
        assert torch.equal(t, t2), f"case {i} value mismatch"
        print(f"  case {i}: {tuple(t.shape)} {t.dtype}  packed={len(b)}B  OK")
    print("protocol.py round-trip: OK")


if __name__ == "__main__":
    print("SwarmGen protocol self-test")
    print(f"  torch={torch.__version__}")
    _roundtrip_check()
