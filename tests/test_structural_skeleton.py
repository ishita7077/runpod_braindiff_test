"""Synthetic tests for backend/structural_skeleton.py."""
from __future__ import annotations

import pytest

from backend.structural_skeleton import (
    detect_text_events,
    detect_audio_events,
    detect_visual_events,
    compute_alignment,
    build_skeleton_for_side,
    build_skeleton_both_sides,
)


# ─── Text events ─────────────────────────────────────────────────────────────

def test_text_topic_shift_fires_on_distinct_phrases():
    segments = [
        {"start": 0.0,  "end": 6.0,  "text": "We talked about the budget last quarter and pricing"},
        {"start": 6.0,  "end": 12.0, "text": "Then we shifted to discuss cake recipes flour butter sugar oven"},
    ]
    events = detect_text_events(segments)
    assert len(events) == 1
    e = events[0]
    assert e["type"] == "topic_shift"
    assert e["time"] == pytest.approx(6.0, abs=1e-6)
    assert e["before_summary"]
    assert e["after_summary"]


def test_text_no_shift_between_two_consecutive_similar_phrases():
    # We need >2 segments for TF-IDF's inverse-document-frequency to be
    # meaningful. With a richer document set the budget-budget pair lands
    # well below the 0.55 shift threshold.
    segments = [
        {"start": 0.0,  "end": 6.0,  "text": "The board met to discuss the cake recipes for the festival"},
        {"start": 6.0,  "end": 12.0, "text": "The budget overall grew quickly this year because revenue rose"},
        {"start": 12.0, "end": 18.0, "text": "The budget overall kept growing across every department this year"},
        {"start": 18.0, "end": 24.0, "text": "After lunch the team played football and discussed weekend plans"},
    ]
    events = detect_text_events(segments)
    # We expect shifts at the 1st and 3rd boundaries, NOT between the two
    # budget phrases (segments[1] vs segments[2]).
    times = [e["time"] for e in events]
    assert 12.0 not in times, f"Budget→budget should not register as a shift; got events at {times}"


def test_text_handles_empty_or_single_segment():
    assert detect_text_events([]) == []
    assert detect_text_events([{"start": 0, "end": 5, "text": "alone"}]) == []


# ─── Audio events ────────────────────────────────────────────────────────────

def test_audio_spike_detected_above_local_baseline():
    # 30 quiet bins then one loud bin
    waveform = [0.05] * 30 + [0.95] + [0.05] * 30
    events = detect_audio_events(waveform, duration_seconds=30.0)
    spikes = [e for e in events if e["type"] == "energy_spike"]
    assert len(spikes) >= 1
    # The spike's time should land near bin 30 of 61 → ~14.75s
    assert 13.0 < spikes[0]["time"] < 17.0


def test_audio_silence_run_detected():
    # 20 bins of silence + 20 bins of signal in a 40s clip → 20s of silence at start
    waveform = [0.0] * 20 + [0.4] * 20
    events = detect_audio_events(waveform, duration_seconds=40.0)
    silences = [e for e in events if e["type"] == "silence_start"]
    assert len(silences) >= 1


def test_audio_no_events_for_constant_signal():
    waveform = [0.4] * 60
    events = detect_audio_events(waveform, duration_seconds=30.0)
    assert events == []


def test_audio_handles_empty_waveform():
    assert detect_audio_events([], 0) == []
    assert detect_audio_events([0.1, 0.2], 0) == []


# ─── Visual events ───────────────────────────────────────────────────────────

def test_visual_events_one_per_keyframe():
    keyframes = [{"time": 0.0}, {"time": 5.5}, {"time": 12.0}]
    events = detect_visual_events(keyframes)
    assert [e["time"] for e in events] == [0.0, 5.5, 12.0]
    assert events[0]["type"] == "scene_open"
    assert events[1]["type"] == "scene_cut"
    # Tighter cadence (smaller gap) → higher magnitude.
    assert events[1]["magnitude"] > events[2]["magnitude"]


def test_visual_handles_empty_keyframes():
    assert detect_visual_events([]) == []


# ─── Cross-modal alignment ───────────────────────────────────────────────────

def test_alignment_when_two_modalities_coincide():
    text_events = [{"time": 5.0, "type": "topic_shift", "score": 0.5}]
    visual_events = [{"time": 5.4, "type": "scene_cut", "score": 0.5}]
    audio_events: list[dict] = []
    out = compute_alignment(text_events, visual_events, audio_events)
    assert out["cross_modal_alignment_score"] > 0
    assert any("text" in m["modalities"] and "visual" in m["modalities"] for m in out["aligned_moments"])


def test_alignment_score_zero_when_all_misaligned():
    text_events = [{"time": 0.0, "type": "topic_shift", "score": 0.5}]
    visual_events = [{"time": 10.0, "type": "scene_cut", "score": 0.5}]
    audio_events = [{"time": 20.0, "type": "energy_spike", "score": 0.5}]
    out = compute_alignment(text_events, visual_events, audio_events)
    assert out["cross_modal_alignment_score"] == 0.0
    assert len(out["misaligned_moments"]) == 3


def test_alignment_handles_empty_input():
    out = compute_alignment([], [], [])
    assert out["cross_modal_alignment_score"] == 0.0
    assert out["aligned_moments"] == []
    assert out["misaligned_moments"] == []


# ─── End-to-end ──────────────────────────────────────────────────────────────

def test_build_skeleton_for_side_returns_summary_line():
    transcript = [
        {"start": 0.0, "end": 4.0, "text": "Welcome to the budget meeting"},
        {"start": 4.0, "end": 9.0, "text": "Now let's talk about cake recipes flour sugar"},
    ]
    waveform = [0.1] * 30 + [0.9] + [0.1] * 30
    keyframes = [{"time": 0.0}, {"time": 5.0}]
    out = build_skeleton_for_side(transcript, waveform, keyframes, duration_seconds=10.0)
    assert "summary_line" in out and "topic shift" in out["summary_line"]
    assert isinstance(out["text_events"], list)
    assert isinstance(out["visual_events"], list)
    assert isinstance(out["audio_events"], list)
    assert "alignment" in out


def test_build_skeleton_both_sides_includes_structural_similarity():
    transcript_a = [
        {"start": 0.0, "end": 4.0, "text": "Topic alpha first"},
        {"start": 4.0, "end": 8.0, "text": "Switching now to topic gamma cake recipes"},
    ]
    transcript_b = [
        {"start": 0.0, "end": 4.0, "text": "Topic beta first"},
        {"start": 4.0, "end": 8.0, "text": "Switching now to topic delta movie tickets"},
    ]
    waveform_a = [0.1] * 30 + [0.95] + [0.1] * 9
    waveform_b = [0.1] * 30 + [0.95] + [0.1] * 9
    keyframes_a = [{"time": 0.0}, {"time": 4.0}]
    keyframes_b = [{"time": 0.0}, {"time": 4.0}]
    out = build_skeleton_both_sides(
        transcript_a, transcript_b, waveform_a, waveform_b,
        keyframes_a, keyframes_b,
        duration_a_s=8.0, duration_b_s=8.0,
    )
    assert "a" in out and "b" in out
    assert "structural_similarity" in out
    assert 0.0 <= out["structural_similarity"] <= 1.0


def test_build_skeleton_handles_missing_data_gracefully():
    out = build_skeleton_for_side([], [], [], duration_seconds=0.0)
    assert out["text_events"] == []
    assert out["visual_events"] == []
    assert out["audio_events"] == []
    assert out["alignment"]["cross_modal_alignment_score"] == 0.0
