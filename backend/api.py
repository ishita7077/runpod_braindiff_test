import asyncio
import hashlib
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

from backend.atlas_peaks import describe_peak_abs_delta
from backend.brain_regions import build_vertex_masks
from backend.differ import compute_diff
from backend.heatmap import compute_vertex_delta, generate_heatmap_artifact
from backend.logging_utils import build_error_payload, configure_logging, write_structured_error
from backend.model_service import TribeService
from backend.narrative import build_headline
from backend.preflight import build_preflight_report
from backend.result_semantics import enrich_dimension_payload, winner_summary
from backend.insight_engine import build_insight_payload
from backend.schemas import DiffRequest, JobStartResponse
from backend.scorer import score_predictions
from backend.startup_manifest import build_startup_manifest, write_startup_manifest
from backend.status_store import JobStore
from backend.telemetry_store import TelemetryStore

logger = logging.getLogger("braindiff.api")

SLOW_NOTICE_MS = 180_000
HARD_TIMEOUT_MS = 1_200_000

# Populated by _initialize_app for /api/ready diagnostics.
startup_info: dict[str, Any] = {
    "skip_startup": False,
    "warmup_requested": False,
    "warmup_completed": False,
    "warmup_error": None,
}

job_store = JobStore()
tribe_service = TribeService(model_revision=os.getenv("TRIBEV2_REVISION", "facebook/tribev2"))
masks: dict[str, dict[str, Any]] = {}
LOG_DIR = os.getenv("BRAIN_DIFF_LOG_DIR", "logs")
TELEMETRY_DB_PATH = os.getenv("BRAIN_DIFF_TELEMETRY_DB", os.path.join(LOG_DIR, "telemetry.sqlite3"))
telemetry_store = TelemetryStore(TELEMETRY_DB_PATH)

# Single-job concurrency guard for local (mps/cpu) execution.
# CUDA users can raise the limit via BRAIN_DIFF_MAX_CONCURRENT_JOBS.
_diff_semaphore: asyncio.Semaphore | None = None


def _get_diff_semaphore() -> asyncio.Semaphore:
    global _diff_semaphore
    if _diff_semaphore is None:
        runtime_backend = ""
        if getattr(tribe_service, "runtime_profile", None) is not None:
            runtime_backend = tribe_service.runtime_profile.backend
        default_limit = 1  # conservative default for mps/cpu
        if runtime_backend == "cuda":
            default_limit = 4
        limit = int(os.getenv("BRAIN_DIFF_MAX_CONCURRENT_JOBS", str(default_limit)))
        _diff_semaphore = asyncio.Semaphore(limit)
    return _diff_semaphore


def _error_code_for_exception(err: Exception) -> tuple[str, str]:
    msg = str(err)
    if msg.startswith("HF_AUTH_REQUIRED:"):
        return "HF_AUTH_REQUIRED", msg
    if msg.startswith("FFMPEG_REQUIRED:"):
        return "FFMPEG_REQUIRED", msg
    if msg.startswith("UVX_REQUIRED:"):
        return "UVX_REQUIRED", msg
    if msg.startswith("WHISPERX_FAILED:"):
        return "WHISPERX_FAILED", msg
    if msg.startswith("LLAMA_LOAD_FAILED:"):
        return "LLAMA_LOAD_FAILED", msg
    if "Missing atlas area" in msg:
        return "ATLAS_MAPPING_ERROR", msg
    return "DIFF_JOB_FAILED", msg


