
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from collections import Counter, defaultdict


def _effective_modality(row: dict[str, Any]) -> str:
    m = (row.get("modality") or "").strip() or "unknown"
    if m not in ("unknown", ""):
        return m
    ta = int(row.get("text_a_length") or 0)
    tb = int(row.get("text_b_length") or 0)
    if ta + tb > 0:
        return "text (legacy)"
    return "unknown"


CO_ACTIVATION_PAIRS = (
    ("attention_salience", "memory_encoding", "Attention + Memory"),
    ("personal_resonance", "gut_reaction", "Personal + Visceral"),
    ("social_thinking", "language_depth", "Social + Language"),
    ("brain_effort", "language_depth", "Effort + Meaning"),
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stage_label(stage_times: dict[str, Any]) -> str:
    if not stage_times:
        return "The run stopped before BrainDiff recorded a processing step."
    if any(k.startswith("predict_b") for k in stage_times):
        return "It reached the second file's brain-model prediction step."
    if any(k.startswith("events_b") for k in stage_times):
        return "It reached the second file's transcript/alignment step."
    if any(k.startswith("predict_a") for k in stage_times):
        return "It reached the first file's brain-model prediction step."
    if any(k.startswith("events_a") for k in stage_times):
        return "It reached the first file's transcript/alignment step."
    if "score_diff_ms" in stage_times or "heatmap_ms" in stage_times:
        return "It reached final scoring and brain-map rendering."
    return "It started processing, but did not record enough detail to identify the exact step."


def explain_failure(
    error_code: str | None,
    error_message: str | None,
    stage_times: dict[str, Any] | None = None,
) -> dict[str, str]:
    code = (error_code or "").strip() or "UNKNOWN_ERROR"
    message = (error_message or "").strip()
    text = f"{code} {message}".lower()
    stage = _stage_label(stage_times or {})

    if "timeout" in text or code in {"DIFF_TIMEOUT", "TIMED_OUT"}:
        reason = "The job took too long and was stopped."
        action = "Try shorter files/text, then check whether the RunPod worker has enough GPU time for media jobs."
    elif "media_duration_mismatch" in text or ("durations differ" in text and "within 5s" in text):
        reason = "The two files are too different in length."
        action = "Upload files within 5 seconds of each other, or choose the trim option so BrainDiff compares the first part of both files."
    elif "cuda" in text and "memory" in text or "out of memory" in text or "oom" in text:
        reason = "The worker ran out of GPU memory."
        action = "Use a smaller worker/GPU load, shorter media, or lower the model memory settings before retrying."
    elif "hf_auth" in text or "hugging face" in text or "401" in text or "403" in text:
        reason = "The worker could not access a required model."
        action = "Check the Hugging Face token on the RunPod worker and confirm it has access to the gated model."
    elif "ffmpeg" in text:
        reason = "The worker could not read or convert the uploaded media."
        action = "Install/verify ffmpeg in the worker image and retry with a standard mp3/wav/mp4 file."
    elif "whisperx" in text or "transcrib" in text:
        reason = "Audio transcription/alignment failed."
        action = "Try a clearer or shorter audio track, and check WhisperX device/compute settings on the worker."
    elif "duration" in text or "too different" in text or "input_rejected" in text:
        reason = "The two inputs were rejected before analysis."
        action = "Use two files/texts that are similar enough in length and format to compare fairly."
    elif "blob" in text or "media_url" in text or "download" in text or "fetch" in text:
        reason = "The worker could not download one of the uploaded files."
        action = "Check the Vercel Blob token, file URL expiry, and whether both uploads are reachable from RunPod."
    elif "atlas" in text:
        reason = "The worker is missing required brain atlas files."
        action = "Verify the atlas files exist in the worker image under the configured atlas directory."
    elif "runpod" in text:
        reason = "RunPod reported the job as failed, but did not provide a specific backend error."
        action = "Open the RunPod job logs for the exact stack trace; the app should show that detail once the worker returns it."
    else:
        reason = "The BrainDiff pipeline raised an unexpected error."
        action = "Check the worker logs for the stack trace, then retry with shorter, clearly supported inputs."

    return {
        "code": code,
        "reason": reason,
        "stage": stage,
        "action": action,
        "raw_message": message,
    }


def extract_result_analytics(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {}

    dimensions = result.get("dimensions") if isinstance(result, dict) else None
    if not isinstance(dimensions, list):
        dimensions = []
    by_key = {
        str(row.get("key")): row
        for row in dimensions
        if isinstance(row, dict) and row.get("key")
    }

    co_patterns: list[dict[str, Any]] = []
    for left, right, label in CO_ACTIVATION_PAIRS:
        a = by_key.get(left)
        b = by_key.get(right)
        if not a or not b:
            continue
        left_delta = _safe_float(a.get("delta"))
        right_delta = _safe_float(b.get("delta"))
        left_mag = abs(_safe_float(a.get("magnitude"), abs(left_delta)))
        right_mag = abs(_safe_float(b.get("magnitude"), abs(right_delta)))
        integration = round((left_mag + right_mag) / 2.0, 6)
        alignment = round(max(0.0, 1.0 - abs(left_delta - right_delta)), 6)
        winner = "mixed"
        if left_delta > 0 and right_delta > 0:
            winner = "B"
        elif left_delta < 0 and right_delta < 0:
            winner = "A"
        co_patterns.append(
            {
                "pattern": label,
                "integration_score": integration,
                "alignment_score": alignment,
                "winner": winner,
            }
        )
    co_patterns.sort(
        key=lambda row: (
            _safe_float(row.get("integration_score")),
            _safe_float(row.get("alignment_score")),
        ),
        reverse=True,
    )

    strongest = None
    if dimensions:
        strongest = max(
            (row for row in dimensions if isinstance(row, dict)),
            key=lambda row: abs(_safe_float(row.get("magnitude"), _safe_float(row.get("delta")))),
            default=None,
        )
    critical_state: dict[str, Any] = {}
    if strongest:
        direction = strongest.get("direction") or "neutral"
        label = strongest.get("label") or strongest.get("key") or "unknown"
        state = "balanced" if direction == "neutral" or strongest.get("low_confidence") else str(direction)
        critical_state = {
            "state": state,
            "dimension": strongest.get("key") or "unknown",
            "label": label,
            "magnitude": round(abs(_safe_float(strongest.get("magnitude"), _safe_float(strongest.get("delta")))), 6),
        }

    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    stage_times = meta.get("stage_times") if isinstance(meta.get("stage_times"), dict) else {}
    groups = {"transcribe": 0, "predict": 0, "score": 0, "heatmap": 0, "other": 0}
    for key, value in stage_times.items():
        ms = int(_safe_float(value))
        if key.startswith("events_"):
            groups["transcribe"] += ms
        elif key.startswith("predict_"):
            groups["predict"] += ms
        elif "score" in key:
            groups["score"] += ms
        elif "heatmap" in key:
            groups["heatmap"] += ms
        else:
            groups["other"] += ms
    total = sum(groups.values())
    shares = {
        key: round(value / total, 4)
        for key, value in groups.items()
        if total > 0 and value > 0
    }
    dominant = max(groups, key=groups.get) if total > 0 else "unknown"

    atlas_peak = meta.get("atlas_peak") if isinstance(meta.get("atlas_peak"), dict) else {}
    hub_node = str(atlas_peak.get("label") or critical_state.get("dimension") or "unknown")

    return {
        "top_pattern": co_patterns[0]["pattern"] if co_patterns else "",
        "co_activation_patterns": co_patterns,
        "pipeline_mix": {"dominant": dominant, "shares": shares},
        "critical_state": critical_state,
        "hub_node": hub_node,
    }


class TelemetryStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    job_id TEXT PRIMARY KEY,
                    request_id TEXT,
                    created_at TEXT,
                    modality TEXT,
                    status TEXT,
                    success INTEGER,
                    text_a_length INTEGER,
                    text_b_length INTEGER,
                    text_a_hash TEXT,
                    text_b_hash TEXT,
                    text_a_timesteps INTEGER,
                    text_b_timesteps INTEGER,
                    total_ms INTEGER,
                    stage_times_json TEXT,
                    warnings_json TEXT,
                    runtime_json TEXT,
                    result_analytics_json TEXT,
                    error_code TEXT,
                    error_message TEXT
                )
                """
            )
            existing_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "modality" not in existing_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN modality TEXT")
            if "result_analytics_json" not in existing_columns:
                conn.execute("ALTER TABLE runs ADD COLUMN result_analytics_json TEXT")
            conn.commit()

    def upsert_run(self, payload: dict[str, Any]) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        job_id, request_id, created_at, modality, status, success,
                        text_a_length, text_b_length, text_a_hash, text_b_hash,
                        text_a_timesteps, text_b_timesteps, total_ms,
                        stage_times_json, warnings_json, runtime_json, result_analytics_json,
                        error_code, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        request_id=excluded.request_id,
                        created_at=excluded.created_at,
                        modality=excluded.modality,
                        status=excluded.status,
                        success=excluded.success,
                        text_a_length=excluded.text_a_length,
                        text_b_length=excluded.text_b_length,
                        text_a_hash=excluded.text_a_hash,
                        text_b_hash=excluded.text_b_hash,
                        text_a_timesteps=excluded.text_a_timesteps,
                        text_b_timesteps=excluded.text_b_timesteps,
                        total_ms=excluded.total_ms,
                        stage_times_json=excluded.stage_times_json,
                        warnings_json=excluded.warnings_json,
                        runtime_json=excluded.runtime_json,
                        result_analytics_json=excluded.result_analytics_json,
                        error_code=excluded.error_code,
                        error_message=excluded.error_message
                    """,
                    (
                        payload.get('job_id'), payload.get('request_id'), payload.get('created_at'),
                        payload.get('modality'), payload.get('status'),
                        1 if payload.get('success') else 0,
                        payload.get('text_a_length'), payload.get('text_b_length'), payload.get('text_a_hash'), payload.get('text_b_hash'),
                        payload.get('text_a_timesteps'), payload.get('text_b_timesteps'), payload.get('total_ms'),
                        json.dumps(payload.get('stage_times', {})), json.dumps(payload.get('warnings', [])), json.dumps(payload.get('runtime', {})), json.dumps(payload.get('result_analytics', {})),
                        payload.get('error_code'), payload.get('error_message')
                    ),
                )
                conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = {
            'job_id': row['job_id'],
            'request_id': row['request_id'],
            'created_at': row['created_at'],
            'modality': row['modality'] or 'unknown',
            'status': row['status'],
            'success': bool(row['success']),
            'text_a_length': row['text_a_length'],
            'text_b_length': row['text_b_length'],
            'text_a_hash': row['text_a_hash'],
            'text_b_hash': row['text_b_hash'],
            'text_a_timesteps': row['text_a_timesteps'],
            'text_b_timesteps': row['text_b_timesteps'],
            'total_ms': row['total_ms'],
            'stage_times': json.loads(row['stage_times_json'] or '{}'),
            'warnings': json.loads(row['warnings_json'] or '[]'),
            'runtime': json.loads(row['runtime_json'] or '{}'),
            'result_analytics': json.loads(row['result_analytics_json'] or '{}'),
            'error_code': row['error_code'],
            'error_message': row['error_message'],
        }
        d['modality_effective'] = _effective_modality(d)
        d['failure_summary'] = (
            explain_failure(d['error_code'], d['error_message'], d['stage_times'])
            if not d['success']
            else {}
        )
        return d

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_runs(self, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    'SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?',
                    (limit, offset),
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def aggregate_metrics(self) -> dict[str, Any]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute('SELECT * FROM runs').fetchall()

        if not rows:
            return {
                'total_runs': 0,
                'success_count': 0,
                'failure_count': 0,
                'success_rate': 0.0,
                'avg_total_ms': 0,
                'p50_total_ms': 0,
                'p90_total_ms': 0,
                'p95_total_ms': 0,
                'warnings_rate': 0.0,
                'modality_counts': {},
                'modality_effective_counts': {},
                'error_code_counts': {},
                'status_counts': {},
                'runtime_backend_counts': {},
                'runs_last_24h': 0,
                'runs_last_7d': 0,
                'activity_by_day': [],
                'per_modality': {},
                'stage_ms_avg': {},
                'co_activation_pattern_counts': {},
                'co_activation_pattern_avg': {},
                'pipeline_mix_counts': {},
                'pipeline_share_avg': {},
                'critical_state_counts': {},
                'hub_node_counts': {},
                'failure_reason_counts': {},
            }

        decoded = [self._row_to_dict(row) for row in rows]
        total_runs = len(decoded)
        success_count = sum(1 for row in decoded if row['success'])
        failure_count = total_runs - success_count
        with_runtime = sorted(
            [int(row['total_ms']) for row in decoded if row['total_ms'] is not None]
        )
        success_runtime = sorted(
            [
                int(row['total_ms'])
                for row in decoded
                if row['success'] and row['total_ms'] is not None
            ]
        )
        warnings_count = sum(1 for row in decoded if row['warnings'])
        modality_counts = Counter(row['modality'] or 'unknown' for row in decoded)
        modality_effective_counts = Counter(
            row.get('modality_effective') or 'unknown' for row in decoded
        )
        status_counts = Counter(row['status'] or 'unknown' for row in decoded)
        error_code_counts = Counter(
            row['error_code'] for row in decoded if row['error_code']
        )
        runtime_backend_counts = Counter(
            str((row.get('runtime') or {}).get('backend') or 'unknown')
            for row in decoded
        )

        def percentile(sorted_values: list[int], p: float) -> int:
            if not sorted_values:
                return 0
            idx = int(round((len(sorted_values) - 1) * p))
            return sorted_values[idx]

        def parse_ts(created: str | None) -> datetime | None:
            if not created:
                return None
            try:
                s = created.replace('Z', '+00:00')
                return datetime.fromisoformat(s)
            except ValueError:
                return None

        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        c24 = c7 = 0
        day_buckets: dict[str, int] = {}
        for i in range(7):
            d = (day_start - timedelta(days=6 - i)).date().isoformat()
            day_buckets[d] = 0
        for row in decoded:
            ts = parse_ts(row.get('created_at'))
            if not ts:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= last_24h:
                c24 += 1
            if ts >= last_7d:
                c7 += 1
            key = ts.astimezone(timezone.utc).date().isoformat()
            if key in day_buckets:
                day_buckets[key] += 1

        activity_by_day = [{'date': d, 'count': day_buckets[d]} for d in sorted(day_buckets.keys())]

        per_modality: dict[str, Any] = {}
        for m in set(modality_effective_counts.keys()):
            subset = [r for r in decoded if r.get('modality_effective') == m]
            ok = [r for r in subset if r['success']]
            rts = sorted(
                int(r['total_ms']) for r in ok if r.get('total_ms') is not None
            )
            per_modality[m] = {
                'total': len(subset),
                'success': len(ok),
                'success_rate': round((len(ok) / len(subset)) * 100.0, 2) if subset else 0.0,
                'p50_total_ms': percentile(rts, 0.50) if rts else 0,
                'p95_total_ms': percentile(rts, 0.95) if rts else 0,
            }

        stage_sums: dict[str, int] = defaultdict(int)
        stage_n = 0
        for row in decoded:
            if not row.get('success'):
                continue
            st = row.get('stage_times') or {}
            if not isinstance(st, dict):
                continue
            for k, v in st.items():
                if isinstance(v, (int, float)):
                    stage_sums[k] += int(v)
            stage_n += 1
        stage_ms_avg: dict[str, int] = {}
        if stage_n:
            for k, total in stage_sums.items():
                stage_ms_avg[k] = int(total / stage_n)

        pattern_counts: Counter[str] = Counter()
        pattern_scores: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: {"integration": [], "alignment": []}
        )
        pipeline_mix_counts: Counter[str] = Counter()
        pipeline_share_sums: dict[str, float] = defaultdict(float)
        pipeline_share_n: dict[str, int] = defaultdict(int)
        critical_state_counts: Counter[str] = Counter()
        hub_node_counts: Counter[str] = Counter()
        failure_reason_counts: Counter[str] = Counter()
        for row in decoded:
            if not row.get('success'):
                failure = row.get('failure_summary') or {}
                reason = str(failure.get('reason') or row.get('error_code') or 'Unknown failure')
                failure_reason_counts[reason] += 1
            analytics = row.get('result_analytics') or {}
            if not isinstance(analytics, dict):
                continue
            patterns = analytics.get('co_activation_patterns') or []
            if isinstance(patterns, list):
                for item in patterns:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get('pattern') or '').strip()
                    if not name:
                        continue
                    pattern_counts[name] += 1
                    pattern_scores[name]["integration"].append(
                        _safe_float(item.get('integration_score'))
                    )
                    pattern_scores[name]["alignment"].append(
                        _safe_float(item.get('alignment_score'))
                    )
            pipeline_mix = analytics.get('pipeline_mix') or {}
            if isinstance(pipeline_mix, dict):
                dominant = str(pipeline_mix.get('dominant') or 'unknown')
                pipeline_mix_counts[dominant] += 1
                shares = pipeline_mix.get('shares') or {}
                if isinstance(shares, dict):
                    for key, value in shares.items():
                        pipeline_share_sums[str(key)] += _safe_float(value)
                        pipeline_share_n[str(key)] += 1
            critical = analytics.get('critical_state') or {}
            if isinstance(critical, dict):
                label = str(critical.get('label') or critical.get('dimension') or '').strip()
                state = str(critical.get('state') or '').strip()
                if label:
                    critical_state_counts[f"{label} · {state}" if state else label] += 1
            hub = str(analytics.get('hub_node') or '').strip()
            if hub:
                hub_node_counts[hub] += 1

        co_activation_pattern_avg = {
            name: {
                'integration_score': round(
                    sum(vals['integration']) / len(vals['integration']), 4
                ) if vals['integration'] else 0.0,
                'alignment_score': round(
                    sum(vals['alignment']) / len(vals['alignment']), 4
                ) if vals['alignment'] else 0.0,
            }
            for name, vals in pattern_scores.items()
        }
        pipeline_share_avg = {
            key: round(pipeline_share_sums[key] / pipeline_share_n[key], 4)
            for key in pipeline_share_sums
            if pipeline_share_n[key]
        }

        avg_total_ms = int(sum(with_runtime) / len(with_runtime)) if with_runtime else 0
        return {
            'total_runs': total_runs,
            'success_count': success_count,
            'failure_count': failure_count,
            'success_rate': round((success_count / total_runs) * 100.0, 2),
            'avg_total_ms': avg_total_ms,
            'p50_total_ms': percentile(with_runtime, 0.50),
            'p90_total_ms': percentile(with_runtime, 0.90),
            'p95_total_ms': percentile(with_runtime, 0.95),
            'p50_total_ms_success': percentile(success_runtime, 0.50) if success_runtime else 0,
            'p95_total_ms_success': percentile(success_runtime, 0.95) if success_runtime else 0,
            'warnings_rate': round((warnings_count / total_runs) * 100.0, 2),
            'modality_counts': dict(modality_counts),
            'modality_effective_counts': dict(modality_effective_counts),
            'error_code_counts': dict(error_code_counts),
            'status_counts': dict(status_counts),
            'runtime_backend_counts': dict(runtime_backend_counts),
            'runs_last_24h': c24,
            'runs_last_7d': c7,
            'activity_by_day': activity_by_day,
            'per_modality': per_modality,
            'stage_ms_avg': stage_ms_avg,
            'co_activation_pattern_counts': dict(pattern_counts),
            'co_activation_pattern_avg': co_activation_pattern_avg,
            'pipeline_mix_counts': dict(pipeline_mix_counts),
            'pipeline_share_avg': pipeline_share_avg,
            'critical_state_counts': dict(critical_state_counts),
            'hub_node_counts': dict(hub_node_counts),
            'failure_reason_counts': dict(failure_reason_counts),
        }

    def get_run(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute('SELECT * FROM runs WHERE job_id = ?', (job_id,)).fetchone()
        return None if row is None else self._row_to_dict(row)
