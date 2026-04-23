"""
Preview server for the BrainDiff marketing site.

Serves:
  - Static pages in frontend_new/ (landing, research, methodology, case studies)
  - Clean URL routes (/research, /methodology, /case-studies, /launch)
  - /api/brain-mesh — real fsaverage5 mesh via the existing backend/brain_mesh.py
  - /api/diff/start + /api/diff/status/{job_id} — MOCK pipeline. Returns
    deterministic fake results after a ~4 second simulated run so the whole
    input → run → results UX can be clicked through without the real ML
    stack. Swap the mock endpoints for the production ones in backend/api.py
    for a real deployment.

Deliberately does NOT load Llama / TRIBE v2 / WhisperX, so it boots in seconds
without a Hugging Face token.

Run:
    .venv/bin/python scripts/preview_server.py
Then open http://127.0.0.1:8000
"""

from __future__ import annotations

import base64
import math
import os
import random
import secrets
import struct
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.brain_mesh import build_brain_mesh_payload
from backend.schemas import DiffRequest

app = FastAPI(title="BrainDiff preview")

FRONTEND_DIR = REPO_ROOT / "frontend_new"


def _page(name: str) -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / f"{name}.html"))


@app.get("/research")
async def page_research() -> FileResponse:
    return _page("research")


@app.get("/methodology")
async def page_methodology() -> FileResponse:
    return _page("methodology")


@app.get("/launch")
async def page_launch() -> FileResponse:
    return _page("input")


@app.get("/api/brain-mesh")
async def brain_mesh() -> JSONResponse:
    return JSONResponse(build_brain_mesh_payload())


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "mode": "preview"})


# ---------------------------------------------------------------------------
# Mock comparison pipeline. Real pipeline lives in backend/api.py and needs
# the full ML stack (Llama + TRIBE v2 + WhisperX). The mock here just tracks
# when a job was created and returns a scripted status + fake result.
# ---------------------------------------------------------------------------

_MOCK_JOBS: dict[str, dict[str, Any]] = {}
MOCK_RUN_SECONDS = 4.0  # how long the fake "processing" takes

# Mock per-region signed deltas (B - A). Positive = B stronger.
_MOCK_DIMS = [
    ("attention_salience",  "Attention",           +0.18),
    ("memory_encoding",     "Memory encoding",     +0.24),
    ("personal_resonance",  "Personal relevance",  +0.31),
    ("gut_reaction",        "Gut reaction",        +0.22),
    ("social_thinking",     "Social reasoning",    -0.04),
    ("language_depth",      "Language depth",      -0.12),
    ("brain_effort",        "Processing effort",   -0.09),
]


def _encode_f32_b64(values: list[float]) -> str:
    buf = struct.pack(f"<{len(values)}f", *values)
    return base64.b64encode(buf).decode("ascii")


def _mock_vertex_delta() -> str:
    """Generate a fake per-vertex signed delta array (fsaverage5 ≈ 20,484 verts).
    Structure: a smooth gaussian bump over the cortex weighted by region deltas,
    enough to paint results.html's brain viewer without looking random."""
    n = 20_484
    values = [0.0] * n
    rng = random.Random(42)
    for i in range(n):
        # Three overlapping gaussian hotspots — one B-stronger, two mixed.
        u = i / n
        v = (
            0.35 * math.exp(-((u - 0.25) ** 2) / 0.02)   # +B hotspot
            - 0.18 * math.exp(-((u - 0.55) ** 2) / 0.025)  # +A hotspot
            + 0.12 * math.exp(-((u - 0.78) ** 2) / 0.015)  # +B hotspot
        )
        values[i] = v + rng.uniform(-0.015, 0.015)  # tiny noise
    return _encode_f32_b64(values)


def _build_mock_result(text_a: str, text_b: str) -> dict[str, Any]:
    dimensions = [
        {
            "key": k,
            "label": label,
            "delta": delta,
            "magnitude": abs(delta),
            "sign": "B" if delta >= 0 else "A",
            "low_confidence": abs(delta) < 0.06,
            "description": f"{label} · modelled contrast",
        }
        for (k, label, delta) in _MOCK_DIMS
    ]
    b_wins = sum(1 for _, _, d in _MOCK_DIMS if d > 0.05)
    a_wins = sum(1 for _, _, d in _MOCK_DIMS if d < -0.05)
    tied = len(_MOCK_DIMS) - b_wins - a_wins
    peak_label = "Medial prefrontal cortex (mPFC)"
    return {
        "meta": {
            "text_a_length": len(text_a),
            "text_b_length": len(text_b),
            "atlas_peak": {
                "label": peak_label,
                "abs_delta": 0.42,
                "vertex_index_flat": 4200,
            },
            "winner_summary": {"a_wins": a_wins, "b_wins": b_wins, "tied": tied},
            "stage_times": {
                "events_total_ms": 900,
                "predict_total_ms": 1800,
                "score_diff_ms": 120,
                "heatmap_ms": 240,
            },
            "headline": "Version B lands harder where it counts.",
            "mode": "preview-mock",
        },
        "insights": {
            "headline": "Version B lands harder where it counts.",
            "subhead": "Stronger on personal relevance, memory encoding, and gut reaction — slightly lower on language depth and processing effort.",
        },
        "dimensions": dimensions,
        "vertex_delta_b64": _mock_vertex_delta(),
    }


@app.post("/api/diff/start")
async def mock_diff_start(req: DiffRequest) -> JSONResponse:
    job_id = "mock-" + secrets.token_hex(8)
    _MOCK_JOBS[job_id] = {
        "status": "queued",
        "created": time.time(),
        "text_a": req.text_a,
        "text_b": req.text_b,
    }
    return JSONResponse({"job_id": job_id})


@app.get("/api/diff/status/{job_id}")
async def mock_diff_status(job_id: str) -> JSONResponse:
    job = _MOCK_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    elapsed = time.time() - job["created"]
    if elapsed < MOCK_RUN_SECONDS:
        # Map elapsed → [queued, running, running] phases for a bit of animation.
        phase = "predict" if elapsed < MOCK_RUN_SECONDS * 0.4 else (
            "score" if elapsed < MOCK_RUN_SECONDS * 0.75 else "heatmap"
        )
        return JSONResponse({
            "status": "running",
            "phase": phase,
            "progress": min(0.98, elapsed / MOCK_RUN_SECONDS),
        })
    # Build + cache the result once, return on subsequent polls.
    if "result" not in job:
        job["result"] = _build_mock_result(job["text_a"], job["text_b"])
        job["status"] = "done"
    return JSONResponse({"status": "done", "result": job["result"]})


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
