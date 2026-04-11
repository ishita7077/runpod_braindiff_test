"""Compact vertex arrays for JSON (avoid slow float .tolist() and huge number payloads)."""

from __future__ import annotations

import base64

import numpy as np


def f32_b64(arr: np.ndarray) -> str:
    """Little-endian float32 values as standard base64 text."""
    flat = np.asarray(arr, dtype=np.float32).reshape(-1)
    return base64.b64encode(flat.tobytes()).decode("ascii")
