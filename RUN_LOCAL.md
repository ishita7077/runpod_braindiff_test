# Run Brain Diff locally

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
- Full predict + WhisperX smoke: `TRIBEV2_E2E_PREDICT=1 PYTHONPATH=. .venv/bin/pytest tests/test_model_smoke.py -k predicts` (slow; best on Linux+CUDA).

## Notes

- Runtime device auto-detects: CUDA → MPS (Apple Silicon) → CPU fallback. Override with `BRAIN_DIFF_DEVICE=cpu` if needed.
- On Apple Silicon, the app tries MPS first and falls back to CPU only if needed.
- If the atlas cannot build an exact fsaverage → fsaverage5 mapping locally, dev mode falls back to an approximate downsample and surfaces a warning. Set `BRAIN_DIFF_STRICT_ATLAS=1` to hard-fail instead.
- If preflight says Hugging Face access is missing, inference will not run until the token/access issue is fixed.
- WhisperX runs via `uvx`; ensure `uv` is installed (`pip install uv` in the venv adds `uvx` on PATH).
- Optional tuning: `TRIBEV2_WHISPERX_MODEL`, `TRIBEV2_WHISPERX_BATCH_SIZE`, `TRIBEV2_NUM_WORKERS` (see `backend/model_service.py` and `tribev2/tribev2/grids/defaults.py`).
