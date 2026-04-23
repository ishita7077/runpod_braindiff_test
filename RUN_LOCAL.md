# Run BrainDiff locally

1. Create the local environment and install everything:

```bash
./scripts/setup_local.sh
```

2. Activate the environment:

```bash
source .venv/bin/activate
```

3. Log into Hugging Face with a token that has access to `meta-llama/Llama-3.2-3B`:

```bash
huggingface-cli login
```

4. Run preflight:

```bash
./scripts/preflight.sh
```

5. Start the API + frontend:

```bash
./scripts/run_api.sh
```

6. Open:

```text
http://localhost:8000
```

## Tests

```bash
BRAIN_DIFF_SKIP_STARTUP=1 PYTHONPATH=. .venv/bin/pytest tests/ -q
```

- Default suite includes a fast `test_tribe_model_loads_from_hub` (loads weights, no WhisperX).
- Full predict + WhisperX smoke: `TRIBEV2_E2E_PREDICT=1 PYTHONPATH=. .venv/bin/pytest tests/test_model_smoke.py -k predicts` (slow).

## Notes

- **Device selection is automatic:** NVIDIA CUDA if available, else **Apple MPS** on macOS when available, else CPU. To force a specific backend (e.g. debugging), set `BRAIN_DIFF_DEVICE` to `cuda`, `mps`, or `cpu`.
- **WhisperX** uses **CTranslate2**, which supports **`cuda` and `cpu` only** (no Apple MPS). On Apple Silicon, transcription runs on **CPU** while TRIBEv2 encoders still use **MPS** via `accelerate`. Set `TRIBEV2_WHISPERX_DEVICE=cuda` only on NVIDIA; otherwise leave unset or use `cpu`.
- **`pip install accelerate`** is required: Llama loads with `device_map="auto"` from Hugging Face **Transformers**, which errors without the **`accelerate`** package (see preflight `accelerate` field).
- **Apple Silicon:** `BRAIN_DIFF_LLAMA_ON_CPU` defaults to **`1`** (Llama weights on CPU; TRIBEv2 brain + audio still on MPS). Set to **`0`** to try MPS split (`BRAIN_DIFF_MPS_TEXT_MAX_MEMORY`, default `2500MiB`). Full fp32 on MPS: `BRAIN_DIFF_MPS_LLAMA_FP32_FULL=1` (needs headroom).
- **Warm cache before users arrive:** `BRAIN_DIFF_STARTUP_WARMUP=1` runs one short text through the full pipeline at startup (slow; `scripts/run_api.sh` defaults this to `1`; set `BRAIN_DIFF_STARTUP_WARMUP=0` to skip).
- **Readiness:** `GET /api/ready` returns `model_loaded`, `masks_ready`, `warmup_*`, and `startup_skipped` (true when `BRAIN_DIFF_SKIP_STARTUP=1`).
- **Logs / latency:** Server log file `logs/braindiff.log` (plus stderr). Each successful diff includes `meta.stage_times` (`events_*_ms`, `predict_*_ms`, `score_diff_ms`, `heatmap_ms`) for where time went.
- **Insight tone:** `BRAIN_DIFF_NARRATIVE_TONE=sober` (default) or `punchy` for alternate headline voice.
- **HTTP e2e smoke:** With the API already running (`./scripts/run_api.sh`), run `BRAIN_DIFF_E2E_BASE=http://127.0.0.1:8000 .venv/bin/python scripts/e2e_diff_http.py` (timeout `BRAIN_DIFF_E2E_TIMEOUT`, default 1200s). The script checks `/api/preflight`, `/api/ready`, `/api/brain-mesh`, then an async diff job. Quick path: `BRAIN_DIFF_E2E_FAST=1` (identical texts → short-circuit, no Whisper/Llama). First `/api/brain-mesh` may take minutes while nilearn caches fsaverage5; override wait with `BRAIN_DIFF_E2E_BRAIN_MESH_TIMEOUT`.
- **WhisperX cold start:** Optional one-time `uvx whisperx --help` (or a tiny transcription) so the `uvx` environment is resolved before the first user hits the audio path.
- If the atlas cannot build an exact fsaverage → fsaverage5 mapping locally, dev mode falls back to an approximate downsample and surfaces a warning. Set `BRAIN_DIFF_STRICT_ATLAS=1` to hard-fail instead.
- If preflight says Hugging Face access is missing, inference will not run until the token/access issue is fixed.
- WhisperX runs via `uvx`; ensure `uv` is installed (`pip install uv` in the venv adds `uvx` on PATH).
- Optional tuning: `TRIBEV2_WHISPERX_MODEL`, `TRIBEV2_WHISPERX_DEVICE`, `TRIBEV2_WHISPERX_BATCH_SIZE`, `TRIBEV2_NUM_WORKERS` (see `backend/model_service.py` and `tribev2/tribev2/eventstransforms.py` / `grids/defaults.py`).
