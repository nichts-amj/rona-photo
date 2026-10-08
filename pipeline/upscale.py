"""One official, pinned SwinIR lightweight x2 model. FP32 only."""
from __future__ import annotations

import gc
import importlib.metadata
import json
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from pipeline.io import sha256
from pipeline.tiling import infer_with_retries

from resource_paths import ROOT
MODEL_CONFIG = dict(upscale=2, in_chans=3, img_size=64, window_size=8,
                    img_range=1.0, depths=[6, 6, 6, 6], embed_dim=60,
                    num_heads=[6, 6, 6, 6], mlp_ratio=2,
                    upsampler="pixelshuffledirect", resi_connection="1conv")


class SwinIRX2:
    def __init__(self, device="cuda"):
        if device not in {"cuda", "cpu"}:
            raise ValueError("Device harus cuda atau cpu.")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA tidak tersedia. Jalankan doctor.py --probe-cuda atau pilih --device cpu secara eksplisit.")
        manifest_path = ROOT / "models/provenance.json"
        if not manifest_path.exists():
            raise RuntimeError("Model belum tersedia; jalankan setup_model.py terlebih dahulu.")
        self.provenance = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative, entry in self.provenance["files"].items():
            path = ROOT / relative
            if not path.is_file() or sha256(path) != entry["sha256"]:
                raise RuntimeError(f"Hash sumber/checkpoint berbeda: {relative}")
        # Import only after validating the vendored source. Architecture unchanged.
        from third_party.swinir.network_swinir import SwinIR
        self.device = torch.device(device)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        start = time.perf_counter()
        self.model = SwinIR(**MODEL_CONFIG)
        checkpoint = torch.load(ROOT / "models" / self.provenance["checkpoint"], map_location="cpu", weights_only=True)
        self.model.load_state_dict(checkpoint["params"], strict=True)
        del checkpoint
        self.model.eval().to(self.device)
        if device == "cuda":
            torch.cuda.synchronize()
        self.load_seconds = time.perf_counter() - start

    def infer_float(self, rgb, tile=128, overlap=32, progress=None):
        if self.device.type == "cuda":
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
        start = time.perf_counter()
        result, info = infer_with_retries(rgb, self.model, self.device, tile, overlap, progress)
        if self.device.type == "cuda":
            torch.cuda.synchronize()
        info.update({"inference_seconds": time.perf_counter() - start, "model_load_seconds": self.load_seconds,
                     "device": str(self.device), "precision": "float32", "tf32": False,
                     "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated() if self.device.type == "cuda" else None,
                     "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved() if self.device.type == "cuda" else None,
                     "gpu_name": torch.cuda.get_device_name() if self.device.type == "cuda" else None})
        return result, info

    def infer(self, image: Image.Image, tile=128, overlap=32, progress=None):
        if image.width * image.height > 50_000_000:
            raise ValueError("SR tahap ini dibatasi 50 juta piksel input untuk membatasi RAM. Foto tidak diperkecil otomatis.")
        result, info = self.infer_float(np.asarray(image, dtype=np.uint8), tile, overlap, progress)
        np.clip(result, 0, 1, out=result)
        result *= 255.0
        np.rint(result, out=result)
        return Image.fromarray(result.astype(np.uint8)), info

    def metadata(self):
        return {"name": "SwinIR lightweight x2", "config": MODEL_CONFIG, "provenance": self.provenance,
                "packages": {name: importlib.metadata.version(name) for name in ("torch", "torchvision", "timm", "numpy", "Pillow")}}

    def close(self):
        self.model = None
        gc.collect()
        if self.device.type == "cuda":
            torch.cuda.empty_cache()
