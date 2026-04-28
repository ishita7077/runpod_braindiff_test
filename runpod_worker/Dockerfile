FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# ── Step 1: tribev2 ────────────────────────────────────────────────────────────
# Install from the exact commit captured in requirements_frozen.txt.
# This transitively brings: neuralset 0.0.2, neuraltrain 0.0.2, torch 2.6,
# numpy 2.2.6, torchvision 0.21, transformers, spacy, gtts, langdetect,
# huggingface_hub, moviepy, soundfile, etc.
RUN pip install \
    "git+https://github.com/facebookresearch/tribev2.git@72399081ed3f1040c4d996cefb2864a4c46f5b8e#egg=tribev2"

# ── Step 2: remaining backend packages ────────────────────────────────────────
# Use the frozen requirements as the single source of truth for all version pins.
# Drop the editable (-e) tribev2 line — it's already installed above.
COPY backend/requirements_frozen.txt /app/requirements_frozen.txt
RUN grep -v "^-e " /app/requirements_frozen.txt | pip install -r /dev/stdin

# ── Step 3: whisperx ──────────────────────────────────────────────────────────
# tribev2's eventstransforms.py transcribes audio by running:
#   sys.executable -m whisperx <wav> ...
# whisperx must therefore be pip-installed in the same Python environment.
RUN pip install whisperx

# ── Step 4: RunPod serverless SDK ─────────────────────────────────────────────
RUN pip install runpod

# ── Application code ──────────────────────────────────────────────────────────
COPY backend /app/backend
COPY atlases /app/atlases
COPY runpod_worker /app/runpod_worker

ENV BRAIN_DIFF_ATLAS_DIR=/app/atlases
ENV PYTHONPATH=/app

CMD ["python", "-u", "runpod_worker/handler.py"]
