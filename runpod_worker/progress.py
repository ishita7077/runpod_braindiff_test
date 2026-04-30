"""Real progress events from the RunPod worker → Upstash Redis → status endpoint.

Why this exists: RunPod serverless `/status` only reports IN_QUEUE / IN_PROGRESS
/ COMPLETED. Without an out-of-band channel the UI cannot show what the worker
is doing during the 6-12 minute predict window. This module is that channel.

Design:

- Events are appended to `events:{job_id}` as JSON strings via Upstash REST.
- Each event is `{"ts": iso8601, "status": str, "message": str}`.
- The status endpoint (api/diff/status/[jobId].js) reads the list with LRANGE
  and returns it to the frontend; run.html's Deep Scope already knows how to
  consume an `events` array.
- A 24-hour TTL is set so completed-job events do not pile up in Redis.
- All Redis calls are best-effort: if Upstash is misconfigured or
  unreachable, the worker still completes the job. We never let observability
  break the actual work.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Iterable

import httpx

logger = logging.getLogger("braindiff.progress")

_TTL_SECONDS = 24 * 60 * 60
_HTTP_TIMEOUT_S = 5.0


class RedisProgressEmitter:
    """Push `(status, message)` events for a job into Upstash Redis."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._url = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
        self._token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or ""
        self._enabled = bool(self._url and self._token and job_id)
        if not self._enabled:
            logger.info(
                "progress: emitter disabled job_id=%s url_set=%s token_set=%s",
                job_id,
                bool(self._url),
                bool(self._token),
            )

    @property
    def key(self) -> str:
        return f"events:{self.job_id}"

    def emit(self, status: str, message: str) -> None:
        if not self._enabled:
            return
        event = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": status,
            "message": message,
        }
        # Upstash REST accepts a pipeline of commands as a JSON array; we use
        # it to push and refresh the TTL atomically. RPUSH so order matches
        # arrival; EXPIRE so the list doesn't outlive the job.
        payload: list[list[str]] = [
            ["RPUSH", self.key, json.dumps(event, separators=(",", ":"))],
            ["EXPIRE", self.key, str(_TTL_SECONDS)],
        ]
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT_S) as client:
                resp = client.post(
                    f"{self._url}/pipeline",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json=payload,
                )
                resp.raise_for_status()
        except Exception as err:
            # Never let progress emission fail the job — log and move on.
            logger.warning(
                "progress: emit failed job_id=%s status=%s err=%s",
                self.job_id,
                status,
                err,
            )


class NullProgressEmitter:
    """No-op emitter used when no job_id is present (e.g. local CLI runs)."""

    def emit(self, status: str, message: str) -> None:
        return None


def emitter_for(job_id: str | None) -> "RedisProgressEmitter | NullProgressEmitter":
    if not job_id:
        return NullProgressEmitter()
    return RedisProgressEmitter(job_id)


def emit_each(emitter: object, items: Iterable[tuple[str, str]]) -> None:
    """Helper for pushing a sequence of `(status, message)` events in order."""
    for status, message in items:
        try:
            emitter.emit(status, message)  # type: ignore[attr-defined]
        except Exception:
            pass
