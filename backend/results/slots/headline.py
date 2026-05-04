"""Headline slot — first end-to-end slot (Phase 1)."""

from __future__ import annotations

import json
from typing import Any

from ..lib.input_normalizer import CANONICAL_SYSTEMS, NormalizedInputs
from ..validators.headline import HeadlineValidator
from .base import Slot, voice_exemplars


# Which systems sit on the body axis vs the mind axis.
_BODY_AXIS = {"gut_reaction", "personal_resonance"}
_MIND_AXIS = {"language_depth", "memory_encoding", "brain_effort"}


class HeadlineSlot(Slot):
    slot_address = "headline"
    template_name = "headline.txt"
    max_new_tokens = 120

    def __init__(self) -> None:
        super().__init__(validator=HeadlineValidator())

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        a = inputs.video_a
        b = inputs.video_b

        # Top deltas (B - A) — sorted by magnitude.
        deltas = sorted(
            [(s, b.system_means[s] - a.system_means[s]) for s in CANONICAL_SYSTEMS],
            key=lambda kv: abs(kv[1]),
            reverse=True,
        )[:3]
        top_deltas = "\n".join(
            f"  - {sys}: {delta:+.2f} ({'B higher' if delta > 0 else 'A higher'})"
            for sys, delta in deltas
        )

        # Which body-axis systems are higher in B.
        body_axis_b = ", ".join(
            sys for sys in _BODY_AXIS
            if b.system_means[sys] > a.system_means[sys]
        ) or "none"

        # Which mind-axis systems are higher in A.
        mind_axis_a = ", ".join(
            sys for sys in _MIND_AXIS
            if a.system_means[sys] > b.system_means[sys]
        ) or "none"

        exemplars = voice_exemplars().get("headline", [])
        exemplar_block = "\n".join(f"  {i+1}. \"{e}\"" for i, e in enumerate(exemplars[:6]))

        return {
            "video_a_display_name": a.display_name,
            "video_b_display_name": b.display_name,
            "top_deltas_formatted": top_deltas,
            "body_axis_b":          body_axis_b,
            "mind_axis_a":          mind_axis_a,
            "exemplars":            exemplar_block,
        }
