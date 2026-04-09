#!/usr/bin/env bash
set -euo pipefail

if [ -d ".venv" ]; then
  . ".venv/bin/activate"
  # Ensure uvx (from `pip install uv`) is on PATH for WhisperX subprocesses
  export PATH="$(pwd)/.venv/bin:${PATH}"
fi

uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
