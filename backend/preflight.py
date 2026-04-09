import os
import shutil
from pathlib import Path
from typing import Any


def check_ffmpeg() -> tuple[bool, str]:
    for candidate in os.environ.get("PATH", "").split(":"):
        if not candidate:
            continue
        fp = Path(candidate) / "ffmpeg"
        if fp.exists() and os.access(fp, os.X_OK):
            return True, str(fp)
    try:
        import imageio_ffmpeg  # type: ignore

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if Path(ffmpeg_exe).exists():
            return True, f"imageio_ffmpeg:{ffmpeg_exe}"
    except Exception:
        pass
    return False, "ffmpeg not found on PATH and imageio_ffmpeg unavailable"


def check_hf_gated_access() -> tuple[bool, str]:
    try:
        from huggingface_hub import HfApi, scan_cache_dir
    except Exception:
        return False, "huggingface_hub not installed"
    try:
        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_id == "meta-llama/Llama-3.2-3B":
                return True, "local_cache_present"
    except Exception:
        pass
    token = HfApi().token
    if token:
        return True, "token_present_unverified"
    return False, "no local gated-model cache and no Hugging Face token found"


def check_uvx() -> tuple[bool, str]:
    uvx_path = shutil.which("uvx")
    if uvx_path:
        return True, uvx_path
    return False, "uvx command not found on PATH (install uv and ensure uvx is available)"


def check_accelerate() -> tuple[bool, str]:
    """Required when HuggingFaceText uses device=accelerate (device_map=auto), e.g. on Apple Silicon."""
    try:
        import accelerate  # noqa: F401

        return True, getattr(accelerate, "__version__", "installed")
    except Exception:
        return False, "accelerate not installed (pip install accelerate) — needed for Llama with device_map"


def build_preflight_report(
    *,
    model_loaded: bool,
    masks_ready: bool,
    runtime: dict[str, Any] | None = None,
    text_backend_strategy: str | None = None,
    slow_notice_ms: int = 180_000,
    hard_timeout_ms: int = 1_200_000,
    max_concurrent_jobs: int = 1,
) -> dict[str, Any]:
    ffmpeg_ok, ffmpeg_detail = check_ffmpeg()
    hf_ok, hf_detail = check_hf_gated_access()
    uvx_ok, uvx_detail = check_uvx()
    accelerate_ok, accelerate_detail = check_accelerate()

    runtime_backend = (runtime or {}).get("backend", "")
    # accelerate is only required when the runtime actually uses device_map=auto (mps).
    accelerate_required = runtime_backend == "mps"

    effective_whisper = {
        "device": os.environ.get("TRIBEV2_WHISPERX_DEVICE", "unknown"),
        "model": os.environ.get("TRIBEV2_WHISPERX_MODEL", "unknown"),
        "batch_size": os.environ.get("TRIBEV2_WHISPERX_BATCH_SIZE", "unknown"),
        "align_model": os.environ.get("TRIBEV2_WHISPERX_ALIGN_MODEL", "unknown"),
    }

    blockers: list[str] = []
    if not model_loaded:
        blockers.append("model_not_loaded")
    if not masks_ready:
        blockers.append("masks_not_ready")
    if not ffmpeg_ok:
        blockers.append("ffmpeg_missing")
    if not uvx_ok:
        blockers.append("uvx_missing")
    if not hf_ok:
        blockers.append("hf_auth_or_access_missing")
    if accelerate_required and not accelerate_ok:
        blockers.append("accelerate_missing")

    return {
        "ok": len(blockers) == 0,
        "model_loaded": model_loaded,
        "masks_ready": masks_ready,
        "runtime": runtime or {},
        "text_backend_strategy": text_backend_strategy or "unknown",
        "effective_whisper_defaults": effective_whisper,
        "limits": {
            "slow_notice_ms": slow_notice_ms,
            "hard_timeout_ms": hard_timeout_ms,
            "max_concurrent_jobs": max_concurrent_jobs,
        },
        "ffmpeg": {"ok": ffmpeg_ok, "detail": ffmpeg_detail},
        "uvx": {"ok": uvx_ok, "detail": uvx_detail},
        "accelerate": {
            "ok": accelerate_ok,
            "detail": accelerate_detail,
            "required": accelerate_required,
        },
        "hf_gated_model_access": {"ok": hf_ok, "detail": hf_detail},
        "blockers": blockers,
    }
