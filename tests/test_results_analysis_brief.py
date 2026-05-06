"""Phase C.3 — analysis_brief validator + slot integration.

Validator coverage:
  * structural shape (thesis, tradeoff, why_it_happened, recommendations,
    limitations, confidence)
  * confidence enum
  * banned generic phrases in recommendations
  * recommendations require evidence_refs
  * evidence-ref grounding (Phase C.6 cross-check)

Slot integration:
  * build_template_context returns the JSON-encoded evidence packet
  * parse_selected pulls the JSON object out of noisy LLM text
  * after build_template_context, the slot's validator is bound to the
    packet's evidence refs (so subsequent .validate() rejects fabricated
    timestamps)
"""

from __future__ import annotations

from backend.results.lib.input_normalizer import (
    CANONICAL_SYSTEMS,
    ChordEvent,
    CouplingEntry,
    NormalizedInputs,
    TranscriptLine,
    VideoSignature,
)
from backend.results.lib.lead_insight import LeadInsight
from backend.results.slots.analysis_brief import AnalysisBriefSlot
from backend.results.validators.analysis_brief import AnalysisBriefValidator


def _good_brief() -> dict:
    return {
        "thesis": "B reaches the gut faster while A carries the explanation.",
        "tradeoff": "A trades immediate impact for a clearer argument; B trades nuance for visceral pull.",
        "why_it_happened": [
            {"claim": "Visceral response peaked early in B.", "evidence_refs": ["video_b:0:08"]},
            {"claim": "Cognitive control stayed elevated through A.", "evidence_refs": ["video_a:0:14"]},
        ],
        "recommendations": [
            {
                "action": "Borrow B's opening hook in the first 8 seconds of A.",
                "because": "A loses the body before it builds the argument.",
                "evidence_refs": ["video_b:0:08"],
            },
        ],
        "limitations": "Cortical predictions cannot tell us what action the viewer takes after.",
        "confidence": "medium",
    }


def _make_inputs() -> NormalizedInputs:
    means = {s: 0.5 for s in CANONICAL_SYSTEMS}
    peaks = {s: {"time": 5.0, "value": 0.6} for s in CANONICAL_SYSTEMS}
    matrix = [[1.0] * len(CANONICAL_SYSTEMS) for _ in CANONICAL_SYSTEMS]
    va = VideoSignature(
        id="vid_a", display_name="A", creator=None, title="A",
        duration_seconds=30.0,
        system_means=means, system_peaks=peaks,
        chord_events=[
            ChordEvent(chord_id="visceral-hit", timestamp_seconds=8.0,
                       duration_seconds=1.0, quote="hits hard"),
        ],
        integration_score=0.5, hub_node="attention",
        couplings=[CouplingEntry(system_a="attention", system_b="memory_encoding", r=0.5)],
        timeseries={s: [0.5] * 31 for s in CANONICAL_SYSTEMS},
        coupling_matrix=matrix,
        transcript=[TranscriptLine(t=0.0, text="opening"), TranscriptLine(t=14.0, text="argument")],
        poster_path=None,
    )
    vb = VideoSignature(
        id="vid_b", display_name="B", creator=None, title="B",
        duration_seconds=30.0,
        system_means=means, system_peaks=peaks,
        chord_events=[
            ChordEvent(chord_id="visceral-hit", timestamp_seconds=8.0,
                       duration_seconds=1.0, quote="hits hard"),
        ],
        integration_score=0.5, hub_node="gut_reaction",
        couplings=[CouplingEntry(system_a="gut_reaction", system_b="attention", r=0.6)],
        timeseries={s: [0.5] * 31 for s in CANONICAL_SYSTEMS},
        coupling_matrix=matrix,
        transcript=[TranscriptLine(t=0.0, text="opening"), TranscriptLine(t=14.0, text="argument")],
        poster_path=None,
    )
    return NormalizedInputs(
        schema_version="normalized_inputs.v1",
        analysis_version="test",
        video_a=va, video_b=vb,
    )


