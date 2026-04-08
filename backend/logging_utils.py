import json
import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def configure_logging(log_dir: str = "logs") -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    app_log_path = Path(log_dir) / "braindiff.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(app_log_path),
            logging.StreamHandler(),
        ],
        force=True,
    )


def write_structured_error(log_dir: str, payload: dict[str, Any]) -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    error_log_path = Path(log_dir) / "errors.jsonl"
    with error_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def build_error_payload(
    *,
    request_id: str,
    route: str,
    stage: str,
    err: Exception,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "route": route,
        "stage": stage,
        "error_type": type(err).__name__,
        "error_message": str(err),
        "traceback": traceback.format_exc(),
        "host": {
            "pid": os.getpid(),
            "python_version": os.sys.version,
        },
    }
    if extra:
        payload["context"] = extra
    return payload

