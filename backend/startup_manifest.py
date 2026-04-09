import hashlib
import json
import logging
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("braindiff.startup_manifest")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _hash_label_names(atlas_labels_path: Path) -> str:
    if not atlas_labels_path.exists():
        return "missing"
    return _sha256_file(atlas_labels_path)


def build_startup_manifest(
    *,
    model_revision: str,
    atlas_dir: str = "atlases",
    requirements_lock_path: str = "backend/requirements_frozen.txt",
    runtime: dict[str, Any] | None = None,
    text_backend_strategy: str | None = None,
) -> dict[str, Any]:
    atlas_path = Path(atlas_dir)
    lh = atlas_path / "lh.HCP-MMP1.annot"
    rh = atlas_path / "rh.HCP-MMP1.annot"
    labels = atlas_path / "atlas_labels.txt"
    requirements = Path(requirements_lock_path)

    torch_version = "unknown"
    cuda_version = "none"
    gpu_name = "cpu"
    gpu_memory_gb: float | str = "n/a"
    text_encoder_auth = False
    try:
        import torch  # type: ignore

        torch_version = getattr(torch, "__version__", "unknown")
        cuda_version = str(getattr(torch.version, "cuda", None) or "none")
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            mem_bytes = torch.cuda.get_device_properties(0).total_memory
            gpu_memory_gb = round(mem_bytes / (1024**3), 2)
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            gpu_name = "Apple Silicon (MPS)"
            gpu_memory_gb = "unified_memory"
    except Exception:
        logger.warning("Torch metadata unavailable for startup manifest", exc_info=True)

    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tribev2_revision": model_revision,
        "atlas": "HCP_MMP1.0",
        "atlas_checksum": {
            "lh": _sha256_file(lh) if lh.exists() else "missing",
            "rh": _sha256_file(rh) if rh.exists() else "missing",
        },
        "atlas_labels_hash": _hash_label_names(labels),
        "python_version": platform.python_version(),
        "cuda_version": cuda_version,
        "torch_version": torch_version,
        "dependency_lock_hash": _sha256_file(requirements) if requirements.exists() else "missing",
        "text_encoder_auth": text_encoder_auth,
        "gpu_name": gpu_name,
        "gpu_memory_gb": gpu_memory_gb,
        "runtime": runtime or {},
        "text_backend_strategy": text_backend_strategy or "unknown",
        "mps_text_memory_cap": os.environ.get("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY") if text_backend_strategy == "mps_split" else None,
        "host": {
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
    }
    return manifest


def write_startup_manifest(manifest: dict[str, Any], output_path: str = "backend/startup_manifest.json") -> None:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    logger.info("startup_manifest:written path=%s", target)

