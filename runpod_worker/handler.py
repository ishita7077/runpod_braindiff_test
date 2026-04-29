import os
import tempfile
import time
import uuid
from typing import Any

import httpx
import numpy as np
import runpod


def _hf_login_from_env() -> None:
    """Authenticate with HuggingFace Hub before any model download.

    The huggingface_hub library auto-detects HF_TOKEN / HUGGING_FACE_HUB_TOKEN /
    HUGGINGFACE_HUB_TOKEN, but the priority order has changed across versions
    and the env-var-only path silently sends unauthenticated requests when the
    var name doesn't match. To make gated-model access (meta-llama/Llama-3.2-3B)
    rock-solid we explicitly call huggingface_hub.login() with whichever token
    env var is set, before any TribeModel.from_pretrained call.
    """
    token = (
        os.getenv("HF_TOKEN")
        or os.getenv("HUGGING_FACE_HUB_TOKEN")
        or os.getenv("HUGGINGFACE_HUB_TOKEN")
    )
    if not token:
        return
    try:
        from huggingface_hub import login as _hf_login
        _hf_login(token=token, add_to_git_credential=False)
        # Also normalise the env var name so transformers/huggingface_hub
        # downstream code paths that read directly from os.environ all agree.
        os.environ["HF_TOKEN"] = token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = token
        os.environ["HUGGINGFACE_HUB_TOKEN"] = token
    except Exception:
        # Login failure is non-fatal here; subsequent gated downloads will
        # still raise the original 401 with our HF_AUTH_REQUIRED wrapper.
        pass


_hf_login_from_env()


from backend.atlas_peaks import describe_peak_abs_delta
from backend.brain_regions import build_vertex_masks
from backend.differ import compute_diff
from backend.heatmap import compute_vertex_delta, generate_heatmap_artifact
from backend.insight_engine import build_insight_payload
from backend.model_service import TribeService
from backend.narrative import build_headline
from backend.result_semantics import enrich_dimension_payload, winner_summary
from backend.scorer import score_predictions
from backend.vertex_codec import f32_b64

MODEL_REVISION = os.getenv("TRIBEV2_REVISION", "facebook/tribev2")
ATLAS_DIR = os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases")
MAX_DOWNLOAD_MB = int(os.getenv("RUNPOD_MEDIA_MAX_MB", "200"))

tribe_service = TribeService(model_revision=MODEL_REVISION)
masks: dict[str, dict[str, Any]] = {}


def _warm_start() -> None:
    global masks
    masks = build_vertex_masks(atlas_dir=ATLAS_DIR)
    tribe_service.load()


def _download_to_temp(url: str, blob_token: str = "") -> str:
    suffix = os.path.splitext(url.split("?", 1)[0])[1] or ".bin"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    downloaded = 0
    try:
        headers = {"authorization": f"Bearer {blob_token}"} if blob_token else None
        with httpx.stream("GET", url, headers=headers, timeout=60.0) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_MB * 1024 * 1024:
                    raise ValueError(f"MEDIA_TOO_LARGE: exceeded {MAX_DOWNLOAD_MB}MB download cap")
                handle.write(chunk)
        handle.close()
        return handle.name
    except Exception:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def _warnings_for_text(text_a: str, text_b: str) -> list[str]:
    warnings: list[str] = []
    words_a = len([w for w in text_a.strip().split() if w])
    words_b = len([w for w in text_b.strip().split() if w])
    if words_a < 3 or words_b < 3:
        warnings.append("Very short text may produce unreliable results")
    return warnings


def _coerce_prediction_output(output: Any) -> tuple[np.ndarray, Any, dict[str, int]]:
    if not (isinstance(output, tuple) and len(output) == 3):
        raise ValueError(f"Unexpected prediction output shape: {type(output).__name__}")
    preds, segments, timing = output
    return preds, segments, timing


def _build_response(
    *,
    text_a: str,
    text_b: str,
    modality: str,
    stage_times: dict[str, int],
    processing_time_ms: int,
    preds_a: np.ndarray,
    preds_b: np.ndarray,
    diff: dict[str, Any],
    dimension_rows: list[dict[str, Any]],
    vertex_delta: np.ndarray,
    vertex_a: np.ndarray,
    vertex_b: np.ndarray,
    median_a: float,
    median_b: float,
    warnings: list[str],
) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    insights = build_insight_payload(
        dimension_rows,
        warnings,
        narrative_tone=os.environ.get("BRAIN_DIFF_NARRATIVE_TONE", "sober"),
        text_a=text_a,
        text_b=text_b,
    )
    heatmap = generate_heatmap_artifact(vertex_delta)
    meta = {
        "model_revision": tribe_service.model_revision,
        "atlas": "HCP_MMP1.0",
        "method_primary": "signed_roi_contrast",
        "normalization": "within_stimulus_median",
        "text_to_speech": True,
        "text_a": text_a,
        "text_b": text_b,
        "text_a_length": len(text_a),
        "text_b_length": len(text_b),
        "text_a_timesteps": int(preds_a.shape[0]),
        "text_b_timesteps": int(preds_b.shape[0]),
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
        "modality": modality,
    }
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


