#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN=${PYTHON_BIN:-python3}
VENV_DIR=${VENV_DIR:-.venv}

$PYTHON_BIN -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

if [ ! -d tribev2 ]; then
  git clone https://github.com/facebookresearch/tribev2.git
fi
python -m pip install -e ./tribev2

echo ""
echo "Local setup complete."
echo "Next steps:"
echo "  1) huggingface-cli login"
echo "  2) ./scripts/preflight.sh"
echo "  3) ./scripts/run_api.sh"
