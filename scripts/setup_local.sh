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
"$PYTHON_BIN" -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
if [ ! -d tribev2 ]; then
  git clone https://github.com/facebookresearch/tribev2.git
fi
python -m pip install -e ./tribev2
python -m pip install uv

echo "Local setup complete."
echo "Next steps: huggingface-cli login && ./scripts/preflight.sh && ./scripts/run_api.sh"
