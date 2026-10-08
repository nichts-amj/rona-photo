import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from pipeline.io import read_photo, save_png, sha256
from pipeline.run import comparison


def run_sr(input_path: Path, output_root: Path, device="cuda", tile=128, overlap=32):
    from pipeline.tiling import validate_tiles
    from pipeline.upscale import SwinIRX2
    validate_tiles(tile, overlap)
    start = time.perf_counter()
    before, source = read_photo(input_path)
    timestamp = datetime.now(timezone.utc)
    run_dir = output_root.resolve() / (timestamp.strftime("%Y%m%dT%H%M%S_%fZ") + "_sr2_" + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    model = None
    try:
        save_png(before, run_dir / "input_normalized.png")
        model = SwinIRX2(device)
        metadata = model.metadata()
        result, stats = model.infer(before, tile, overlap,
            lambda done, total, size: print(f"Tile {done}/{total} ({size}px, FP32)", flush=True))
        model.close()
        model = None
        if result.size != (before.width * 2, before.height * 2):
            raise RuntimeError("Ukuran hasil bukan tepat x2.")
        save_png(result, run_dir / "result_swinir_x2.png")
        baseline = before.resize(result.size, Image.Resampling.BICUBIC)
        save_png(baseline, run_dir / "baseline_bicubic_x2.png")
        save_png(comparison(baseline, result, "Input diperbesar bicubic x2 (pembanding)", "SwinIR lightweight x2"), run_dir / "comparison.png")
        manifest = {"schema_version": 2, "status": "success", "timestamp_utc": timestamp.isoformat(),
            "mode": "sr2", "scale": 2, "restoration_applied": True, "synthetic_degradation_applied": False,
            "source": source, "output_size": list(result.size), "model": metadata,
            "requested_tile": tile, "requested_overlap": overlap, **stats,
            "metrics": None, "metrics_note": "Foto nyata tanpa pasangan ground truth; tidak menghitung metrik kualitas referensi.",
            "total_seconds_before_manifest": time.perf_counter() - start,
            "artifacts": {name: {"sha256": sha256(run_dir / name)} for name in
                          ("input_normalized.png", "result_swinir_x2.png", "baseline_bicubic_x2.png", "comparison.png")}}
        (run_dir / "processing.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as error:
        (run_dir / "failure.json").write_text(json.dumps({"status": "failed", "source": source,
            "error": str(error), "oom_attempts": getattr(error, "attempts", [])}, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        if model is not None:
            model.close()
    return run_dir
