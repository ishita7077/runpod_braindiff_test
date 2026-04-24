
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
                        stage_times_json, warnings_json, runtime_json,
                        error_code, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        error_code=excluded.error_code,
                        error_message=excluded.error_message
                    """,
                    (
                        payload.get('job_id'), payload.get('request_id'), payload.get('created_at'),
                        payload.get('modality'), payload.get('status'),
                        1 if payload.get('success') else 0,
                        payload.get('text_a_length'), payload.get('text_b_length'), payload.get('text_a_hash'), payload.get('text_b_hash'),
                        payload.get('text_a_timesteps'), payload.get('text_b_timesteps'), payload.get('total_ms'),
                        json.dumps(payload.get('stage_times', {})), json.dumps(payload.get('warnings', [])), json.dumps(payload.get('runtime', {})),
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
            'error_code': row['error_code'],
            'error_message': row['error_message'],
        }
        d['modality_effective'] = _effective_modality(d)
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
        }

    def get_run(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute('SELECT * FROM runs WHERE job_id = ?', (job_id,)).fetchone()
        return None if row is None else self._row_to_dict(row)
