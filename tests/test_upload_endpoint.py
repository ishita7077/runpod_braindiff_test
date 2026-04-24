"""Contract tests for /api/diff/upload."""
import io

from fastapi.testclient import TestClient

from backend import api
from conftest import DummyTribeService, apply_api_test_stubs, dummy_masks


def test_upload_rejects_mixed_modality(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    response = client.post(
        "/api/diff/upload",
        files={
            "file_a": ("a.wav", io.BytesIO(b"\x00" * 16), "audio/wav"),
            "file_b": ("b.mp4", io.BytesIO(b"\x00" * 16), "video/mp4"),
        },
    )
    assert response.status_code == 400
    assert "same modality" in response.json()["detail"].lower()


def test_upload_rejects_unsupported_extension(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    response = client.post(
        "/api/diff/upload",
        files={
            "file_a": ("a.xyz", io.BytesIO(b"\x00"), "application/octet-stream"),
            "file_b": ("b.xyz", io.BytesIO(b"\x00"), "application/octet-stream"),
        },
    )
    assert response.status_code == 400
    assert "unsupported file extension" in response.json()["detail"].lower()


def test_upload_accepts_two_audio_files_returns_job_payload(monkeypatch):
    apply_api_test_stubs(
        monkeypatch, api, tribe_service=DummyTribeService(), masks=dummy_masks()
    )
    client = TestClient(api.app)
    response = client.post(
        "/api/diff/upload",
        files={
            "file_a": ("a.wav", io.BytesIO(b"\x00" * 1024), "audio/wav"),
            "file_b": ("b.wav", io.BytesIO(b"\x00" * 1024), "audio/wav"),
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert "job_id" in payload
    assert payload["status"] == "queued"
