"""
Apple Silicon + Llama for HuggingFaceText (neuralset ``device=accelerate``):

- fp16 + ``device_map=auto`` on MPS-only can hit bad ``mps.matmul`` kernels.
- fp32 + full ``.to("mps")`` often OOMs next to the TRIBEv2 brain model (~9GB MPS cap).

Default: **fp16** + ``device_map=auto`` + **max_memory** so part of Llama stays on MPS
and the rest spills to CPU (still uses GPU; not CPU-only).

Env:
- ``BRAIN_DIFF_MPS_TEXT_MAX_MEMORY`` — cap for MPS slice (default ``4500MiB``).
- ``BRAIN_DIFF_MPS_LLAMA_FP32_FULL=1`` — force full fp32 on MPS (large RAM only).
- ``BRAIN_DIFF_DISABLE_MPS_FP32_PATCH=1`` — disable this module (use stock neuralset).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("braindiff.neuralset_mps_patch")

_PATCHED = False


def apply_huggingface_text_mps_dtype_patch() -> None:
    global _PATCHED
    if _PATCHED:
        return
    if os.getenv("BRAIN_DIFF_DISABLE_MPS_FP32_PATCH", "0") == "1":
        logger.info("neuralset_mps_patch: disabled via BRAIN_DIFF_DISABLE_MPS_FP32_PATCH")
        _PATCHED = True
        return
    try:
        import torch
        from neuralset.extractors.text import HuggingFaceText
    except Exception as err:
        logger.warning("neuralset_mps_patch: skip import: %s", err)
        return

    mps_ok = bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
    if not mps_ok:
        _PATCHED = True
        return

    _orig = HuggingFaceText._load_model

    def _load_model(self: Any, **kw: Any) -> Any:
        import itertools

        import torch as th
        from neuralset.extractors.text import part_reversal  # type: ignore

        if self.device != "accelerate":
            return _orig(self, **kw)

        Model: Any
        from transformers import AutoModel as Model

        if "t5" in self.model_name or "bert" in self.model_name:
            from transformers import AutoModelForTextEncoding as Model
        elif "Phi-3" in self.model_name:
            from transformers import AutoModelForCausalLM as Model
        elif "Llama-3.2-11B-Vision" in self.model_name:
            from transformers import MllamaForConditionalGeneration as Model

        mps_ok = bool(getattr(th.backends, "mps", None)) and th.backends.mps.is_available()

        if mps_ok:
            # Full fp32 .to(mps) OOMs beside the brain model on ~9GB MPS caps; full fp16 device_map
            # hit bad mps.matmul kernels. Split with max_memory: hot layers on MPS, spill to CPU.
            use_fp32_single = os.getenv("BRAIN_DIFF_MPS_LLAMA_FP32_FULL", "0") == "1"
            if use_fp32_single:
                dtype = th.float32
                logger.info("neuralset_mps_patch: MPS Llama fp32 full-device (BRAIN_DIFF_MPS_LLAMA_FP32_FULL=1)")
                model = Model.from_pretrained(self.model_name, torch_dtype=dtype)
                if not self.pretrained:
                    rawmodel = Model.from_config(model.config)
                    with th.no_grad():
                        for p1, p2 in itertools.zip_longest(model.parameters(), rawmodel.parameters()):
                            p1.data = p2.to(p1)
                elif self.pretrained == "part-reversal":
                    with th.no_grad():
                        for p in model.parameters():
                            part_reversal(p)
                model.to(th.device("mps"))
                model.eval()
                return model

            if os.getenv("BRAIN_DIFF_LLAMA_ON_CPU", "0") == "1":
                logger.info("neuralset_mps_patch: Llama on CPU only (BRAIN_DIFF_LLAMA_ON_CPU=1); brain/audio may still use MPS")
                model = Model.from_pretrained(self.model_name, torch_dtype=th.float16)
                if not self.pretrained:
                    rawmodel = Model.from_config(model.config)
                    with th.no_grad():
                        for p1, p2 in itertools.zip_longest(model.parameters(), rawmodel.parameters()):
                            p1.data = p2.to(p1)
                elif self.pretrained == "part-reversal":
                    with th.no_grad():
                        for p in model.parameters():
                            part_reversal(p)
                model.to(th.device("cpu"))
                model.eval()
                return model

            mps_cap = os.getenv("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY", "2500MiB")
            load_kw: dict[str, Any] = {
                "device_map": "auto",
                "torch_dtype": th.float16,
                "max_memory": {"mps": mps_cap, "cpu": "200GiB"},
            }
            logger.info(
                "neuralset_mps_patch: MPS+CPU split Llama fp16 max_memory[mps]=%s (set BRAIN_DIFF_MPS_TEXT_MAX_MEMORY to tune)",
                mps_cap,
            )
            model = Model.from_pretrained(self.model_name, **load_kw)
            if not self.pretrained:
                rawmodel = Model.from_config(model.config)
                with th.no_grad():
                    for p1, p2 in itertools.zip_longest(model.parameters(), rawmodel.parameters()):
                        p1.data = p2.to(p1)
            elif self.pretrained == "part-reversal":
                with th.no_grad():
                    for p in model.parameters():
                        part_reversal(p)
            model.eval()
            return model

        return _orig(self, **kw)

    HuggingFaceText._load_model = _load_model  # type: ignore[method-assign]
    _PATCHED = True
    logger.info("neuralset_mps_patch: HuggingFaceText._load_model patched for Apple Silicon Llama loading")
