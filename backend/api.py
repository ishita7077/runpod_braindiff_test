import asyncio
import base64
import hashlib
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.atlas_peaks import describe_peak_abs_delta
from backend.brain_regions import build_vertex_masks
from backend.differ import compute_diff
from backend.duration_utils import (
    DurationMismatch,
    DurationProbeError,
    check_media_similarity,
    check_text_similarity,
    ensure_within_max,
)
from backend.heatmap import compute_vertex_delta, generate_heatmap_artifact
from backend.logging_utils import build_error_payload, configure_logging, write_structured_error
from backend.model_service import TribeService
from backend.narrative import build_headline
from backend.preflight import build_preflight_report
from backend.result_semantics import enrich_dimension_payload, winner_summary
from backend.insight_engine import build_insight_payload
from backend.runtime import runtime_to_dict
from backend.schemas import DiffRequest, JobStartResponse, ReportRequest
from backend.scorer import score_predictions
from backend.startup_manifest import build_startup_manifest, write_startup_manifest
from backend.status_store import JobStore
from backend.telemetry_store import TelemetryStore
from backend.vertex_codec import f32_b64

logger = logging.getLogger("braindiff.api")

SLOW_NOTICE_MS = 180_000
HARD_TIMEOUT_MS = 1_200_000
HEARTBEAT_INTERVAL_SEC = 10

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
VIDEO_EXTRACTOR_WARMUP: dict[str, str] = {
    "state": "idle",
    "repo_id": "facebook/vjepa2-vitg-fpc64-256",
    "local_path": "",
    "error": "",
    "started_at": "",
    "finished_at": "",
}
UPLOAD_ROOT = os.path.join("cache", "uploads")
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg"}
VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _compute_report_summary(results: list[dict[str, Any]], processing_time_ms: int) -> dict[str, Any]:
    dim_buckets: dict[str, list[tuple[str, float]]] = {}
    for row in results:
        label = row.get("label", "")
        for dim, payload in row.get("diff", {}).items():
            dim_buckets.setdefault(dim, []).append((label, float(payload.get("delta", 0.0))))
    dimension_summary: dict[str, Any] = {}
    for dim, values in dim_buckets.items():
        if not values:
            continue
        avg_delta = sum(v for _, v in values) / len(values)
        max_pair = max(values, key=lambda x: x[1])[0]
        min_pair = min(values, key=lambda x: x[1])[0]
        dimension_summary[dim] = {
            "avg_delta": round(avg_delta, 6),
            "max_delta_pair": max_pair,
            "min_delta_pair": min_pair,
        }
    return {
        "total_pairs": len(results),
        "processing_time_ms": processing_time_ms,
        "dimension_summary": dimension_summary,
    }


def _service_runtime_dict() -> dict[str, str]:
    return runtime_to_dict(getattr(tribe_service, "runtime_profile", None))


def _get_diff_semaphore() -> asyncio.Semaphore:
    global _diff_semaphore
    if _diff_semaphore is None:
        runtime_backend = _service_runtime_dict().get("backend", "")
        default_limit = 1  # conservative default for mps/cpu
        if runtime_backend == "cuda":
            default_limit = 4
        limit = int(os.getenv("BRAIN_DIFF_MAX_CONCURRENT_JOBS", str(default_limit)))
        _diff_semaphore = asyncio.Semaphore(limit)
    return _diff_semaphore


