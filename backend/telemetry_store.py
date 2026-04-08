
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


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
            conn.commit()

    def upsert_run(self, payload: dict[str, Any]) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        job_id, request_id, created_at, status, success,
                        text_a_length, text_b_length, text_a_hash, text_b_hash,
                        text_a_timesteps, text_b_timesteps, total_ms,
                        stage_times_json, warnings_json, runtime_json,
                        error_code, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        request_id=excluded.request_id,
                        created_at=excluded.created_at,
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
                        payload.get('job_id'), payload.get('request_id'), payload.get('created_at'), payload.get('status'),
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
        return {
            'job_id': row['job_id'],
            'request_id': row['request_id'],
            'created_at': row['created_at'],
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

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_run(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute('SELECT * FROM runs WHERE job_id = ?', (job_id,)).fetchone()
        return None if row is None else self._row_to_dict(row)
