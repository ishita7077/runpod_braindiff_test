import os
import tempfile
import time
import uuid
from typing import Any
from urllib.parse import unquote, urlparse

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
        os.environ["HF_TOKEN"] = token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = token
        os.environ["HUGGINGFACE_HUB_TOKEN"] = token
    except Exception:
        pass


_hf_login_from_env()


from backend.atlas_peaks import describe_peak_abs_delta
from backend.brain_regions import build_vertex_masks
from backend.differ import compute_diff
from backend.duration_utils import (
    DurationMismatch,
    DurationProbeError,
    check_media_similarity,
    ensure_within_max,
    probe_duration_seconds,
)
from backend.heatmap import compute_vertex_delta, generate_heatmap_artifact
from backend.insight_engine import build_insight_payload
from backend.media_features import audio_envelope, peak_moments, video_keyframes
from backend.model_service import TribeService
from backend.narrative import build_headline
from backend.result_semantics import enrich_dimension_payload, winner_summary
from backend.scorer import score_predictions
from backend.vertex_codec import f32_b64

from runpod_worker.progress import emitter_for

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


def _filename_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return unquote(os.path.basename(parsed.path)) or ""
    except Exception:
        return ""


def _warnings_for_text(text_a: str, text_b: str) -> list[str]:
    warnings: list[str] = []
    words_a = len([w for w in text_a.strip().split() if w])
    words_b = len([w for w in text_b.strip().split() if w])
    if words_a < 3 or words_b < 3:
        warnings.append("Very short text may produce unreliable results")
    return warnings


def _coerce_prediction_output(output: Any) -> tuple[np.ndarray, Any, dict[str, Any]]:
    if not (isinstance(output, tuple) and len(output) == 3):
        raise ValueError(f"Unexpected prediction output shape: {type(output).__name__}")
    preds, segments, timing = output
    return preds, segments, timing


def _pipeline_label(modality: str) -> str:
    """Honest description of which pre-encoding pipeline ran.

    Replaces the old `text_to_speech: True` flag, which lied for audio/video
    (those skip TTS entirely — real audio goes straight to WhisperX, video is
    FFmpeg-extracted frames + audio).
    """
    if modality == "text":
        return "text_to_speech"
    if modality == "audio":
        return "audio_direct"
    return "video_frames_audio"


