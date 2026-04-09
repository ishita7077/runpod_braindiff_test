#!/usr/bin/env bash
set -euo pipefail

# TRIBEv2 requires exactly Python 3.11.x
PYTHON_BIN=${PYTHON_BIN:-$(command -v python3.11 2>/dev/null || true)}

if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: Python 3.11 not found. Install it first (e.g. brew install python@3.11)." >&2
  exit 1
fi

PYTHON_VERSION=$("$PYTHON_BIN" --version 2>&1)
case "$PYTHON_VERSION" in
  *"3.11."*)
    echo "Using Python: $PYTHON_VERSION ($PYTHON_BIN)"
    ;;
  *)
    echo "ERROR: Python 3.11.x required, but found: $PYTHON_VERSION" >&2
    echo "Set PYTHON_BIN=/path/to/python3.11 to override." >&2
    exit 1
    ;;
esac

VENV_DIR=${VENV_DIR:-.venv}
if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
. "$VENV_DIR/bin/activate"

# Use uv for installs (parallel resolver + downloads). Tune for flaky / rate-limited CDNs:
# too many concurrent connections to files.pythonhosted.org can stall with no log output.
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-600}"
export UV_CONCURRENT_DOWNLOADS="${UV_CONCURRENT_DOWNLOADS:-3}"

UV_BIN=$(command -v uv 2>/dev/null || echo "")
if [ -z "$UV_BIN" ]; then
  echo "uv not found on PATH; falling back to pip (slower)" >&2
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install -r requirements.txt
else
  echo "Using uv (timeout=${UV_HTTP_TIMEOUT}s concurrent_downloads=${UV_CONCURRENT_DOWNLOADS})"
  uv pip install --python "$VENV_DIR/bin/python" --upgrade pip setuptools wheel
  uv pip install --python "$VENV_DIR/bin/python" -r requirements.txt
fi

if [ ! -d tribev2 ]; then
  git clone https://github.com/facebookresearch/tribev2.git
  git -C tribev2 checkout 72399081ed3f1040c4d996cefb2864a4c46f5b8e
fi

# BrainDiff: vendored patch for upstream tribev2 (not in git). WhisperX env + CPU int8 + uvx --python.
PATCH_FILE="third_party/tribev2_patches/eventstransforms.py"
if [ -f "$PATCH_FILE" ]; then
  cp "$PATCH_FILE" tribev2/tribev2/eventstransforms.py
fi

# Pull the heaviest wheels first (torch ~60MB+). Fewer concurrent CDN streams = fewer stalls.
if [ -n "$UV_BIN" ]; then
  uv pip install --python "$VENV_DIR/bin/python" \
    "numpy==2.2.6" "torch>=2.5.1,<2.7" "torchvision>=0.20,<0.22"
  uv pip install --python "$VENV_DIR/bin/python" -e ./tribev2
else
  python -m pip install "numpy==2.2.6" "torch>=2.5.1,<2.7" "torchvision>=0.20,<0.22"
  python -m pip install -e ./tribev2
fi

# Install uv into the venv so uvx is on PATH for WhisperX subprocesses.
python -m pip install uv

echo "Local setup complete."
echo "Next steps: hf auth login  (or: export HF_TOKEN=...)  && ./scripts/preflight.sh && ./scripts/run_api.sh"
