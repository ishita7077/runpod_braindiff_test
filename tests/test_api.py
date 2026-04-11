import numpy as np
from fastapi.testclient import TestClient

from backend import api


class _DummyTribeService:
    model_revision = "facebook/tribev2@test"
    runtime_profile = type("Runtime", (), {"device": "cpu", "backend": "cpu"})()

    def text_to_predictions(self, text: str):
        base = np.zeros((6, 20484), dtype=np.float32)
        if "B" in text:
            base[:, :100] = 0.05
        else:
            base[:, :100] = 0.01
        return base, [], {"events_ms": 1, "predict_ms": 2}


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


def test_api_sync_shape(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
    )

    client = TestClient(api.app)
    response = client.post("/api/diff", json={"text_a": "Version A", "text_b": "Version B"})
    assert response.status_code == 200
    payload = response.json()
    assert "diff" in payload
    assert "dimensions" in payload
    assert "insights" in payload
    assert payload["insights"]["headline"]
    assert len(payload["vertex_delta"]) == 20484
    assert payload["meta"]["atlas"] == "HCP_MMP1.0"
    assert "atlas_peak" in payload["meta"]


def test_api_ready_reports_skip_startup(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "masks", _dummy_masks())
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


def test_brain_mesh_endpoint_uses_payload_builder(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "masks", _dummy_masks())
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
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
    )
    client = TestClient(api.app)

    invalid = client.post("/api/diff", json={"text_a": "", "text_b": "x"})
    assert invalid.status_code == 422

    payload = client.post("/api/diff", json={"text_a": "A", "text_b": "BBBBBBBBBBBBBBBBBBBB"}).json()
    assert any("Very short text" in warning for warning in payload["warnings"])
    assert any("Large length difference" in warning for warning in payload["warnings"])


def test_api_error_code_mapping(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")

    class _FailingService:
        model_revision = "facebook/tribev2@test"

        def text_to_predictions(self, text: str):
            raise RuntimeError("HF_AUTH_REQUIRED: Access required")

    monkeypatch.setattr(api, "tribe_service", _FailingService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
    )
    client = TestClient(api.app)
    response = client.post("/api/diff", json={"text_a": "A content", "text_b": "B content"})
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "HF_AUTH_REQUIRED"


def test_preflight_endpoint(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(api.tribe_service, "model", object())

    client = TestClient(api.app)
    response = client.get("/api/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert "ok" in payload
    assert "blockers" in payload


def test_preflight_returns_runtime_and_limits(monkeypatch):
    """Preflight must include runtime, text_backend_strategy, and limits."""
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "masks", _dummy_masks())
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

    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "masks", _dummy_masks())
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
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
    )

    client = TestClient(api.app)
    response = client.post("/api/diff", json={"text_a": "Version A text here", "text_b": "Version B text here"})
    assert response.status_code == 200
    assert "diff" in response.json()


def test_identical_texts_have_zero_delta(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
    )
    client = TestClient(api.app)
    response = client.post("/api/diff", json={"text_a": "Same text", "text_b": "Same text"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["identical_text_short_circuit"] is True
    for dim_payload in payload["diff"].values():
        assert dim_payload["delta"] == 0.0


def test_api_accepts_unicode_emoji_and_url_inputs(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
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
    assert len(payload["dimensions"]) == 5


def test_text_length_bounds(monkeypatch):
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setattr(api, "tribe_service", _DummyTribeService())
    monkeypatch.setattr(api, "masks", _dummy_masks())
    monkeypatch.setattr(
        api,
        "generate_heatmap_artifact",
        lambda vertex_delta: {"format": "png_base64", "image_base64": "x"},
    )
    client = TestClient(api.app)
    valid = client.post("/api/diff", json={"text_a": "a" * 5000, "text_b": "b" * 5000})
    assert valid.status_code == 200
    invalid = client.post("/api/diff", json={"text_a": "a" * 5001, "text_b": "b" * 5000})
    assert invalid.status_code == 422

