import base64

import numpy as np
from fastapi.testclient import TestClient

from backend import api
from conftest import DummyTribeService, apply_api_test_stubs, dummy_masks


def _decode_f32_b64(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=np.float32)


def test_api_sync_shape(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )

    client = TestClient(api.app)
    response = client.post("/api/diff", json={"text_a": "Version A", "text_b": "Version B"})
    assert response.status_code == 200
    payload = response.json()
    assert "diff" in payload
    expected_dims = len(dummy_masks())
    assert len(payload["diff"]) == expected_dims
    assert "dimensions" in payload
    assert len(payload["dimensions"]) == expected_dims
    assert "insights" in payload
    assert payload["insights"]["headline"]
    assert _decode_f32_b64(payload["vertex_delta_b64"]).shape == (20484,)
    assert _decode_f32_b64(payload["vertex_a_b64"]).shape == (20484,)
    assert _decode_f32_b64(payload["vertex_b_b64"]).shape == (20484,)
    assert payload["meta"]["atlas"] == "HCP_MMP1.0"
    assert payload["meta"]["dimensions_count"] == expected_dims
    assert "atlas_peak" in payload["meta"]
    for dim_payload in payload["diff"].values():
        assert "timeseries_a" in dim_payload
        assert "timeseries_b" in dim_payload