def _build_response(
    *,
    transcript_a: str,
    transcript_b: str,
    transcript_segments_a: list[dict[str, Any]],
    transcript_segments_b: list[dict[str, Any]],
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
    media_durations: dict[str, float] | None = None,
    media_filenames: dict[str, str] | None = None,
    media_features: dict[str, Any] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    if not job_id:
        job_id = str(uuid.uuid4())
    # Insight engine reads transcript_a/b to detect content quality
    # ("Personal, direct language", "Corporate jargon", etc.) and weave that
    # into the discovery headline. Audio/video paths feed it the WhisperX
    # transcript so they get the same content-aware narrative as text mode
    # instead of the generic "Version A vs Version B" fallback.
    insights = build_insight_payload(
        dimension_rows,
        warnings,
        narrative_tone=os.environ.get("BRAIN_DIFF_NARRATIVE_TONE", "sober"),
        text_a=transcript_a,
        text_b=transcript_b,
    )
    heatmap = generate_heatmap_artifact(vertex_delta)
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
        "transcript_segments_a": transcript_segments_a,
        "transcript_segments_b": transcript_segments_b,
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
    if media_filenames is not None:
        # Codex's status endpoint already populates `media_name_a/b` from the
        # job-meta blob URL; we mirror those names here so a worker-only
        # consumer still gets the filename even without the job-meta merge.
        meta["media_filename_a"] = media_filenames.get("a", "")
        meta["media_filename_b"] = media_filenames.get("b", "")
        meta["media_name_a"] = media_filenames.get("a", "")
        meta["media_name_b"] = media_filenames.get("b", "")
    if media_features is not None:
        meta["media_features"] = media_features
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


def _run_text(text_a: str, text_b: str, *, job_id: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    warnings = _warnings_for_text(text_a, text_b)
    progress = emitter_for(job_id)

    progress.emit("predicting_version_a", "Encoding Version A through TRIBE v2...")
    preds_a, _, timing_a = _coerce_prediction_output(
        tribe_service.text_to_predictions(text_a, progress=progress)
    )
    progress.emit("predicting_version_b", "Encoding Version B through TRIBE v2...")
    preds_b, _, timing_b = _coerce_prediction_output(
        tribe_service.text_to_predictions(text_b, progress=progress)
    )

    progress.emit("computing_brain_contrast", "Computing brain contrast...")
    scores_a, median_a = score_predictions(preds_a, masks)
    scores_b, median_b = score_predictions(preds_b, masks)
    diff = compute_diff(scores_a, scores_b)
    dimension_rows = enrich_dimension_payload(diff)
    vertex_delta, vertex_a, vertex_b = compute_vertex_delta(preds_a, preds_b)
    stage_times = {
        "events_a_ms": int(timing_a.get("events_ms", 0) or 0),
        "predict_a_ms": int(timing_a.get("predict_ms", 0) or 0),
        "events_b_ms": int(timing_b.get("events_ms", 0) or 0),
        "predict_b_ms": int(timing_b.get("predict_ms", 0) or 0),
    }
    processing_time_ms = int((time.perf_counter() - started) * 1000)
    return _build_response(
        transcript_a=text_a,
        transcript_b=text_b,
        transcript_segments_a=[],
        transcript_segments_b=[],
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
        job_id=job_id,
    )


def _run_media(
    modality: str,
    media_url_a: str,
    media_url_b: str,
    *,
    job_id: str | None = None,
    blob_token: str = "",
) -> dict[str, Any]:
    started = time.perf_counter()
    warnings: list[str] = []
    progress = emitter_for(job_id)

    # Track every temp file we create so cleanup works regardless of which
    # step fails. ensure_within_max may produce a `.trim` sibling.
    temp_files: set[str] = set()

    def _track(p: str) -> str:
        if p:
            temp_files.add(p)
        return p

    progress.emit("downloading_a", f"Downloading Version A {modality}...")
    path_a = _track(_download_to_temp(media_url_a, blob_token))
    try:
        progress.emit("downloading_b", f"Downloading Version B {modality}...")
        path_b = _track(_download_to_temp(media_url_b, blob_token))
    except Exception:
        for p in list(temp_files):
            try:
                os.unlink(p)
            except OSError:
                pass
        raise

    media_durations: dict[str, float] = {}
    media_filenames: dict[str, str] = {
        "a": _filename_from_url(media_url_a),
        "b": _filename_from_url(media_url_b),
    }
    media_features_payload: dict[str, Any] = {}
    try:
        progress.emit(
            "decoding_video" if modality == "video" else "decoding_audio",
            (
                "Decoding video + extracting frames..."
                if modality == "video"
                else "Decoding audio features..."
            ),
        )
        # Enforce the same 30-second / similar-duration constraints the local
        # FastAPI path enforces (backend/api.py). Without these the worker
        # would silently chew on arbitrarily long uploads.
        try:
            path_a, dur_a, trimmed_a = ensure_within_max(path_a)
            _track(path_a)
            path_b, dur_b, trimmed_b = ensure_within_max(path_b)
            _track(path_b)
        except DurationProbeError as err:
            raise RuntimeError(f"MEDIA_DURATION_PROBE_FAILED: {err}") from err
        media_durations = {"a": float(dur_a), "b": float(dur_b)}
        if trimmed_a or trimmed_b:
            warnings.append("One or both stimuli were truncated to 30 seconds.")
        try:
            check_media_similarity(dur_a, dur_b)
        except DurationMismatch as err:
            raise RuntimeError(f"MEDIA_DURATION_MISMATCH: {err}") from err

        # Pre-compute the modality-specific features the result page needs.
        # Done before prediction so they're cheap to skip on failure (they
        # don't block the actual contrast).
        try:
            if modality == "audio":
                progress.emit("waveform_a", "Computing audio waveform A...")
                wave_a = audio_envelope(path_a)
                progress.emit("waveform_b", "Computing audio waveform B...")
                wave_b = audio_envelope(path_b)
                media_features_payload = {
                    "waveform_a": wave_a,
                    "waveform_b": wave_b,
                }
            else:
                progress.emit("keyframes_a", "Extracting keyframes A...")
                keys_a = video_keyframes(path_a)
                progress.emit("keyframes_b", "Extracting keyframes B...")
                keys_b = video_keyframes(path_b)
                media_features_payload = {
                    "keyframes_a": keys_a,
                    "keyframes_b": keys_b,
                }
        except Exception as err:
            # Feature extraction is best-effort. Surface the failure as a
            # warning and continue — the result page renders empty states
            # for missing features rather than fake placeholders.
            warnings.append(f"Media feature extraction failed: {err}")

        if modality == "audio":
            preds_a, _, timing_a = _coerce_prediction_output(
                tribe_service.audio_to_predictions(path_a, progress=progress)
            )
            preds_b, _, timing_b = _coerce_prediction_output(
                tribe_service.audio_to_predictions(path_b, progress=progress)
            )
        else:
            preds_a, _, timing_a = _coerce_prediction_output(
                tribe_service.video_to_predictions(path_a, progress=progress)
            )
            preds_b, _, timing_b = _coerce_prediction_output(
                tribe_service.video_to_predictions(path_b, progress=progress)
            )

        progress.emit("computing_brain_contrast", "Computing brain contrast...")
        scores_a, median_a = score_predictions(preds_a, masks)
        scores_b, median_b = score_predictions(preds_b, masks)
        diff = compute_diff(scores_a, scores_b)
        dimension_rows = enrich_dimension_payload(diff)
        vertex_delta, vertex_a, vertex_b = compute_vertex_delta(preds_a, preds_b)
        stage_times = {
            "events_a_ms": int(timing_a.get("events_ms", 0) or 0),
            "predict_a_ms": int(timing_a.get("predict_ms", 0) or 0),
            "events_b_ms": int(timing_b.get("events_ms", 0) or 0),
            "predict_b_ms": int(timing_b.get("predict_ms", 0) or 0),
        }

        # Real per-timestep peak-Δ moment detection — replaces the old
        # buildMoments() template that fabricated identical "{label}
        # changes at beat N" prose for every job.
        # Use Version-B duration as the timeline anchor (matches the
        # frontend, which scrubs along max(durA, durB)).
        anchor_duration = max(dur_a, dur_b) if dur_b else dur_a
        try:
            moments = peak_moments(
                preds_a, preds_b, masks,
                duration_seconds=anchor_duration,
                top_k=4,
            )
        except Exception:
            moments = []
        if moments:
            media_features_payload["moments"] = moments

        # Co-activation pattern detection. Reads the published-evidence
        # pattern definitions from frontend_new/data/pattern-definitions.json
        # (single source of truth — same file the frontend's Pattern Card
        # UI reads) and returns per-side instances with start/end/peak.
        try:
            from backend.pattern_detector import detect_patterns_both_sides
            patterns_payload = detect_patterns_both_sides(
                dimension_rows,
                duration_a_s=dur_a,
                duration_b_s=dur_b,
            )
            if patterns_payload.get("a") or patterns_payload.get("b"):
                media_features_payload["patterns"] = patterns_payload
        except Exception as err:
            warnings.append(f"Pattern detection failed: {err}")

        # Connectivity map: pairwise Pearson correlation between the
        # 7 cortical-system timeseries, integration / parallel scores,
        # hub + isolated node, plus the B−A delta matrix.
        # Cheap (21 correlations on ~30 floats); never blocks the result.
        try:
            from backend.connectivity import compute_connectivity_both_sides
            connectivity_payload = compute_connectivity_both_sides(dimension_rows)
            media_features_payload["connectivity"] = connectivity_payload
        except Exception as err:
            warnings.append(f"Connectivity map failed: {err}")

        # Structural Skeleton (Prompt 1, trimmed): when the *content*
        # changes across text / visual / audio. Uses transcript segments,
        # waveform RMS bins, and keyframe times we already extracted —
        # no new ML, no LLM summaries, no audio classifier (deferred to
        # v2 — see /methodology/skeleton).
        try:
            from backend.structural_skeleton import build_skeleton_both_sides
            transcripts_a_for_skeleton = list(timing_a.get("transcript_segments") or [])
            transcripts_b_for_skeleton = list(timing_b.get("transcript_segments") or [])
            skeleton_payload = build_skeleton_both_sides(
                transcripts_a_for_skeleton,
                transcripts_b_for_skeleton,
                media_features_payload.get("waveform_a") or [],
                media_features_payload.get("waveform_b") or [],
                media_features_payload.get("keyframes_a") or [],
                media_features_payload.get("keyframes_b") or [],
                duration_a_s=dur_a,
                duration_b_s=dur_b,
            )
            media_features_payload["skeleton"] = skeleton_payload
        except Exception as err:
            warnings.append(f"Structural skeleton failed: {err}")

        processing_time_ms = int((time.perf_counter() - started) * 1000)
        return _build_response(
            transcript_a=str(timing_a.get("transcript_text", "") or ""),
            transcript_b=str(timing_b.get("transcript_text", "") or ""),
            transcript_segments_a=list(timing_a.get("transcript_segments") or []),
            transcript_segments_b=list(timing_b.get("transcript_segments") or []),
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
            warnings=warnings,
            media_durations=media_durations,
            media_filenames=media_filenames,
            media_features=media_features_payload,
            job_id=job_id,
        )
    finally:
        for path in temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass


def handler(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("input", {})
    # RunPod assigns the outer job id; surface it so the worker can write
    # progress events to the same `events:{job_id}` key the status endpoint
    # reads. Falls back to payload.job_id (older callers) or "" (no events).
    job_id = (
        event.get("id")
        or payload.get("job_id")
        or ""
    )
    if isinstance(job_id, str):
        job_id = job_id.strip()
    else:
        job_id = ""
    blob_token = (payload.get("blob_token") or "").strip()
    progress = emitter_for(job_id)
    progress.emit("worker_started", "Worker booted, loading inputs...")

    mode = (payload.get("mode") or "text").strip().lower()
    if mode == "text":
        text_a = (payload.get("text_a") or "").strip()
        text_b = (payload.get("text_b") or "").strip()
        if not text_a or not text_b:
            raise ValueError("text_a and text_b are required for mode=text")
        result = _run_text(text_a=text_a, text_b=text_b, job_id=job_id)
        progress.emit("done", "Done")
        return result
    if mode not in {"audio", "video"}:
        raise ValueError("mode must be one of: text, audio, video")
    media_url_a = (payload.get("media_url_a") or "").strip()
    media_url_b = (payload.get("media_url_b") or "").strip()
    if not media_url_a or not media_url_b:
        raise ValueError("media_url_a and media_url_b are required for audio/video mode")
    result = _run_media(
        mode,
        media_url_a=media_url_a,
        media_url_b=media_url_b,
        job_id=job_id,
        blob_token=blob_token,
    )
    progress.emit("done", "Done")
    return result


if os.getenv("BRAIN_DIFF_RUNPOD_SKIP_WARMUP", "0") != "1":
    _warm_start()
runpod.serverless.start({"handler": handler})
