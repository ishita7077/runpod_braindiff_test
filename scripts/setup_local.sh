#!/usr/bin/env bash
set -euo pipefail
# TRIBEv2 requires Python >=3.11
PYTHON_BIN=${PYTHON_BIN:-$(command -v python3.11 2>/dev/null || command -v python3)}
VENV_DIR=${VENV_DIR:-.venv}
$PYTHON_BIN -m venv "$VENV_DIR"
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
