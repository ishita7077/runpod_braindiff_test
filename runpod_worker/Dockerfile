FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── uv / uvx ──────────────────────────────────────────────────────────────────
# tribev2's text pipeline calls `uvx` as a subprocess (eventstransforms.py).
# Install uv via its official installer so both `uv` and `uvx` land at
# /root/.local/bin and are available system-wide.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

RUN pip install --upgrade pip

# ── Single combined pip install ────────────────────────────────────────────────
# WHY one RUN command?
#   If we split into separate RUN steps, pip installs torch once for whisperx
#   (~3 GB), again for frozen requirements (~3 GB upgrade), and the GitHub
#   Actions runner runs out of disk space (Errno 28).  By doing all installs in
#   ONE step the pip resolver sees every constraint at once and only ever
#   downloads each wheel once.
#
# Install order:
#   1. whisperx — establishes its torch/torchaudio lower bounds first
#   2. frozen requirements — pins everything (torch 2.6.0, numpy 2.2.6, etc.),
#      overriding what whisperx just pulled; pip upgrades in-place so the wheel
#      is only on disk once at the end.
#   3. tribev2 git install — its deps are already satisfied by the frozen reqs
#   4. runpod — small SDK, installed last so its version is never overridden
#
# The editable (-e) line for tribev2 is removed from frozen reqs with grep
# because we install it properly via git+ in step 3.

COPY backend/requirements_frozen.txt /app/requirements_frozen.txt

RUN pip install whisperx && \
    grep -v "^-e " /app/requirements_frozen.txt | pip install --upgrade -r /dev/stdin && \
    pip install \
        "git+https://github.com/facebookresearch/tribev2.git@72399081ed3f1040c4d996cefb2864a4c46f5b8e#egg=tribev2" && \
    pip install runpod

# ── Application code ──────────────────────────────────────────────────────────
COPY backend /app/backend
COPY atlases /app/atlases
COPY runpod_worker /app/runpod_worker

ENV BRAIN_DIFF_ATLAS_DIR=/app/atlases
ENV PYTHONPATH=/app

CMD ["python", "-u", "runpod_worker/handler.py"]
