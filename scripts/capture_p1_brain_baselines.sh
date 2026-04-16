#!/usr/bin/env bash
# TASK-00 style captures after P1 brain changes. Requires Chrome and a running API on :8000.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/frontend/baseline_screenshots/p1-3d"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
mkdir -p "$OUT"
BASE="${BRAIN_BASE_URL:-http://127.0.0.1:8000}"
TAG="${BRAIN_BASE_TAG:-p1}"

capture() {
  local w="$1" h="$2" path="$3" url="$4"
  "$CHROME" --headless --disable-gpu --window-size="${w},${h}" \
    --screenshot="$path" "$url"
}

# Desktop + narrow viewports (layout / shell QA)
capture 1440 2200 "$OUT/landing-${TAG}-1440.png" "${BASE}/"
capture 1440 2200 "$OUT/app-${TAG}-1440.png" "${BASE}/app.html"
capture 390 1800 "$OUT/landing-${TAG}-390.png" "${BASE}/"
capture 390 1800 "$OUT/app-${TAG}-390.png" "${BASE}/app.html"
capture 1440 2200 "$OUT/methodology-${TAG}-1440.png" "${BASE}/methodology.html"

echo "Wrote PNGs under $OUT"
