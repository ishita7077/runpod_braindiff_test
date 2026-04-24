FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt
RUN pip install runpod

COPY backend /app/backend
COPY atlases /app/atlases
COPY runpod_worker /app/runpod_worker

ENV BRAIN_DIFF_ATLAS_DIR=/app/atlases
ENV PYTHONPATH=/app

CMD ["python", "-u", "runpod_worker/handler.py"]