def test_api_ready_reports_skip_startup(monkeypatch):
    apply_api_test_stubs(monkeypatch, api, masks=dummy_masks(), stub_heatmap=False)
    monkeypatch.setattr(api.tribe_service, "model", object())

    # Context manager runs ASGI lifespan so _initialize_app sees BRAIN_DIFF_SKIP_STARTUP.
    with TestClient(api.app) as client:
        response = client.get("/api/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["startup_skipped"] is True
    assert body["ok"] is False
    assert "warmup_requested" in body
    assert "runtime" in body


def test_dimension_masks_endpoint(monkeypatch):
    apply_api_test_stubs(monkeypatch, api, masks=dummy_masks(), stub_heatmap=False)
    client = TestClient(api.app)
    response = client.get("/api/dimension-masks")
    assert response.status_code == 200
    body = response.json()
    assert "personal_resonance" in body
    decoded = np.frombuffer(base64.b64decode(body["personal_resonance"]), dtype=np.uint8)
    assert decoded.shape == (20484,)
    assert decoded.dtype == np.uint8


def test_brain_mesh_endpoint_uses_payload_builder(monkeypatch):
    apply_api_test_stubs(monkeypatch, api, masks=dummy_masks(), stub_heatmap=False)
    monkeypatch.setattr(api.tribe_service, "model", object())
    fake_mesh = {
        "format": "fsaverage5_pial",
        "lh_coord": [0.0, 0.0, 0.0],
        "lh_faces": [0, 1, 2],
        "rh_coord": [1.0, 0.0, 0.0],
        "rh_faces": [0, 1, 2],
    }
    monkeypatch.setattr("backend.brain_mesh.build_brain_mesh_payload", lambda **kwargs: fake_mesh)

    with TestClient(api.app) as client:
        response = client.get("/api/brain-mesh")
    assert response.status_code == 200
    assert response.json() == fake_mesh


def test_api_validation_and_warnings(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)

    invalid = client.post("/api/diff", json={"text_a": "", "text_b": "x"})
    assert invalid.status_code == 422

    payload = client.post("/api/diff", json={"text_a": "A", "text_b": "BBBBBBBBBBBBBBBBBBBB"}).json()
    assert any("Very short text" in warning for warning in payload["warnings"])
    assert any("Large length difference" in warning for warning in payload["warnings"])


def test_api_error_code_mapping(monkeypatch):
    class _FailingService:
        model_revision = "facebook/tribev2@test"

        def text_to_predictions(self, text: str, progress=None):
            raise RuntimeError("HF_AUTH_REQUIRED: Access required")

    apply_api_test_stubs(
        monkeypatch, api, tribe_service=_FailingService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    response = client.post("/api/diff", json={"text_a": "A content", "text_b": "B content"})
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "HF_AUTH_REQUIRED"


def test_preflight_endpoint(monkeypatch):
    apply_api_test_stubs(monkeypatch, api, masks=dummy_masks(), stub_heatmap=False)
    monkeypatch.setattr(api.tribe_service, "model", object())

    client = TestClient(api.app)
    response = client.get("/api/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert "ok" in payload
    assert "blockers" in payload


def test_preflight_returns_runtime_and_limits(monkeypatch):
    """Preflight must include runtime, text_backend_strategy, and limits."""
    apply_api_test_stubs(monkeypatch, api, masks=dummy_masks(), stub_heatmap=False)
    monkeypatch.setattr(api.tribe_service, "model", object())

    client = TestClient(api.app)
    response = client.get("/api/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert "runtime" in payload
    assert "text_backend_strategy" in payload
    limits = payload.get("limits", {})
    assert "slow_notice_ms" in limits
    assert "hard_timeout_ms" in limits
    assert limits["hard_timeout_ms"] == api.HARD_TIMEOUT_MS
    assert limits["slow_notice_ms"] == api.SLOW_NOTICE_MS


def test_preflight_cpu_runtime_accelerate_not_a_blocker(monkeypatch):
    """On cpu runtime, missing accelerate must NOT appear in blockers."""
    import backend.preflight as pf

    apply_api_test_stubs(monkeypatch, api, masks=dummy_masks(), stub_heatmap=False)
    monkeypatch.setattr(api.tribe_service, "model", object())
    # Simulate cpu runtime profile.
    from backend.runtime import _profile_for_device
    monkeypatch.setattr(api.tribe_service, "runtime_profile", _profile_for_device("cpu"))
    # Simulate accelerate missing.
    monkeypatch.setattr(pf, "check_accelerate", lambda: (False, "accelerate not installed"))

    client = TestClient(api.app)
    response = client.get("/api/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert "accelerate_missing" not in payload["blockers"]


def test_api_works_on_cpu_when_accelerate_unavailable(monkeypatch):
    """Diff jobs must succeed on cpu runtime even when accelerate is not installed."""
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )

    client = TestClient(api.app)
    response = client.post("/api/diff", json={"text_a": "Version A text here", "text_b": "Version B text here"})
    assert response.status_code == 200
    assert "diff" in response.json()


def test_identical_texts_have_zero_delta(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    response = client.post("/api/diff", json={"text_a": "Same text", "text_b": "Same text"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["identical_text_short_circuit"] is True
    for dim_payload in payload["diff"].values():
        assert dim_payload["delta"] == 0.0


def test_api_accepts_unicode_emoji_and_url_inputs(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    response = client.post(
        "/api/diff",
        json={
            "text_a": "Hola mundo 😊 https://example.com/noticia",
            "text_b": "Namaste duniya 🚀 https://example.org/update",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["dimensions"]) == len(dummy_masks())


def test_text_length_bounds(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    valid = client.post("/api/diff", json={"text_a": "a" * 5000, "text_b": "b" * 5000})
    assert valid.status_code == 200
    invalid = client.post("/api/diff", json={"text_a": "a" * 5001, "text_b": "b" * 5000})
    assert invalid.status_code == 422


def test_report_endpoint_returns_summary(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    response = client.post(
        "/api/report",
        json={
            "pairs": [
                {"label": "one", "text_a": "Version A", "text_b": "Version B"},
                {"label": "two", "text_a": "A draft", "text_b": "B draft"},
                {"label": "three", "text_a": "A", "text_b": "B"},
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 3
    assert payload["summary"]["total_pairs"] == 3
    assert "personal_resonance" in payload["summary"]["dimension_summary"]


def test_report_endpoint_rejects_too_many_pairs(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    pairs = [{"label": str(i), "text_a": "A", "text_b": "B"} for i in range(21)]
    response = client.post("/api/report", json={"pairs": pairs})
    assert response.status_code in (400, 422)


def test_report_endpoint_rejects_empty_text(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    response = client.post("/api/report", json={"pairs": [{"label": "bad", "text_a": "", "text_b": "B"}]})
    assert response.status_code in (400, 422)

