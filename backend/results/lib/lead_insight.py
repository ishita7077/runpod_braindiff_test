"""Lead-insight selector — picks THE most striking coupling pattern across both
videos, which becomes the primary input to the headline + body slots.

Run AFTER all 6 coupling callouts have completed (or at least after the data
is available). Returns the winner with enough context for the headline prompt
to write a sharp two-tone line.

Scoring: combines (a) absolute r-value (signal strength), (b) anti-coupling
bonus (negative-r couplings tend to make sharper headlines), (c) integration-
score asymmetry between videos (couplings inside the integrated video are
more remarkable). Deterministic — no LLM in the picker, only in the eventual
phrasing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .input_normalizer import CouplingEntry, NormalizedInputs


_SYSTEM_PRETTY = {
    "personal_resonance": "Self-relevance",
    "attention":          "Attention",
    "brain_effort":       "Cognitive control",
    "gut_reaction":       "Visceral response",
    "memory_encoding":    "Memory encoding",
    "social_thinking":    "Theory-of-mind",
    "language_depth":     "Language",
}


@dataclass
class LeadInsight:
    video_key: str            # "video_a" | "video_b"
    video_title: str
    coupling_type: str        # "strongest" | "weakest" | "anti"
    system_a: str
    system_b: str
    r: float
    score: float              # interest score (higher = more striking)
    plain_summary: str        # one-line plain-English summary, fed to headline + body prompts


def select_lead_insight(inputs: NormalizedInputs) -> LeadInsight:
    """Pick the single most striking coupling across both videos."""
    candidates: list[LeadInsight] = []

    for vid_key in ("video_a", "video_b"):
        video = getattr(inputs, vid_key)
        if not video.couplings:
            continue
        for entry in video.couplings:
            if entry.system_a == entry.system_b:
                continue  # diagonal
            ar = abs(entry.r)
            # Anti-coupling bonus: negative r values often make the punchiest headlines.
            anti_bonus = 0.20 if entry.r < -0.20 else 0.0
            # Integration-asymmetry bonus: when the videos differ in integration, the
            # tightly-coupled one's couplings stand out more.
            other_video = getattr(inputs, "video_b" if vid_key == "video_a" else "video_a")
            int_asym = abs(video.integration_score - other_video.integration_score)
            asym_bonus = min(0.15, int_asym * 0.5)
            score = ar + anti_bonus + asym_bonus

            ctype = "anti" if entry.r < 0 else "strongest"
            sa = _SYSTEM_PRETTY.get(entry.system_a, entry.system_a)
            sb = _SYSTEM_PRETTY.get(entry.system_b, entry.system_b)
            if entry.r < -0.20:
                summary = (
                    f"In {video.display_name}, when {sa} fires, {sb} goes DOWN "
                    f"(r = {entry.r:+.2f}) — the cortex actively suppresses one mode "
                    f"while the other runs."
                )
            elif entry.r >= 0.55:
                summary = (
                    f"In {video.display_name}, {sa} and {sb} rose together across the "
                    f"runtime (r = {entry.r:+.2f}) — these two systems fired as a team."
                )
            else:
                summary = (
                    f"In {video.display_name}, {sa} and {sb} operated independently "
                    f"(r = {entry.r:+.2f}) — these systems didn't pull together."
                )

            candidates.append(LeadInsight(
                video_key=vid_key,
                video_title=video.display_name,
                coupling_type=ctype,
                system_a=entry.system_a,
                system_b=entry.system_b,
                r=entry.r,
                score=score,
                plain_summary=summary,
            ))

    if not candidates:
        # No couplings at all — synthesise a degenerate insight from system means.
        va = inputs.video_a
        return LeadInsight(
            video_key="video_a",
            video_title=va.display_name,
            coupling_type="strongest",
            system_a="attention",
            system_b="memory_encoding",
            r=0.0,
            score=0.0,
            plain_summary=f"{va.display_name} and the comparison video showed no remarkable coupling pattern.",
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[0]
