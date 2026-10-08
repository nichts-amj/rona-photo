"""Verify completed exports without re-running GPU inference."""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from PIL import Image

from pipeline.io import sha256


def verify(root):
    state = json.loads((root / "batch.json").read_text(encoding="utf-8"))
    checks = []
    for entry in state["entries"]:
        check = {"id": entry["id"], "source_unchanged": sha256(Path(entry["path"])) == entry["sha256"]}
        if entry["status"] != "success":
            check.update({"passed": False, "error": entry.get("error", "not completed")})
        else:
            run = root / entry["run"]
            manifest = json.loads((run / "processing.json").read_text(encoding="utf-8"))
            check["artifact_hashes_match"] = all(sha256(run / name) == info["sha256"] for name, info in manifest["artifacts"].items())
            with Image.open(run / "input_normalized.png") as image:
                expected = (image.width * 2, image.height * 2)
                check["input_size_matches_log"] = list(image.size) == entry["input_size"]
                image.verify()
            for name in ("result_swinir_x2.png", "baseline_bicubic_x2.png"):
                with Image.open(run / name) as image:
                    check[name + "_size_color_valid"] = image.size == expected and image.mode == "RGB" and bool(image.info.get("icc_profile"))
                    image.verify()
            check["configuration_matches"] = (manifest["requested_tile"] == state["config"]["tile"] and
                manifest["requested_overlap"] == state["config"]["overlap"] and manifest["precision"] == state["config"]["precision"] and
                manifest["scale"] == 2 and not manifest["synthetic_degradation_applied"])
            check["passed"] = all(value is True for key, value in check.items() if key != "id")
        checks.append(check)
    successful = [entry for entry in state["entries"] if entry["status"] == "success"]
    times = [entry["inference_seconds"] for entry in successful]
    report = {"all_passed": all(check["passed"] for check in checks), "images": len(checks), "checks": checks,
        "counts": dict(Counter(entry["status"] for entry in state["entries"])),
        "formats": dict(Counter(entry["detected_format"] for entry in successful)),
        "sum_inference_seconds": sum(times), "min_inference_seconds": min(times) if times else None,
        "median_inference_seconds": statistics.median(times) if times else None, "max_inference_seconds": max(times) if times else None,
        "max_allocated_bytes": max((entry["peak_allocated_bytes"] or 0 for entry in successful), default=0),
        "max_reserved_bytes": max((entry["peak_reserved_bytes"] or 0 for entry in successful), default=0),
        "oom_retries": sum(entry["oom_retries"] for entry in successful),
        "interpretation": "Single run per image of different sizes. Timing distribution is not a repeatability benchmark; no quality scores computed."}
    (root / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch_dir", type=Path)
    arguments = parser.parse_args()
    result = verify(arguments.batch_dir)
    print(json.dumps({key: value for key, value in result.items() if key != "checks"}, indent=2))
    raise SystemExit(0 if result["all_passed"] else 1)
