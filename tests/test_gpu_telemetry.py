"""Phase A.4 — GPU memory telemetry.

The audit module must work in three environments:
  * cuda (production RunPod): emits allocated/reserved/peak/free/total
  * cpu (CI / local sandbox): emits stage marker only
  * torch missing entirely: emits stage marker + telemetry_error

We test the cpu and cuda-emulated paths by monkeypatching the torch import.
"""

from __future__ import annotations

import threading
from unittest import mock

from backend.gpu_telemetry import GPUAuditCollector, gpu_memory_snapshot


def test_snapshot_includes_stage_even_without_torch() -> None:
    """If torch import fails the snapshot still has the stage marker."""
    snap = gpu_memory_snapshot("smoke_stage")
    assert snap["stage"] == "smoke_stage"
    # device_name will be "cpu", "cuda:N", or "unknown" depending on env.
    assert "device_name" in snap


def test_snapshot_handles_cpu_only_environment() -> None:
    """When torch is present but cuda isn't available, no MB fields appear."""
    fake_torch = mock.MagicMock()
    fake_torch.cuda.is_available.return_value = False
    with mock.patch.dict("sys.modules", {"torch": fake_torch}):
        snap = gpu_memory_snapshot("cpu_only")
    assert snap["stage"] == "cpu_only"
    assert snap["device_name"] == "cpu"
    assert "allocated_mb" not in snap


def test_snapshot_emits_cuda_fields_when_available() -> None:
    fake_torch = mock.MagicMock()
    fake_torch.cuda.is_available.return_value = True
    fake_torch.cuda.current_device.return_value = 0
    fake_torch.cuda.get_device_name.return_value = "Test GPU"
    fake_torch.cuda.memory_allocated.return_value = 2 * (1024 ** 2)   # 2 MB
    fake_torch.cuda.memory_reserved.return_value = 4 * (1024 ** 2)
    fake_torch.cuda.max_memory_allocated.return_value = 8 * (1024 ** 2)
    fake_torch.cuda.mem_get_info.return_value = (40 * 1024 ** 2, 48 * 1024 ** 2)

    with mock.patch.dict("sys.modules", {"torch": fake_torch}):
        snap = gpu_memory_snapshot("post_load")

    assert snap["stage"] == "post_load"
    assert snap["device_name"] == "Test GPU"
    assert snap["allocated_mb"] == 2.0
    assert snap["reserved_mb"] == 4.0
    assert snap["peak_allocated_mb"] == 8.0
    assert snap["free_mb"] == 40.0
    assert snap["total_mb"] == 48.0


def test_collector_to_audit_shape() -> None:
    col = GPUAuditCollector()
    col.record("a")
    col.record("b")
    col.record("c")
    audit = col.to_audit(safe_inprocess_concurrency=1)
    assert audit["schema_version"] == "gpu_audit.v1"
    assert audit["safe_inprocess_concurrency"] == 1
    assert [s["stage"] for s in audit["snapshots"]] == ["a", "b", "c"]


def test_collector_is_thread_safe() -> None:
    col = GPUAuditCollector()

    def worker(i: int) -> None:
        col.record(f"stage_{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    audit = col.to_audit()
    assert len(audit["snapshots"]) == 20
    stages = sorted(s["stage"] for s in audit["snapshots"])
    assert stages == sorted(f"stage_{i}" for i in range(20))


def test_collector_picks_first_non_cpu_device() -> None:
    """When mixed snapshots arrive (cpu boot, then cuda once loaded), the
    summary should pick the cuda device name as the rollup device.
    """
    col = GPUAuditCollector()
    col._snapshots.append({"stage": "boot", "device_name": "cpu"})
    col._snapshots.append({"stage": "post_load", "device_name": "Test GPU"})
    audit = col.to_audit()
    assert audit["device"] == "Test GPU"
