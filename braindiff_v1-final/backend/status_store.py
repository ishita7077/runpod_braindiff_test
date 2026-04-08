import threading
from datetime import datetime, timezone
from typing import Any


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, job_id: str, request_id: str) -> None:
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "request_id": request_id,
                "status": "queued",
                "events": [],
                "result": None,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

    def update_status(self, job_id: str, status: str, message: str | None = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = status
            job["events"].append(
                {
                    "status": status,
                    "message": message,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

    def set_result(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job_id]["result"] = result
            self._jobs[job_id]["status"] = "done"

    def set_error(self, job_id: str, error_payload: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job_id]["error"] = error_payload
            self._jobs[job_id]["status"] = "error"

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._jobs.get(job_id)

