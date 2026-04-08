import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.brain_regions import build_vertex_masks
from backend.differ import compute_diff
from backend.heatmap import compute_vertex_delta, generate_heatmap_artifact
from backend.logging_utils import build_error_payload, configure_logging, write_structured_error
from backend.model_service import TribeService
from backend.narrative import build_headline
from backend.preflight import build_preflight_report
from backend.result_semantics import enrich_dimension_payload, winner_summary
from backend.schemas import DiffRequest, JobStartResponse
from backend.scorer import score_predictions
from backend.startup_manifest import build_startup_manifest, write_startup_manifest
from backend.status_store import JobStore

logger = logging.getLogger("braindiff.api")

job_store = JobStore()
tribe_service = TribeService(model_revision=os.getenv("TRIBEV2_REVISION", "facebook/tribev2"))
masks: dict[str, dict[str, Any]] = {}
LOG_DIR = os.getenv("BRAIN_DIFF_LOG_DIR", "logs")


def _error_code_for_exception(err: Exception) -> tuple[str, str]:
    msg = str(err)
    if msg.startswith("HF_AUTH_REQUIRED:"):
        return "HF_AUTH_REQUIRED", msg
    if msg.startswith("FFMPEG_REQUIRED:"):
        return "FFMPEG_REQUIRED", msg
    if msg.startswith("UVX_REQUIRED:"):
        return "UVX_REQUIRED", msg
    if "Missing atlas area" in msg:
        return "ATLAS_MAPPING_ERROR", msg
    return "DIFF_JOB_FAILED", msg


