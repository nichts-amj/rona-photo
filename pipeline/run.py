from __future__ import annotations

import json
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, __version__ as pillow_version

from pipeline.io import PhotoError, read_photo, save_png, sha256
from pipeline.restore import control


def comparison(before: Image.Image, after: Image.Image, left_label="Input: orientasi + sRGB", right_label="Kontrol 1x: tanpa restorasi") -> Image.Image:
    if before.size != after.size:
        raise PhotoError("Perbandingan kontrol memerlukan ukuran yang sama.")
    width, height = before.size
    canvas = Image.new("RGB", (2 * width, height + 44), "#18202b")
    canvas.paste(before, (0, 44))
    canvas.paste(after, (width, 44))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 14), left_label, fill="white")
    draw.text((width + 10, 14), right_label, fill="white")
    return canvas


def run_control(input_path: Path, output_root: Path) -> Path:
    start = time.perf_counter()
    before, source = read_photo(input_path)
    io_seconds = time.perf_counter() - start
    stage_start = time.perf_counter()
    result = control(before)
    stage_seconds = time.perf_counter() - stage_start
    if result.size != before.size or result.tobytes() != before.tobytes():
        raise RuntimeError("Kontrol 1x mengubah piksel.")
    # A unique directory prevents accidental replacement of any source/old result.
    timestamp = datetime.now(timezone.utc)
    run_dir = output_root.resolve() / (timestamp.strftime("%Y%m%dT%H%M%S_%fZ") + "_" + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        save_png(before, run_dir / "input_normalized.png")
        save_png(result, run_dir / "result_control.png")
        save_png(comparison(before, result), run_dir / "comparison.png")
        with Image.open(run_dir / "result_control.png") as exported:
            exact = exported.mode == "RGB" and exported.size == before.size and exported.tobytes() == before.tobytes()
            if not exact:
                raise RuntimeError("PNG hasil tidak sama dengan kontrol dalam memori.")
        manifest = {
            "schema_version": 1, "status": "success", "timestamp_utc": timestamp.isoformat(),
            "implementation_stage": "1: IO and identity control", "mode": "control",
            "restoration_applied": False, "synthetic_degradation_applied": False,
            "scale": 1, "source": source, "output_size": list(result.size),
            "model": None, "device": "cpu", "precision": "uint8",
            "tile": None, "tile_overlap": None, "oom_retries": [],
            "peak_cuda_allocated_bytes": None, "peak_cuda_reserved_bytes": None,
            "metrics": None, "metrics_note": "Tanpa referensi independen; tidak mengklaim peningkatan kualitas.",
            "verification": {"control_pixels_equal_normalized_input": exact},
            "timing_seconds": {"decode_and_normalize": io_seconds, "control_copy": stage_seconds,
                               "total_before_manifest_write": time.perf_counter() - start},
            "environment": {"python": platform.python_version(), "executable": sys.executable,
                            "pillow": pillow_version, "platform": platform.platform()},
            "artifacts": {name: {"sha256": sha256(run_dir / name)} for name in
                          ("input_normalized.png", "result_control.png", "comparison.png")},
        }
        (run_dir / "processing.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as error:
        (run_dir / "failure.json").write_text(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    return run_dir
