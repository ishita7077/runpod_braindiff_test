#!/usr/bin/env python3
"""End-to-end Brain Diff via HTTP (expects API already running)."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("BRAIN_DIFF_E2E_BASE", "http://127.0.0.1:8000").rstrip("/")
# First diff on Mac often >15m (Whisper CPU + Llama CPU + MPS brain ×2)
TIMEOUT_S = int(os.environ.get("BRAIN_DIFF_E2E_TIMEOUT", "1200"))


def _req(method: str, path: str, body: dict | None = None, timeout: float = 60) -> tuple[int, dict | list | None]:
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return e.code, parsed


def main() -> int:
    print(f"e2e: base={BASE} timeout_job={TIMEOUT_S}s", flush=True)
    code, pre = _req("GET", "/api/preflight", timeout=120)
    if code != 200 or not isinstance(pre, dict):
        print("e2e: FAIL preflight", code, pre, flush=True)
        return 1
    print(
        "e2e: preflight",
        json.dumps(
            {k: pre.get(k) for k in ("ok", "blockers", "model_loaded", "runtime", "text_backend_strategy", "limits")},
            indent=2,
        ),
        flush=True,
    )
    if not pre.get("ok"):
        print("e2e: FAIL preflight not ok — fix blockers first", flush=True)
        return 1

    code, ready = _req("GET", "/api/ready", timeout=30)
    if code != 200 or not isinstance(ready, dict):
        print("e2e: FAIL /api/ready", code, ready, flush=True)
        return 1
    for key in ("model_loaded", "masks_ready", "startup_skipped", "warmup_requested", "warmup_completed", "ok"):
        if key not in ready:
            print("e2e: FAIL /api/ready missing key", key, flush=True)
            return 1
    print(
        "e2e: ready",
        json.dumps(
            {k: ready.get(k) for k in ("ok", "model_loaded", "masks_ready", "startup_skipped", "warmup_completed", "warmup_error")},
            indent=2,
        ),
        flush=True,
    )

    mesh_timeout = float(os.environ.get("BRAIN_DIFF_E2E_BRAIN_MESH_TIMEOUT", "240"))
    code, mesh = _req("GET", "/api/brain-mesh", timeout=mesh_timeout)
    if code != 200 or not isinstance(mesh, dict):
        print("e2e: FAIL /api/brain-mesh", code, mesh, flush=True)
        return 1
    for key in ("format", "lh_coord", "lh_faces", "rh_coord", "rh_faces"):
        if key not in mesh:
            print("e2e: FAIL /api/brain-mesh missing key", key, flush=True)
            return 1
    lh_n = len(mesh["lh_coord"]) if isinstance(mesh["lh_coord"], list) else 0
    print("e2e: brain-mesh ok format=", mesh.get("format"), "lh_coord_len=", lh_n, flush=True)

    fast = os.environ.get("BRAIN_DIFF_E2E_FAST", "0") == "1"
    if fast:
        payload = {"text_a": "identical short smoke", "text_b": "identical short smoke"}
    else:
        payload = {
            "text_a": "The team celebrated after winning the regional match last night.",
            "text_b": "After securing the regional title, the squad gathered for a quiet dinner.",
        }
    code, start = _req("POST", "/api/diff/start", payload, timeout=60)
    if code != 200 or not isinstance(start, dict) or "job_id" not in start:
        print("e2e: FAIL start", code, start, flush=True)
        return 1
    job_id = start["job_id"]
    print("e2e: job_id", job_id, flush=True)

    deadline = time.monotonic() + TIMEOUT_S
    last_status = None
    while time.monotonic() < deadline:
        code, st = _req("GET", f"/api/diff/status/{job_id}", timeout=60)
        if code != 200 or not isinstance(st, dict):
            print("e2e: FAIL status", code, st, flush=True)
            return 1
        last_status = st.get("status")
        if last_status in ("done", "error"):
            break
        time.sleep(0.5)
    else:
        print("e2e: FAIL timeout waiting for job", flush=True)
        return 1

    if last_status == "error":
        print("e2e: FAIL job error", json.dumps(st.get("error"), indent=2), flush=True)
        return 1

    result = st.get("result")
    if not isinstance(result, dict) or "dimensions" not in result:
        print("e2e: FAIL missing result", flush=True)
        return 1
    print("e2e: OK dimensions count", len(result.get("dimensions", [])), flush=True)

    # Fetch telemetry for this run.
    tel_code, tel = _req("GET", f"/api/telemetry/run/{job_id}", timeout=30)
    if tel_code == 200 and isinstance(tel, dict):
        runtime = tel.get("runtime") or {}
        stage_times = tel.get("stage_times") or {}
        print(
            "e2e: telemetry",
            json.dumps(
                {
                    "runtime_device": runtime.get("device"),
                    "runtime_backend": runtime.get("backend"),
                    "text_backend_strategy": tel.get("text_backend_strategy"),
                    "total_ms": tel.get("total_ms"),
                    "stage_times": stage_times,
                },
                indent=2,
            ),
            flush=True,
        )
    else:
        print(f"e2e: telemetry fetch failed (status={tel_code})", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
