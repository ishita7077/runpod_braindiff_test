"""Recipe description slot — one per video."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..lib.input_normalizer import CANONICAL_SYSTEMS, NormalizedInputs
from ..lib.library_matcher import match_recipe
from ..validators.recipe_description import RecipeDescriptionValidator
from .base import Slot, voice_exemplars


def _format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


class RecipeDescriptionSlot(Slot):
    template_name = "recipe_description.txt"
    max_new_tokens = 100

    def __init__(self, *, video_key: str) -> None:
        if video_key not in ("video_a", "video_b"):
            raise ValueError(f"video_key must be video_a or video_b, got {video_key}")
        self.video_key = video_key
        self.slot_address = f"recipe_description.{video_key}"
        super().__init__(validator=RecipeDescriptionValidator())

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        video = getattr(inputs, self.video_key)
        match = match_recipe(video)

        # Chord moments with timestamps.
        chord_lines = "\n".join(
            f"  - {ev.chord_id} at {_format_time(ev.timestamp_seconds)}"
            + (f" (\"{ev.quote[:60]}...\")" if ev.quote else "")
            for ev in video.chord_events
        ) or "  (no chords detected)"

        # Top 2 system peaks.
        peaks_sorted = sorted(
            video.system_peaks.items(),
            key=lambda kv: kv[1].get("value", 0),
            reverse=True,
        )[:2]
        top_peaks = "\n".join(
            f"  - {sys} peak at {_format_time(peak.get('time', 0))} (value {peak.get('value', 0):.2f})"
            for sys, peak in peaks_sorted
        )

        exemplars = voice_exemplars().get("recipe_description", [])
        exemplar_block = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(exemplars[:5]))

        return {
            "recipe_name":                 match.name,
            "recipe_description_template": match.description_template,
            "built_for_tag":               match.built_for_tag,
            "chord_moments_formatted":     chord_lines,
            "top_peaks_formatted":         top_peaks,
            "video_display_name":          video.display_name,
            "exemplars":                   exemplar_block,
        }
