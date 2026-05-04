"""Normalise raw cortical-analysis inputs into a canonical shape.

Slot prompts and the library matcher all read from the normalised dict, never
from raw analysis output. This means upstream changes to TRIBE output don't
ripple through every slot.

Phase 0 ships:
  * a TypedDict-style schema (NormalizedInputs)
  * a normaliser that accepts a permissive dict and produces a canonical one
  * an input_hash() so audit logs can prove which inputs a generation used
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any


# ────────────────────────────────────────────────────────────
# Canonical shape
# ────────────────────────────────────────────────────────────

CANONICAL_SYSTEMS: tuple[str, ...] = (
    "personal_resonance",
    "attention",
    "brain_effort",
    "gut_reaction",
    "memory_encoding",
    "social_thinking",
    "language_depth",
)


@dataclass
class ChordEvent:
    chord_id: str
    timestamp_seconds: float
    duration_seconds: float
    quote: str | None = None
    formula_values: dict[str, float] = field(default_factory=dict)


@dataclass
class CouplingEntry:
    system_a: str
    system_b: str
    r: float


@dataclass
class TranscriptLine:
    t: float
    text: str


@dataclass
class VideoSignature:
    id: str
    display_name: str
    creator: str | None
    title: str | None
    duration_seconds: float
    system_means: dict[str, float]                 # keyed by CANONICAL_SYSTEMS
    system_peaks: dict[str, dict[str, float]]      # {system: {time: float, value: float}}
    chord_events: list[ChordEvent]
    integration_score: float
    hub_node: str | None
    couplings: list[CouplingEntry]                 # all 21 unique pairs
    # v2 additions for v7-faithful frontend:
    timeseries: dict[str, list[float]]             # {system: [v0, v1, ..., v_runtime]} per-second
    coupling_matrix: list[list[float]]             # 7x7 symmetric, ordered by CANONICAL_SYSTEMS
    transcript: list[TranscriptLine]
    poster_path: str | None                        # /assets/results/{id}.jpg


@dataclass
class NormalizedInputs:
    schema_version: str
    analysis_version: str
    video_a: VideoSignature
    video_b: VideoSignature

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InputValidationError(Exception):
    """Raised when raw inputs are missing required fields."""


def normalize_inputs(
    raw: dict[str, Any],
    *,
    analysis_version: str,
) -> NormalizedInputs:
    """Take a permissive dict and produce a canonical NormalizedInputs.

    Raises InputValidationError if required fields are missing — the caller
    (generate.py) catches this and emits an `input_invalid` audit event.
    """
    try:
        return NormalizedInputs(
            schema_version="normalized_inputs.v1",
            analysis_version=analysis_version,
            video_a=_normalize_video(raw["video_a"]),
            video_b=_normalize_video(raw["video_b"]),
        )
    except KeyError as exc:
        raise InputValidationError(f"Missing required field: {exc}") from exc


def _normalize_video(d: dict[str, Any]) -> VideoSignature:
    means = d.get("system_means", {})
    peaks = d.get("system_peaks", {})
    chords = [
        ChordEvent(
            chord_id=c["chord_id"],
            timestamp_seconds=float(c["timestamp_seconds"]),
            duration_seconds=float(c.get("duration_seconds", 1.0)),
            quote=c.get("quote"),
            formula_values=c.get("formula_values", {}),
        )
        for c in d.get("chord_events", [])
    ]
    couplings = [
        CouplingEntry(system_a=c["system_a"], system_b=c["system_b"], r=float(c["r"]))
        for c in d.get("couplings", [])
    ]
    duration = float(d.get("duration_seconds", 60.0))
    runtime_int = int(round(duration))

    # Timeseries — fall back to sinusoid based on mean if not provided (so v1 inputs still work).
    raw_ts = d.get("timeseries", {})
    timeseries: dict[str, list[float]] = {}
    for sys in CANONICAL_SYSTEMS:
        series = raw_ts.get(sys)
        if series and isinstance(series, list):
            timeseries[sys] = [float(v) for v in series]
        else:
            mean = float(means.get(sys, 0.5))
            # Fallback synthetic series — flat at mean.
            timeseries[sys] = [mean for _ in range(runtime_int + 1)]

    # Coupling matrix (7x7). If not provided, build from the supplied couplings list.
    raw_matrix = d.get("coupling_matrix")
    if raw_matrix and isinstance(raw_matrix, list) and len(raw_matrix) == 7:
        coupling_matrix = [[float(v) for v in row] for row in raw_matrix]
    else:
        coupling_matrix = _matrix_from_couplings(couplings)

    transcript = [
        TranscriptLine(t=float(line["t"]), text=str(line["text"]))
        for line in d.get("transcript", [])
    ]

    return VideoSignature(
        id=d["id"],
        display_name=d.get("display_name", d["id"]),
        creator=d.get("creator"),
        title=d.get("title"),
        duration_seconds=duration,
        system_means={k: float(means.get(k, 0.5)) for k in CANONICAL_SYSTEMS},
        system_peaks={k: dict(peaks.get(k, {"time": 0.0, "value": 0.0})) for k in CANONICAL_SYSTEMS},
        chord_events=chords,
        integration_score=float(d.get("integration_score", 0.0)),
        hub_node=d.get("hub_node"),
        couplings=couplings,
        timeseries=timeseries,
        coupling_matrix=coupling_matrix,
        transcript=transcript,
        poster_path=d.get("poster_path"),
    )


def _matrix_from_couplings(couplings: list[CouplingEntry]) -> list[list[float]]:
    """Build a 7x7 symmetric matrix (ordered by CANONICAL_SYSTEMS) from a sparse couplings list."""
    idx = {s: i for i, s in enumerate(CANONICAL_SYSTEMS)}
    m = [[0.0] * 7 for _ in range(7)]
    for i in range(7):
        m[i][i] = 1.0
    for c in couplings:
        if c.system_a in idx and c.system_b in idx:
            i, j = idx[c.system_a], idx[c.system_b]
            m[i][j] = c.r
            m[j][i] = c.r
    return m


def input_hash(inputs: NormalizedInputs) -> str:
    """Stable hash of normalised inputs. Logged with every slot generation."""
    canonical_json = json.dumps(inputs.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:16]
