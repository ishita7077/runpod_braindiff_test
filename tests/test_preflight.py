"""Tests for preflight report logic."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.preflight import build_preflight_report


def _report(runtime_backend: str = "cpu", accelerate_ok: bool = True, **kwargs):
    """Build a preflight report with stubbed checks."""
    runtime = {"device": runtime_backend, "backend": runtime_backend}
    with (
        patch("backend.preflight.check_ffmpeg", return_value=(True, "/usr/bin/ffmpeg")),
        patch("backend.preflight.check_hf_gated_access", return_value=(True, "token_present_unverified")),
        patch("backend.preflight.check_uvx", return_value=(True, "/usr/bin/uvx")),
        patch(
            "backend.preflight.check_accelerate",
            return_value=(accelerate_ok, "0.34.0" if accelerate_ok else "accelerate not installed"),
        ),
    ):
        return build_preflight_report(
            model_loaded=True,
            masks_ready=True,
            runtime=runtime,
            **kwargs,
        )


class TestAccelerateBlocker:
    def test_accelerate_missing_not_blocker_on_cpu(self):
        report = _report(runtime_backend="cpu", accelerate_ok=False)
        assert "accelerate_missing" not in report["blockers"]
        assert report["ok"] is True

    def test_accelerate_missing_is_blocker_on_mps(self):
        report = _report(runtime_backend="mps", accelerate_ok=False)
        assert "accelerate_missing" in report["blockers"]
        assert report["ok"] is False

    def test_accelerate_present_never_blocks(self):
        for backend in ("cpu", "mps", "cuda"):
            report = _report(runtime_backend=backend, accelerate_ok=True)
            assert "accelerate_missing" not in report["blockers"]

    def test_accelerate_required_flag_on_mps(self):
        report = _report(runtime_backend="mps", accelerate_ok=False)
        assert report["accelerate"]["required"] is True

    def test_accelerate_required_flag_false_on_cpu(self):
        report = _report(runtime_backend="cpu", accelerate_ok=False)
        assert report["accelerate"]["required"] is False


class TestPreflightFields:
    def test_runtime_included(self):
        report = _report(runtime_backend="mps")
        assert report["runtime"]["backend"] == "mps"
        assert "device" in report["runtime"]

    def test_text_backend_strategy_included(self):
        report = _report(text_backend_strategy="mps_split")
        assert report["text_backend_strategy"] == "mps_split"

    def test_text_backend_strategy_unknown_when_not_set(self):
        report = _report()
        assert report["text_backend_strategy"] == "unknown"

    def test_limits_included(self):
        report = _report(slow_notice_ms=180_000, hard_timeout_ms=1_200_000, max_concurrent_jobs=1)
        limits = report["limits"]
        assert limits["slow_notice_ms"] == 180_000
        assert limits["hard_timeout_ms"] == 1_200_000
        assert limits["max_concurrent_jobs"] == 1

    def test_effective_whisper_defaults_included(self, monkeypatch):
        monkeypatch.setenv("TRIBEV2_WHISPERX_DEVICE", "cpu")
        monkeypatch.setenv("TRIBEV2_WHISPERX_MODEL", "tiny.en")
        report = _report()
        assert report["effective_whisper_defaults"]["device"] == "cpu"
        assert report["effective_whisper_defaults"]["model"] == "tiny.en"

    def test_hf_access_wording_is_honest(self):
        report = _report()
        # Must not claim "verified" — only "token_present_unverified" or similar.
        detail = report["hf_gated_model_access"]["detail"]
        assert "verified" not in detail or "unverified" in detail

    def test_ok_true_when_all_checks_pass(self):
        report = _report(runtime_backend="cpu", accelerate_ok=True)
        assert report["ok"] is True
        assert report["blockers"] == []

    def test_ok_false_when_model_not_loaded(self):
        with (
            patch("backend.preflight.check_ffmpeg", return_value=(True, "")),
            patch("backend.preflight.check_hf_gated_access", return_value=(True, "token_present_unverified")),
            patch("backend.preflight.check_uvx", return_value=(True, "")),
            patch("backend.preflight.check_accelerate", return_value=(True, "ok")),
        ):
            report = build_preflight_report(model_loaded=False, masks_ready=True)
        assert report["ok"] is False
        assert "model_not_loaded" in report["blockers"]
