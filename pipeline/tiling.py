"""Official SwinIR overlap averaging, with the image/output buffers on CPU."""
from __future__ import annotations

import gc
import time

import numpy as np
import torch


def validate_tiles(tile: int, overlap: int):
    if tile < 64 or tile % 8:
        raise ValueError("Tile harus kelipatan 8 dan minimal 64 piksel input.")
    if overlap < 0 or overlap % 8 or overlap >= tile:
        raise ValueError("Overlap harus kelipatan 8, >=0 dan lebih kecil daripada tile.")


def official_pad(rgb: np.ndarray) -> np.ndarray:
    # main_test_swinir.py extends even aligned dimensions by a full window.
    # Symmetric padding equals its flip+concatenate, also for very small inputs.
    height, width = rgb.shape[:2]
    return np.pad(rgb, ((0, 8 - height % 8), (0, 8 - width % 8), (0, 0)), mode="symmetric")


def starts(length: int, tile: int, overlap: int):
    return list(range(0, length - tile, tile - overlap)) + [length - tile]


def tiled_forward(rgb, model, device, tile, overlap, progress=None):
    padded = official_pad(rgb)
    height, width = padded.shape[:2]
    actual_tile = min(tile, height, width)
    actual_overlap = min(overlap, actual_tile - 8)
    rows = starts(height, actual_tile, actual_overlap)
    columns = starts(width, actual_tile, actual_overlap)
    output = np.zeros((height * 2, width * 2, 3), dtype=np.float32)
    weight = np.zeros((height * 2, width * 2, 1), dtype=np.float32)
    total = len(rows) * len(columns)
    with torch.inference_mode():
        for index, (y, x) in enumerate(((y, x) for y in rows for x in columns), 1):
            patch = np.ascontiguousarray(padded[y:y + actual_tile, x:x + actual_tile].transpose(2, 0, 1))
            tensor = torch.from_numpy(patch).unsqueeze(0).to(device=device, dtype=torch.float32).div_(255.0)
            predicted = model(tensor)
            if tuple(predicted.shape) != (1, 3, actual_tile * 2, actual_tile * 2):
                raise RuntimeError("Dimensi keluaran model tidak sesuai skala x2.")
            if not torch.isfinite(predicted).all().item():
                raise RuntimeError("Model menghasilkan NaN/Inf; ekspor dibatalkan.")
            tile_result = predicted[0].permute(1, 2, 0).float().cpu().numpy()
            output[y * 2:(y + actual_tile) * 2, x * 2:(x + actual_tile) * 2] += tile_result
            weight[y * 2:(y + actual_tile) * 2, x * 2:(x + actual_tile) * 2] += 1
            del predicted, tensor, tile_result
            if progress:
                progress(index, total, actual_tile)
    if np.any(weight == 0):
        raise RuntimeError("Tiling menyisakan piksel tanpa bobot.")
    output /= weight
    h, w = rgb.shape[:2]
    return output[:h * 2, :w * 2], {"tile_used": actual_tile, "overlap_used": actual_overlap,
        "tiles": total, "padded_input_size": [width, height], "merge": "uniform overlap average on CPU"}


def infer_with_retries(rgb, model, device, tile, overlap, progress=None):
    validate_tiles(tile, overlap)
    attempts = []
    candidates = sorted({tile, *(size for size in (128, 96, 64) if size < tile)}, reverse=True)
    for candidate in candidates:
        if candidate <= overlap:
            continue
        start = time.perf_counter()
        oom = None
        try:
            result, info = tiled_forward(rgb, model, device, candidate, min(overlap, candidate-8), progress)
            attempts.append({"tile": candidate, "status": "success", "seconds": time.perf_counter() - start})
            return result, {**info, "attempts": attempts}
        except torch.cuda.OutOfMemoryError as error:
            oom = str(error)
        # Leave except scope before collecting to release traceback-held tensors.
        attempts.append({"tile": candidate, "status": "cuda_oom", "seconds": time.perf_counter() - start, "error": oom})
        gc.collect()
        if str(device).startswith("cuda"):
            torch.cuda.empty_cache()
        print(f"CUDA OOM pada tile {candidate}; mencoba tile lebih kecil tanpa resize foto.", flush=True)
    failure = RuntimeError("CUDA OOM pada seluruh tile yang diizinkan. Tutup aplikasi GPU lain atau jalankan --device cpu. Foto tidak diperkecil.")
    failure.attempts = attempts
    raise failure
