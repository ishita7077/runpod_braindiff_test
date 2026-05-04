"""Deterministic recipe matcher (audit point #3).

The recipe library is structured data — 18 entries with explicit fingerprints.
Asking a small LLM to fuzzy-match against it is fragile (token-burning, wrong
sometimes for no reason). Instead we score the comparison's signature against
each library entry with weighted rules:

    35%  system mean match           (does each system land in the spec'd range)
    25%  chord type match            (do the characteristic chords appear)
    15%  chord timing pattern        (do they fire at the right times)
    15%  integration score match     (does integration sit where it should)
    10%  hub / coupling match        (is the hub system among candidates;
                                      anti-coupling threshold met if specified)

The library entry with the highest score wins. If the top score is below
0.6 the match is "uncategorized" and the audit log records a
library_match_low_confidence event with the closest entry in `data`.

The LLM is only used for the one-sentence rationale (a separate, narrow slot
prompt that takes the deterministic match + score breakdown as input).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .input_normalizer import VideoSignature


REPO_ROOT = Path(__file__).resolve().parents[3]
LIBRARY_PATH = REPO_ROOT / "backend" / "results" / "assets" / "recipe_library.json"

CONFIDENCE_THRESHOLD = 0.6


# ────────────────────────────────────────────────────────────
# Result types
# ────────────────────────────────────────────────────────────

@dataclass
class RecipeScore:
    library_id: str
    name: str
    built_for_tag: str
    description_template: str
    score: float
    breakdown: dict[str, float]


@dataclass
class MatchResult:
    library_id: str             # "uncategorized" if score < threshold
    name: str
    built_for_tag: str
    description_template: str
    confidence: float
    score_breakdown: dict[str, float]
    closest_entry_if_uncategorized: RecipeScore | None = None
    all_scores: list[RecipeScore] = field(default_factory=list)  # for audit logging


# ────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────

_LIBRARY_CACHE: list[dict[str, Any]] | None = None


def load_library() -> list[dict[str, Any]]:
    global _LIBRARY_CACHE
    if _LIBRARY_CACHE is None:
        _LIBRARY_CACHE = json.loads(LIBRARY_PATH.read_text())["library"]
    return _LIBRARY_CACHE


def match_recipe(video: VideoSignature) -> MatchResult:
    """Score every library entry against this video; pick the best."""
    library = load_library()
    scores: list[RecipeScore] = []
    uncategorized = None

    for entry in library:
        if entry["id"] == "uncategorized":
            uncategorized = entry
            continue
        breakdown = _score_entry(video, entry)
        weighted = (
            0.35 * breakdown["system_means"]
            + 0.25 * breakdown["chords"]
            + 0.15 * breakdown["timing"]
            + 0.15 * breakdown["integration"]
            + 0.10 * breakdown["hub"]
        )
        scores.append(RecipeScore(
            library_id=entry["id"],
            name=entry["name"],
            built_for_tag=entry.get("built_for_tag", ""),
            description_template=entry.get("description_template", ""),
            score=round(weighted, 4),
            breakdown={k: round(v, 4) for k, v in breakdown.items()},
        ))

    scores.sort(key=lambda s: s.score, reverse=True)
    top = scores[0]

    if top.score >= CONFIDENCE_THRESHOLD:
        return MatchResult(
            library_id=top.library_id,
            name=top.name,
            built_for_tag=top.built_for_tag,
            description_template=top.description_template,
            confidence=top.score,
            score_breakdown=top.breakdown,
            all_scores=scores,
        )

    # Below threshold: uncategorized, but record the closest.
    return MatchResult(
        library_id="uncategorized",
        name=uncategorized["name"] if uncategorized else "Uncategorized",
        built_for_tag=uncategorized.get("built_for_tag", "novel pattern") if uncategorized else "novel pattern",
        description_template=uncategorized.get("description_template", "") if uncategorized else "",
        confidence=top.score,
        score_breakdown=top.breakdown,
        closest_entry_if_uncategorized=top,
        all_scores=scores,
    )


# ────────────────────────────────────────────────────────────
# Per-component scorers
# ────────────────────────────────────────────────────────────

_RANGE_RE = re.compile(r"^(>=|<=|>|<|==)\s*([0-9.]+)$")


def _score_entry(video: VideoSignature, entry: dict[str, Any]) -> dict[str, float]:
    fp = entry.get("fingerprint")
    if fp is None:
        return {"system_means": 0.0, "chords": 0.0, "timing": 0.0, "integration": 0.0, "hub": 0.0}

    return {
        "system_means": _score_system_means(video, fp.get("system_means_pattern", {})),
        "chords":       _score_chord_types(video, fp.get("characteristic_chords", [])),
        "timing":       _score_chord_timing(video, fp.get("chord_timing_pattern", "")),
        "integration":  _score_integration(video, fp.get("integration_score", "")),
        "hub":          _score_hub_and_coupling(video, fp),
    }


def _score_system_means(video: VideoSignature, pattern: Any) -> float:
    """Each system constraint is one term; mean of per-term satisfaction."""
    if not pattern:
        return 0.5
    if isinstance(pattern, str):
        # Special-case the two string patterns used in the library.
        if pattern == "all_systems_in_range_0.45_to_0.65":
            in_range = sum(1 for v in video.system_means.values() if 0.45 <= v <= 0.65)
            return in_range / 7.0
        if pattern == "at_least_3_systems_above_0.55":
            n = sum(1 for v in video.system_means.values() if v >= 0.55)
            return min(1.0, n / 3.0)
        if pattern == "high_variance":
            vals = list(video.system_means.values())
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            return min(1.0, var * 30)  # crude variance → [0,1]
        return 0.5

    # Dict of {system: ">=0.55"} etc.
    sats: list[float] = []
    for system, constraint in pattern.items():
        actual = video.system_means.get(system)
        if actual is None:
            sats.append(0.0)
            continue
        sats.append(_satisfaction(actual, constraint))
    return sum(sats) / len(sats) if sats else 0.5


def _satisfaction(actual: float, constraint: str) -> float:
    """Soft satisfaction in [0, 1]. Exact match = 1.0; far misses approach 0."""
    if not isinstance(constraint, str):
        return 0.5
    m = _RANGE_RE.match(constraint.strip())
    if not m:
        return 0.5
    op, target_str = m.groups()
    target = float(target_str)
    delta = actual - target
    # Sigmoid-ish: within 0.02 of threshold = ~1; >0.20 off the wrong way = ~0.
    if op in (">=", ">"):
        if delta >= 0:
            return 1.0
        return max(0.0, 1.0 + delta * 5)  # delta is negative
    if op in ("<=", "<"):
        if delta <= 0:
            return 1.0
        return max(0.0, 1.0 - delta * 5)
    if op == "==":
        return max(0.0, 1.0 - abs(delta) * 5)
    return 0.5


def _score_chord_types(video: VideoSignature, expected_chord_ids: list[str]) -> float:
    """Fraction of expected chord types that actually appear (and absence of others
    when the entry is "no chords detected" = empty list)."""
    detected = {ev.chord_id for ev in video.chord_events}
    if not expected_chord_ids:
        # Recipe characterised by absence of chords: penalise if any fired.
        return 1.0 if not detected else max(0.0, 1.0 - 0.25 * len(detected))
    hits = sum(1 for cid in expected_chord_ids if cid in detected)
    return hits / len(expected_chord_ids)


def _score_chord_timing(video: VideoSignature, timing_spec: str) -> float:
    """Loose timing match. Recognised phrases:
       'first half', 'second half', 'first 10s', 'first 15s', 'last 10s',
       'last 15s', 'last 20s', 'spread across', 'no chords in first Xs'.
    """
    if not timing_spec or not video.chord_events:
        return 0.5
    spec = timing_spec.lower()
    duration = video.duration_seconds or 60.0
    times = [ev.timestamp_seconds for ev in video.chord_events]

    score = 0.5

    if "second half" in spec or "back half" in spec:
        in_second = sum(1 for t in times if t >= duration / 2)
        score = in_second / len(times)
    elif "first half" in spec:
        in_first = sum(1 for t in times if t < duration / 2)
        score = in_first / len(times)
    elif "first 10s" in spec or "opening" in spec:
        in_open = sum(1 for t in times if t < 10)
        score = min(1.0, in_open / 1.0)
    elif "last 15s" in spec or "last 20s" in spec or "closing" in spec:
        win = 20 if "last 20s" in spec else 15
        in_close = sum(1 for t in times if t >= duration - win)
        score = min(1.0, in_close / 1.0)
    elif "spread across" in spec:
        # Reward chords spanning wide time-range.
        spread = (max(times) - min(times)) / max(1.0, duration)
        score = min(1.0, spread * 1.5)
    elif "no chords in first" in spec:
        m = re.search(r"no chords in first (\d+)s", spec)
        if m:
            cutoff = float(m.group(1))
            none_in_window = all(t >= cutoff for t in times)
            score = 1.0 if none_in_window else 0.3
    return score


def _score_integration(video: VideoSignature, constraint: str) -> float:
    if not constraint:
        return 0.5
    return _satisfaction(video.integration_score, constraint)


def _score_hub_and_coupling(video: VideoSignature, fp: dict[str, Any]) -> float:
    """Combine hub-node match and (if specified) anti-coupling threshold."""
    parts: list[float] = []
    candidates = fp.get("hub_node_candidates", [])
    if candidates:
        parts.append(1.0 if video.hub_node in candidates else 0.0)

    anti = fp.get("anti_coupling")
    if anti:
        # Spec format: "effort_x_gut < -0.20"
        m = re.match(r"(\w+)_x_(\w+)\s*<\s*([-0-9.]+)", anti)
        if m:
            sa, sb, thresh = m.group(1), m.group(2), float(m.group(3))
            for c in video.couplings:
                if {c.system_a, c.system_b} >= {f"{sa}_reaction" if sa == "gut" else sa,
                                                 f"{sb}_reaction" if sb == "gut" else sb} or \
                   {c.system_a.split("_")[0], c.system_b.split("_")[0]} == {sa, sb}:
                    parts.append(1.0 if c.r < thresh else 0.0)
                    break
            else:
                parts.append(0.3)  # no matching pair found
    return sum(parts) / len(parts) if parts else 0.5
