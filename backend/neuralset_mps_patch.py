"""
Apple Silicon + Llama for HuggingFaceText (neuralset ``device=accelerate``):

- fp16 + ``device_map=auto`` on MPS-only can hit bad ``mps.matmul`` kernels.
- fp32 + full ``.to("mps")`` often OOMs next to the TRIBEv2 brain model (~9 GB MPS cap).

Default strategy is resolved by ``model_service._resolve_text_backend_strategy``:
- ``cpu``: Llama loaded in float32 on CPU. Brain/audio still use MPS.
  Recommended default on Apple Silicon (avoids MPS placeholder bugs in Llama).
- ``mps_split``: fp16 + ``device_map=auto`` + ``max_memory`` (hot on MPS, rest on CPU).
  Opt-in via ``BRAIN_DIFF_TEXT_BACKEND=mps_split`` — can raise
  ``Placeholder storage has not been allocated on MPS device`` on some PyTorch builds.
- ``mps_full_fp32``: fp32 full ``.to("mps")``. Large-RAM machines only.
  Active when BRAIN_DIFF_MPS_LLAMA_FP32_FULL=1.

Env:
- ``BRAIN_DIFF_MPS_TEXT_MAX_MEMORY`` — MPS cap for mps_split
  (default ``3500MiB`` on >=16 GiB RAM, ``2500MiB`` below 16 GiB).
- ``BRAIN_DIFF_LLAMA_ON_CPU=1``      — force Llama to CPU (float32). Wins over fp32-full-device.
- ``BRAIN_DIFF_MPS_LLAMA_FP32_FULL=1`` — force fp32 full MPS (large RAM only, LLAMA_ON_CPU must be 0).
- ``BRAIN_DIFF_DISABLE_MPS_FP32_PATCH=1`` — skip this module entirely.
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

        mps_available = bool(getattr(th.backends, "mps", None)) and th.backends.mps.is_available()

        if mps_available:
            # Precedence: LLAMA_ON_CPU wins over fp32-full-device regardless of order.
            llama_on_cpu = os.getenv("BRAIN_DIFF_LLAMA_ON_CPU", "0") == "1"
            use_fp32_single = (
                os.getenv("BRAIN_DIFF_MPS_LLAMA_FP32_FULL", "0") == "1" and not llama_on_cpu
            )

            if llama_on_cpu:
                logger.info(
                    "neuralset_mps_patch: Llama on CPU float32 (BRAIN_DIFF_LLAMA_ON_CPU=1); brain/audio may still use MPS"
                )
                model = Model.from_pretrained(self.model_name, torch_dtype=th.float32)
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

            if use_fp32_single:
                logger.info(
                    "neuralset_mps_patch: MPS Llama fp32 full-device (BRAIN_DIFF_MPS_LLAMA_FP32_FULL=1)"
                )
                model = Model.from_pretrained(self.model_name, torch_dtype=th.float32)
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

            # mps_split: hot layers on MPS, rest spills to CPU.
            mps_cap = os.getenv("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY", "3500MiB")
            load_kw: dict[str, Any] = {
                "device_map": "auto",
                "torch_dtype": th.float16,
                "max_memory": {"mps": mps_cap, "cpu": "200GiB"},
            }
            logger.info(
                "neuralset_mps_patch: MPS+CPU split Llama fp16 max_memory[mps]=%s "
                "(set BRAIN_DIFF_MPS_TEXT_MAX_MEMORY to tune)",
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

    # ── Video / image feature extractor MPS patch ────────────────────────────
    # _HFVideoModel.__init__ loads the model to CPU. _get_data then does:
    #   if model.model.device.type == "cpu": model.model.to(self.image.device)
    # Since self.image.device is "cpu" (Pydantic Literal rejects "mps"), the model
    # stays on CPU. Fix: patch _HFVideoModel.__init__ to auto-move to MPS after
    # loading so the device.type check sees "mps" and skips the .to() call entirely.
    try:
        from neuralset.extractors.video import _HFVideoModel
        _orig_hfvideo_init = _HFVideoModel.__init__

        def _mps_hfvideo_init(
            self: Any,
            model_name: str,
            pretrained: bool = True,
            layer_type: str = "",
            num_frames: int | None = None,
        ) -> None:
            _orig_hfvideo_init(
                self,
                model_name=model_name,
                pretrained=pretrained,
                layer_type=layer_type,
                num_frames=num_frames,
            )
            import torch as th
            _mps_ok = bool(getattr(th.backends, "mps", None)) and th.backends.mps.is_available()
            if not _mps_ok:
                return
            try:
                device_type = self.model.device.type
            except Exception:
                device_type = None
            if device_type == "cpu":
                logger.info(
                    "neuralset_mps_patch: moving %s to MPS (was cpu)", model_name
                )
                self.model = self.model.to(th.device("mps"))

        _HFVideoModel.__init__ = _mps_hfvideo_init  # type: ignore[method-assign]

        # Wrap predict() with fp16 autocast so MPS runs matrix-ops in fp16
        # (ViT-Giant in fp32 on MPS is ~3× slower than fp16 autocast path).
        _orig_predict = _HFVideoModel.predict

        def _mps_predict(self: Any, images: Any, audio: Any = None) -> Any:
            import torch as th
            try:
                dev_type = next(self.model.parameters()).device.type
            except Exception:
                dev_type = None
            if dev_type == "mps":
                with th.amp.autocast(device_type="mps", dtype=th.float16):
                    return _orig_predict(self, images, audio)
            return _orig_predict(self, images, audio)

        _HFVideoModel.predict = _mps_predict  # type: ignore[method-assign]
        logger.info(
            "neuralset_mps_patch: _HFVideoModel patched — vjepa2/DINOv2 will auto-move to MPS + fp16 autocast"
        )
    except Exception as err:
        logger.warning("neuralset_mps_patch: _HFVideoModel patch skipped: %s", err)

    _PATCHED = True
    logger.info("neuralset_mps_patch: HuggingFaceText._load_model patched for Apple Silicon Llama loading")
