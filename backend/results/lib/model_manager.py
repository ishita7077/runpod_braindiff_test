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
    """In-process backend for dev / pre-LLaMA testing — no GPU, no model load.

    Returns slot-aware deterministic placeholder text so the full pipeline can be
    exercised end-to-end without a model. The stub recognises which slot called
    it by scanning the prompt for the slot-prompt's opening line, then returns
    fixture content that passes the slot's validator.

    When the real LLaMA backend lands (Phase 1.5), it implements the same
    `ModelBackend` protocol and is swapped in via `set_model_manager()`.
    """

    model_id = "stub-llama-3.2-3b-instruct"
    model_revision = "stub-v0"

    # Slot-detection markers — unique generation-line phrases that appear in
    # exactly one slot prompt. Stops cross-matching across slots (where a body
    # prompt mentions "hero headline" in its description).
    _STUB_FIXTURES: tuple[tuple[str, str], ...] = (
        # Headline: 2 short sentences, ≤10 words each.
        ("Generate 5 candidate headlines",   "B reaches the gut. A builds the argument."),
        # Body: 2-3 sentences, ≤60 words, supports headline + hooks the reader.
        ("Generate 3 candidate body",        "These two videos pull the cortex apart in opposite directions. One arrives in the chest before deliberation, the other builds in the head as you follow the argument. The systems they recruit barely overlap — keep scrolling for the chord-by-chord breakdown."),
        # Frame 02 sub.
        ("Frame 02",                          "Two recipes unfold across the runtime. A chord fires when two systems cross threshold at the same second and hold for at least one or two more. Watch where each video's chords land — the timing IS the strategy."),
        # Recipe match rationale (deterministic match writes the rationale).
        ("rationale for a Brain Diff recipe","System means landed in the spec'd range and the characteristic chords appeared at the right times across the runtime."),
        # Recipe description: 2 sentences, ≤35 words, ends with *Built for X.*
        ("Generate 2 candidate descriptions","Gradual attention building over the runtime, deep language and memory engagement, climax in a Reasoning Beat at 0:32. *Built for retention.*"),
        # Coupling callout: 2 sentences, ≤38 words.
        ("Generate 2 candidate callouts",    "Memory and Language systems rose together across the runtime. The two systems fired as a team — the signature of content built to stick."),
    )

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        start = time.perf_counter()
        await asyncio.sleep(0.005)

        text = self._fixture_for_prompt(req.prompt)

        latency_ms = int((time.perf_counter() - start) * 1000)
        return GenerationResponse(
            text=text,
            latency_ms=latency_ms,
            tokens_input=len(req.prompt.split()),
            tokens_output=len(text.split()),
            model_id=self.model_id,
            model_revision=self.model_revision,
        )

    def _fixture_for_prompt(self, prompt: str) -> str:
        import re

        # Chord contextual meaning: 2-3 sentences ≤70 words, references the firing.
        if "rewriting the meaning of a chord" in prompt.lower():
            ts_m = re.search(r"Firing timestamp \(M:SS\): (\d+:\d{2})", prompt)
            title_m = re.search(r"Video title: (.+)", prompt)
            ts = ts_m.group(1) if ts_m else "0:08"
            title = title_m.group(1).strip() if title_m else "this video"
            return (
                f"At {ts} in {title}, the body reacts before the mind catches up. "
                f"The systems involved cross threshold together while cognitive control stays quiet — "
                f"a moment that lands in the chest before the brain has decided whether to care."
            )

        # OLD chord_context marker (now removed — kept as fallback so legacy
        # prompts don't crash if invoked).
        if "personalized sentence to append to a chord" in prompt.lower():
            ts_m = re.search(r"Firing timestamp \(M:SS\): (\d+:\d{2})", prompt)
            ts = ts_m.group(1) if ts_m else "0:08"
            return f"The viewer's body responds at {ts} before deciding whether to care."

        # Frame 02 sub: must mention both recipe names.
        if "Frame 02" in prompt:
            ra = re.search(r"Recipe A name: (.+)", prompt)
            rb = re.search(r"Recipe B name: (.+)", prompt)
            recipe_a = ra.group(1).strip() if ra else "Recipe A"
            recipe_b = rb.group(1).strip() if rb else "Recipe B"
            return (
                f"{recipe_a} and {recipe_b} unfold across the runtime. "
                "A chord fires when two systems cross threshold at the same second and hold."
            )

        # Coupling callout: must mention both system display names.
        if "coupling callout" in prompt.lower():
            sa = re.search(r"System pair: (\w+) ", prompt)
            sb = re.search(r"System pair: \w+ . (\w+)", prompt)
            sys_a = sa.group(1) if sa else "memory_encoding"
            sys_b = sb.group(1) if sb else "language_depth"
            display = {
                "personal_resonance": "Self-relevance", "attention": "Attention",
                "brain_effort": "Effort", "gut_reaction": "Gut",
                "memory_encoding": "Memory", "social_thinking": "Social",
                "language_depth": "Language",
            }
            a_disp = display.get(sys_a, sys_a)
            b_disp = display.get(sys_b, sys_b)
            return (
                f"{a_disp} and {b_disp} systems rose together across the runtime. "
                "The two systems fired as a team — the signature of content built to stick."
            )

        for marker, fixture in self._STUB_FIXTURES:
            if marker.lower() in prompt.lower():
                return fixture

        return "Stub backend: no fixture matched this prompt."

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


