#!/usr/bin/env bash
set -euo pipefail

if [ -d ".venv" ]; then
  . ".venv/bin/activate"
fi

uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
