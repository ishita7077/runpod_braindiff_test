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

## Notes
- Runtime device auto-detects: CUDA -> MPS -> CPU fallback.
- On Apple Silicon, the app will try MPS first and fall back to CPU only if needed.
- If the atlas cannot build an exact fsaverage -> fsaverage5 mapping locally, dev mode falls back to an approximate downsample and surfaces a warning. Set `BRAIN_DIFF_STRICT_ATLAS=1` to hard-fail instead.
- If preflight says Hugging Face access is missing, the app will not run inference until the token/access issue is fixed.
