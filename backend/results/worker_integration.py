"""Worker integration glue — the runpod_worker imports and calls this.

ONE function: `generate_content_for_worker(...)`. Pass it the TRIBE outputs
already computed in the worker (predictions, dimension rows, transcripts,
metadata) and a comparison_id. It returns a dict containing the full
content.json shape plus the audit log path. The worker attaches this dict to
its response payload under `result.content`.

The function:
  1. Converts TRIBE-shape outputs → our NormalizedInputs schema
  2. Calls `use_real_content_model()` (lazy — first call materialises the
     content LLM, default google/gemma-3-1b-it, from cache)
  3. Runs the slot pipeline (deterministic lead-insight → wave 1 → wave 2)
  4. Assembles content.json
  5. Returns it to the worker

Failure mode: if any step fails, returns {"error": "...", "content": None}.
The worker should still return its existing payload — the page falls back to
the static demo or shows an error.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .lib.audit_log import AuditLogger
from .lib.content_assembler import assemble_content
from .lib.ids import comparison_id, run_id as new_run_id
from .lib.input_normalizer import (
    CANONICAL_SYSTEMS,
    ChordEvent,
    CouplingEntry,
    NormalizedInputs,
    TranscriptLine,
    VideoSignature,
    input_hash,
)
from .lib.lead_insight import select_lead_insight
from .lib.library_matcher import match_recipe
from .lib.model_manager import use_real_content_model
from .slots.base import Slot
from .slots.body import BodySlot
from .slots.chord_contextual_meaning import ChordContextualMeaningSlot
from .slots.coupling_callout import CouplingCalloutSlot
from .slots.frame2_sub import Frame2SubSlot
from .slots.headline import HeadlineSlot
from .slots.recipe_description import RecipeDescriptionSlot
from .slots.recipe_match import RecipeMatchSlot


log = logging.getLogger(__name__)


# Map from TRIBE dimension keys (whatever shape they ship in) → our 7 canonical systems.
# TRIBE output uses these strings in `dimension_rows[].dimension`. Adjust if upstream changes.
#
# Why every alias is listed explicitly: previously `attention_salience` (the name
# the legacy backend uses in result_semantics / connectivity / insight_engine)
# silently fell through and the canonical "attention" series was filled with the
# 0.5-flat fallback further down. The rich-content audit had no way to see this.
_TRIBE_DIM_TO_CANONICAL: dict[str, str] = {
    "personal_resonance":  "personal_resonance",
    "self_relevance":      "personal_resonance",
    "attention":           "attention",
    "attention_salience":  "attention",
    "brain_effort":        "brain_effort",
    "cognitive_control":   "brain_effort",
    "gut_reaction":        "gut_reaction",
    "visceral_response":   "gut_reaction",
    "memory_encoding":     "memory_encoding",
    "memory":              "memory_encoding",
    "social_thinking":     "social_thinking",
    "theory_of_mind":      "social_thinking",
    "language_depth":      "language_depth",
    "language":            "language_depth",
}


def _canonicalise_dim(name: str) -> str | None:
    return _TRIBE_DIM_TO_CANONICAL.get(name.lower().replace("-", "_").replace(" ", "_"))


def _build_video(
    *,
    video_id: str,
    display_name: str,
    duration_seconds: float,
    transcript_segments: list[dict[str, Any]],
    timeseries_per_dim: dict[str, list[float]],   # {tribe_dim_name: [v0..vT]}
    chord_events: list[dict[str, Any]] = (),
    input_audit: dict[str, Any] | None = None,
) -> VideoSignature:
    """Convert one video's TRIBE-shape data into a VideoSignature.

    `timeseries_per_dim` is the per-second predicted activation per dimension
    (TRIBE's preds aggregated by mask, normalised to 0-1). Length should equal
    int(duration_seconds) + 1.

    `input_audit` (optional): if provided, the function appends per-video
    notes — which dim names were unmapped, which canonical systems had to be
    filled with the flat-0.5 fallback. The caller surfaces this into the
    response's `content_audit.input_mapping` so we can see silent flattening
    in production rather than guessing from logs.
    """
    canonical_ts: dict[str, list[float]] = {s: [] for s in CANONICAL_SYSTEMS}
    unmapped_dims: list[str] = []
    for tribe_name, series in timeseries_per_dim.items():
        canonical = _canonicalise_dim(tribe_name)
        if canonical is None:
            unmapped_dims.append(tribe_name)
            continue
        canonical_ts[canonical] = [float(v) for v in series]

    # Fill any missing system with a flat-mean fallback. Surface this — a flat
    # 0.5 for a whole system silently kills coupling/chord detection.
    filled_flat_systems: list[str] = []
    for s in CANONICAL_SYSTEMS:
        if not canonical_ts[s]:
            canonical_ts[s] = [0.5 for _ in range(int(duration_seconds) + 1)]
            filled_flat_systems.append(s)

    if input_audit is not None:
        per_video = input_audit.setdefault(video_id, {})
        per_video["unmapped_dimensions"] = unmapped_dims
        per_video["filled_flat_systems"] = filled_flat_systems
        per_video["input_dim_count"] = len(timeseries_per_dim)
        if unmapped_dims:
            log.warning(
                "content_pipeline.input_audit: video=%s unmapped=%s",
                video_id, unmapped_dims,
            )
        if filled_flat_systems:
            log.warning(
                "content_pipeline.input_audit: video=%s flat_filled=%s",
                video_id, filled_flat_systems,
            )

    # Means + peaks from the timeseries.
    means: dict[str, float] = {}
    peaks: dict[str, dict[str, float]] = {}
    for sys, series in canonical_ts.items():
        means[sys] = sum(series) / max(1, len(series))
        peak_idx = max(range(len(series)), key=lambda i: series[i])
        peaks[sys] = {"time": float(peak_idx), "value": float(series[peak_idx])}

    # Coupling matrix — Pearson r between every pair of timeseries.
    matrix = _pearson_matrix(canonical_ts)
    couplings = _matrix_to_couplings_list(matrix)

    # Chord events from caller (worker computes these — see _detect_chords below
    # for a self-contained implementation if the worker doesn't already).
    parsed_chords = [
        ChordEvent(
            chord_id=c["chord_id"],
            timestamp_seconds=float(c["timestamp_seconds"]),
            duration_seconds=float(c.get("duration_seconds", 1.0)),
            quote=c.get("quote"),
            formula_values=c.get("formula_values", {}),
        )
        for c in (chord_events or _detect_chords(canonical_ts, transcript_segments))
    ]

    integration = _integration_score(matrix)
    hub = _hub_node(matrix)

    transcript = [
        TranscriptLine(t=float(seg.get("start", 0)), text=str(seg.get("text", "")))
        for seg in transcript_segments
        if seg.get("text")
    ]

    return VideoSignature(
        id=video_id,
        display_name=display_name,
        creator=None,
        title=display_name,
        duration_seconds=duration_seconds,
        system_means=means,
        system_peaks=peaks,
        chord_events=parsed_chords,
        integration_score=integration,
        hub_node=hub,
        couplings=couplings,
        timeseries=canonical_ts,
        coupling_matrix=matrix,
        transcript=transcript,
        poster_path=None,
    )


def _pearson_matrix(ts: dict[str, list[float]]) -> list[list[float]]:
    keys = list(CANONICAL_SYSTEMS)
    n = len(keys)
    m = [[0.0] * n for _ in range(n)]
    for i in range(n):
        m[i][i] = 1.0
        xi = ts[keys[i]]
        for j in range(i + 1, n):
            xj = ts[keys[j]]
            r = _pearson(xi, xj)
            m[i][j] = r
            m[j][i] = r
    return m


def _pearson(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    ma = sum(a[:n]) / n
    mb = sum(b[:n]) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((a[i] - ma) ** 2 for i in range(n)) ** 0.5
    db = sum((b[i] - mb) ** 2 for i in range(n)) ** 0.5
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def _matrix_to_couplings_list(m: list[list[float]]) -> list[CouplingEntry]:
    out: list[CouplingEntry] = []
    keys = list(CANONICAL_SYSTEMS)
    n = len(keys)
    for i in range(n):
        for j in range(i + 1, n):
            out.append(CouplingEntry(system_a=keys[i], system_b=keys[j], r=float(m[i][j])))
    return out


def _integration_score(m: list[list[float]]) -> float:
    """Mean of |r| across off-diagonal pairs — proxy for global integration."""
    n = len(m)
    vals = [abs(m[i][j]) for i in range(n) for j in range(i + 1, n)]
    return sum(vals) / len(vals) if vals else 0.0


def _hub_node(m: list[list[float]]) -> str:
    """The system with the highest mean |r| to all others."""
    keys = list(CANONICAL_SYSTEMS)
    n = len(keys)
    scores = []
    for i in range(n):
        s = sum(abs(m[i][j]) for j in range(n) if j != i) / max(1, n - 1)
        scores.append((keys[i], s))
    scores.sort(key=lambda kv: kv[1], reverse=True)
    return scores[0][0]


# ────────────────────────────────────────────────────────────
# Self-contained chord detection — used if the worker doesn't already detect chords.
# Applies the formulae from chord_library.json against per-second timeseries.
# ────────────────────────────────────────────────────────────

_CHORD_RULES: tuple[tuple[str, list[tuple[str, str, str]], int], ...] = (
    # (chord_id, [(system, op, threshold_kind)], min_duration_seconds)
    ("visceral-hit",        [("gut_reaction", ">=", "H"), ("brain_effort", "<=", "L")], 1),
    ("learning-moment",     [("attention", ">=", "H"), ("memory_encoding", ">=", "H")], 1),
    ("reasoning-beat",      [("brain_effort", ">=", "H"), ("language_depth", ">=", "H")], 2),
    ("emotional-impact",    [("personal_resonance", ">=", "H"), ("gut_reaction", ">=", "H")], 1),
    ("social-resonance",    [("social_thinking", ">=", "H"), ("personal_resonance", ">=", "H")], 1),
    ("cold-cognitive-work", [("brain_effort", ">=", "H"), ("personal_resonance", "<=", "L")], 2),
)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _detect_chords(
    ts: dict[str, list[float]],
    transcript_segments: list[dict[str, Any]],
    *,
    min_gap_seconds: int = 6,
    max_per_chord_type: int = 3,
    max_total: int = 8,
) -> list[dict[str, Any]]:
    """Detect chords from per-second timeseries with sane caps.

    - Per-clip 70th/30th percentile thresholds
    - Each detected run becomes one chord event (start of the run)
    - Adjacent firings of the SAME chord type within `min_gap_seconds` are
      collapsed (we keep the strongest)
    - Cap N per chord type and a total cap so we don't end up with 40+
      chord events per comparison
    """
    thresholds = {
        s: {"H": _percentile(ts[s], 70), "L": _percentile(ts[s], 30)}
        for s in CANONICAL_SYSTEMS
    }

    n = min(len(v) for v in ts.values())
    raw: list[dict[str, Any]] = []
    for chord_id, conditions, min_dur in _CHORD_RULES:
        run_start: int | None = None
        for t in range(n):
            met = all(
                (ts[s][t] >= thresholds[s][kind]) if op == ">=" else (ts[s][t] <= thresholds[s][kind])
                for s, op, kind in conditions
            )
            if met:
                if run_start is None:
                    run_start = t
            else:
                if run_start is not None and (t - run_start) >= min_dur:
                    raw.append(_chord_event(chord_id, run_start, conditions, ts, transcript_segments))
                run_start = None
        if run_start is not None and (n - run_start) >= min_dur:
            raw.append(_chord_event(chord_id, run_start, conditions, ts, transcript_segments))

    # Score each event by mean trigger-system value (rough "intensity").
    def intensity(ev: dict[str, Any]) -> float:
        vals = list((ev.get("formula_values") or {}).values())
        return sum(vals) / len(vals) if vals else 0.0

    # Group by chord type, sort by time, then collapse adjacent firings.
    by_type: dict[str, list[dict[str, Any]]] = {}
    for ev in sorted(raw, key=lambda e: e["timestamp_seconds"]):
        by_type.setdefault(ev["chord_id"], []).append(ev)

    collapsed: list[dict[str, Any]] = []
    for chord_id, events in by_type.items():
        bucket: list[dict[str, Any]] = []
        for ev in events:
            if not bucket or (ev["timestamp_seconds"] - bucket[-1]["timestamp_seconds"]) >= min_gap_seconds:
                bucket.append(ev)
            else:
                # Same chord too close — keep the more intense one.
                if intensity(ev) > intensity(bucket[-1]):
                    bucket[-1] = ev
        # Cap per-type, keeping the most intense N.
        bucket.sort(key=intensity, reverse=True)
        collapsed.extend(bucket[:max_per_chord_type])

    # Final cap across all types — most intense first.
    collapsed.sort(key=intensity, reverse=True)
    collapsed = collapsed[:max_total]
    # Return chronologically.
    collapsed.sort(key=lambda e: e["timestamp_seconds"])
    return collapsed


def _chord_event(
    chord_id: str,
    t: int,
    conditions: list[tuple[str, str, str]],
    ts: dict[str, list[float]],
    transcript_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    quote = ""
    for seg in transcript_segments:
        if seg.get("start", 0) <= t < seg.get("end", seg.get("start", 0) + 5):
            quote = seg.get("text", "")
            break
    return {
        "chord_id": chord_id,
        "timestamp_seconds": float(t),
        "duration_seconds": 1.0,
        "quote": quote or None,
        "formula_values": {s: float(ts[s][t]) for s, _op, _k in conditions},
    }


# ────────────────────────────────────────────────────────────
# Top-level: the function the worker calls
# ────────────────────────────────────────────────────────────

def generate_content_for_worker(
    *,
    video_a_id: str,
    video_b_id: str,
    video_a_title: str,
    video_b_title: str,
    duration_a_s: float,
    duration_b_s: float,
    timeseries_a: dict[str, list[float]],
    timeseries_b: dict[str, list[float]],
    transcript_segments_a: list[dict[str, Any]],
    transcript_segments_b: list[dict[str, Any]],
    analysis_version: str = "tribev2.live",
    audit_log_dir: str | None = None,
    use_stub: bool = False,
) -> dict[str, Any]:
    """Run the full content pipeline. Returns {comparison_id, content, audit_log_path}.

    `use_stub=True` skips loading LLaMA — useful for worker smoke tests and CI.
    """
    cmp_id = comparison_id(video_a_id, video_b_id, analysis_version)
    rid = new_run_id()

    if audit_log_dir is None:
        audit_log_dir = f"/tmp/braindiff_audit/{cmp_id}"
    audit_path = Path(audit_log_dir) / f"{cmp_id}.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit = AuditLogger(comparison_id=cmp_id, run_id=rid, log_dir=audit_log_dir)
    audit.emit("comparison_started", data={"analysis_version": analysis_version, "in_worker": True})

    input_audit: dict[str, Any] = {}
    try:
        va = _build_video(
            video_id=video_a_id, display_name=video_a_title,
            duration_seconds=duration_a_s,
            transcript_segments=transcript_segments_a,
            timeseries_per_dim=timeseries_a,
            input_audit=input_audit,
        )
        vb = _build_video(
            video_id=video_b_id, display_name=video_b_title,
            duration_seconds=duration_b_s,
            transcript_segments=transcript_segments_b,
            timeseries_per_dim=timeseries_b,
            input_audit=input_audit,
        )
    except Exception as exc:
        audit.emit("input_invalid", error_code="TRIBE_TO_NORMALIZED_FAILED", error_detail=f"{type(exc).__name__}: {exc}")
        audit.emit("comparison_failed")
        return {"comparison_id": cmp_id, "content": None, "error": str(exc), "input_audit": input_audit}

    inputs = NormalizedInputs(
        schema_version="normalized_inputs.v1",
        analysis_version=analysis_version,
        video_a=va, video_b=vb,
    )
    audit.emit("input_normalized", input_hash=input_hash(inputs))

    # Switch ModelManager onto the real content model unless stubbed.
    if not use_stub:
        try:
            use_real_content_model(per_slot_timeout_seconds=600.0)
        except Exception as exc:
            audit.emit("model_manager_failed", error_code="CONTENT_MODEL_LOAD_FAILED",
                       error_detail=f"{type(exc).__name__}: {exc}")
            return {
                "comparison_id": cmp_id,
                "content": None,
                "error": f"content_model_load_failed: {exc}",
                "input_audit": input_audit,
            }

    from .lib.model_manager import get_model_manager
    manager = get_model_manager()

    # Pipeline: lead → wave1 → wave2.
    lead = select_lead_insight(inputs)
    audit.emit("input_normalized", data={"lead_insight": {
        "video": lead.video_key, "system_a": lead.system_a, "system_b": lead.system_b,
        "r": lead.r, "score": lead.score,
    }})

    out_dir = Path("/tmp/outputs") / cmp_id
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    overrides_dir = Path("/tmp/manual_overrides") / cmp_id
    overrides_dir.mkdir(parents=True, exist_ok=True)

    match_a = match_recipe(va)
    match_b = match_recipe(vb)
    wave1: list[Slot] = [
        HeadlineSlot(lead_insight=lead),
        RecipeMatchSlot(video_key="video_a"),
        RecipeMatchSlot(video_key="video_b"),
        RecipeDescriptionSlot(video_key="video_a"),
        RecipeDescriptionSlot(video_key="video_b"),
        Frame2SubSlot(recipe_a_name=match_a.name, recipe_b_name=match_b.name),
    ]
    for vid_key in ("video_a", "video_b"):
        for ctype in ("strongest", "weakest", "anti"):
            wave1.append(CouplingCalloutSlot(video_key=vid_key, coupling_type=ctype))

    firing_index = 0
    for vid_key in ("video_a", "video_b"):
        video = getattr(inputs, vid_key)
        for ev in video.chord_events:
            wave1.append(ChordContextualMeaningSlot(
                firing_index=firing_index, video_key=vid_key, event=ev,
            ))
            firing_index += 1

    async def _run(slots):
        return await asyncio.gather(*[
            s.run(inputs=inputs, comparison_id=cmp_id, run_id=rid,
                  outputs_dir=out_dir, manager=manager, audit=audit)
            for s in slots
        ])

    def _run_coro(coro):
        """Run a coroutine whether or not the caller is already inside a
        running event loop. asyncio.run() raises RuntimeError when called
        from inside an active loop (which is what happens here when the
        worker has already spun up async machinery for TRIBE / model
        loading). We detect that case and run the coro in a fresh thread
        with its own loop so it can complete cleanly.
        """
        try:
            asyncio.get_running_loop()
            inside_loop = True
        except RuntimeError:
            inside_loop = False
        if not inside_loop:
            return asyncio.run(coro)
        import threading
        box = {}
        def _runner():
            try:
                box["value"] = asyncio.run(coro)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc
        t = threading.Thread(target=_runner, daemon=False)
        t.start()
        t.join()
        if "error" in box:
            raise box["error"]
        return box.get("value")

    wave1_results = _run_coro(_run(wave1))
    headline_result = next((r for r in wave1_results if r.slot_address == "headline"), None)
    headline_text = (
        headline_result.selected
        if headline_result and headline_result.succeeded and isinstance(headline_result.selected, str)
        else "(headline unavailable)"
    )

    wave2 = [BodySlot(headline_text=headline_text, lead_insight=lead)]
    _run_coro(_run(wave2))

    content = assemble_content(
        comparison_id=cmp_id, run_id=rid,
        analysis_version=analysis_version,
        inputs=inputs.to_dict(),
        outputs_dir=out_dir, overrides_dir=overrides_dir, audit=audit,
    )

    content_audit = _summarise_content_sources(content)
    content_audit["input_mapping"] = input_audit
    content_model = _describe_content_model(manager)

    audit.emit("comparison_completed", data={"content_audit": content_audit})
    return {
        "comparison_id": cmp_id,
        "content": content,
        "audit_log_path": str(audit_path),
        "input_audit": input_audit,
        "content_audit": content_audit,
        "content_model": content_model,
    }


# ────────────────────────────────────────────────────────────
# content_audit + content_model helpers
# ────────────────────────────────────────────────────────────

def _walk_slot_sources(slots: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Yield (slot_address, source, status) for every leaf slot in content.slots.

    Mirrors the structure assemble_content produces: scalar slots at the top
    level, recipe_match/recipe_description/coupling_callouts nested by video,
    chord_meanings keyed by chord id, chord_moments as an indexed list.
    """
    out: list[tuple[str, str, str]] = []

    def take(addr: str, slot: dict[str, Any] | None) -> None:
        if not isinstance(slot, dict):
            return
        out.append((addr, str(slot.get("source", "missing")), str(slot.get("status", "missing"))))

    for top_key in ("headline", "body", "frame2_sub"):
        take(top_key, slots.get(top_key))

    for grouping in ("recipe_match", "recipe_description"):
        for vid in ("video_a", "video_b"):
            take(f"{grouping}.{vid}", (slots.get(grouping) or {}).get(vid))

    for vid in ("video_a", "video_b"):
        for kind in ("strongest", "weakest", "anti"):
            take(
                f"coupling_callouts.{vid}.{kind}",
                (slots.get("coupling_callouts") or {}).get(vid, {}).get(kind),
            )

    for chord_id, slot in (slots.get("chord_meanings") or {}).items():
        take(f"chord_meanings.{chord_id}", slot)

    for moment in slots.get("chord_moments") or []:
        meaning = moment.get("meaning")
        idx = moment.get("index", "?")
        take(f"chord_moments[{idx}].meaning", meaning)

    return out


def _summarise_content_sources(content: dict[str, Any]) -> dict[str, Any]:
    """Roll up every slot's source/status into a single audit object.

    Shape:
        {
          "schema_version": "content_audit.v1",
          "slots_total": N,
          "slots_llm": int, "slots_override": int,
          "slots_library": int, "slots_fallback": int, "slots_missing": int,
          "fallback_rate": float (0..1),
          "fallback_slots": [{"slot": "...", "status": "..."}],
          "input_mapping": {...}        # filled by caller
        }
    """
    slots = content.get("slots") or {}
    walked = _walk_slot_sources(slots)
    counts: dict[str, int] = {}
    fallback_slots: list[dict[str, str]] = []
    for addr, source, status in walked:
        counts[source] = counts.get(source, 0) + 1
        if source == "fallback":
            fallback_slots.append({"slot": addr, "status": status})
    total = len(walked)
    fallback = counts.get("fallback", 0)
    return {
        "schema_version": "content_audit.v1",
        "slots_total": total,
        "slots_llm": counts.get("llm", 0),
        "slots_override": counts.get("override", 0),
        "slots_library": counts.get("library", 0),
        "slots_fallback": fallback,
        "slots_missing": counts.get("missing", 0),
        "fallback_rate": (fallback / total) if total else 0.0,
        "fallback_slots": fallback_slots,
    }


def _describe_content_model(manager: Any) -> dict[str, Any]:
    """Best-effort description of the loaded content model.

    The worker forwards this into response.meta.content_model so we can see in
    the API response which model actually produced the content (instead of
    grepping logs). Soft-fails on any attribute that isn't there.
    """
    backend = getattr(manager, "backend", None)
    if backend is None:
        return {"id": "unknown", "runtime": "unknown"}
    info: dict[str, Any] = {
        "id": getattr(backend, "model_id", "unknown"),
        "revision": getattr(backend, "model_revision", None),
        "runtime": "transformers" if backend.__class__.__name__ == "LoadedTransformersBackend" else backend.__class__.__name__,
    }
    dtype = getattr(backend, "_dtype_str", None)
    if dtype:
        info["dtype"] = dtype
    device = getattr(backend, "_device", None)
    if device:
        info["device"] = device
    return info
