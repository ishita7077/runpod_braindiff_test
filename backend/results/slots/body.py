"""Body slot — supports the headline, explains why, hooks the reader to scroll.

Takes the just-generated headline AND the lead coupling insight as primary
inputs. No body/mind axis. Video titles only."""

from __future__ import annotations

from typing import Any

from ..lib.input_normalizer import CANONICAL_SYSTEMS, NormalizedInputs
from ..lib.lead_insight import LeadInsight
from ..lib.library_matcher import match_recipe
from ..validators.body import BodyValidator
from .base import Slot, voice_exemplars


class BodySlot(Slot):
    slot_address = "body"
    template_name = "body.txt"
    max_new_tokens = 180

    def __init__(self, *, headline_text: str, lead_insight: LeadInsight) -> None:
        super().__init__(validator=BodyValidator())
        self.headline_text = headline_text
        self.lead_insight = lead_insight

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

        exemplars = voice_exemplars().get("body", [])
        exemplar_block = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(exemplars[:4]))

        return {
            "headline":         self.headline_text,
            "video_a_title":    a.display_name,
            "video_b_title":    b.display_name,
            "lead_insight":     f"  - {self.lead_insight.plain_summary}",
            "top_2_deltas":     top_2_deltas,
            "recipe_a_name":    match_a.name,
            "recipe_b_name":    match_b.name,
            "recipe_a_short":   (match_a.description_template or "")[:140],
            "recipe_b_short":   (match_b.description_template or "")[:140],
            "exemplars":        exemplar_block,
        }
