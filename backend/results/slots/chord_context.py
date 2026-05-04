"""Chord context slot — one per chord firing.

slot_address: chord_moments[N].context  where N = global firing index across both videos.
The slot is constructed with the firing index + the firing data + a video_key.
The validator gets a list of "required_any_of" hints (timestamp string, creator
short name, quote substring) so we enforce that the LLM grounded in this firing.
"""

from __future__ import annotations

import json
from typing import Any

from ..lib.input_normalizer import ChordEvent, NormalizedInputs
from ..validators.chord_context import ChordContextValidator
from .base import Slot, voice_exemplars


def _format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


class ChordContextSlot(Slot):
    template_name = "chord_context.txt"
    max_new_tokens = 80

    def __init__(self, *, firing_index: int, video_key: str, event: ChordEvent) -> None:
        self.firing_index = firing_index
        self.video_key = video_key
        self.event = event
        self.slot_address = f"chord_moments[{firing_index}].context"

        # Hints the LLM must reference (any one).
        ts = _format_time(event.timestamp_seconds)
        hints = [ts]
        if event.quote:
            # Pick a distinctive 2-3 word fragment.
            words = event.quote.split()
            if len(words) >= 2:
                hints.append(" ".join(words[:3]))
        super().__init__(validator=ChordContextValidator(required_any_of=hints))

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        video = getattr(inputs, self.video_key)

        # Pull the chord meaning from the chord library for prompt context.
        from ..lib.content_assembler import ASSETS_DIR
        chord_lib = json.loads((ASSETS_DIR / "chord_library.json").read_text())
        chord_def = next((c for c in chord_lib["chords"] if c["id"] == self.event.chord_id), None)
        chord_name = chord_def["name"] if chord_def else self.event.chord_id
        chord_meaning = chord_def["meaning"][:200] if chord_def else "(unknown chord)"

        exemplars_for_chord = voice_exemplars().get("chord_context", {}).get(self.event.chord_id, [])
        exemplar_block = "\n".join(f"  - {e}" for e in exemplars_for_chord[:3]) or "  (none for this chord type)"

        return {
            "chord_name":         chord_name,
            "chord_meaning":      chord_meaning,
            "timestamp_human":    _format_time(self.event.timestamp_seconds),
            "video_display_name": video.display_name,
            "quote":              (self.event.quote or "(no quote available)")[:200],
            "formula_values":     ", ".join(f"{k}={v:.2f}" for k, v in (self.event.formula_values or {}).items()) or "(not provided)",
            "exemplars":          exemplar_block,
        }