# ────────────────────────────────────────────────────────────
# LoadedTransformersBackend — real LLaMA via transformers.generate()
# ────────────────────────────────────────────────────────────
#
# This is the backend used in production (Mode B). The worker imports it,
# loads LLaMA-3.2-3B-Instruct from the SAME HuggingFace cache TRIBE uses
# (./cache, populated when TRIBE first ran), and points ModelManager at it.
#
# Loading is lazy — first call materialises the model, subsequent calls reuse
# it. Inside the runpod_worker's long-lived process, this means one cold load
# per container lifecycle (~30s on first comparison, milliseconds thereafter).
#
# Memory: ~6GB VRAM for Llama-3.2-3B fp16. On a 24GB+ GPU this sits alongside
# TRIBE comfortably. On smaller GPUs we should switch to the shared-instance
# path (use TRIBE's already-loaded text encoder + add the LM head). That's a
# follow-up — for now this is the simplest correct thing.

class LoadedTransformersBackend:
    """Real LLaMA backend. Uses transformers.AutoModelForCausalLM."""

    model_id = "meta-llama/Llama-3.2-3B-Instruct"

    def __init__(
        self,
        *,
        model_name: str = "meta-llama/Llama-3.2-3B-Instruct",
        cache_folder: str | None = None,    # None = use HF default (HF_HOME / ~/.cache/huggingface)
        device: str | None = None,
        dtype: str = "float16",
    ) -> None:
        self.model_name = model_name
        self.cache_folder = cache_folder
        self._device = device
        self._dtype_str = dtype
        self._model = None
        self._tokenizer = None
        self.model_revision: str | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        log.info("LoadedTransformersBackend: loading %s (cache=%s)", self.model_name, self.cache_folder)
        import torch  # type: ignore
        from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore

        # Pick device.
        if self._device is None:
            if torch.cuda.is_available():
                self._device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                self._device = "mps"
            else:
                self._device = "cpu"

        dtype = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }.get(self._dtype_str, torch.float16)

        # Pick CPU dtype = float32 (MPS GQA bug + better numerics on CPU);
        # GPU dtype = whatever the caller asked (fp16 default).
        load_dtype = torch.float32 if self._device == "cpu" else dtype

        tok_kwargs: dict[str, Any] = {}
        model_kwargs: dict[str, Any] = {}
        if self.cache_folder:
            tok_kwargs["cache_dir"] = self.cache_folder
            model_kwargs["cache_dir"] = self.cache_folder

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, **tok_kwargs)
        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token_id = self._tokenizer.eos_token_id

        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=load_dtype,
            device_map=self._device if self._device not in ("cpu", None) else None,
            **model_kwargs,
        )
        if self._device == "cpu":
            self._model = self._model.to("cpu")
        self._model.eval()
        try:
            self.model_revision = self._model.config._name_or_path  # noqa: SLF001
        except Exception:
            self.model_revision = None
        log.info("LoadedTransformersBackend: ready on device=%s dtype=%s", self._device, self._dtype_str)

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        # Run the blocking transformers call in a thread so other slots can
        # progress concurrently if the ModelManager Semaphore allows.
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(None, self._generate_sync, req)

    def _generate_sync(self, req: GenerationRequest) -> GenerationResponse:
        self._ensure_loaded()
        import torch  # type: ignore

        start = time.perf_counter()
        torch.manual_seed(req.seed)
        messages = [{"role": "user", "content": req.prompt}]
        if not getattr(self._tokenizer, "chat_template", None):
            # Base model with no chat template — encode prompt directly.
            encoded = self._tokenizer(req.prompt, return_tensors="pt", return_attention_mask=True)
            chat_input = {"input_ids": encoded["input_ids"], "attention_mask": encoded["attention_mask"]}
        else:
            chat_input = self._tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, return_tensors="pt", return_dict=True,
            )
        if not isinstance(chat_input, dict) or "input_ids" not in chat_input:
            raise RuntimeError(f"apply_chat_template returned unexpected type: {type(chat_input)}")
        input_ids = chat_input["input_ids"]
        attention_mask = chat_input.get("attention_mask")
        if self._device not in ("cpu", None):
            input_ids = input_ids.to(self._device)
            if attention_mask is not None:
                attention_mask = attention_mask.to(self._device)
        input_len = input_ids.shape[1]

        gen_kwargs: dict[str, Any] = {
            "max_new_tokens": req.max_new_tokens,
            "do_sample": req.do_sample,
            "pad_token_id": self._tokenizer.pad_token_id,
        }
        if attention_mask is not None:
            gen_kwargs["attention_mask"] = attention_mask
        if req.do_sample:
            gen_kwargs["temperature"] = req.temperature
            gen_kwargs["top_p"] = req.top_p
        with torch.inference_mode():
            output_ids = self._model.generate(input_ids, **gen_kwargs)

        new_tokens = output_ids[0, input_len:]
        text = self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        latency_ms = int((time.perf_counter() - start) * 1000)

        try:
            import transformers as _tf  # type: ignore
            tf_ver = _tf.__version__
        except Exception:
            tf_ver = None
        try:
            torch_ver = torch.__version__
        except Exception:
            torch_ver = None

        return GenerationResponse(
            text=text,
            latency_ms=latency_ms,
            tokens_input=int(input_len),
            tokens_output=int(new_tokens.shape[0]),
            model_id=self.model_id,
            model_revision=self.model_revision,
            transformers_version=tf_ver,
            torch_version=torch_ver,
        )

    def vram_peak_mb(self) -> float | None:
        try:
            import torch  # type: ignore
            if self._device == "cuda":
                return torch.cuda.max_memory_allocated() / (1024 * 1024)
        except Exception:
            pass
        return None

    def reset_vram_peak(self) -> None:
        try:
            import torch  # type: ignore
            if self._device == "cuda":
                torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass


def use_real_llama(
    *,
    cache_folder: str = "./cache",
    device: str | None = None,
    max_parallel: int = 1,
    per_slot_timeout_seconds: float = 30.0,
) -> ModelManager:
    """Convenience: swap the singleton to a LoadedTransformersBackend.

    Call this once at worker startup (or anywhere we want real LLaMA instead
    of the stub). Returns the new manager.

    max_parallel=1 by default — generation is GPU-bound; running >1 in
    parallel only helps if VRAM has headroom for KV-cache duplication.
    """
    backend = LoadedTransformersBackend(cache_folder=cache_folder, device=device)
    mgr = ModelManager(
        backend,
        max_parallel=max_parallel,
        per_slot_timeout_seconds=per_slot_timeout_seconds,
    )
    set_model_manager(mgr)
    return mgr
