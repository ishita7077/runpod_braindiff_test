"""Headline slot — driven by the lead coupling insight (no body/mind axis,
no creator names, video titles only)."""

from __future__ import annotations

from typing import Any

from ..lib.input_normalizer import CANONICAL_SYSTEMS, NormalizedInputs
from ..lib.lead_insight import LeadInsight
from ..validators.headline import HeadlineValidator
from .base import Slot, voice_exemplars


class HeadlineSlot(Slot):
    slot_address = "headline"
    template_name = "headline.txt"
    max_new_tokens = 120

    def __init__(
        self,
        *,
        lead_insight: LeadInsight,
        analysis_brief: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(validator=HeadlineValidator())
        self.lead_insight = lead_insight
        # Phase C.7: when AnalysisBriefSlot succeeded its result is passed in
        # so the headline can anchor on the brief's chosen thesis. None falls
        # back to the lead-insight summary alone.
        self.analysis_brief = analysis_brief

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        a, b = inputs.video_a, inputs.video_b

        deltas = sorted(
            [(s, b.system_means[s] - a.system_means[s]) for s in CANONICAL_SYSTEMS],
            key=lambda kv: abs(kv[1]),
            reverse=True,
        )[:3]
        top_deltas = "\n".join(
            f"  - {s}: {d:+.2f} ({'B higher' if d > 0 else 'A higher'})"
            for s, d in deltas
        )

        exemplars = voice_exemplars().get("headline", [])
        exemplar_block = "\n".join(f"  {i+1}. \"{e}\"" for i, e in enumerate(exemplars[:6]))

        thesis = ""
        if isinstance(self.analysis_brief, dict):
            thesis = str(self.analysis_brief.get("thesis") or "").strip()

        return {
            "video_a_title": a.display_name,
            "video_b_title": b.display_name,
            "lead_insight":  f"  - {self.lead_insight.plain_summary}",
            "top_deltas":    top_deltas,
            "exemplars":     exemplar_block,
            "analysis_thesis": thesis or "(brief unavailable; rely on the lead insight)",
        }
