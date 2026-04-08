
from fastapi.testclient import TestClient
import numpy as np

from backend import api
from backend.telemetry_store import TelemetryStore


class _DummyTribeService:
    model_revision = "facebook/tribev2@test"
    runtime_profile = type("Runtime", (), {"device": "cpu", "backend": "torch_cpu"})()

    def text_to_predictions(self, text: str):
        base = np.zeros((6, 20484), dtype=np.float32)
        if "B" in text:
            base[:, :100] = 0.05
        else:
            base[:, :100] = 0.01
        return base, [], {"events_ms": 12, "predict_ms": 34}


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
    }


def test_telemetry_records_and_surfaces_recent_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(api, "telemetry_store", TelemetryStore(str(tmp_path / "telemetry.sqlite3")))
    monkeypatch.setattr(api, "generate_heatmap_artifact", lambda vertex_delta: {"format": "png_base64", "image_base64": "x"})

    client = TestClient(api.app)
    start = client.post("/api/diff/start", json={"text_a": "Version A", "text_b": "Version B"})
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    import time
    for _ in range(50):
        status = client.get(f"/api/diff/status/{job_id}")
        assert status.status_code == 200
        payload = status.json()
        if payload["status"] == "done":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("job did not finish")

    recent = client.get("/api/telemetry/recent")
    assert recent.status_code == 200
    runs = recent.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["job_id"] == job_id
    assert runs[0]["stage_times"]["events_a_ms"] == 12
    assert runs[0]["runtime"]["backend"] == "torch_cpu"

    one = client.get(f"/api/telemetry/run/{job_id}")
    assert one.status_code == 200
    payload = one.json()
    assert payload["job_id"] == job_id
    assert payload["success"] is True
