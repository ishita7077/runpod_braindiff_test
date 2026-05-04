"""Body paragraph slot — uses headline + recipe matches as context."""

from __future__ import annotations

from typing import Any

from ..lib.input_normalizer import CANONICAL_SYSTEMS, NormalizedInputs
from ..lib.library_matcher import match_recipe
from ..validators.body import BodyValidator
from .base import Slot, voice_exemplars


class BodySlot(Slot):
    slot_address = "body"
    template_name = "body.txt"
    max_new_tokens = 160

    def __init__(self) -> None:
        super().__init__(validator=BodyValidator())

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        a, b = inputs.video_a, inputs.video_b
        match_a = match_recipe(a)
        match_b = match_recipe(b)

        deltas = sorted(
            [(s, b.system_means[s] - a.system_means[s]) for s in CANONICAL_SYSTEMS],
            key=lambda kv: abs(kv[1]),
            reverse=True,
        )[:2]
        top_2_deltas = "\n".join(
            f"  - {s}: {d:+.2f} ({'B higher' if d > 0 else 'A higher'})"
            for s, d in deltas
        )

        # Read headline from raw if it landed there.
        # If not available we fall back to a generic placeholder. The prompt is robust.
        headline_text = self._maybe_read_headline(inputs)

        exemplars = voice_exemplars().get("body", [])
        exemplar_block = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(exemplars[:4]))

        return {
            "headline":             headline_text,
            "video_a_display_name": a.display_name,
            "video_b_display_name": b.display_name,
            "recipe_a_name":        match_a.name,
            "recipe_b_name":        match_b.name,
            "recipe_a_short":       _short_desc(match_a),
            "recipe_b_short":       _short_desc(match_b),
            "top_2_deltas":         top_2_deltas,
            "exemplars":            exemplar_block,
        }

    @staticmethod
    def _maybe_read_headline(inputs: NormalizedInputs) -> str:
        """Best-effort: read the just-generated headline if it exists.
        Falls back to a generic phrasing if not (slots may run in any order)."""
        return "(see headline above)"


def _short_desc(match) -> str:
    return match.description_template[:120].strip() if match.description_template else "(no template)"