def _initialize_app() -> None:
    configure_logging(log_dir=LOG_DIR)
    logger.info("startup:start")
    if os.getenv("BRAIN_DIFF_SKIP_STARTUP", "0") == "1":
        logger.warning("startup:skipped via BRAIN_DIFF_SKIP_STARTUP=1")
        return
    global masks
    masks = build_vertex_masks(atlas_dir=os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases"))
    tribe_service.load()
    manifest = build_startup_manifest(
        model_revision=tribe_service.model_revision,
        atlas_dir=os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases"),
        requirements_lock_path=os.getenv(
            "BRAIN_DIFF_REQUIREMENTS_LOCK", "backend/requirements_frozen.txt"
        ),
        runtime_info=tribe_service.runtime_info,
    )
    write_startup_manifest(manifest, output_path="backend/startup_manifest.json")
    logger.info("startup:ok")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _initialize_app()
    yield


app = FastAPI(title="Brain Diff API", version="0.1.0", lifespan=lifespan)


def _warnings_for_input(text_a: str, text_b: str) -> list[str]:
    warnings: list[str] = []
    if len(text_a) < 10 or len(text_b) < 10:
        warnings.append("Very short text may produce unreliable results")
    min_len = max(1, min(len(text_a), len(text_b)))
    max_len = max(len(text_a), len(text_b))
    if max_len / min_len >= 10:
        warnings.append("Large length difference may affect comparison")
    return warnings


def _run_diff_job(job_id: str, request_id: str, payload: DiffRequest) -> None:
    started_at = time.perf_counter()
    warnings = _warnings_for_input(payload.text_a, payload.text_b)
    stage_times: dict[str, int] = {}
    route = "/api/diff/start"

    try:
        job_store.update_status(job_id, "converting_text_to_speech", "Converting text to speech...")
        if payload.text_a.strip() == payload.text_b.strip():
            job_store.update_status(job_id, "predicting_version_a", "Predicting neural response for Version A...")
            job_store.update_status(job_id, "predicting_version_b", "Predicting neural response for Version B...")
            job_store.update_status(job_id, "computing_brain_contrast", "Computing brain contrast...")
            zero_scores = {
                dim_name: {"normalized_signed_mean": 0.0}
                for dim_name in masks.keys()
            }
            diff = compute_diff(zero_scores, zero_scores)
            dimension_rows = enrich_dimension_payload(diff)
            summary = winner_summary(dimension_rows)
            vertex_delta = np.zeros(20484, dtype=np.float32)
            heatmap = generate_heatmap_artifact(vertex_delta)
            processing_time_ms = int((time.perf_counter() - started_at) * 1000)
            result = {
                "diff": diff,
                "dimensions": dimension_rows,
                "vertex_delta": vertex_delta.astype(float).tolist(),
                "warnings": warnings,
                "meta": {
                    "model_revision": tribe_service.model_revision,
                    "atlas": "HCP_MMP1.0",
                    "method_primary": "signed_roi_contrast",
                    "normalization": "within_stimulus_median",
                    "text_to_speech": True,
                    "text_a_length": len(payload.text_a),
                    "text_b_length": len(payload.text_b),
                    "text_a_timesteps": 0,
                    "text_b_timesteps": 0,
                    "processing_time_ms": processing_time_ms,
                    "request_id": request_id,
                    "job_id": job_id,
                    "headline": build_headline(diff),
                    "winner_summary": summary,
                    "stage_times": stage_times,
                    "median_a": 0.0,
                    "median_b": 0.0,
                    "heatmap": heatmap,
                    "identical_text_short_circuit": True,
                },
            }
            job_store.set_result(job_id, result)
            job_store.update_status(job_id, "done", "Done")
            return

        job_store.update_status(job_id, "predicting_version_a", "Predicting neural response for Version A...")
        t0 = time.perf_counter()
        preds_a, _ = tribe_service.text_to_predictions(payload.text_a)
        stage_times["predict_a_ms"] = int((time.perf_counter() - t0) * 1000)

        if (time.perf_counter() - started_at) * 1000 > 15000:
            job_store.update_status(job_id, "slow_processing", "Still processing - longer texts take more time")

        job_store.update_status(job_id, "predicting_version_b", "Predicting neural response for Version B...")
        t1 = time.perf_counter()
        preds_b, _ = tribe_service.text_to_predictions(payload.text_b)
        stage_times["predict_b_ms"] = int((time.perf_counter() - t1) * 1000)

        job_store.update_status(job_id, "computing_brain_contrast", "Computing brain contrast...")
        t2 = time.perf_counter()
        scores_a, median_a = score_predictions(preds_a, masks)
        scores_b, median_b = score_predictions(preds_b, masks)
        diff = compute_diff(scores_a, scores_b)
        dimension_rows = enrich_dimension_payload(diff)
        summary = winner_summary(dimension_rows)
        vertex_delta = compute_vertex_delta(preds_a, preds_b)
        heatmap = generate_heatmap_artifact(vertex_delta)
        stage_times["score_diff_ms"] = int((time.perf_counter() - t2) * 1000)

        processing_time_ms = int((time.perf_counter() - started_at) * 1000)
        result = {
            "diff": diff,
            "dimensions": dimension_rows,
            "vertex_delta": vertex_delta.astype(float).tolist(),
            "warnings": warnings,
            "meta": {
                "model_revision": tribe_service.model_revision,
                "atlas": "HCP_MMP1.0",
                "method_primary": "signed_roi_contrast",
                "normalization": "within_stimulus_median",
                "text_to_speech": True,
                "text_a_length": len(payload.text_a),
                "text_b_length": len(payload.text_b),
                "text_a_timesteps": int(preds_a.shape[0]),
                "text_b_timesteps": int(preds_b.shape[0]),
                "processing_time_ms": processing_time_ms,
                "request_id": request_id,
                "job_id": job_id,
                "headline": build_headline(diff),
                "winner_summary": summary,
                "stage_times": stage_times,
                "median_a": median_a,
                "median_b": median_b,
                "heatmap": heatmap,
            },
        }
        job_store.set_result(job_id, result)
        job_store.update_status(job_id, "done", "Done")
        logger.info(
            "diff_job:ok request_id=%s job_id=%s a_len=%s b_len=%s total_ms=%s",
            request_id,
            job_id,
            len(payload.text_a),
            len(payload.text_b),
            processing_time_ms,
        )
    except Exception as err:
        code, message = _error_code_for_exception(err)
        error = build_error_payload(
            request_id=request_id,
            route=route,
            stage=job_store.get(job_id)["status"] if job_store.get(job_id) else "unknown",
            err=err,
            extra={
                "job_id": job_id,
                "text_a_len": len(payload.text_a),
                "text_b_len": len(payload.text_b),
            },
        )
        write_structured_error(LOG_DIR, error)
        logger.error("diff_job:failed request_id=%s job_id=%s", request_id, job_id, exc_info=True)
        job_store.set_error(
            job_id,
            {
                "request_id": request_id,
                "job_id": job_id,
                "code": code,
                "message": message,
            },
        )


@app.post("/api/diff/start", response_model=JobStartResponse)
async def start_diff(payload: DiffRequest) -> JobStartResponse:
    request_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    job_store.create(job_id, request_id)
    asyncio.create_task(asyncio.to_thread(_run_diff_job, job_id, request_id, payload))
    return JobStartResponse(job_id=job_id, request_id=request_id, status="queued")


@app.get("/api/diff/status/{job_id}")
async def diff_status(job_id: str) -> JSONResponse:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    return JSONResponse(job)


@app.get("/api/diff/status/{job_id}/stream")
async def diff_status_stream(job_id: str) -> StreamingResponse:
    async def _event_stream() -> Any:
        cursor = 0
        while True:
            job = job_store.get(job_id)
            if not job:
                yield "event: error\ndata: {\"message\": \"Unknown job\"}\n\n"
                return
            events = job["events"]
            while cursor < len(events):
                event = events[cursor]
                cursor += 1
                yield f"event: status\ndata: {json.dumps(event)}\n\n"
            if job["status"] in {"done", "error"}:
                yield f"event: terminal\ndata: {{\"status\": \"{job['status']}\"}}\n\n"
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@app.post("/api/diff")
async def diff_sync(payload: DiffRequest) -> JSONResponse:
    request_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    job_store.create(job_id, request_id)
    await asyncio.to_thread(_run_diff_job, job_id, request_id, payload)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=500, detail={"request_id": request_id, "message": "Job missing"})
    if job["status"] == "error":
        raise HTTPException(status_code=500, detail=job["error"])
    return JSONResponse(job["result"])


@app.get("/api/preflight")
async def preflight() -> JSONResponse:
    report = build_preflight_report(
        model_loaded=tribe_service.model is not None,
        masks_ready=len(masks) > 0,
        runtime_info=tribe_service.runtime_info,
    )
    return JSONResponse(report)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

