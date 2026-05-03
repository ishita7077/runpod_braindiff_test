"""Stable IDs and deterministic seeds.

Audit point #1: Python's built-in hash() is salted per process and unsafe for
reproducibility. Every ID and seed in the pipeline uses SHA256 of a canonical
string so the same inputs always produce the same outputs across processes,
machines, and runs.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone


def comparison_id(video_a_id: str, video_b_id: str, analysis_version: str) -> str:
    """Stable 16-hex-char ID for a (video_a, video_b, analysis_version) triple.

    Order matters: comparison_id("a", "b", v) != comparison_id("b", "a", v).
    Callers should canonicalise the order upstream if they want order-insensitivity.
    """
    canonical = f"{video_a_id}|{video_b_id}|{analysis_version}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def deterministic_seed(comparison_id_str: str, slot_address: str) -> int:
    """Per-slot deterministic 32-bit seed derived from comparison_id + slot.

    Different slots get different seeds (so headline and body don't share random
    state) but the same slot in the same comparison always seeds identically.
    """
    canonical = f"{comparison_id_str}|{slot_address}"
    return int(hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8], 16)


def run_id() -> str:
    """Per-invocation ID — UUID4. Distinguishes re-runs of the same comparison.

    Audit logs include both comparison_id (deterministic) and run_id (per-run)
    so we can tell whether two log streams are for the same comparison or not.
    """
    return str(uuid.uuid4())


def hash_string(s: str, length: int = 12) -> str:
    """SHA256 prefix of an arbitrary string. Used for asset/prompt hashing."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:length]


def hash_file(path: str, length: int = 12) -> str:
    """SHA256 prefix of a file's contents. Used for voice_exemplars/template hashing."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def now_iso() -> str:
    """UTC ISO-8601 timestamp with microseconds."""
    return datetime.now(timezone.utc).isoformat()
