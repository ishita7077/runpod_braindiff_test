#!/usr/bin/env bash
set -euo pipefail

if [ ! -d ".venv" ]; then
  echo "Missing .venv. Create and install dependencies first."
  exit 1
fi

. ".venv/bin/activate"

python - <<'PY'
import json
import sys
from backend.brain_regions import build_vertex_masks
from backend.model_service import TribeService
from backend.preflight import build_preflight_report
import anyio

async def run():
    model_loaded = False
    masks_ready = False
    mask_error = None
    model_error = None
    runtime = None

    try:
        build_vertex_masks("atlases")
        masks_ready = True
    except Exception as err:
        mask_error = str(err)

    try:
        service = TribeService()
        service.load()
        model_loaded = True
        runtime = getattr(service, "runtime_profile", None)
    except Exception as err:
        model_error = str(err)

    runtime_payload = {"device": runtime.device, "backend": runtime.backend} if model_loaded and runtime else {}
    report = build_preflight_report(model_loaded=model_loaded, masks_ready=masks_ready, runtime=runtime_payload)
    if mask_error:
        report["mask_error"] = mask_error
    if model_error:
        report["model_error"] = model_error

    print(json.dumps(report))
    if not report["ok"]:
        sys.exit(2)

anyio.run(run)
PY