def _error_code_for_exception(err: Exception) -> tuple[str, str]:
    if isinstance(err, DurationMismatch):
        return "INPUT_REJECTED", str(err)
    if isinstance(err, DurationProbeError):
        return "MEDIA_PROBE_FAILED", str(err)
    msg = str(err)
    if "Can't pickle" in msg and "LlamaDecoderLayer.forward" in msg:
        return (
            "MODEL_RUNTIME_PICKLE_ERROR",
            "Model runtime hit a pickling error inside prediction; check model worker/runtime compatibility.",
        )
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
    runtime_dict = _service_runtime_dict()
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
    runtime = _service_runtime_dict()
    text_a = payload.text_a or ""
    text_b = payload.text_b or ""
    telemetry_store.upsert_run({
        'job_id': job_id,
        'request_id': request_id,
        'created_at': created_at,
        'modality': payload.modality(),
        'status': status,
        'success': success,
        'text_a_length': len(text_a),
        'text_b_length': len(text_b),
        'text_a_hash': _hash_text(text_a),
        'text_b_hash': _hash_text(text_b),
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
    if not (isinstance(output, tuple) and len(output) == 3):
        raise ValueError(f"Unexpected prediction output shape: {type(output).__name__}")
    preds, segments, timing = output
    return preds, segments, timing


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


def _narrative_tone() -> str:
    tone = os.environ.get("BRAIN_DIFF_NARRATIVE_TONE", "sober").strip().lower()
    return tone or "sober"


def _pipeline_label(modality: str) -> str:
    """Mirror of the runpod worker's _pipeline_label.

    Replaces the old `text_to_speech: True` flag, which was true for text but
    silently set on audio/video too — those skip TTS entirely.
    """
    if modality == "text":
        return "text_to_speech"
    if modality == "audio":
        return "audio_direct"
    return "video_frames_audio"


def _build_diff_result(
    *,
    payload: DiffRequest,
    request_id: str,
    job_id: str,
    diff: dict[str, Any],
    dimension_rows: list[dict[str, Any]],
    warnings: list[str],
    vertex_delta: np.ndarray,
    vertex_a: np.ndarray,
    vertex_b: np.ndarray,
    heatmap: dict[str, Any],
    stage_times: dict[str, int],
    processing_time_ms: int,
    text_a_timesteps: int,
    text_b_timesteps: int,
    median_a: float,
    median_b: float,
    transcript_a: str = "",
    transcript_b: str = "",
    transcript_segments_a: list[dict[str, Any]] | None = None,
    transcript_segments_b: list[dict[str, Any]] | None = None,
    media_durations: dict[str, float] | None = None,
    media_features: dict[str, Any] | None = None,
    identical_short_circuit: bool = False,
) -> dict[str, Any]:
    """Assemble the shared /api/diff response body used by both the real
    and the identical-texts short-circuit paths."""
    modality = payload.modality()
    # For text mode the transcript is the original input. For audio/video the
    # caller passes the WhisperX-aligned word stream so the insight engine and
    # results recall card both have access to the actual content of the
    # stimulus rather than empty fallbacks.
    if modality == "text":
        transcript_a = transcript_a or (payload.text_a or "")
        transcript_b = transcript_b or (payload.text_b or "")
    insights = build_insight_payload(
        dimension_rows,
        warnings,
        narrative_tone=_narrative_tone(),
        text_a=transcript_a,
        text_b=transcript_b,
    )
    meta: dict[str, Any] = {
        "model_revision": tribe_service.model_revision,
        "atlas": "HCP_MMP1.0",
        "method_primary": "signed_roi_contrast",
        "normalization": "within_stimulus_median",
        "pipeline": _pipeline_label(modality),
        "modality": modality,
        "transcript_a": transcript_a,
        "transcript_b": transcript_b,
        "transcript_a_length": len(transcript_a),
        "transcript_b_length": len(transcript_b),
        "transcript_segments_a": list(transcript_segments_a or []),
        "transcript_segments_b": list(transcript_segments_b or []),
        "text_a_timesteps": text_a_timesteps,
        "text_b_timesteps": text_b_timesteps,
        "processing_time_ms": processing_time_ms,
        "request_id": request_id,
        "job_id": job_id,
        "headline": build_headline(diff),
        "winner_summary": winner_summary(dimension_rows),
        "stage_times": stage_times,
        "median_a": median_a,
        "median_b": median_b,
        "heatmap": heatmap,
        "atlas_peak": describe_peak_abs_delta(vertex_delta),
        "dimensions_count": len(diff),
        "stimulus_a_path": payload.audio_path_a or payload.video_path_a or "",
        "stimulus_b_path": payload.audio_path_b or payload.video_path_b or "",
    }
    if modality == "text":
        # Back-compat: text mode keeps text_a/text_b at the meta top level
        # because the recall card and tests still read them.
        meta["text_a"] = transcript_a
        meta["text_b"] = transcript_b
        meta["text_a_length"] = len(transcript_a)
        meta["text_b_length"] = len(transcript_b)
    if media_durations is not None:
        meta["media_duration_a_s"] = float(media_durations.get("a", 0.0))
        meta["media_duration_b_s"] = float(media_durations.get("b", 0.0))
    if media_features is not None:
        meta["media_features"] = media_features
    if identical_short_circuit:
        meta["identical_text_short_circuit"] = True
    return {
        "diff": diff,
        "dimensions": dimension_rows,
        "insights": insights,
        "vertex_delta_b64": f32_b64(vertex_delta),
        "vertex_a_b64": f32_b64(vertex_a),
        "vertex_b_b64": f32_b64(vertex_b),
        "warnings": warnings,
        "meta": meta,
    }


def _run_diff_job(job_id: str, request_id: str, payload: DiffRequest) -> None:
    started_at = time.perf_counter()
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    modality = payload.modality()
    logger.info("diff_job:start request_id=%s job_id=%s modality=%s", request_id, job_id, modality)
    warnings = _warnings_for_input(payload.text_a or "", payload.text_b or "") if modality == "text" else []
    stage_times: dict[str, int] = {}
    route = "/api/diff/start" if modality == "text" else "/api/diff/upload"

    media_durations: dict[str, float] | None = None
    media_features_payload: dict[str, Any] | None = None
    try:
        if modality == "text":
            check_text_similarity(payload.text_a or "", payload.text_b or "")
            job_store.update_status(job_id, "synthesizing_speech", "Synthesising speech for the text via gTTS...")
        elif modality == "audio":
            job_store.update_status(job_id, "decoding_audio", "Decoding audio features...")
            logger.info("diff_job:probe_media request_id=%s job_id=%s side=a modality=audio path=%s", request_id, job_id, payload.audio_path_a)
            path_a, dur_a, trimmed_a = ensure_within_max(payload.audio_path_a or "")
            logger.info("diff_job:probe_media_ok request_id=%s job_id=%s side=a duration_s=%.2f trimmed=%s", request_id, job_id, dur_a, trimmed_a)
            logger.info("diff_job:probe_media request_id=%s job_id=%s side=b modality=audio path=%s", request_id, job_id, payload.audio_path_b)
            path_b, dur_b, trimmed_b = ensure_within_max(payload.audio_path_b or "")
            logger.info("diff_job:probe_media_ok request_id=%s job_id=%s side=b duration_s=%.2f trimmed=%s", request_id, job_id, dur_b, trimmed_b)
            check_media_similarity(dur_a, dur_b)
            media_durations = {"a": float(dur_a), "b": float(dur_b)}
            payload = DiffRequest(audio_path_a=path_a, audio_path_b=path_b)
            if trimmed_a or trimmed_b:
                warnings.append("One or both stimuli were truncated to 30 seconds.")
            # Real audio amplitude envelope (200 RMS bins per side).
            try:
                from backend.media_features import audio_envelope
                media_features_payload = {
                    "waveform_a": audio_envelope(path_a),
                    "waveform_b": audio_envelope(path_b),
                }
            except Exception as err:
                warnings.append(f"Audio waveform extraction failed: {err}")
        else:
            job_store.update_status(job_id, "decoding_video", "Decoding video + extracting frames...")
            logger.info("diff_job:probe_media request_id=%s job_id=%s side=a modality=video path=%s", request_id, job_id, payload.video_path_a)
            path_a, dur_a, trimmed_a = ensure_within_max(payload.video_path_a or "")
            logger.info("diff_job:probe_media_ok request_id=%s job_id=%s side=a duration_s=%.2f trimmed=%s", request_id, job_id, dur_a, trimmed_a)
            logger.info("diff_job:probe_media request_id=%s job_id=%s side=b modality=video path=%s", request_id, job_id, payload.video_path_b)
            path_b, dur_b, trimmed_b = ensure_within_max(payload.video_path_b or "")
            logger.info("diff_job:probe_media_ok request_id=%s job_id=%s side=b duration_s=%.2f trimmed=%s", request_id, job_id, dur_b, trimmed_b)
            check_media_similarity(dur_a, dur_b)
            media_durations = {"a": float(dur_a), "b": float(dur_b)}
            payload = DiffRequest(video_path_a=path_a, video_path_b=path_b)
            if trimmed_a or trimmed_b:
                warnings.append("One or both stimuli were truncated to 30 seconds.")
            # Real video keyframes (scene-detected, embedded as base64).
            try:
                from backend.media_features import video_keyframes
                media_features_payload = {
                    "keyframes_a": video_keyframes(path_a),
                    "keyframes_b": video_keyframes(path_b),
                }
            except Exception as err:
                warnings.append(f"Video keyframe extraction failed: {err}")

        if modality == "text" and (payload.text_a or "").strip() == (payload.text_b or "").strip():
            job_store.update_status(job_id, "predicting_version_a", "Predicting neural response for Version A...")
            job_store.update_status(job_id, "predicting_version_b", "Predicting neural response for Version B...")
            job_store.update_status(job_id, "computing_brain_contrast", "Computing brain contrast...")
            zero_scores = {
                dim_name: {"normalized_signed_mean": 0.0}
                for dim_name in masks.keys()
            }
            diff = compute_diff(zero_scores, zero_scores)
            dimension_rows = enrich_dimension_payload(diff)
            vertex_delta = np.zeros(20484, dtype=np.float32)
            vertex_a = np.zeros(20484, dtype=np.float32)
            vertex_b = np.zeros(20484, dtype=np.float32)
            t_heat = time.perf_counter()
            heatmap = generate_heatmap_artifact(vertex_delta)
            stage_times["heatmap_ms"] = int((time.perf_counter() - t_heat) * 1000)
            processing_time_ms = int((time.perf_counter() - started_at) * 1000)
            result = _build_diff_result(
                payload=payload,
                request_id=request_id,
                job_id=job_id,
                diff=diff,
                dimension_rows=dimension_rows,
                warnings=warnings,
                vertex_delta=vertex_delta,
                vertex_a=vertex_a,
                vertex_b=vertex_b,
                heatmap=heatmap,
                stage_times=stage_times,
                processing_time_ms=processing_time_ms,
                text_a_timesteps=0,
                text_b_timesteps=0,
                median_a=0.0,
                median_b=0.0,
                identical_short_circuit=True,
            )
            job_store.set_result(job_id, result)
            job_store.update_status(job_id, "done", "Done")
            _persist_run(job_id=job_id, request_id=request_id, created_at=created_at, status="done", success=True, payload=payload, stage_times=stage_times, warnings=warnings, text_a_timesteps=0, text_b_timesteps=0, total_ms=processing_time_ms)
            return

        # The local FastAPI path emits two events per side via job_store —
        # transcribing_* (WhisperX) then predicting_* (TRIBE forward pass) —
        # which run.html's progress UI reads. The model_service call itself
        # is monolithic; we wrap it so the user sees real stage transitions,
        # not invented ones. The runpod worker uses the equivalent Redis
        # emitter for the same purpose.

        class _StoreEmitter:
            """Bridge model_service's ProgressEmitter Protocol onto job_store."""

            def __init__(self, side: str) -> None:
                self.side = side

            def emit(self, status: str, message: str) -> None:
                if status == "transcribing":
                    job_store.update_status(job_id, f"transcribing_version_{self.side}", message)
                elif status == "predicting":
                    job_store.update_status(job_id, f"predicting_version_{self.side}", message)
                elif status == "synthesizing_speech":
                    job_store.update_status(job_id, "synthesizing_speech", message)

        if modality == "text":
            logger.info("diff_job:predict_start request_id=%s job_id=%s side=a modality=text", request_id, job_id)
            preds_a, _, timing_a = _coerce_prediction_output(
                tribe_service.text_to_predictions(payload.text_a or "", progress=_StoreEmitter("a"))
            )
        elif modality == "audio":
            logger.info("diff_job:predict_start request_id=%s job_id=%s side=a modality=audio path=%s", request_id, job_id, payload.audio_path_a)
            preds_a, _, timing_a = _coerce_prediction_output(
                tribe_service.audio_to_predictions(payload.audio_path_a or "", progress=_StoreEmitter("a"))
            )
        else:
            logger.info("diff_job:predict_start request_id=%s job_id=%s side=a modality=video path=%s", request_id, job_id, payload.video_path_a)
            preds_a, _, timing_a = _coerce_prediction_output(
                tribe_service.video_to_predictions(payload.video_path_a or "", progress=_StoreEmitter("a"))
            )
        logger.info("diff_job:predict_ok request_id=%s job_id=%s side=a events_ms=%s predict_ms=%s timesteps=%s", request_id, job_id, timing_a.get("events_ms", 0), timing_a.get("predict_ms", 0), int(preds_a.shape[0]))
        stage_times["events_a_ms"] = int(timing_a.get("events_ms", 0) or 0)
        stage_times["predict_a_ms"] = int(timing_a.get("predict_ms", 0) or 0)

        if (time.perf_counter() - started_at) * 1000 > 15000:
            job_store.update_status(job_id, "slow_processing", "Still processing - longer stimuli take more time")

        if modality == "text":
            logger.info("diff_job:predict_start request_id=%s job_id=%s side=b modality=text", request_id, job_id)
            preds_b, _, timing_b = _coerce_prediction_output(
                tribe_service.text_to_predictions(payload.text_b or "", progress=_StoreEmitter("b"))
            )
        elif modality == "audio":
            logger.info("diff_job:predict_start request_id=%s job_id=%s side=b modality=audio path=%s", request_id, job_id, payload.audio_path_b)
            preds_b, _, timing_b = _coerce_prediction_output(
                tribe_service.audio_to_predictions(payload.audio_path_b or "", progress=_StoreEmitter("b"))
            )
        else:
            logger.info("diff_job:predict_start request_id=%s job_id=%s side=b modality=video path=%s", request_id, job_id, payload.video_path_b)
            preds_b, _, timing_b = _coerce_prediction_output(
                tribe_service.video_to_predictions(payload.video_path_b or "", progress=_StoreEmitter("b"))
            )
        logger.info("diff_job:predict_ok request_id=%s job_id=%s side=b events_ms=%s predict_ms=%s timesteps=%s", request_id, job_id, timing_b.get("events_ms", 0), timing_b.get("predict_ms", 0), int(preds_b.shape[0]))
        stage_times["events_b_ms"] = int(timing_b.get("events_ms", 0) or 0)
        stage_times["predict_b_ms"] = int(timing_b.get("predict_ms", 0) or 0)

        job_store.update_status(job_id, "computing_brain_contrast", "Computing brain contrast...")
        t2 = time.perf_counter()
        scores_a, median_a = score_predictions(preds_a, masks)
        scores_b, median_b = score_predictions(preds_b, masks)
        diff = compute_diff(scores_a, scores_b)
        dimension_rows = enrich_dimension_payload(diff)
        stage_times["score_diff_ms"] = int((time.perf_counter() - t2) * 1000)
        t_heat = time.perf_counter()
        vertex_delta, vertex_a, vertex_b = compute_vertex_delta(preds_a, preds_b)
        heatmap = generate_heatmap_artifact(vertex_delta)
        stage_times["heatmap_ms"] = int((time.perf_counter() - t_heat) * 1000)

        processing_time_ms = int((time.perf_counter() - started_at) * 1000)
        # Pull the WhisperX-aligned transcripts out of the model timing dicts
        # so the insight engine and the audio/video result pages both have
        # access to the actual content of the stimulus, not just zeros.
        transcript_a = str(timing_a.get("transcript_text", "") or "")
        transcript_b = str(timing_b.get("transcript_text", "") or "")
        transcript_segments_a = list(timing_a.get("transcript_segments") or [])
        transcript_segments_b = list(timing_b.get("transcript_segments") or [])
        # Real per-timestep peak-Δ moment detection (top-4) for media results.
        if modality != "text" and media_durations is not None:
            try:
                from backend.media_features import peak_moments
                anchor_duration = max(media_durations.get("a", 0.0), media_durations.get("b", 0.0))
                moments = peak_moments(
                    preds_a, preds_b, masks,
                    duration_seconds=anchor_duration,
                    top_k=4,
                )
                if moments:
                    media_features_payload = dict(media_features_payload or {})
                    media_features_payload["moments"] = moments
            except Exception as err:
                warnings.append(f"Peak moment detection failed: {err}")
        # Co-activation pattern detection (Learning Moment, Emotional Impact,
        # Reasoning Beat, Social Resonance). Reads pattern definitions from
        # frontend_new/data/pattern-definitions.json — same file the frontend
        # Pattern Card UI fetches, so the science stays consistent across the
        # whole stack.
        try:
            from backend.pattern_detector import detect_patterns_both_sides
            dur_a_anchor = (media_durations or {}).get("a") if media_durations else None
            dur_b_anchor = (media_durations or {}).get("b") if media_durations else None
            patterns_payload = detect_patterns_both_sides(
                dimension_rows,
                duration_a_s=dur_a_anchor,
                duration_b_s=dur_b_anchor,
            )
            if patterns_payload.get("a") or patterns_payload.get("b"):
                media_features_payload = dict(media_features_payload or {})
                media_features_payload["patterns"] = patterns_payload
        except Exception as err:
            warnings.append(f"Pattern detection failed: {err}")
        result = _build_diff_result(
            payload=payload,
            request_id=request_id,
            job_id=job_id,
            diff=diff,
            dimension_rows=dimension_rows,
            warnings=warnings,
            vertex_delta=vertex_delta,
            vertex_a=vertex_a,
            vertex_b=vertex_b,
            heatmap=heatmap,
            stage_times=stage_times,
            processing_time_ms=processing_time_ms,
            text_a_timesteps=int(preds_a.shape[0]),
            text_b_timesteps=int(preds_b.shape[0]),
            median_a=median_a,
            median_b=median_b,
            transcript_a=transcript_a,
            transcript_b=transcript_b,
            transcript_segments_a=transcript_segments_a,
            transcript_segments_b=transcript_segments_b,
            media_durations=media_durations,
            media_features=media_features_payload,
        )
        job_store.set_result(job_id, result)
        job_store.update_status(job_id, "done", "Done")
        _persist_run(job_id=job_id, request_id=request_id, created_at=created_at, status="done", success=True, payload=payload, stage_times=stage_times, warnings=warnings, text_a_timesteps=int(preds_a.shape[0]), text_b_timesteps=int(preds_b.shape[0]), total_ms=processing_time_ms)
        logger.info(
            "diff_job:ok request_id=%s job_id=%s modality=%s a_len=%s b_len=%s total_ms=%s",
            request_id,
            job_id,
            modality,
            len(payload.text_a or ""),
            len(payload.text_b or ""),
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
                "text_a_len": len(payload.text_a or ""),
                "text_b_len": len(payload.text_b or ""),
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
        started_at = time.perf_counter()
        task = asyncio.create_task(asyncio.to_thread(_run_diff_job, job_id, request_id, payload))
        timeout_sec = HARD_TIMEOUT_MS / 1000.0
        try:
            while True:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=HEARTBEAT_INTERVAL_SEC)
                    break
                except asyncio.TimeoutError:
                    elapsed = int(time.perf_counter() - started_at)
                    job = job_store.get(job_id) or {}
                    status = job.get("status", "processing")
                    events = job.get("events") or []
                    last_message = events[-1]["message"] if events else "Processing..."
                    base_message = last_message.split(" [heartbeat", 1)[0]
                    heartbeat_message = f"{base_message} [heartbeat +{elapsed}s]"
                    if status not in {"done", "error"}:
                        job_store.update_status(job_id, status, heartbeat_message)
                    logger.info(
                        "diff_job:heartbeat request_id=%s job_id=%s status=%s elapsed_s=%s",
                        request_id,
                        job_id,
                        status,
                        elapsed,
                    )
                    if elapsed >= timeout_sec:
                        raise asyncio.TimeoutError(f"Diff job exceeded {HARD_TIMEOUT_MS}ms")
            await task
        except asyncio.TimeoutError:
            if not task.done():
                task.cancel()
            created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            message = (
                f"The run exceeded the hard timeout ({HARD_TIMEOUT_MS // 1000}s). "
                "Check logs for the last active stage."
            )
            logger.error(
                "diff_job:timeout request_id=%s job_id=%s elapsed_ms=%s",
                request_id,
                job_id,
                elapsed_ms,
            )
            job_store.set_error(
                job_id,
                {"request_id": request_id, "job_id": job_id, "code": "DIFF_TIMEOUT", "message": message},
            )
            warnings = _warnings_for_input(payload.text_a or "", payload.text_b or "") if payload.modality() == "text" else []
            _persist_run(
                job_id=job_id,
                request_id=request_id,
                created_at=created_at,
                status="error",
                success=False,
                payload=payload,
                stage_times={},
                warnings=warnings,
                text_a_timesteps=0,
                text_b_timesteps=0,
                total_ms=elapsed_ms,
                error_code="DIFF_TIMEOUT",
                error_message=message,
            )


def _classify_ext(filename: str) -> str | None:
    ext = os.path.splitext(filename)[1].lower()
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    return None


async def _persist_upload(file: UploadFile, dest_dir: str, slot: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower()
    dest = os.path.join(dest_dir, f"{slot}{ext}")
    total_bytes = 0
    with open(dest, "wb") as handle:
        while chunk := await file.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_BYTES:
                handle.close()
                os.remove(dest)
                raise HTTPException(
                    status_code=413,
                    detail=f"{file.filename} exceeds 100 MB size cap.",
                )
            handle.write(chunk)
    return dest


def _warm_video_extractor_in_background() -> None:
    if VIDEO_EXTRACTOR_WARMUP["state"] in {"warming", "ready"}:
        return
    VIDEO_EXTRACTOR_WARMUP["state"] = "warming"
    VIDEO_EXTRACTOR_WARMUP["error"] = ""
    VIDEO_EXTRACTOR_WARMUP["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        from huggingface_hub import snapshot_download

        local_path = snapshot_download(
            repo_id=VIDEO_EXTRACTOR_WARMUP["repo_id"],
            allow_patterns=["*.json", "*.safetensors", "*.bin"],
        )
        VIDEO_EXTRACTOR_WARMUP["state"] = "ready"
        VIDEO_EXTRACTOR_WARMUP["local_path"] = local_path
    except Exception as err:
        VIDEO_EXTRACTOR_WARMUP["state"] = "error"
        VIDEO_EXTRACTOR_WARMUP["error"] = str(err)
    finally:
        VIDEO_EXTRACTOR_WARMUP["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@app.post("/api/diff/upload", response_model=JobStartResponse, status_code=202)
async def upload_diff(file_a: UploadFile, file_b: UploadFile) -> JSONResponse:
    kind_a = _classify_ext(file_a.filename or "")
    kind_b = _classify_ext(file_b.filename or "")
    if kind_a is None or kind_b is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file extension(s). Audio: {sorted(AUDIO_EXTS)}. "
                f"Video: {sorted(VIDEO_EXTS)}."
            ),
        )
    if kind_a != kind_b:
        raise HTTPException(
            status_code=400,
            detail=f"Both stimuli must be the same modality (got {kind_a} + {kind_b}).",
        )
    request_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    upload_dir = os.path.join(UPLOAD_ROOT, job_id)
    try:
        path_a = await _persist_upload(file_a, upload_dir, "a")
        path_b = await _persist_upload(file_b, upload_dir, "b")
    except Exception:
        if os.path.isdir(upload_dir):
            for filename in os.listdir(upload_dir):
                try:
                    os.remove(os.path.join(upload_dir, filename))
                except OSError:
                    pass
            try:
                os.rmdir(upload_dir)
            except OSError:
                pass
        raise
    payload = (
        DiffRequest(audio_path_a=path_a, audio_path_b=path_b)
        if kind_a == "audio"
        else DiffRequest(video_path_a=path_a, video_path_b=path_b)
    )
    job_store.create(job_id, request_id)
    asyncio.create_task(_guarded_diff_job(job_id, request_id, payload))
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "request_id": request_id, "status": "queued"},
    )


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


@app.post("/api/report")
async def report_batch(payload: ReportRequest) -> JSONResponse:
    if len(payload.pairs) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 pairs per report request")
    started_at = time.perf_counter()
    results: list[dict[str, Any]] = []
    sem = _get_diff_semaphore()
    for pair in payload.pairs:
        if not pair.text_a.strip() or not pair.text_b.strip():
            raise HTTPException(status_code=400, detail=f"Pair '{pair.label}' has empty text")
        request_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        job_store.create(job_id, request_id)
        async with sem:
            await asyncio.to_thread(
                _run_diff_job,
                job_id,
                request_id,
                DiffRequest(text_a=pair.text_a, text_b=pair.text_b),
            )
        job = job_store.get(job_id)
        if not job:
            raise HTTPException(status_code=500, detail=f"Report job missing: {job_id}")
        if job["status"] == "error":
            raise HTTPException(status_code=500, detail=job["error"])
        row = {
            "label": pair.label,
            "diff": job["result"]["diff"],
            "meta": job["result"]["meta"],
            "warnings": job["result"].get("warnings", []),
        }
        results.append(row)
    total_ms = int((time.perf_counter() - started_at) * 1000)
    summary = _compute_report_summary(results, total_ms)
    logger.info("report_batch:ok total_pairs=%s total_ms=%s", len(results), total_ms)
    return JSONResponse({"results": results, "summary": summary})


@app.get("/api/preflight")
async def preflight() -> JSONResponse:
    runtime_dict = _service_runtime_dict()
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
    report["video_extractor"] = {
        "ok": VIDEO_EXTRACTOR_WARMUP["state"] == "ready",
        "state": VIDEO_EXTRACTOR_WARMUP["state"],
        "repo_id": VIDEO_EXTRACTOR_WARMUP["repo_id"],
        "local_path": VIDEO_EXTRACTOR_WARMUP["local_path"],
        "error": VIDEO_EXTRACTOR_WARMUP["error"],
        "started_at": VIDEO_EXTRACTOR_WARMUP["started_at"],
        "finished_at": VIDEO_EXTRACTOR_WARMUP["finished_at"],
    }
    return JSONResponse(report)


@app.post("/api/warmup/video-extractor")
async def warmup_video_extractor() -> JSONResponse:
    if VIDEO_EXTRACTOR_WARMUP["state"] != "warming":
        asyncio.create_task(asyncio.to_thread(_warm_video_extractor_in_background))
    return JSONResponse(status_code=202, content={"ok": True, "status": VIDEO_EXTRACTOR_WARMUP})


@app.get("/api/health")
async def health() -> JSONResponse:
    return await api_ready()


@app.get("/api/ready")
async def api_ready() -> JSONResponse:
    """Lightweight readiness probe (after lifespan startup). Model/masks are warm."""
    runtime_dict = _service_runtime_dict()
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


@app.get("/api/dimension-masks")
async def dimension_masks() -> JSONResponse:
    """Authoritative boolean masks per cortical dimension (20484 vertices, uint8 0/1). For landing explainer."""
    global masks
    if not masks:
        try:
            masks = build_vertex_masks(atlas_dir=os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases"))
        except Exception as exc:
            logger.warning("dimension_masks:build_failed %s", exc)
            raise HTTPException(status_code=503, detail="atlas_masks_unavailable") from exc
    out: dict[str, str] = {}
    for name, payload in masks.items():
        m = np.asarray(payload["mask"], dtype=np.uint8)
        if m.size != 20484:
            raise HTTPException(status_code=500, detail=f"bad_mask_len:{name}")
        out[name] = base64.b64encode(m.tobytes()).decode("ascii")
    return JSONResponse(out)


@app.get("/api/telemetry/recent")
async def telemetry_recent(limit: int = 20) -> JSONResponse:
    return JSONResponse({"runs": telemetry_store.get_recent(limit)})


@app.get("/api/telemetry/run/{job_id}")
async def telemetry_run(job_id: str) -> JSONResponse:
    run = telemetry_store.get_run(job_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    return JSONResponse(run)


@app.get("/api/telemetry/dashboard")
async def telemetry_dashboard(limit: int = 200, offset: int = 0) -> JSONResponse:
    safe_limit = max(1, min(limit, 1000))
    safe_offset = max(0, offset)
    return JSONResponse(
        {
            "runs": telemetry_store.list_runs(limit=safe_limit, offset=safe_offset),
            "aggregate": telemetry_store.aggregate_metrics(),
            "pagination": {
                "limit": safe_limit,
                "offset": safe_offset,
            },
        }
    )

# ---------------------------------------------------------------------------
# Clean URL routes for the marketing site.
# Routes are registered BEFORE the StaticFiles mount so they win over the
# catch-all. Each returns the corresponding HTML file without the `.html`
# extension so the public URLs are tidy (e.g. /research, /launch).
# ---------------------------------------------------------------------------

_FRONTEND_DIR = os.path.join(os.getcwd(), "frontend_new")


def _page(name: str) -> FileResponse:
    return FileResponse(os.path.join(_FRONTEND_DIR, f"{name}.html"))


@app.get("/research")
async def page_research() -> FileResponse:
    return _page("research")


@app.get("/methodology")
async def page_methodology() -> FileResponse:
    return _page("methodology")


@app.get("/launch")
async def page_launch() -> FileResponse:
    # "Launch" is the input screen — the entry point to the live app flow.
    return _page("input")


@app.get("/dashboard")
async def page_dashboard() -> FileResponse:
    return _page("dashboard")


app.mount("/", StaticFiles(directory="frontend_new", html=True), name="frontend")

