"""Phase C.5 — sampled generation + repair loop in Slot.run.

We don't load a real model. We stub ModelManager to return a script of
responses, and we stub the slot's prompt template + validator so the test is
hermetic. The harness asserts:

  * sample-then-pass: only one attempt, no repair
  * sample-fail-then-repair-pass: two attempts logged, repair carries the
    prior errors + prior raw text, final selected = repair output
  * sample-fail-repair-fail-resample-pass: three attempts, all logged
  * persistent failure: returns failed result with three logged attempts
  * the raw_doc.attempts list is JSON-serialisable
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.results.lib.audit_log import AuditLogger
from backend.results.lib.input_normalizer import (
    CANONICAL_SYSTEMS,
    NormalizedInputs,
    VideoSignature,
)
from backend.results.lib.model_manager import (
    GenerationRequest,
    GenerationResponse,
    ModelManager,
)
from backend.results.slots.base import Slot
from backend.results.validators.base import (
    BaseValidator,
    ValidationError,
    ValidationResult,
)


# ────────────────────────────────────────────────────────────
# Test scaffolding
# ────────────────────────────────────────────────────────────

@dataclass
class _ScriptedBackend:
    model_id: str = "test-stub"
    model_revision: str | None = "test"
    responses: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.responses is None:
            self.responses = []
        self.calls: list[GenerationRequest] = []

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        self.calls.append(req)
        if not self.responses:
            raise RuntimeError("scripted backend exhausted")
        text = self.responses.pop(0)
        return GenerationResponse(
            text=text, latency_ms=1, tokens_input=10, tokens_output=10,
            model_id=self.model_id, model_revision=self.model_revision,
        )

    def vram_peak_mb(self) -> float | None:
        return None

    def reset_vram_peak(self) -> None:
        return None


class _AcceptIfStartsWith(BaseValidator):
    """Accepts strings beginning with the magic word "OK"."""

    slot = "test_slot"

    def validate(self, output: Any) -> ValidationResult:
        if isinstance(output, str) and output.strip().startswith("OK"):
            return ValidationResult(passed=True)
        return ValidationResult(
            passed=False,
            errors=[ValidationError(code="WRONG_PREFIX", detail="must start with OK")],
        )


class _MinimalSlot(Slot):
    """Slot with a hand-rolled prompt template (no template file needed)."""
    slot_address = "test.slot"
    template_name = "test_slot.txt"  # we override render_prompt below
    max_new_tokens = 32
    temperature = 0.5
    do_sample = True

    def __init__(self) -> None:
        super().__init__(validator=_AcceptIfStartsWith())

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        return {}

    def render_prompt(self, ctx: dict[str, Any]) -> str:
        return "Return a string starting with OK."


def _empty_inputs() -> NormalizedInputs:
    matrix = [[1.0] * len(CANONICAL_SYSTEMS) for _ in CANONICAL_SYSTEMS]

    def _vid(vid_id: str) -> VideoSignature:
        means = {s: 0.5 for s in CANONICAL_SYSTEMS}
        peaks = {s: {"time": 0.0, "value": 0.5} for s in CANONICAL_SYSTEMS}
        return VideoSignature(
            id=vid_id, display_name=vid_id, creator=None, title=vid_id,
            duration_seconds=10.0,
            system_means=means, system_peaks=peaks,
            chord_events=[], integration_score=0.0, hub_node="attention",
            couplings=[], timeseries={s: [0.5] * 11 for s in CANONICAL_SYSTEMS},
            coupling_matrix=matrix, transcript=[], poster_path=None,
        )

    return NormalizedInputs(
        schema_version="normalized_inputs.v1",
        analysis_version="test",
        video_a=_vid("video_a"), video_b=_vid("video_b"),
    )


def _run(slot: _MinimalSlot, backend: _ScriptedBackend) -> Any:
    manager = ModelManager(backend, max_parallel=1, per_slot_timeout_seconds=5.0)
    audit = AuditLogger(comparison_id="cmp", run_id="run", log_dir=tempfile.mkdtemp())
    out_dir = Path(tempfile.mkdtemp())
    return asyncio.run(slot.run(
        inputs=_empty_inputs(),
        comparison_id="cmp", run_id="run",
        outputs_dir=out_dir, manager=manager, audit=audit,
    ))


# ────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────

def test_first_sample_passes_no_repair() -> None:
    backend = _ScriptedBackend(responses=["OK first try"])
    result = _run(_MinimalSlot(), backend)
    assert result.succeeded
    assert result.selected == "OK first try"
    assert result.attempts == 1
    raw = json.loads(result.raw_path.read_text())
    assert raw["attempts_count"] == 1
    assert raw["attempts"][0]["kind"] == "sample"
    assert len(backend.calls) == 1


def test_repair_after_sample_failure_carries_prior_output() -> None:
    backend = _ScriptedBackend(responses=["bad first attempt", "OK after repair"])
    result = _run(_MinimalSlot(), backend)
    assert result.succeeded
    assert result.selected == "OK after repair"
    raw = json.loads(result.raw_path.read_text())
    assert raw["attempts_count"] == 2
    assert raw["attempts"][0]["kind"] == "sample"
    assert raw["attempts"][1]["kind"] == "repair"
    # The repair prompt must contain the previous output.
    repair_prompt = backend.calls[1].prompt
    assert "bad first attempt" in repair_prompt
    assert "must start with OK" in repair_prompt  # the validation error string


def test_resample_after_repair_failure() -> None:
    backend = _ScriptedBackend(responses=["bad", "still bad", "OK third"])
    result = _run(_MinimalSlot(), backend)
    assert result.succeeded
    assert result.selected == "OK third"
    raw = json.loads(result.raw_path.read_text())
    assert raw["attempts_count"] == 3
    assert [a["kind"] for a in raw["attempts"]] == ["sample", "repair", "sample"]


def test_persistent_failure_returns_failed_result_with_full_log() -> None:
    backend = _ScriptedBackend(responses=["nope1", "nope2", "nope3"])
    result = _run(_MinimalSlot(), backend)
    assert not result.succeeded
    assert result.selected is None
    raw = json.loads(result.raw_path.read_text())
    assert raw["attempts_count"] == 3
    # Every attempt logged its raw_text and validation summary.
    for a in raw["attempts"]:
        assert "raw_text" in a
        assert a["validation"]["passed"] is False


def test_attempts_log_is_json_serialisable() -> None:
    """Even if a slot returns dicts with non-string values the audit must
    persist. Defensive: parse_selected may produce a dict in JSON slots."""
    backend = _ScriptedBackend(responses=["OK fine"])
    result = _run(_MinimalSlot(), backend)
    raw = result.raw_path.read_text()
    # Must round-trip without TypeError.
    obj = json.loads(raw)
    assert obj["selected"] == "OK fine"
