"""Phase A.3 — content_audit + content_model meta.

The audit summary walks the assembled content.slots tree once and counts, per
source, how many slots came from llm/override/library/fallback. We assert:

  * a healthy content (all llm) reports fallback_rate=0
  * a degraded content with two fallbacks reports the right slot addresses
  * chord_meanings (library) and chord_moments (llm) are both counted
  * content_model picks up id/runtime/dtype/device from the backend
"""

from __future__ import annotations

import types

from backend.results.worker_integration import (
    _describe_content_model,
    _summarise_content_sources,
    _walk_slot_sources,
)


def _scalar(source: str = "llm", status: str = "ok") -> dict[str, str]:
    return {"value": "x", "source": source, "status": status, "raw_path": None, "errors": []}


def _full_slots(*, fallbacks: list[str] | None = None) -> dict[str, object]:
    fallbacks = fallbacks or []

    def s(addr: str) -> dict[str, str]:
        if addr in fallbacks:
            return _scalar(source="fallback", status="generic")
        return _scalar()

    return {
        "headline":   s("headline"),
        "body":       s("body"),
        "frame2_sub": s("frame2_sub"),
        "recipe_match": {
            "video_a": s("recipe_match.video_a"),
            "video_b": s("recipe_match.video_b"),
        },
        "recipe_description": {
            "video_a": s("recipe_description.video_a"),
            "video_b": s("recipe_description.video_b"),
        },
        "coupling_callouts": {
            "video_a": {
                "strongest": s("coupling_callouts.video_a.strongest"),
                "weakest":   s("coupling_callouts.video_a.weakest"),
                "anti":      s("coupling_callouts.video_a.anti"),
            },
            "video_b": {
                "strongest": s("coupling_callouts.video_b.strongest"),
                "weakest":   s("coupling_callouts.video_b.weakest"),
                "anti":      s("coupling_callouts.video_b.anti"),
            },
        },
        "chord_meanings": {
            "visceral-hit": _scalar(source="library"),
            "learning-moment": _scalar(source="library"),
        },
        "chord_moments": [
            {"index": 0, "video": "video_a", "chord_id": "visceral-hit",
             "timestamp_seconds": 5, "quote": None, "meaning": s("chord_moments[0].meaning")},
            {"index": 1, "video": "video_b", "chord_id": "learning-moment",
             "timestamp_seconds": 12, "quote": None, "meaning": s("chord_moments[1].meaning")},
        ],
    }


def test_walk_slot_sources_visits_every_leaf() -> None:
    addrs = [a for a, _src, _st in _walk_slot_sources(_full_slots())]
    expected = {
        "headline", "body", "frame2_sub",
        "recipe_match.video_a", "recipe_match.video_b",
        "recipe_description.video_a", "recipe_description.video_b",
        "coupling_callouts.video_a.strongest", "coupling_callouts.video_a.weakest", "coupling_callouts.video_a.anti",
        "coupling_callouts.video_b.strongest", "coupling_callouts.video_b.weakest", "coupling_callouts.video_b.anti",
        "chord_meanings.visceral-hit", "chord_meanings.learning-moment",
        "chord_moments[0].meaning", "chord_moments[1].meaning",
    }
    assert set(addrs) == expected


def test_summary_reports_zero_fallback_when_clean() -> None:
    audit = _summarise_content_sources({"slots": _full_slots()})
    assert audit["schema_version"] == "content_audit.v1"
    assert audit["slots_fallback"] == 0
    assert audit["fallback_rate"] == 0.0
    assert audit["slots_library"] == 2
    # 13 scalar slots (3 top + 2 recipe_match + 2 recipe_desc + 6 coupling)
    # + 2 chord_moments meanings = 15 llm slots.
    assert audit["slots_llm"] == 15


def test_summary_lists_fallback_slots_with_addresses() -> None:
    fallbacks = ["headline", "coupling_callouts.video_a.anti"]
    audit = _summarise_content_sources({"slots": _full_slots(fallbacks=fallbacks)})
    assert audit["slots_fallback"] == 2
    addrs = {entry["slot"] for entry in audit["fallback_slots"]}
    assert addrs == set(fallbacks)
    assert 0 < audit["fallback_rate"] < 1


def test_summary_handles_missing_slots_gracefully() -> None:
    audit = _summarise_content_sources({"slots": {}})
    assert audit["slots_total"] == 0
    assert audit["fallback_rate"] == 0.0


def test_describe_content_model_picks_up_backend_attrs() -> None:
    class LoadedTransformersBackend:
        model_id = "google/gemma-3-1b-it"
        model_revision = "rev123"
        _dtype_str = "bfloat16"
        _device = "cuda"

    fake_manager = types.SimpleNamespace(backend=LoadedTransformersBackend())
    info = _describe_content_model(fake_manager)
    assert info["id"] == "google/gemma-3-1b-it"
    assert info["runtime"] == "transformers"
    assert info["dtype"] == "bfloat16"
    assert info["device"] == "cuda"


def test_describe_content_model_handles_stub() -> None:
    fake_backend = types.SimpleNamespace(model_id="stub", model_revision="stub-v0")
    fake_manager = types.SimpleNamespace(backend=fake_backend)
    info = _describe_content_model(fake_manager)
    assert info["id"] == "stub"
    # No dtype/device on stub — fields should simply be absent.
    assert "dtype" not in info
