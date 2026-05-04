"""Frame 02 sub-paragraph slot."""

from __future__ import annotations

from typing import Any

from ..lib.input_normalizer import NormalizedInputs
from ..lib.library_matcher import match_recipe
from ..validators.frame2_sub import Frame2SubValidator
from .base import Slot, voice_exemplars


class Frame2SubSlot(Slot):
    slot_address = "frame2_sub"
    template_name = "frame2_sub.txt"
    max_new_tokens = 130

    def __init__(self, *, recipe_a_name: str, recipe_b_name: str) -> None:
        super().__init__(validator=Frame2SubValidator(
            required_recipe_names=[recipe_a_name, recipe_b_name],
        ))
        self.recipe_a_name = recipe_a_name
        self.recipe_b_name = recipe_b_name

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        total_chords = len(inputs.video_a.chord_events) + len(inputs.video_b.chord_events)
        runtime = max(inputs.video_a.duration_seconds, inputs.video_b.duration_seconds)

        exemplars = voice_exemplars().get("frame2_sub", [])
        exemplar_block = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(exemplars[:4]))

        return {
            "recipe_a_name":     self.recipe_a_name,
            "recipe_b_name":     self.recipe_b_name,
            "total_chord_count": total_chords,
            "runtime_seconds":   int(runtime),
            "exemplars":         exemplar_block,
        }
