#!/usr/bin/env bash
set -euo pipefail

if [ -d ".venv" ]; then
  . ".venv/bin/activate"
  # Prefer venv-local uvx; fall back to global uv install for WhisperX subprocesses.
  export PATH="$(pwd)/.venv/bin:${PATH}"
fi
# Ensure global uv (and uvx) is also reachable regardless of venv state.
export PATH="/opt/homebrew/bin:${PATH}"

# Warm the full text→predict path once at startup so first user diff is faster (adds startup time).
export BRAIN_DIFF_STARTUP_WARMUP="${BRAIN_DIFF_STARTUP_WARMUP:-1}"
# sober | punchy — headline voice for insights (see backend/insight_engine.py)
export BRAIN_DIFF_NARRATIVE_TONE="${BRAIN_DIFF_NARRATIVE_TONE:-sober}"

# Apple Silicon (M-series) — WhisperX has no MPS backend; keep it on CPU.
export TRIBEV2_WHISPERX_DEVICE="${TRIBEV2_WHISPERX_DEVICE:-cpu}"
# Use base.en for better transcription quality; M-series CPU handles it well.
export TRIBEV2_WHISPERX_MODEL="${TRIBEV2_WHISPERX_MODEL:-base.en}"
# Llama defaults to CPU (reliable). If you set BRAIN_DIFF_TEXT_BACKEND=mps_split, this cap applies.
export BRAIN_DIFF_MPS_TEXT_MAX_MEMORY="${BRAIN_DIFF_MPS_TEXT_MAX_MEMORY:-10000MiB}"
# Allow 2 parallel diff jobs given available memory headroom.
export BRAIN_DIFF_MAX_CONCURRENT_JOBS="${BRAIN_DIFF_MAX_CONCURRENT_JOBS:-2}"

if [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
else
  uvicorn backend.api:app --host 0.0.0.0 --port 8000
fi
