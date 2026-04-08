#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  echo "Missing .venv. Create and install dependencies first."
  exit 1
fi

. ".venv/bin/activate"

echo "[1/4] Running preflight report..."
if ! bash "scripts/preflight.sh"; then
  echo "Preflight failed. Resolve blockers before continuing."
  exit 2
fi

echo "[2/4] Running core non-gated tests..."
python -m pytest \
  "tests/test_install.py" \
  "tests/test_masks_nonzero.py" \
  "tests/test_signed_diff.py" \
  "tests/test_heatmap_basis.py" \
  "tests/test_api.py" \
  "tests/test_status_flow.py" \
  "tests/test_atlas_labels.py" \
  "tests/test_scoring.py" -q

echo "[3/4] Running model smoke test..."
python -m pytest "tests/test_model_smoke.py" -q

if [ "${RUN_TRIBEV2_SANITY:-0}" = "1" ]; then
  echo "[4/4] Running full sanity-pair gate..."
  python -m pytest "tests/test_sanity_pairs.py" -q
else
  echo "[4/4] Skipping full sanity-pair gate (set RUN_TRIBEV2_SANITY=1 to enable)."
fi

echo "All requested checks completed."

