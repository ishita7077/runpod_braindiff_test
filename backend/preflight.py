import os
from pathlib import Path
from typing import Any
import shutil


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
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import GatedRepoError
    except Exception:
        return False, "huggingface_hub not installed"

    try:
        hf_hub_download("meta-llama/Llama-3.2-3B", "config.json")
        return True, "ok"
    except GatedRepoError:
        return False, "missing access to meta-llama/Llama-3.2-3B"
    except Exception as err:  # network/offline/etc
        return False, f"unable to verify access: {err}"


def check_uvx() -> tuple[bool, str]:
    uvx_path = shutil.which("uvx")
    if uvx_path:
        return True, uvx_path
    return False, "uvx command not found on PATH (install uv and ensure uvx is available)"


def build_preflight_report(*, model_loaded: bool, masks_ready: bool) -> dict[str, Any]:
    ffmpeg_ok, ffmpeg_detail = check_ffmpeg()
    hf_ok, hf_detail = check_hf_gated_access()
    uvx_ok, uvx_detail = check_uvx()
    blockers = []
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
    return {
        "ok": len(blockers) == 0,
        "model_loaded": model_loaded,
        "masks_ready": masks_ready,
        "ffmpeg": {"ok": ffmpeg_ok, "detail": ffmpeg_detail},
        "uvx": {"ok": uvx_ok, "detail": uvx_detail},
        "hf_gated_model_access": {"ok": hf_ok, "detail": hf_detail},
        "blockers": blockers,
    }

