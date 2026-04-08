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
        from huggingface_hub import try_to_load_from_cache
        from huggingface_hub import HfApi
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import GatedRepoError
    except Exception:
        return False, "huggingface_hub not installed"

    cached = try_to_load_from_cache("meta-llama/Llama-3.2-3B", "config.json")
    if cached and cached is not None:
        return True, f"cached:{cached}"

    token = HfApi().token
    if not token:
        return False, "no Hugging Face token found; run `huggingface-cli login`"

    try:
        hf_hub_download("meta-llama/Llama-3.2-3B", "config.json", token=token)
        return True, "ok"
    except GatedRepoError:
        return False, "missing access to meta-llama/Llama-3.2-3B"
    except Exception as err:
        # Token exists but network may be offline; don't block purely on that.
        return True, f"token_present_unverified:{err}"


def check_uvx() -> tuple[bool, str]:
    uvx_path = shutil.which("uvx")
    if uvx_path:
        return True, uvx_path
    return False, "uvx command not found on PATH (install uv and ensure uvx is available)"


def detect_runtime_device() -> tuple[str, str]:
    try:
        import torch
    except Exception:
        return "cpu", "torch not importable"
    if torch.cuda.is_available():
        return "cuda", torch.cuda.get_device_name(0)
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps", "Apple Metal"
    return "cpu", "CPU"


def build_preflight_report(*, model_loaded: bool, masks_ready: bool, runtime_info: dict[str, Any] | None = None) -> dict[str, Any]:
    ffmpeg_ok, ffmpeg_detail = check_ffmpeg()
    hf_ok, hf_detail = check_hf_gated_access()
    uvx_ok, uvx_detail = check_uvx()
    selected_device, device_detail = detect_runtime_device()
    blockers = []
    warnings = []
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
    if os.getenv("BRAIN_DIFF_ATLAS_APPROX_USED") == "1":
        warnings.append("atlas_approximation_in_use")
    return {
        "ok": len(blockers) == 0,
        "model_loaded": model_loaded,
        "masks_ready": masks_ready,
        "runtime_device": {"selected": selected_device, "detail": device_detail},
        "runtime_info": runtime_info or {},
        "ffmpeg": {"ok": ffmpeg_ok, "detail": ffmpeg_detail},
        "uvx": {"ok": uvx_ok, "detail": uvx_detail},
        "hf_gated_model_access": {"ok": hf_ok, "detail": hf_detail},
        "warnings": warnings,
        "blockers": blockers,
    }
