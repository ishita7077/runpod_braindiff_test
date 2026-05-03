"""Per-comparison audit log writer.

Writes one JSONL file per comparison_id at audit_log/{comparison_id}.jsonl.
Each line is one event matching audit_event.schema.json. Append-only.

Use the AuditLogger context-manager-style class so callers can't forget to
include comparison_id / run_id on every event.

The debug CLI reads these files. They are the source of truth for "why did
this slot fail?"
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .ids import now_iso


# Whitelist matching audit_event.schema.json -> event_type enum.
ALLOWED_EVENT_TYPES = frozenset({
    "comparison_started",
    "input_normalized",
    "input_invalid",
    "model_manager_started",
    "model_manager_failed",
    "slot_started",
    "slot_prompt_rendered",
    "slot_model_called",
    "slot_model_returned",
    "slot_model_failed",
    "slot_validation_passed",
    "slot_validation_failed",
    "slot_retry_started",
    "slot_fallback_used",
    "slot_override_used",
    "slot_override_invalid",
    "slot_completed",
    "library_match_scored",
    "library_match_low_confidence",
    "content_assembled",
    "content_schema_invalid",
    "frontend_contract_validated",
    "comparison_completed",
    "comparison_failed",
})


class AuditLogger:
    """Append-only JSONL writer scoped to one (comparison_id, run_id)."""

    def __init__(
        self,
        comparison_id: str,
        run_id: str,
        log_dir: str | os.PathLike[str] = "audit_log",
    ) -> None:
        self.comparison_id = comparison_id
        self.run_id = run_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{comparison_id}.jsonl"

    def emit(
        self,
        event_type: str,
        *,
        slot: str | None = None,
        attempt: int | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        input_hash: str | None = None,
        prompt_hash: str | None = None,
        raw_output_path: str | None = None,
        latency_ms: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValueError(
                f"Unknown audit event_type {event_type!r}. "
                f"Add it to audit_event.schema.json + ALLOWED_EVENT_TYPES."
            )

        event: dict[str, Any] = {
            "schema_version": "audit_event.v1",
            "event_type": event_type,
            "timestamp": now_iso(),
            "comparison_id": self.comparison_id,
            "run_id": self.run_id,
            "slot": slot,
            "attempt": attempt,
            "error_code": error_code,
            "error_detail": error_detail,
            "input_hash": input_hash,
            "prompt_hash": prompt_hash,
            "raw_output_path": raw_output_path,
            "latency_ms": latency_ms,
            "data": data,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(comparison_id: str, log_dir: str | os.PathLike[str] = "audit_log") -> list[dict[str, Any]]:
    """Load all events for a comparison_id. Used by the debug CLI."""
    path = Path(log_dir) / f"{comparison_id}.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events
