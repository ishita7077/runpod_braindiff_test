"""Phase C.2 — evidence_packet builder.

The packet is the deterministic ground truth the LLM reasons over. Tests:
  * shape: schema_version + every section present
  * top_deltas: ordered by abs delta, length=3
  * top_moments: every entry has a video-prefixed evidence_ref
  * couplings: includes strongest_positive and (when present) most_negative
  * chords: chronological, every chord retains its quote + ref
  * transcript_quotes: deduped + chronologically sorted
  * collect_valid_evidence_refs: returns every ref the LLM could cite
"""

from __future__ import annotations

from backend.results.lib.evidence_packet import (
    build_evidence_packet,
    collect_valid_evidence_refs,
)
from backend.results.lib.input_normalizer import (
    CANONICAL_SYSTEMS,
    ChordEvent,
    CouplingEntry,
    NormalizedInputs,
    TranscriptLine,
    VideoSignature,
)


def _make_video(*, vid_id: str, name: str, dur: float) -> VideoSignature:
    means = {s: 0.5 for s in CANONICAL_SYSTEMS}
    means["attention"] = 0.8 if vid_id == "vid_a" else 0.3
    means["language_depth"] = 0.4 if vid_id == "vid_a" else 0.7
    peaks = {s: {"time": 5.0, "value": float(means[s])} for s in CANONICAL_SYSTEMS}
    couplings = [
        CouplingEntry(system_a="attention", system_b="memory_encoding", r=0.7),
        CouplingEntry(system_a="brain_effort", system_b="gut_reaction", r=-0.6),
        CouplingEntry(system_a="social_thinking", system_b="language_depth", r=0.05),
    ]
    matrix = [[1.0] * len(CANONICAL_SYSTEMS) for _ in CANONICAL_SYSTEMS]
    chords = [
        ChordEvent(chord_id="visceral-hit", timestamp_seconds=8.0,
                   duration_seconds=1.0, quote="this lands hard"),
        ChordEvent(chord_id="learning-moment", timestamp_seconds=14.0,
                   duration_seconds=2.0, quote="here is the proof"),
    ]
    transcript = [
        TranscriptLine(t=0.0, text="opening line"),
        TranscriptLine(t=8.0, text="this lands hard"),
        TranscriptLine(t=14.0, text="here is the proof"),
        TranscriptLine(t=25.0, text="closing line"),
    ]
    return VideoSignature(
        id=vid_id, display_name=name, creator=None, title=name,
        duration_seconds=dur,
        system_means=means, system_peaks=peaks,
        chord_events=chords,
        integration_score=0.4 if vid_id == "vid_a" else 0.7,
        hub_node="attention" if vid_id == "vid_a" else "language_depth",
        couplings=couplings,
        timeseries={s: [0.5] * (int(dur) + 1) for s in CANONICAL_SYSTEMS},
        coupling_matrix=matrix,
        transcript=transcript,
        poster_path=None,
    )


def _make_inputs() -> NormalizedInputs:
    return NormalizedInputs(
        schema_version="normalized_inputs.v1",
        analysis_version="test",
        video_a=_make_video(vid_id="vid_a", name="A", dur=30),
        video_b=_make_video(vid_id="vid_b", name="B", dur=30),
    )


def test_packet_has_schema_and_sections() -> None:
    p = build_evidence_packet(_make_inputs())
    assert p["schema_version"] == "evidence_packet.v1"
    for section in ("videos", "top_deltas", "top_moments", "couplings", "chords", "transcript_quotes", "media_structure"):
        assert section in p


def test_top_deltas_sorted_by_abs_delta() -> None:
    p = build_evidence_packet(_make_inputs())
    deltas = p["top_deltas"]
    assert len(deltas) == 3
    assert deltas == sorted(deltas, key=lambda d: d["abs_delta"], reverse=True)
    # The biggest A-vs-B differences in our fixture are attention (+0.5) and
    # language_depth (-0.3), both should appear.
    systems = [d["system"] for d in deltas]
    assert "attention" in systems
    assert "language_depth" in systems


def test_top_moments_carry_evidence_refs() -> None:
    p = build_evidence_packet(_make_inputs())
    for moment in p["top_moments"]:
        assert moment["evidence_ref"].startswith(moment["video"] + ":")
        # ref format video_X:M:SS
        ref = moment["evidence_ref"]
        assert ":" in ref.split(":", 1)[1]


def test_couplings_include_strongest_and_most_negative() -> None:
    p = build_evidence_packet(_make_inputs())
    kinds_a = {c["kind"] for c in p["couplings"] if c["video"] == "video_a"}
    assert "strongest_positive" in kinds_a
    # We seeded an r=-0.6 anti-coupling — expect it to surface.
    assert "most_negative" in kinds_a


def test_chords_are_chronological_with_quotes() -> None:
    p = build_evidence_packet(_make_inputs())
    chord_a = [c for c in p["chords"] if c["video"] == "video_a"]
    times = [c["time_seconds"] for c in chord_a]
    assert times == sorted(times)
    assert all(c["evidence_ref"].startswith("video_a:") for c in chord_a)
    # Quotes should round-trip from the fixture.
    assert any(c.get("quote") == "this lands hard" for c in chord_a)


def test_transcript_quotes_dedupe_and_sort() -> None:
    p = build_evidence_packet(_make_inputs())
    quotes_a = [q for q in p["transcript_quotes"] if q["video"] == "video_a"]
    times = [q["time_seconds"] for q in quotes_a]
    assert times == sorted(times)
    # No duplicate timestamps.
    assert len(set(times)) == len(times)


def test_collect_valid_evidence_refs_covers_moments_and_chords() -> None:
    p = build_evidence_packet(_make_inputs())
    refs = collect_valid_evidence_refs(p)
    # Every chord ref + every transcript quote ref must be present.
    for ev in p["chords"]:
        assert ev["evidence_ref"] in refs
    for q in p["transcript_quotes"]:
        assert q["evidence_ref"] in refs


def test_packet_handles_missing_chords_and_transcript() -> None:
    """Empty chord_events and transcript must not raise."""
    inputs = _make_inputs()
    inputs.video_a.chord_events = []
    inputs.video_a.transcript = []
    p = build_evidence_packet(inputs)
    chord_a = [c for c in p["chords"] if c["video"] == "video_a"]
    quote_a = [q for q in p["transcript_quotes"] if q["video"] == "video_a"]
    assert chord_a == []
    assert quote_a == []
    # video_b should still produce evidence.
    chord_b = [c for c in p["chords"] if c["video"] == "video_b"]
    assert chord_b
