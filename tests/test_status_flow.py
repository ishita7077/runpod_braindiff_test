import time

import numpy as np
from fastapi.testclient import TestClient

from backend import api


class _DummyTribeService:
    model_revision = "facebook/tribev2@test"

    def text_to_predictions(self, text: str, progress=None):
        if progress is not None:
            progress.emit("synthesizing_speech", "Synthesising speech...")
            progress.emit("predicting", "Encoding through TRIBE v2...")
        base = np.zeros((6, 20484), dtype=np.float32)
        if "B" in text:
            base[:, :100] = 0.05
        else:
            base[:, :100] = 0.01
        return base, [], {
            "events_ms": 1,
            "predict_ms": 2,
            "transcript_text": text,
            "transcript_segments": [],
        }


def _dummy_masks():
    mask = np.zeros(20484, dtype=bool)
    mask[:100] = True
    empty = np.zeros(20484, dtype=bool)
    empty[100:200] = True
    return {
        "personal_resonance": {"mask": mask},
        "social_thinking": {"mask": empty},
        "brain_effort": {"mask": empty},
        "language_depth": {"mask": empty},
        "gut_reaction": {"mask": empty},
        "memory_encoding": {"mask": empty},
        "attention_salience": {"mask": empty},
    }


def test_async_status_progression(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
    )
    client = TestClient(api.app)

    start = client.post("/api/diff/start", json={"text_a": "Version A", "text_b": "Version B"})
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    deadline = time.time() + 5.0
    last = None
    while time.time() < deadline:
        status = client.get(f"/api/diff/status/{job_id}")
        assert status.status_code == 200
        last = status.json()
        if last["status"] in {"done", "error"}:
            break
        time.sleep(0.05)

    assert last is not None
    assert last["status"] == "done"
    statuses = [event["status"] for event in last["events"]]
    required = [
        "synthesizing_speech",
        "predicting_version_a",
        "predicting_version_b",
        "computing_brain_contrast",
    ]
    for item in required:
        assert item in statuses
    assert statuses.index("predicting_version_a") < statuses.index("predicting_version_b")


def test_rapid_submissions_complete_without_conflict(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
    )
    client = TestClient(api.app)

    start_a = client.post("/api/diff/start", json={"text_a": "Version A 1", "text_b": "Version B 1"})
    start_b = client.post("/api/diff/start", json={"text_a": "Version A 2", "text_b": "Version B 2"})
    assert start_a.status_code == 200
    assert start_b.status_code == 200
    job_ids = [start_a.json()["job_id"], start_b.json()["job_id"]]
    assert job_ids[0] != job_ids[1]

    deadline = time.time() + 5.0
    terminal = {}
    while time.time() < deadline and len(terminal) < 2:
        for job_id in job_ids:
            if job_id in terminal:
                continue
            status = client.get(f"/api/diff/status/{job_id}")
            assert status.status_code == 200
            payload = status.json()
            if payload["status"] in {"done", "error"}:
                terminal[job_id] = payload["status"]
        time.sleep(0.05)

    assert terminal.get(job_ids[0]) == "done"
    assert terminal.get(job_ids[1]) == "done"

