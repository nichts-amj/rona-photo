"""Compact official Real-ESRGAN, FP32, cropped-context tiles, CPU image buffers."""
from __future__ import annotations

import gc
import json
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from pipeline.io import sha256

from pipeline.performance import NonFiniteOutput, TileProfiler, autocast, precision_for, adaptive_tile, run_with_fallback
from resource_paths import ROOT
CONFIG = dict(num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=32, upscale=4, act_type="prelu")
# 34 successive 3x3 convolutions: radius 34 input pixels. Context at least
# this large avoids truncating the receptive field at internal tile borders.
CONTEXT = 34


def tiled_x4(rgb, model, device, tile=256, context=CONTEXT, progress=None, floating=False, precision=None):
    if tile < 16 or context < CONTEXT:
        raise ValueError("Tile must be >=16 and context >=34 input pixels")
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("Expected RGB uint8")
    h, w = rgb.shape[:2]
    output = np.empty((h * 4, w * 4, 3), dtype=np.float32 if floating else np.uint8)
    total = ((h + tile - 1) // tile) * ((w + tile - 1) // tile)
    index = 0
    profiler = TileProfiler(device)
    with torch.inference_mode(), autocast(device, precision):
        for y in range(0, h, tile):
            for x in range(0, w, tile):
                y1, x1 = min(y + tile, h), min(x + tile, w)
                py, px = max(y - context, 0), max(x - context, 0)
                py1, px1 = min(y1 + context, h), min(x1 + context, w)
                patch = np.ascontiguousarray(rgb[py:py1, px:px1].transpose(2, 0, 1))
                tensor = profiler.call("upload_seconds", lambda: torch.from_numpy(patch).unsqueeze(0).to(device=device, dtype=torch.float32).div_(255))
                predicted = profiler.forward(model, tensor, precision)
                if tuple(predicted.shape) != (1, 3, (py1 - py) * 4, (px1 - px) * 4):
                    raise RuntimeError("Unexpected model output dimensions")
                core = predicted[0, :, (y-py)*4:(y1-py)*4, (x-px)*4:(x1-px)*4]
                values = profiler.download(lambda: core.permute(1, 2, 0).contiguous().float().cpu().numpy())
                merge_start = time.perf_counter()
                if not np.isfinite(values).all():
                    raise NonFiniteOutput("NaN/Inf in Real-ESRGAN output")
                if not floating:
                    values = np.rint(np.clip(values, 0, 1) * 255).astype(np.uint8)
                output[y*4:y1*4, x*4:x1*4] = values
                profiler.times["cpu_merge_seconds"] += time.perf_counter()-merge_start
                del tensor, predicted, core, values
                index += 1
                if progress:
                    progress(index, total, tile)
    return output, {"tile_used": tile, "context_input_pixels": context, "tiles": total,
                    "merge": "discard tile context; copy disjoint cores to CPU buffer", "pre_pad": 0, "timings": profiler.report()}


def tiled_retry(rgb, model, device, tile=256, progress=None, precision=None):
    attempts = []
    for size in sorted({tile, *(s for s in (192, 128, 64) if s < tile)}, reverse=True):
        start = time.perf_counter()
        error_text = None
        try:
            output, info = tiled_x4(rgb, model, device, size, progress=progress, **({"precision":precision} if precision is not None else {}))
            attempts.append({"tile": size, "status": "success", "seconds": time.perf_counter()-start})
            return output, {**info, "attempts": attempts}
        except torch.cuda.OutOfMemoryError as error:
            error_text = str(error)
        attempts.append({"tile": size, "status": "cuda_oom", "error": error_text})
        gc.collect()
        if str(device).startswith("cuda"):
            torch.cuda.empty_cache()
    raise RuntimeError(f"CUDA OOM for all tile sizes: {attempts}")


class CompactRealESRGAN:
    def __init__(self, denoise=0.5, device="cuda"):
        if not 0 <= denoise <= 1:
            raise ValueError("Denoise strength must be between 0 and 1")
        if device not in {"cuda", "cpu"}:
            raise ValueError("Expected cuda or cpu")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; CPU fallback requires explicit selection")
        self.provenance = json.loads((ROOT / "models/realesrgan-provenance.json").read_text(encoding="utf-8"))
        for rel, entry in self.provenance["files"].items():
            if sha256(ROOT / rel) != entry["sha256"]:
                raise RuntimeError(f"Integrity failure: {rel}")
        from third_party.realesrgan.srvgg_arch import SRVGGNetCompact
        self.device = torch.device(device)
        self.denoise = denoise
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        start = time.perf_counter()
        self.model = SRVGGNetCompact(**CONFIG)
        checkpoints = [torch.load(ROOT / f"models/{name}.pth", map_location="cpu", weights_only=True)
                       for name in ("realesr-general-x4v3", "realesr-general-wdn-x4v3")]
        if any("params_ema" in state or "params" not in state for state in checkpoints):
            raise RuntimeError("Unexpected checkpoint keys for official DNI")
        a, b = [state["params"] for state in checkpoints]
        if a.keys() != b.keys():
            raise RuntimeError("DNI checkpoints differ in parameter keys")
        merged = {key: denoise*a[key] + (1-denoise)*b[key] for key in a}
        self.model.load_state_dict(merged, strict=True)
        self.model.eval().to(self.device)
        if device == "cuda":
            torch.cuda.synchronize()
        self.load_seconds = time.perf_counter() - start

    def infer(self, image, tile=256, progress=None, output_scale=2):
        if output_scale not in (2,4):raise ValueError("Output scale must be 2 or 4")
        if image.mode != "RGB" or image.width * image.height > 50_000_000:
            raise ValueError("Requires RGB input <=50 megapixels, without automatic input resize")
        if self.device.type == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        start = time.perf_counter()
        precision = precision_for(self.device, "B", getattr(self, "gpu_optimization", False))
        requested_tile = tile
        tile = adaptive_tile(self.device, "B", tile, precision)
        native, info = run_with_fallback(
            lambda dtype: tiled_retry(np.asarray(image), self.model, self.device, tile, progress, precision=dtype),
            self.device, precision)
        info.update(tile_requested=requested_tile)
        if self.device.type == "cuda":
            torch.cuda.synchronize()
        inference_seconds = time.perf_counter() - start
        # Explicit experimental output normalization. Pillow Lanczos differs
        # from upstream OpenCV INTER_LANCZOS4; no claim of resize parity.
        result = Image.fromarray(native)
        if output_scale==2:
            result = result.resize((image.width*2, image.height*2), Image.Resampling.LANCZOS)
        info.update({"inference_seconds": inference_seconds, "including_resize_seconds": time.perf_counter()-start,
                     "model_load_seconds": self.load_seconds, "tf32": False,
                     "device": str(self.device), "denoise_strength": self.denoise,
                     "native_scale": 4, "output_scale": output_scale, "resize": "none (native x4)" if output_scale==4 else "Pillow LANCZOS, quantized RGB8 x4 to x2",
                     "input_resized": False, "face_enhancement": False,
                     "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated() if self.device.type == "cuda" else None,
                     "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved() if self.device.type == "cuda" else None})
        return result, info

    def close(self):
        self.model = None
        gc.collect()
        if self.device.type == "cuda":
            torch.cuda.empty_cache()
