import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Shared test helpers for /api/* tests that monkeypatch backend.api.
# Kept as plain helpers (not fixtures) so existing tests can opt-in without
# having to rewrite their signatures.
# ---------------------------------------------------------------------------


class DummyTribeService:
    """Stand-in for TribeService used by /api/diff* and telemetry tests.

    Returns a deterministic (preds, segments, timing) 3-tuple so the
    _coerce_prediction_output check passes. Override `runtime_backend`
    (e.g. "torch_cpu") when a test needs to assert on persisted runtime.
    """

    model_revision = "facebook/tribev2@test"

    def __init__(
        self,
        *,
        runtime_backend: str = "cpu",
        events_ms: int = 1,
        predict_ms: int = 2,
    ) -> None:
        self.runtime_profile = type(
            "Runtime",
            (),
            {"device": "cpu", "backend": runtime_backend},
        )()
        self._timing = {"events_ms": events_ms, "predict_ms": predict_ms}

    def text_to_predictions(self, text: str, progress: Any = None) -> tuple[Any, list[Any], dict[str, Any]]:
        import numpy as np

        if progress is not None:
            progress.emit("synthesizing_speech", "Synthesising speech...")
            progress.emit("predicting", "Encoding through TRIBE v2...")
        base = np.zeros((6, 20484), dtype=np.float32)
        if "B" in text:
            base[:, :100] = 0.05
        else:
            base[:, :100] = 0.01
        return base, [], {**self._timing, "transcript_text": text, "transcript_segments": []}


def dummy_masks(extra_keys: tuple[str, ...] = ()) -> dict[str, dict[str, Any]]:
    """Boolean masks shaped like brain_regions.build_vertex_masks output.

    Only the "personal_resonance" mask covers a populated region; the rest
    are empty windows over disjoint vertex ranges — enough to exercise
    compute_diff / score_predictions without loading the real atlas.
    """
    import numpy as np

    mask = np.zeros(20484, dtype=bool)
    mask[:100] = True
    empty = np.zeros(20484, dtype=bool)
    empty[100:200] = True
    base_keys = (
        "personal_resonance",
        "social_thinking",
        "brain_effort",
        "language_depth",
        "gut_reaction",
        "memory_encoding",
        "attention_salience",
    )
    masks: dict[str, dict[str, Any]] = {
        "personal_resonance": {"mask": mask},
    }
    for key in base_keys[1:] + tuple(extra_keys):
        masks[key] = {"mask": empty}
    return masks


def apply_api_test_stubs(
    monkeypatch,
    api_module,
    *,
    tribe_service: Any | None = None,
    masks: dict[str, dict[str, Any]] | None = None,
    stub_heatmap: bool = True,
    skip_startup: bool = True,
) -> None:
    """Apply the common monkeypatches most /api/* tests want in lockstep:

    - BRAIN_DIFF_SKIP_STARTUP=1 so the lifespan doesn't touch disk
    - tribe_service / masks replaced with stubs (when provided)
    - generate_heatmap_artifact replaced with a tiny stub (so nilearn/matplotlib
      is never actually invoked during tests)
    """
    if skip_startup:
        monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    if tribe_service is not None:
        monkeypatch.setattr(api_module, "tribe_service", tribe_service)
    if masks is not None:
        monkeypatch.setattr(api_module, "masks", masks)
    if stub_heatmap:
        monkeypatch.setattr(
            api_module,
            "generate_heatmap_artifact",
            lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
        )