def _initialize_app() -> None:
    global startup_info
    configure_logging(log_dir=LOG_DIR)
    logger.info("startup:start")
    if os.getenv("BRAIN_DIFF_SKIP_STARTUP", "0") == "1":
        logger.warning("startup:skipped via BRAIN_DIFF_SKIP_STARTUP=1")
        startup_info = {
            "skip_startup": True,
            "warmup_requested": False,
            "warmup_completed": False,
            "warmup_error": None,
        }
        return
    global masks
    masks = build_vertex_masks(atlas_dir=os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases"))
    tribe_service.load()
    warmup_on = os.getenv("BRAIN_DIFF_STARTUP_WARMUP", "0") == "1"
    startup_info["warmup_requested"] = warmup_on
    if warmup_on:
        logger.info("startup:warmup:running one text pipeline (set BRAIN_DIFF_STARTUP_WARMUP=0 to skip)")
        try:
            tribe_service.text_to_predictions("Hi.")
            startup_info["warmup_completed"] = True
            startup_info["warmup_error"] = None
            logger.info("startup:warmup:ok")
        except Exception as werr:
            startup_info["warmup_completed"] = False
            startup_info["warmup_error"] = str(werr)
            logger.warning("startup:warmup:failed_non_fatal: %s", werr, exc_info=True)
    runtime_dict: dict[str, Any] = {}
    if getattr(tribe_service, "runtime_profile", None) is not None:
        runtime_dict = {
            "device": tribe_service.runtime_profile.device,
            "backend": tribe_service.runtime_profile.backend,
        }
    manifest = build_startup_manifest(
        model_revision=tribe_service.model_revision,
        atlas_dir=os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases"),
        requirements_lock_path=os.getenv(
            "BRAIN_DIFF_REQUIREMENTS_LOCK", "backend/requirements_frozen.txt"
        ),
        runtime=runtime_dict,
        text_backend_strategy=getattr(tribe_service, "text_backend_strategy", None),
    )
    write_startup_manifest(manifest, output_path="backend/startup_manifest.json")
    logger.info("startup:ok")


@asynccontextmanager
async def lifespan(_: FastAPI):
    _initialize_app()
    yield


app = FastAPI(title="Brain Diff API", version="0.1.0", lifespan=lifespan)






def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _persist_run(*, job_id: str, request_id: str, created_at: str, status: str, success: bool,
                 payload: DiffRequest, stage_times: dict[str, int], warnings: list[str],
                 text_a_timesteps: int, text_b_timesteps: int, total_ms: int,
                 error_code: str | None = None, error_message: str | None = None) -> None:
    runtime = {}
    if getattr(tribe_service, 'runtime_profile', None) is not None:
        runtime = {
            'device': tribe_service.runtime_profile.device,
            'backend': tribe_service.runtime_profile.backend,
        }
    telemetry_store.upsert_run({
        'job_id': job_id,
        'request_id': request_id,
        'created_at': created_at,
        'status': status,
        'success': success,
        'text_a_length': len(payload.text_a),
        'text_b_length': len(payload.text_b),
        'text_a_hash': _hash_text(payload.text_a),
        'text_b_hash': _hash_text(payload.text_b),
        'text_a_timesteps': text_a_timesteps,
        'text_b_timesteps': text_b_timesteps,
        'total_ms': total_ms,
        'stage_times': stage_times,
        'warnings': warnings,
        'runtime': runtime,
        'error_code': error_code,
        'error_message': error_message,
    })
def _coerce_prediction_output(output: Any) -> tuple[np.ndarray, Any, dict[str, int]]:
    if isinstance(output, tuple):
        if len(output) == 3:
            preds, segments, timing = output
            return preds, segments, timing
        if len(output) == 2:
            preds, segments = output
            return preds, segments, {"events_ms": 0, "predict_ms": 0}
    raise ValueError(f"Unexpected prediction output shape: {type(output).__name__}")


def _warnings_for_input(text_a: str, text_b: str) -> list[str]:
    warnings: list[str] = []
    words_a = len([w for w in text_a.strip().split() if w])
    words_b = len([w for w in text_b.strip().split() if w])
    if words_a < 3 or words_b < 3:
        warnings.append("Very short text may produce unreliable results")
    min_len = max(1, min(len(text_a), len(text_b)))
    max_len = max(len(text_a), len(text_b))
    if max_len / min_len >= 10:
        warnings.append("Large length difference may affect comparison")
    return warnings


def _run_diff_job(job_id: str, request_id: str, payload: DiffRequest) -> None:
    started_at = time.perf_counter()
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
            vertex_a = np.zeros(20484, dtype=np.float32)
            vertex_b = np.zeros(20484, dtype=np.float32)
            t_heat = time.perf_counter()
            heatmap = generate_heatmap_artifact(vertex_delta)
            stage_times["heatmap_ms"] = int((time.perf_counter() - t_heat) * 1000)
            processing_time_ms = int((time.perf_counter() - started_at) * 1000)
            tone = os.environ.get("BRAIN_DIFF_NARRATIVE_TONE", "sober").strip().lower() or "sober"
            insights = build_insight_payload(dimension_rows, warnings, narrative_tone=tone)
            result = {
                "diff": diff,
                "dimensions": dimension_rows,
                "insights": insights,
                "vertex_delta": vertex_delta.astype(float).tolist(),
                "vertex_a": vertex_a.astype(float).tolist(),
                "vertex_b": vertex_b.astype(float).tolist(),
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
                    "atlas_peak": describe_peak_abs_delta(vertex_delta),
                },
            }
            job_store.set_result(job_id, result)
            job_store.update_status(job_id, "done", "Done")
            _persist_run(job_id=job_id, request_id=request_id, created_at=created_at, status="done", success=True, payload=payload, stage_times=stage_times, warnings=warnings, text_a_timesteps=0, text_b_timesteps=0, total_ms=processing_time_ms)
            return

        job_store.update_status(job_id, "predicting_version_a", "Predicting neural response for Version A...")
        preds_a, _, timing_a = _coerce_prediction_output(tribe_service.text_to_predictions(payload.text_a))
        stage_times["events_a_ms"] = timing_a.get("events_ms", 0)
        stage_times["predict_a_ms"] = timing_a.get("predict_ms", 0)

        if (time.perf_counter() - started_at) * 1000 > 15000:
            job_store.update_status(job_id, "slow_processing", "Still processing - longer texts take more time")

        job_store.update_status(job_id, "predicting_version_b", "Predicting neural response for Version B...")
        preds_b, _, timing_b = _coerce_prediction_output(tribe_service.text_to_predictions(payload.text_b))
        stage_times["events_b_ms"] = timing_b.get("events_ms", 0)
        stage_times["predict_b_ms"] = timing_b.get("predict_ms", 0)

        job_store.update_status(job_id, "computing_brain_contrast", "Computing brain contrast...")
        t2 = time.perf_counter()
        scores_a, median_a = score_predictions(preds_a, masks)
        scores_b, median_b = score_predictions(preds_b, masks)
        diff = compute_diff(scores_a, scores_b)
        dimension_rows = enrich_dimension_payload(diff)
        summary = winner_summary(dimension_rows)
        stage_times["score_diff_ms"] = int((time.perf_counter() - t2) * 1000)
        t_heat = time.perf_counter()
        vertex_delta, vertex_a, vertex_b = compute_vertex_delta(preds_a, preds_b)
        heatmap = generate_heatmap_artifact(vertex_delta)
        stage_times["heatmap_ms"] = int((time.perf_counter() - t_heat) * 1000)

        processing_time_ms = int((time.perf_counter() - started_at) * 1000)
        tone = os.environ.get("BRAIN_DIFF_NARRATIVE_TONE", "sober").strip().lower() or "sober"
        insights = build_insight_payload(dimension_rows, warnings, narrative_tone=tone)
        result = {
            "diff": diff,
            "dimensions": dimension_rows,
            "insights": insights,
            "vertex_delta": vertex_delta.astype(float).tolist(),
            "vertex_a": vertex_a.astype(float).tolist(),
            "vertex_b": vertex_b.astype(float).tolist(),
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
                "atlas_peak": describe_peak_abs_delta(vertex_delta),
            },
        }
        job_store.set_result(job_id, result)
        job_store.update_status(job_id, "done", "Done")
        _persist_run(job_id=job_id, request_id=request_id, created_at=created_at, status="done", success=True, payload=payload, stage_times=stage_times, warnings=warnings, text_a_timesteps=int(preds_a.shape[0]), text_b_timesteps=int(preds_b.shape[0]), total_ms=processing_time_ms)
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
        _persist_run(job_id=job_id, request_id=request_id, created_at=created_at, status="error", success=False, payload=payload, stage_times=stage_times, warnings=warnings, text_a_timesteps=0, text_b_timesteps=0, total_ms=int((time.perf_counter()-started_at)*1000), error_code=code, error_message=message)


