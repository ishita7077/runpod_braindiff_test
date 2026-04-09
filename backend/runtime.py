from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("braindiff.runtime")


@dataclass(frozen=True)
class RuntimeProfile:
    device: str
    backend: str
    config_update: dict[str, Any]
    fallback_chain: tuple[str, ...]


def _profile_for_device(device: str) -> RuntimeProfile:
    device = device.lower()
    if device == "cuda":
        return RuntimeProfile("cuda", "cuda", {}, ("cuda", "cpu"))
    if device == "mps":
        # TRIBEv2 / neuralset HuggingFace extractors only allow
        # auto | cpu | cuda | accelerate — not the string "mps".
        # Use accelerate + device_map="auto" so Transformers can place weights on MPS when supported.
        return RuntimeProfile(
            "mps",
            "mps",
            {
                "data.audio_feature.device": "cpu",
                "data.audio_feature.infra.gpus_per_node": 0,
                "data.text_feature.device": "accelerate",
                "data.text_feature.infra.gpus_per_node": 0,
                "data.image_feature.image.device": "accelerate",
                "data.image_feature.infra.gpus_per_node": 0,
                "data.video_feature.image.device": "accelerate",
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
