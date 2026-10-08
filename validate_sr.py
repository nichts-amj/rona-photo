"""Engineering parity tests, not restoration quality metrics against ground truth."""
import argparse
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from pipeline.io import read_photo, save_png
from pipeline.tiling import official_pad
from pipeline.upscale import ROOT, SwinIRX2


def delta(a, b):
    difference = np.abs(a - b)
    return {"mae_0_1": float(difference.mean()), "max_abs_0_1": float(difference.max()),
            "rmse_0_1": float(np.sqrt(np.mean(difference ** 2)))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "audit/sr-validation.json")
    args = parser.parse_args()
    # Execute only the unmodified upstream inference function, avoiding unrelated
    # OpenCV/metric imports and upstream dataset/degradation code.
    upstream = ast.parse((ROOT / "third_party/swinir/main_test_swinir_reference.py").read_text(encoding="utf-8"))
    function = next(node for node in upstream.body if isinstance(node, ast.FunctionDef) and node.name == "test")
    namespace = {"torch": torch}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "official_swinir_test", "exec"), namespace)
    official_test = namespace["test"]
    image, _ = read_photo(args.input)
    if image.width < 376 or image.height < 380:
        raise ValueError("Validasi crop wajah ini memerlukan sampel minimal 376x380.")
    # A documented crop for engineering comparison; application still uses full photo.
    crop = image.crop((200, 220, 376, 380))
    rgb = np.asarray(crop)
    model = SwinIRX2("cuda")
    report = {"purpose": "engineering parity; not quality improvement metrics", "crop_xyxy": [200, 220, 376, 380],
              "model": model.metadata(), "comparisons": {}}
    try:
        cpu_result, stats = model.infer_float(rgb, tile=128, overlap=32)
        input_tensor = torch.from_numpy(np.ascontiguousarray(official_pad(rgb).transpose(2, 0, 1))).float().div_(255).unsqueeze(0).cuda()
        with torch.inference_mode():
            reference_tiled = official_test(input_tensor, model.model, SimpleNamespace(tile=128, tile_overlap=32, scale=2), 8)
            reference_tiled = reference_tiled[0, :, :320, :352].permute(1, 2, 0).cpu().numpy()
            full = official_test(input_tensor, model.model, SimpleNamespace(tile=None), 8)
            full = full[0, :, :320, :352].permute(1, 2, 0).cpu().numpy()
        parity = delta(cpu_result, reference_tiled)
        report["comparisons"]["cpu_accumulator_vs_official_tiled"] = parity
        report["comparisons"]["tiled_vs_full_frame"] = delta(cpu_result, full)
        report["cpu_accumulator_parity_passed"] = parity["max_abs_0_1"] <= 2e-5
        report["finite"] = bool(np.isfinite(cpu_result).all())
        report["correct_output_shape"] = cpu_result.shape == (320, 352, 3)
        report["tiled_stats"] = stats
        # Retain crops as reviewable evidence, without calling them application results.
        from PIL import Image
        args.output.parent.mkdir(parents=True, exist_ok=True)
        for name, array in (("validation_tiled", cpu_result), ("validation_full", full)):
            save_png(Image.fromarray(np.rint(np.clip(array, 0, 1) * 255).astype(np.uint8)), args.output.parent / f"{name}.png")
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "model"}, indent=2))
        if not (report["cpu_accumulator_parity_passed"] and report["finite"] and report["correct_output_shape"]):
            raise RuntimeError("Uji parity SwinIR gagal.")
    finally:
        model.close()


if __name__ == "__main__":
    main()