async def _guarded_diff_job(job_id: str, request_id: str, payload: DiffRequest) -> None:
    sem = _get_diff_semaphore()
    async with sem:
        await asyncio.to_thread(_run_diff_job, job_id, request_id, payload)


@app.post("/api/diff/start", response_model=JobStartResponse)
async def start_diff(payload: DiffRequest) -> JobStartResponse:
    request_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    job_store.create(job_id, request_id)
    asyncio.create_task(_guarded_diff_job(job_id, request_id, payload))
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
    sem = _get_diff_semaphore()
    async with sem:
        await asyncio.to_thread(_run_diff_job, job_id, request_id, payload)
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=500, detail={"request_id": request_id, "message": "Job missing"})
    if job["status"] == "error":
        raise HTTPException(status_code=500, detail=job["error"])
    return JSONResponse(job["result"])


@app.get("/api/preflight")
async def preflight() -> JSONResponse:
    runtime_dict: dict[str, Any] = {}
    if getattr(tribe_service, "runtime_profile", None) is not None:
        runtime_dict = {
            "device": tribe_service.runtime_profile.device,
            "backend": tribe_service.runtime_profile.backend,
        }
    runtime_backend = runtime_dict.get("backend", "")
    default_max_jobs = 1 if runtime_backend in ("mps", "cpu", "") else 4
    max_concurrent_jobs = int(os.getenv("BRAIN_DIFF_MAX_CONCURRENT_JOBS", str(default_max_jobs)))
    report = build_preflight_report(
        model_loaded=tribe_service.model is not None,
        masks_ready=len(masks) > 0,
        runtime=runtime_dict,
        text_backend_strategy=getattr(tribe_service, "text_backend_strategy", None),
        slow_notice_ms=SLOW_NOTICE_MS,
        hard_timeout_ms=HARD_TIMEOUT_MS,
        max_concurrent_jobs=max_concurrent_jobs,
    )
    return JSONResponse(report)


