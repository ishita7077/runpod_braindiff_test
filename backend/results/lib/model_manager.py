"""ModelManager — centralised access to the LLM (audit point #2).

Why this exists: every slot needs to call LLaMA, but if we let each slot
directly invoke the model we get GPU memory pressure, parallel queue thrash,
and silent latency spikes when TRIBE inference is also running.

ModelManager:
  * owns the single LLaMA instance (lazy load)
  * caps parallel slot generations
  * enforces a per-slot timeout
  * logs model_load_ms, generation_ms, peak_vram_mb (when GPU available)
  * queues content generation behind cortical inference (hook in scheduler)

Phase 0 ships a working interface with:
  * lazy load + asyncio.Semaphore concurrency cap
  * timeout enforcement via asyncio.wait_for
  * a deterministic-mode flag (do_sample=False) for production
  * a StubBackend for development without a GPU

Phase 1 wires the real transformers backend in.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────
# Generation request / response
# ────────────────────────────────────────────────────────────

@dataclass
class GenerationRequest:
    """One model call. Slot runner builds these."""
    prompt: str
    max_new_tokens: int
    temperature: float = 0.4
    top_p: float = 0.9
    do_sample: bool = False  # default False = deterministic; sampling is opt-in
    seed: int = 0
    stop: list[str] = field(default_factory=list)


@dataclass
class GenerationResponse:
    text: str
    latency_ms: int
    tokens_input: int
    tokens_output: int
    model_id: str
    model_revision: str | None
    transformers_version: str | None = None
    torch_version: str | None = None


# ────────────────────────────────────────────────────────────
# Backend protocol — swap real LLaMA in Phase 1
# ────────────────────────────────────────────────────────────

class ModelBackend(Protocol):
    model_id: str
    model_revision: str | None

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        ...

    def vram_peak_mb(self) -> float | None:
        """Peak VRAM since last reset, in MB. None on CPU-only runs."""
        ...

    def reset_vram_peak(self) -> None:
        ...


class StubBackend:
    """In-process backend for dev / Phase 0 testing — no GPU, no model load.

    Returns deterministic placeholder text so the full pipeline can be exercised
    end-to-end before the real LLaMA backend lands.
    """

    model_id = "stub-llama-3.2-3b-instruct"
    model_revision = "stub-v0"

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        start = time.perf_counter()
        # Tiny artificial delay so latency_ms isn't 0.
        await asyncio.sleep(0.01)
        # Deterministic stub: echo a marker plus seed so tests can assert reproducibility.
        text = f"[STUB seed={req.seed}] (no model loaded — Phase 0 placeholder)"
        latency_ms = int((time.perf_counter() - start) * 1000)
        return GenerationResponse(
            text=text,
            latency_ms=latency_ms,
            tokens_input=len(req.prompt.split()),
            tokens_output=len(text.split()),
            model_id=self.model_id,
            model_revision=self.model_revision,
        )

    def vram_peak_mb(self) -> float | None:
        return None

    def reset_vram_peak(self) -> None:
        return None


# ────────────────────────────────────────────────────────────
# ModelManager — the public face
# ────────────────────────────────────────────────────────────

class ModelTimeoutError(Exception):
    """Raised when a generation exceeds its per-slot timeout."""


class ModelManager:
    """Owns the model. Caps parallelism. Enforces timeouts.

    Use one instance per process.
    """

    def __init__(
        self,
        backend: ModelBackend,
        *,
        max_parallel: int = 2,
        per_slot_timeout_seconds: float = 12.0,
        priority_lock: asyncio.Lock | None = None,
    ) -> None:
        self.backend = backend
        self._sem = asyncio.Semaphore(max_parallel)
        self._timeout = per_slot_timeout_seconds
        # priority_lock = held by cortical inference. If set, ModelManager
        # will await this lock's release before each generation. Wire from
        # the TRIBE scheduler in Phase 1.
        self._priority_lock = priority_lock

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        """Bounded, queued, timeout-enforced generation."""
        # If cortical inference holds the priority lock, wait for it.
        if self._priority_lock is not None:
            async with self._priority_lock:
                pass  # just await release; do not hold during our own work

        async with self._sem:
            try:
                return await asyncio.wait_for(
                    self.backend.generate(req),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError as exc:
                raise ModelTimeoutError(
                    f"Generation exceeded {self._timeout:.1f}s "
                    f"(prompt_len={len(req.prompt)} max_new_tokens={req.max_new_tokens})"
                ) from exc

    def vram_peak_mb(self) -> float | None:
        return self.backend.vram_peak_mb()

    def reset_vram_peak(self) -> None:
        self.backend.reset_vram_peak()


# ────────────────────────────────────────────────────────────
# Convenience: process-singleton accessor
# ────────────────────────────────────────────────────────────

_singleton: ModelManager | None = None


def get_model_manager() -> ModelManager:
    """Process-singleton ModelManager. Defaults to StubBackend in Phase 0."""
    global _singleton
    if _singleton is None:
        _singleton = ModelManager(StubBackend())
    return _singleton


def set_model_manager(mgr: ModelManager) -> None:
    """Override the singleton. Phase 1 calls this with the real backend."""
    global _singleton
    _singleton = mgr
