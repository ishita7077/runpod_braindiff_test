from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass

logger = logging.getLogger("braindiff.runtime")


@dataclass(frozen=True)
class RuntimeProfile:
    device: str
    backend: str
    config_update: dict[str, str | int]
    fallback_chain: tuple[str, ...]


def runtime_to_dict(profile: "RuntimeProfile | None") -> dict[str, str]:
    """Return the `{device, backend}` snapshot dict used by /api/ready,
    /api/preflight, telemetry, and startup manifest. Empty when no profile."""
    if profile is None:
        return {}
    return {"device": profile.device, "backend": profile.backend}


def _profile_for_device(device: str) -> RuntimeProfile:
    device = device.lower()
    if device == "cuda":
        return RuntimeProfile("cuda", "cuda", {}, ("cuda", "cpu"))
    if device == "mps":
        # neuralset video/image extractors call model.model.to(self.image.device) which
        # PyTorch parses as a device string. "accelerate" is not a valid string and raises
        # RuntimeError. Use "mps" directly so the HF model is moved to Apple Silicon's GPU;
        # text feature keeps "accelerate" (uses device_map="auto", no raw .to() call).
        return RuntimeProfile(
            "mps",
            "mps",
            {
                "data.audio_feature.device": "cpu",
                "data.audio_feature.infra.gpus_per_node": 0,
                "data.text_feature.device": "accelerate",
                "data.text_feature.infra.gpus_per_node": 0,
                "data.image_feature.image.device": "cpu",
                "data.image_feature.infra.gpus_per_node": 0,
                "data.video_feature.image.device": "cpu",
                "data.video_feature.infra.gpus_per_node": 0,
            },
            ("mps", "cpu"),
        )
    return RuntimeProfile(
        "cpu",
        "cpu",
        {
            "data.audio_feature.device": "cpu",
            "data.text_feature.device": "cpu",
            "data.image_feature.image.device": "cpu",
            "data.video_feature.image.device": "cpu",
            "data.audio_feature.infra.gpus_per_node": 0,
            "data.text_feature.infra.gpus_per_node": 0,
            "data.image_feature.infra.gpus_per_node": 0,
            "data.video_feature.infra.gpus_per_node": 0,
        },
        ("cpu",),
    )


def detect_runtime_profile() -> RuntimeProfile:
    forced = os.getenv("BRAIN_DIFF_DEVICE", "").strip().lower()
    if forced:
        logger.info("runtime:forced device=%s", forced)
        return _profile_for_device(forced)
    try:
        import torch  # type: ignore
    except Exception:
        return _profile_for_device("cpu")
    if torch.cuda.is_available():
        return _profile_for_device("cuda")
    mps_ok = bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
    if mps_ok and platform.system() == "Darwin":
        return _profile_for_device("mps")
    return _profile_for_device("cpu")
