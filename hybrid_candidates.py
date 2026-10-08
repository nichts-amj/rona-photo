"""Four-sample pilot; reuse verified SwinIR exports, infer only one new model."""
import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from pipeline.io import read_photo, save_png, sha256
from pipeline.realesrgan import CompactRealESRGAN, tiled_x4

ROOT = Path(__file__).resolve().parent
SELECTED = ("006", "010", "013", "020")
CROPS = {
    "006": {"bulu": [390, 560, 610, 780], "bunga": [0, 430, 220, 650]},
    "010": {"teks": [865, 800, 1085, 1020], "logo": [10, 10, 230, 230]},
    "013": {"wajah": [170, 420, 390, 640], "kain": [780, 850, 1000, 1070]},
    "020": {"teks": [275, 805, 495, 1025], "qr": [785, 805, 1005, 1025]},
}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def sheet(images, labels, target):
    w, h = images[0].size
    canvas = Image.new("RGB", (w*len(images), h+36), "#132237")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 19)
    for i, (img, label) in enumerate(zip(images, labels)):
        draw.text((i*w+10, 7), label, font=font, fill="white")
        canvas.paste(img, (i*w, 36))
    save_png(canvas, target)


def validate_model(engine, image):
    # One small crop checks CNN tiling against a full forward pass, including
    # the outer image edge and internal boundaries. It is not another sample.
    rgb = np.asarray(image.crop((0, 0, 143, 137)))
    tensor = torch.from_numpy(rgb.copy().transpose(2, 0, 1)).unsqueeze(0).to(engine.device, torch.float32)/255
    with torch.inference_mode():
        expected = engine.model(tensor)[0].permute(1, 2, 0).cpu().numpy()
    actual, _ = tiled_x4(rgb, engine.model, engine.device, tile=64, floating=True)
    delta = np.abs(expected-actual)
    report = {"crop_input_size": [143, 137], "max_abs_error_0_1": float(delta.max()),
              "mean_abs_error_0_1": float(delta.mean()), "tolerance": 2e-5,
              "passed": bool(delta.max() < 2e-5), "scope": "tiled vs full forward of pinned unchanged network, before resize"}
    if not report["passed"]:
        raise RuntimeError(f"Tiling parity failed: {report}")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=ROOT / "outputs/batch-20260928-test21")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    batch = json.loads((args.baseline / "batch.json").read_text(encoding="utf-8"))
    entries = [e for e in batch["entries"] if e["id"] in SELECTED]
    if len(entries) != 4:
        raise ValueError("Exactly four selected baseline samples required")
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "baseline": str(args.baseline.resolve()),
                "sample_ids": list(SELECTED), "denoise_strength": 0.5, "entries": [],
                "notes": ["Pilot only; no reference high-resolution ground truth.",
                          "Manual masks will be selected after inspecting A/B crops; not an automatic segmentation system."]}
    start = time.perf_counter()
    engine = CompactRealESRGAN(denoise=0.5)
    manifest["model_provenance"] = engine.provenance
    try:
        for e in entries:
            sid = e["id"]
            print(f"SAMPLE {sid} start", flush=True)
            source = Path(e["path"])
            if sha256(source) != e["sha256"]:
                raise RuntimeError(f"Original changed since baseline: {sid}")
            image, metadata = read_photo(source)
            old = args.baseline / e["run"]
            with Image.open(old / "input_normalized.png") as previous:
                if not np.array_equal(np.asarray(previous), np.asarray(image)):
                    raise RuntimeError("Normalized pixels differ from baseline")
            folder = args.output / sid
            folder.mkdir()
            for original, name in (("input_normalized.png", "original.png"), ("result_swinir_x2.png", "A_swinir_x2.png"),
                                   ("baseline_bicubic_x2.png", "baseline_bicubic_x2.png")):
                shutil.copy2(old / original, folder / name)
            if "tiling_validation" not in manifest:
                manifest["tiling_validation"] = validate_model(engine, image)
                print(f"Tiling parity: {manifest['tiling_validation']}", flush=True)
            candidate, stats = engine.infer(image, progress=lambda i,n,t: print(f"{sid}: {i}/{n} tiles ({t})", flush=True))
            save_png(candidate, folder / "B_realesrgan_x2.png")
            row = {"id": sid, "name": e["name"], "source": metadata, "baseline_run": str(old.resolve()),
                   "output_size": list(candidate.size), "inference": stats, "crops": CROPS[sid],
                   "source_unchanged": sha256(source) == e["sha256"], "files": {}}
            if not row["source_unchanged"]:
                raise RuntimeError("Source changed during inference")
            for name in ("original.png", "A_swinir_x2.png", "baseline_bicubic_x2.png", "B_realesrgan_x2.png"):
                row["files"][name] = sha256(folder/name)
            with Image.open(folder/"A_swinir_x2.png") as a, Image.open(folder/"baseline_bicubic_x2.png") as bicubic:
                for label, box in CROPS[sid].items():
                    box2 = tuple(v*2 for v in box)
                    sheet([i.crop(box2) for i in (bicubic, a, candidate)], ["Asli diperbesar", "A - SwinIR", "B - Real-ESRGAN"], folder/f"review_{label}_AB.png")
            manifest["entries"].append(row)
            write_json(args.output/"experiment.json", manifest)
            print(f"SAMPLE {sid} done: {stats['inference_seconds']:.2f}s", flush=True)
    finally:
        engine.close()
    manifest["candidate_stage_seconds"] = time.perf_counter()-start
    write_json(args.output/"experiment.json", manifest)
    print(f"DONE {args.output}", flush=True)


if __name__ == "__main__":
    main()
