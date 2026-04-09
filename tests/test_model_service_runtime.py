"""Tests for model_service runtime resolution logic."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from backend.model_service import _apply_text_backend_strategy, _configure_whisper_defaults, _resolve_text_backend_strategy
from backend.runtime import RuntimeProfile, _profile_for_device

_MPS_PROFILE = _profile_for_device("mps")
_CPU_PROFILE = _profile_for_device("cpu")
_CUDA_PROFILE = _profile_for_device("cuda")

_16GIB = 16 * 1024**3
_8GIB = 8 * 1024**3


def _mock_psutil(total_bytes: int):
    mem = MagicMock()
    mem.total = total_bytes
    return MagicMock(virtual_memory=MagicMock(return_value=mem))


class TestResolveTextBackendStrategy:
    def test_mps_high_ram_picks_mps_split(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_TEXT_BACKEND", raising=False)
        with patch("backend.model_service.psutil", _mock_psutil(_16GIB)):
            strategy = _resolve_text_backend_strategy(_MPS_PROFILE)
        assert strategy == "mps_split"

    def test_mps_low_ram_picks_cpu(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_TEXT_BACKEND", raising=False)
        with patch("backend.model_service.psutil", _mock_psutil(_8GIB)):
            strategy = _resolve_text_backend_strategy(_MPS_PROFILE)
        assert strategy == "cpu"

    def test_cpu_profile_always_cpu(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_TEXT_BACKEND", raising=False)
        strategy = _resolve_text_backend_strategy(_CPU_PROFILE)
        assert strategy == "cpu"

    def test_cuda_profile_always_cpu(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_TEXT_BACKEND", raising=False)
        strategy = _resolve_text_backend_strategy(_CUDA_PROFILE)
        assert strategy == "cpu"

    def test_explicit_env_cpu(self, monkeypatch):
        monkeypatch.setenv("BRAIN_DIFF_TEXT_BACKEND", "cpu")
        strategy = _resolve_text_backend_strategy(_MPS_PROFILE)
        assert strategy == "cpu"

    def test_explicit_env_mps_split(self, monkeypatch):
        monkeypatch.setenv("BRAIN_DIFF_TEXT_BACKEND", "mps_split")
        strategy = _resolve_text_backend_strategy(_CPU_PROFILE)
        assert strategy == "mps_split"

    def test_explicit_env_mps_full_fp32(self, monkeypatch):
        monkeypatch.setenv("BRAIN_DIFF_TEXT_BACKEND", "mps_full_fp32")
        strategy = _resolve_text_backend_strategy(_MPS_PROFILE)
        assert strategy == "mps_full_fp32"

    def test_explicit_env_auto_defers_to_ram(self, monkeypatch):
        monkeypatch.setenv("BRAIN_DIFF_TEXT_BACKEND", "auto")
        with patch("backend.model_service.psutil", _mock_psutil(_16GIB)):
            strategy = _resolve_text_backend_strategy(_MPS_PROFILE)
        assert strategy == "mps_split"

    def test_psutil_unavailable_falls_back_to_cpu(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_TEXT_BACKEND", raising=False)
        import backend.model_service as ms
        monkeypatch.setattr(ms, "psutil", None)
        strategy = _resolve_text_backend_strategy(_MPS_PROFILE)
        assert strategy == "cpu"


class TestApplyTextBackendStrategy:
    def test_cpu_sets_llama_on_cpu(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY", raising=False)
        _apply_text_backend_strategy("cpu")
        assert os.environ["BRAIN_DIFF_LLAMA_ON_CPU"] == "1"
        assert os.environ["BRAIN_DIFF_MPS_LLAMA_FP32_FULL"] == "0"

    def test_mps_split_clears_llama_on_cpu(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY", raising=False)
        with patch("backend.model_service.psutil", _mock_psutil(_16GIB)):
            _apply_text_backend_strategy("mps_split")
        assert os.environ["BRAIN_DIFF_LLAMA_ON_CPU"] == "0"
        assert os.environ["BRAIN_DIFF_MPS_LLAMA_FP32_FULL"] == "0"

    def test_mps_split_high_ram_sets_3500_cap(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY", raising=False)
        with patch("backend.model_service.psutil", _mock_psutil(_16GIB)):
            _apply_text_backend_strategy("mps_split")
        assert os.environ.get("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY") == "3500MiB"

    def test_mps_split_low_ram_sets_2500_cap(self, monkeypatch):
        monkeypatch.delenv("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY", raising=False)
        with patch("backend.model_service.psutil", _mock_psutil(_8GIB)):
            _apply_text_backend_strategy("mps_split")
        assert os.environ.get("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY") == "2500MiB"

    def test_mps_split_respects_user_cap(self, monkeypatch):
        monkeypatch.setenv("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY", "4000MiB")
        _apply_text_backend_strategy("mps_split")
        assert os.environ["BRAIN_DIFF_MPS_TEXT_MAX_MEMORY"] == "4000MiB"

    def test_mps_full_fp32_sets_flags(self):
        _apply_text_backend_strategy("mps_full_fp32")
        assert os.environ["BRAIN_DIFF_LLAMA_ON_CPU"] == "0"
        assert os.environ["BRAIN_DIFF_MPS_LLAMA_FP32_FULL"] == "1"


class TestConfigureWhisperDefaults:
    def test_cuda_leaves_env_untouched(self, monkeypatch):
        monkeypatch.delenv("TRIBEV2_WHISPERX_DEVICE", raising=False)
        _configure_whisper_defaults(_CUDA_PROFILE)
        assert "TRIBEV2_WHISPERX_DEVICE" not in os.environ

    def test_mps_sets_cpu_defaults(self, monkeypatch):
        for key in ("TRIBEV2_WHISPERX_DEVICE", "TRIBEV2_WHISPERX_MODEL", "TRIBEV2_WHISPERX_BATCH_SIZE"):
            monkeypatch.delenv(key, raising=False)
        _configure_whisper_defaults(_MPS_PROFILE)
        assert os.environ["TRIBEV2_WHISPERX_DEVICE"] == "cpu"
        assert os.environ["TRIBEV2_WHISPERX_MODEL"] == "tiny.en"
        assert os.environ["TRIBEV2_WHISPERX_BATCH_SIZE"] == "4"

    def test_cpu_profile_sets_cpu_defaults(self, monkeypatch):
        for key in ("TRIBEV2_WHISPERX_DEVICE", "TRIBEV2_WHISPERX_MODEL", "TRIBEV2_WHISPERX_BATCH_SIZE"):
            monkeypatch.delenv(key, raising=False)
        _configure_whisper_defaults(_CPU_PROFILE)
        assert os.environ["TRIBEV2_WHISPERX_DEVICE"] == "cpu"
        assert os.environ["TRIBEV2_WHISPERX_MODEL"] == "tiny.en"
        assert os.environ["TRIBEV2_WHISPERX_BATCH_SIZE"] == "4"

    def test_user_overrides_are_respected(self, monkeypatch):
        monkeypatch.setenv("TRIBEV2_WHISPERX_DEVICE", "cpu")
        monkeypatch.setenv("TRIBEV2_WHISPERX_MODEL", "base.en")
        _configure_whisper_defaults(_MPS_PROFILE)
        assert os.environ["TRIBEV2_WHISPERX_MODEL"] == "base.en"

    def test_cpu_fallback_after_mps_attempt_gets_correct_defaults(self, monkeypatch):
        """Simulates a fallback from mps to cpu — whisper should still be cpu/tiny.en."""
        for key in ("TRIBEV2_WHISPERX_DEVICE", "TRIBEV2_WHISPERX_MODEL"):
            monkeypatch.delenv(key, raising=False)
        # First attempt: mps
        _configure_whisper_defaults(_MPS_PROFILE)
        assert os.environ["TRIBEV2_WHISPERX_DEVICE"] == "cpu"
        # Second attempt: cpu fallback (setdefault should be idempotent)
        _configure_whisper_defaults(_CPU_PROFILE)
        assert os.environ["TRIBEV2_WHISPERX_DEVICE"] == "cpu"
        assert os.environ["TRIBEV2_WHISPERX_MODEL"] == "tiny.en"
