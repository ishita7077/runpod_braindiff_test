"""Analysis-brief slot — Phase C.3.

The analysis_brief is the FIRST model call of the pipeline. Every section
writer (headline, body, coupling callouts) reads its `selected` value to
ensure the page tells one coherent story.

Output is JSON, validated by AnalysisBriefValidator. Evidence-ref grounding
is enforced by passing the packet's valid_evidence_refs set into the
validator. Generic copywriter phrases ("make it more engaging") are banned.

The slot consumes the deterministic evidence packet (Phase C.2) plus a one-
line lead summary from select_lead_insight, so the model's only job is the
interpretation, not the data summary.
"""

from __future__ import annotations

import json
from typing import Any

from ..lib.evidence_packet import build_evidence_packet, collect_valid_evidence_refs
from ..lib.input_normalizer import NormalizedInputs
from ..lib.json_extract import JSONExtractionError, extract_first_json_object
from ..lib.lead_insight import LeadInsight
from ..validators.analysis_brief import AnalysisBriefValidator
from .base import Slot


class AnalysisBriefSlot(Slot):
    slot_address = "analysis_brief"
    template_name = "analysis_brief.txt"
    max_new_tokens = 600         # Brief is the longest output the pipeline produces.
    temperature = 0.6            # Mild sampling — repair loop handles failures.
    top_p = 0.9
    do_sample = True
    output_is_json = True

    def __init__(self, *, lead_insight: LeadInsight) -> None:
        # The validator is initialised lazily once we know the evidence packet.
        super().__init__(validator=AnalysisBriefValidator())
        self.lead_insight = lead_insight

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        packet = build_evidence_packet(inputs)
        # Re-bind the validator with grounding refs from this packet so the
        # slot runner enforces grounding without callers having to know.
        self.validator = AnalysisBriefValidator(
            valid_evidence_refs=collect_valid_evidence_refs(packet),
        )
        return {
            "evidence_packet_json": json.dumps(packet, ensure_ascii=False, indent=2),
            "video_a_title": inputs.video_a.display_name,
            "video_b_title": inputs.video_b.display_name,
            "lead_summary":  self.lead_insight.plain_summary,
        }

    def parse_selected(self, model_text: str) -> Any:
        """Extract the JSON brief from the model's text output.

        Raises so the slot runner records OUTPUT_UNPARSEABLE on bad output.
        """
        try:
            return extract_first_json_object(model_text)
        except JSONExtractionError as exc:
            raise ValueError(f"analysis_brief output not JSON: {exc}") from exc