def test_validator_passes_on_well_formed_brief() -> None:
    v = AnalysisBriefValidator()
    res = v.validate(_good_brief())
    assert res.passed, res.as_dict()


def test_validator_rejects_missing_thesis() -> None:
    brief = _good_brief()
    brief["thesis"] = ""
    res = AnalysisBriefValidator().validate(brief)
    assert not res.passed
    assert any(e.code == "MISSING_FIELD" for e in res.errors)


def test_validator_rejects_bad_confidence() -> None:
    brief = _good_brief()
    brief["confidence"] = "amazing"
    res = AnalysisBriefValidator().validate(brief)
    assert not res.passed
    assert any(e.code == "MISSING_FIELD" and "confidence" in e.detail for e in res.errors)


def test_validator_rejects_recommendation_without_evidence() -> None:
    brief = _good_brief()
    brief["recommendations"][0]["evidence_refs"] = []
    res = AnalysisBriefValidator().validate(brief)
    assert not res.passed
    assert any(e.code == "REC_NO_EVIDENCE" for e in res.errors)


def test_validator_rejects_generic_phrase_in_recommendation() -> None:
    brief = _good_brief()
    brief["recommendations"][0]["action"] = "Make it more engaging."
    res = AnalysisBriefValidator().validate(brief)
    assert not res.passed
    assert any(e.code == "REC_GENERIC_PHRASE" for e in res.errors)


def test_validator_rejects_too_many_recommendations() -> None:
    brief = _good_brief()
    brief["recommendations"] = [brief["recommendations"][0]] * 4
    res = AnalysisBriefValidator().validate(brief)
    assert not res.passed
    assert any(e.code == "MISSING_FIELD" and "recommendations" in e.detail for e in res.errors)


def test_validator_rejects_ungrounded_evidence_ref() -> None:
    valid = {"video_a:0:08", "video_b:0:14"}
    v = AnalysisBriefValidator(valid_evidence_refs=valid)
    brief = _good_brief()
    # Add a recommendation that cites a fabricated timestamp.
    brief["recommendations"].append({
        "action": "Cut the third beat earlier.",
        "because": "It loses the room.",
        "evidence_refs": ["video_a:9:99"],
    })
    res = v.validate(brief)
    assert not res.passed
    assert any(e.code == "UNGROUNDED_EVIDENCE_REF" for e in res.errors)


def test_validator_passes_when_all_refs_grounded() -> None:
    valid = {"video_a:0:14", "video_b:0:08"}
    v = AnalysisBriefValidator(valid_evidence_refs=valid)
    res = v.validate(_good_brief())
    assert res.passed, res.as_dict()


def test_slot_build_template_context_yields_packet_json_and_binds_validator() -> None:
    lead = LeadInsight(
        video_key="video_a", video_title="A",
        coupling_type="strongest", system_a="attention", system_b="memory_encoding",
        r=0.5, score=0.5, plain_summary="A and B differ on attention.",
    )
    slot = AnalysisBriefSlot(lead_insight=lead)
    ctx = slot.build_template_context(_make_inputs())
    assert "evidence_packet_json" in ctx
    assert "video_a" in ctx["evidence_packet_json"]
    # Validator should now know the packet's refs.
    v = slot.validator
    assert isinstance(v, AnalysisBriefValidator)
    assert v.valid_evidence_refs is not None
    # The fixture has a chord at video_a:0:08 so that ref must be in the packet.
    assert any(ref.startswith("video_a:") for ref in v.valid_evidence_refs)


def test_slot_parse_selected_extracts_json_from_chatter() -> None:
    import json as _json

    lead = LeadInsight(
        video_key="video_a", video_title="A",
        coupling_type="strongest", system_a="attention", system_b="memory_encoding",
        r=0.5, score=0.5, plain_summary="...",
    )
    slot = AnalysisBriefSlot(lead_insight=lead)
    raw = "Sure! Here is the brief:\n```json\n" + _json.dumps(_good_brief()) + "\n```\nDone."
    obj = slot.parse_selected(raw)
    assert obj["thesis"].startswith("B reaches")