def _run_text(text_a: str, text_b: str) -> dict[str, Any]:
    started = time.perf_counter()
    warnings = _warnings_for_text(text_a, text_b)

    preds_a, _, timing_a = _coerce_prediction_output(tribe_service.text_to_predictions(text_a))
    preds_b, _, timing_b = _coerce_prediction_output(tribe_service.text_to_predictions(text_b))

    scores_a, median_a = score_predictions(preds_a, masks)
    scores_b, median_b = score_predictions(preds_b, masks)
    diff = compute_diff(scores_a, scores_b)
    dimension_rows = enrich_dimension_payload(diff)
    vertex_delta, vertex_a, vertex_b = compute_vertex_delta(preds_a, preds_b)
    stage_times = {
        "events_a_ms": timing_a.get("events_ms", 0),
        "predict_a_ms": timing_a.get("predict_ms", 0),
        "events_b_ms": timing_b.get("events_ms", 0),
        "predict_b_ms": timing_b.get("predict_ms", 0),
    }
    processing_time_ms = int((time.perf_counter() - started) * 1000)
    return _build_response(
        text_a=text_a,
        text_b=text_b,
        modality="text",
        stage_times=stage_times,
        processing_time_ms=processing_time_ms,
        preds_a=preds_a,
        preds_b=preds_b,
        diff=diff,
        dimension_rows=dimension_rows,
        vertex_delta=vertex_delta,
        vertex_a=vertex_a,
        vertex_b=vertex_b,
        median_a=median_a,
        median_b=median_b,
        warnings=warnings,
    )


def _run_media(modality: str, media_url_a: str, media_url_b: str, blob_token: str = "") -> dict[str, Any]:
    started = time.perf_counter()
    path_a = _download_to_temp(media_url_a, blob_token=blob_token)
    path_b = _download_to_temp(media_url_b, blob_token=blob_token)
    try:
        if modality == "audio":
            preds_a, _, timing_a = _coerce_prediction_output(tribe_service.audio_to_predictions(path_a))
            preds_b, _, timing_b = _coerce_prediction_output(tribe_service.audio_to_predictions(path_b))
        else:
            preds_a, _, timing_a = _coerce_prediction_output(tribe_service.video_to_predictions(path_a))
            preds_b, _, timing_b = _coerce_prediction_output(tribe_service.video_to_predictions(path_b))

        scores_a, median_a = score_predictions(preds_a, masks)
        scores_b, median_b = score_predictions(preds_b, masks)
        diff = compute_diff(scores_a, scores_b)
        dimension_rows = enrich_dimension_payload(diff)
        vertex_delta, vertex_a, vertex_b = compute_vertex_delta(preds_a, preds_b)
        stage_times = {
            "events_a_ms": timing_a.get("events_ms", 0),
            "predict_a_ms": timing_a.get("predict_ms", 0),
            "events_b_ms": timing_b.get("events_ms", 0),
            "predict_b_ms": timing_b.get("predict_ms", 0),
        }
        processing_time_ms = int((time.perf_counter() - started) * 1000)
        return _build_response(
            text_a="",
            text_b="",
            modality=modality,
            stage_times=stage_times,
            processing_time_ms=processing_time_ms,
            preds_a=preds_a,
            preds_b=preds_b,
            diff=diff,
            dimension_rows=dimension_rows,
            vertex_delta=vertex_delta,
            vertex_a=vertex_a,
            vertex_b=vertex_b,
            median_a=median_a,
            median_b=median_b,
            warnings=[],
        )
    finally:
        for path in (path_a, path_b):
            try:
                os.unlink(path)
            except OSError:
                pass


def handler(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("input", {})
    mode = (payload.get("mode") or "text").strip().lower()
    if mode == "text":
        text_a = (payload.get("text_a") or "").strip()
        text_b = (payload.get("text_b") or "").strip()
        if not text_a or not text_b:
            raise ValueError("text_a and text_b are required for mode=text")
        return _run_text(text_a=text_a, text_b=text_b)
    if mode not in {"audio", "video"}:
        raise ValueError("mode must be one of: text, audio, video")
    media_url_a = (payload.get("media_url_a") or "").strip()
    media_url_b = (payload.get("media_url_b") or "").strip()
    blob_token = (payload.get("blob_token") or "").strip()
    if not media_url_a or not media_url_b:
        raise ValueError("media_url_a and media_url_b are required for audio/video mode")
    return _run_media(mode, media_url_a=media_url_a, media_url_b=media_url_b, blob_token=blob_token)


if os.getenv("BRAIN_DIFF_RUNPOD_SKIP_WARMUP", "0") != "1":
    _warm_start()
runpod.serverless.start({"handler": handler})
