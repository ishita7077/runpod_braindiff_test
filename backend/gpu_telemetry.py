"""GPU memory telemetry — Phase A.4 of the production fix plan.

Why: before we test bigger content models, we need to know whether two
heavy comparisons inside one Python process leaves enough VRAM headroom.
Today there's no observable measurement; the worker just runs and hopes.

This module:
  * `gpu_memory_snapshot(stage)` — current allocated / reserved / peak in MB,
    plus device name. Soft-fails if torch isn't installed or if no GPU is
    visible (CPU/MPS runs return a stage marker with no numeric fields, so
    the audit format is identical regardless of environment).
  * `GPUAuditCollector` — append-only, thread-safe list of snapshots that
    the worker emits as `meta.gpu_audit.snapshots`.

The numbers are deliberately CUDA-specific. ROCm or MPS environments would
need their own paths; we don't have a Mac/AMD GPU in production today, so
this stays simple.
"""

from __future__ import annotations

import os
import threading
from typing import Any


def gpu_memory_snapshot(stage: str) -> dict[str, Any]:
    """Return a single-stage GPU memory snapshot.

    Always returns a dict with at least {"stage": <stage>}; CUDA-specific
    fields appear only when torch.cuda is available. Never raises — telemetry
    must never break the worker path.
    """
    snap: dict[str, Any] = {"stage": stage}
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            snap["device_index"] = int(torch.cuda.current_device())
            snap["device_name"] = torch.cuda.get_device_name(snap["device_index"])
            snap["allocated_mb"] = float(torch.cuda.memory_allocated()) / (1024 ** 2)
            snap["reserved_mb"] = float(torch.cuda.memory_reserved()) / (1024 ** 2)
            snap["peak_allocated_mb"] = float(torch.cuda.max_memory_allocated()) / (1024 ** 2)
            try:
                free_b, total_b = torch.cuda.mem_get_info()
                snap["free_mb"] = float(free_b) / (1024 ** 2)
                snap["total_mb"] = float(total_b) / (1024 ** 2)
            except Exception:
                # Some torch builds / driver combos don't expose mem_get_info.
                pass
        else:
            snap["device_name"] = "cpu"
    except Exception as exc:  # noqa: BLE001
        snap["device_name"] = "unknown"
        snap["telemetry_error"] = f"{type(exc).__name__}: {exc}"
    return snap


class GPUAuditCollector:
    """Thread-safe accumulator for snapshots taken across a worker job.

    The worker creates one collector per job, calls `record(stage)` at the
    documented checkpoints, and surfaces `to_audit()` on the response meta.

    Concurrent .record() calls are safe — torch.cuda.* are themselves
    process-global so the lock only protects our list mutation. We DO NOT
    serialise the GPU itself; that's the GPU job lock's concern (Phase E.1).
    """

    def __init__(self) -> None:
        self._snapshots: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, stage: str) -> dict[str, Any]:
        snap = gpu_memory_snapshot(stage)
        with self._lock:
            self._snapshots.append(snap)
        return snap

    def to_audit(self, *, safe_inprocess_concurrency: int | None = None) -> dict[str, Any]:
        with self._lock:
            snapshots = list(self._snapshots)
        device = "cpu"
        for s in snapshots:
            if s.get("device_name") and s["device_name"] != "cpu":
                device = s["device_name"]
                break
        if safe_inprocess_concurrency is None:
            safe_inprocess_concurrency = int(
                os.getenv("BRAIN_DIFF_GPU_JOB_CONCURRENCY", "1")
            )
        return {
            "schema_version": "gpu_audit.v1",
            "device": device,
            "safe_inprocess_concurrency": safe_inprocess_concurrency,
            "snapshots": snapshots,
        }
