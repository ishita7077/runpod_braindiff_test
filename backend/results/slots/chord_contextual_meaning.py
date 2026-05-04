"""Chord contextual meaning slot — replaces the old chord_context slot.

Per chord firing, generates a 2-3 sentence meaning that REPLACES the generic
library meaning on the page. Uses the generic meaning as a reference in the
prompt only — the LLM rewrites it grounded in this specific firing.

slot_address: chord_moments[N].meaning  (was chord_moments[N].context in v1)
"""

from __future__ import annotations

import json
from typing import Any

from ..lib.input_normalizer import ChordEvent, NormalizedInputs
from ..validators.chord_contextual_meaning import ChordContextualMeaningValidator
from .base import Slot, voice_exemplars


def _format_time(seconds: float) -> str:
    m, s = int(seconds // 60), int(seconds % 60)
    return f"{m}:{s:02d}"


# Which systems trigger each chord (matches chord_library formulae).
_CHORD_SYSTEMS = {
    "visceral-hit":          ["gut_reaction", "brain_effort"],
    "learning-moment":       ["attention", "memory_encoding"],
    "reasoning-beat":        ["brain_effort", "language_depth"],
    "emotional-impact":      ["personal_resonance", "gut_reaction"],
    "social-resonance":      ["social_thinking", "personal_resonance"],
    "cold-cognitive-work":   ["brain_effort", "personal_resonance"],
    "story-integration":     ["memory_encoding", "social_thinking", "language_depth"],
}


class ChordContextualMeaningSlot(Slot):
    template_name = "chord_contextual_meaning.txt"
    max_new_tokens = 220

    def __init__(self, *, firing_index: int, video_key: str, event: ChordEvent) -> None:
        self.firing_index = firing_index
        self.video_key = video_key
        self.event = event
        self.slot_address = f"chord_moments[{firing_index}].meaning"
        super().__init__(validator=ChordContextualMeaningValidator())

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        video = getattr(inputs, self.video_key)

        from ..lib.content_assembler import ASSETS_DIR
        chord_lib = json.loads((ASSETS_DIR / "chord_library.json").read_text())
        chord_def = next((c for c in chord_lib["chords"] if c["id"] == self.event.chord_id), None)
        chord_name = chord_def["name"] if chord_def else self.event.chord_id
        generic_meaning = chord_def["meaning"] if chord_def else "(unknown chord)"
        triggering = _CHORD_SYSTEMS.get(self.event.chord_id, [])

        exemplars_for_chord = voice_exemplars().get("chord_context", {}).get(self.event.chord_id, [])
        exemplar_block = "\n".join(f"  - {e}" for e in exemplars_for_chord[:3]) or "  (none for this chord type)"

        return {
            "chord_name":          chord_name,
            "generic_meaning":     generic_meaning,
            "timestamp_human":     _format_time(self.event.timestamp_seconds),
            "video_title":         video.display_name,
            "quote":               (self.event.quote or "(no quote available)")[:200],
            "formula_values":      ", ".join(f"{k}={v:.2f}" for k, v in (self.event.formula_values or {}).items()) or "(not provided)",
            "triggering_systems":  ", ".join(triggering) or "(unknown)",
            "exemplars":           exemplar_block,
        }
