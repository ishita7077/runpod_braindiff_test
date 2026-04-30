
from fastapi.testclient import TestClient

from backend import api
from backend.telemetry_store import TelemetryStore
from conftest import DummyTribeService, apply_api_test_stubs, dummy_masks


def _telemetry_masks():
    """Original telemetry fixture omitted memory_encoding; keep that behaviour by
    trimming the shared dummy_masks() helper so this test exercises the same
    mask set as before attention_salience / memory_encoding were added."""
    masks = dummy_masks()
    masks.pop("memory_encoding", None)
    masks.pop("attention_salience", None)
    return masks


def test_telemetry_records_and_surfaces_recent_runs(monkeypatch, tmp_path):
    apply_api_test_stubs(
        monkeypatch,
        api,
        tribe_service=DummyTribeService(
            runtime_backend="torch_cpu", events_ms=12, predict_ms=34
        ),
        masks=_telemetry_masks(),
        skip_startup=False,
    )
    monkeypatch.setattr(api, "telemetry_store", TelemetryStore(str(tmp_path / "telemetry.sqlite3")))

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
    assert payload["modality"] == "text"
    assert payload["modality_effective"] == "text"
    assert payload["result_analytics"]["critical_state"]["dimension"] == "personal_resonance"
    assert payload["result_analytics"]["pipeline_mix"]["dominant"] in {"predict", "score"}

    dashboard = client.get("/api/telemetry/dashboard")
    assert dashboard.status_code == 200
    dashboard_payload = dashboard.json()
    assert dashboard_payload["aggregate"]["total_runs"] == 1
    assert dashboard_payload["aggregate"]["success_count"] == 1
    assert dashboard_payload["aggregate"]["modality_counts"]["text"] == 1
    assert "per_modality" in dashboard_payload["aggregate"]
    assert dashboard_payload["aggregate"]["per_modality"]["text"]["total"] == 1
    assert "activity_by_day" in dashboard_payload["aggregate"]
    assert sum(dashboard_payload["aggregate"]["pipeline_mix_counts"].values()) == 1
    assert "critical_state_counts" in dashboard_payload["aggregate"]