@app.get("/api/ready")
async def api_ready() -> JSONResponse:
    """Lightweight readiness probe (after lifespan startup). Model/masks are warm."""
    runtime_dict: dict[str, Any] = {}
    if getattr(tribe_service, "runtime_profile", None) is not None:
        runtime_dict = {
            "device": tribe_service.runtime_profile.device,
            "backend": tribe_service.runtime_profile.backend,
        }
    model_ok = tribe_service.model is not None
    masks_ok = len(masks) > 0
    return JSONResponse(
        {
            "ok": model_ok and masks_ok and not startup_info.get("skip_startup"),
            "model_loaded": model_ok,
            "masks_ready": masks_ok,
            "startup_skipped": startup_info.get("skip_startup", False),
            "warmup_requested": startup_info.get("warmup_requested", False),
            "warmup_completed": startup_info.get("warmup_completed", False),
            "warmup_error": startup_info.get("warmup_error"),
            "runtime": runtime_dict,
        }
    )


@app.get("/api/brain-mesh")
async def brain_mesh() -> JSONResponse:
    """fsaverage5 pial coordinates for left/right hemispheres (WebGL viewer)."""
    from backend.brain_mesh import build_brain_mesh_payload

    return JSONResponse(build_brain_mesh_payload())


@app.get("/api/vertex-atlas")
async def vertex_atlas() -> JSONResponse:
    """Per-vertex HCP region labels + dimension reverse map (for hover tooltips)."""
    from backend.atlas_peaks import build_vertex_atlas_payload

    return JSONResponse(build_vertex_atlas_payload())


@app.get("/api/telemetry/recent")
async def telemetry_recent(limit: int = 20) -> JSONResponse:
    return JSONResponse({"runs": telemetry_store.get_recent(limit)})


@app.get("/api/telemetry/run/{job_id}")
async def telemetry_run(job_id: str) -> JSONResponse:
    run = telemetry_store.get_run(job_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    return JSONResponse(run)

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

