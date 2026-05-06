"""Phase A.1 — input canonicalisation + audit.

These tests pin the bug from the production fix plan: TRIBE-side dimension
names like `attention_salience` were silently dropped, causing the canonical
`attention` system to be filled with the 0.5-flat fallback. That kills coupling
+ chord detection without any visible warning. The fix is twofold:
  * Map every alias explicitly (including `attention_salience`).
  * Surface unmapped dims and flat-filled systems via `input_audit` so the
    response carries a content_audit.input_mapping breadcrumb.

The tests deliberately import only `_build_video` and `_canonicalise_dim`, NOT
`generate_content_for_worker`, so they don't pull in the model_manager (and
therefore don't require torch/transformers in the sandbox).
"""

from __future__ import annotations

from backend.results.worker_integration import _build_video, _canonicalise_dim


def _flat_segments(duration: int) -> list[dict[str, object]]:
    return [{"start": 0.0, "end": float(duration), "text": "hello world"}]


def test_attention_salience_maps_to_attention() -> None:
    """The legacy backend name `attention_salience` must populate canonical
    `attention`. Before this fix it silently fell through and `attention` was
    flat-filled with 0.5s.
    """
    audit: dict[str, object] = {}
    ts = {"attention_salience": [0.1, 0.8, 0.2]}
    video = _build_video(
        video_id="vid_a",
        display_name="A",
        duration_seconds=2.0,
        transcript_segments=_flat_segments(2),
        timeseries_per_dim=ts,
        input_audit=audit,
    )
    assert video.timeseries["attention"] == [0.1, 0.8, 0.2]
    # The audit should NOT mark attention as flat-filled.
    assert "attention" not in audit["vid_a"]["filled_flat_systems"]
    assert audit["vid_a"]["unmapped_dimensions"] == []


def test_unmapped_dimension_is_reported_not_silent() -> None:
    """Unknown dim names must show up in the audit, not vanish."""
    audit: dict[str, object] = {}
    ts = {"made_up_dimension": [0.5, 0.5, 0.5]}
    _build_video(
        video_id="vid_a",
        display_name="A",
        duration_seconds=2.0,
        transcript_segments=_flat_segments(2),
        timeseries_per_dim=ts,
        input_audit=audit,
    )
    assert "made_up_dimension" in audit["vid_a"]["unmapped_dimensions"]
    # All seven canonical systems should be in filled_flat_systems because
    # nothing mapped to anything.
    assert len(audit["vid_a"]["filled_flat_systems"]) == 7


def test_canonicalise_dim_handles_separators_and_case() -> None:
    """Separator and case normalisation must not regress."""
    assert _canonicalise_dim("attention-salience") == "attention"
    assert _canonicalise_dim("ATTENTION_SALIENCE") == "attention"
    assert _canonicalise_dim("Theory of Mind") == "social_thinking"
    assert _canonicalise_dim("language depth") == "language_depth"
    assert _canonicalise_dim("not a dim") is None


def test_alias_table_covers_every_canonical_system() -> None:
    """Smoke check: every canonical system has at least one alias entry."""
    from backend.results.lib.input_normalizer import CANONICAL_SYSTEMS
    from backend.results.worker_integration import _TRIBE_DIM_TO_CANONICAL

    aliased_targets = set(_TRIBE_DIM_TO_CANONICAL.values())
    missing = [s for s in CANONICAL_SYSTEMS if s not in aliased_targets]
    assert not missing, f"Canonical systems with no alias: {missing}"
