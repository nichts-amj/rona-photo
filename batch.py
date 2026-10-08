"""Sequential, restartable folder evaluation; never adds synthetic degradation."""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from pipeline.io import sha256


def atomic_json(path, value):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def inventory(folder):
    entries = []
    # Inspect every file, including misleading extensions; no silent exclusion.
    for number, path in enumerate(sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.name.casefold()), 1):
        entry = {"id": f"{number:03}", "name": path.name, "path": str(path.resolve()),
                 "sha256": sha256(path), "status": "pending"}
        try:
            with Image.open(path) as image:
                entry.update({"detected_format": image.format, "raw_size": list(image.size), "raw_mode": image.mode,
                              "icc_present": bool(image.info.get("icc_profile")), "frames": getattr(image, "n_frames", 1)})
        except Exception as error:
            entry["inspection_error"] = str(error)
        entries.append(entry)
    if not entries:
        raise ValueError("Folder tidak berisi file.")
    return entries


def reusable(entry, root):
    if entry["status"] != "success":
        return False
    try:
        manifest_path = root / entry["run"] / "processing.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["source"]["source_sha256"] != entry["sha256"] or manifest["status"] != "success":
            return False
        return all(sha256(manifest_path.parent / name) == data["sha256"] for name, data in manifest["artifacts"].items())
    except (OSError, KeyError, ValueError):
        return False


def run_batch(folder, destination, device="cuda", tile=128, overlap=32, resume=False, runner=None):
    folder = folder.resolve(strict=True)
    destination = destination.resolve()
    if destination == folder or folder in destination.parents:
        raise ValueError("Folder hasil harus berada di luar folder input.")
    current = inventory(folder)
    config = {"mode": "sr2", "scale": 2, "device": device, "precision": "float32", "tile": tile, "overlap": overlap}
    journal_path = destination / "batch.json"
    if resume:
        state = json.loads(journal_path.read_text(encoding="utf-8"))
        if state["input_folder"] != str(folder) or state["config"] != config:
            raise ValueError("Folder input atau konfigurasi resume berbeda.")
        if [(e["name"], e["sha256"]) for e in current] != [(e["name"], e["sha256"]) for e in state["entries"]]:
            raise ValueError("Daftar file/hash input berubah; buat batch baru agar eksperimen tidak tercampur.")
    else:
        destination.mkdir(parents=True, exist_ok=False)
        state = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
                 "input_folder": str(folder), "config": config, "entries": current, "status": "running",
                 "quality_metrics": None, "quality_note": "Tanpa ground truth: penilaian visual manual, bukan PSNR/SSIM/LPIPS."}
    from pipeline.batch_report import write_report
    if runner is None:
        from pipeline.sr_run import run_sr
        runner = run_sr
    state["status"] = "running"
    atomic_json(journal_path, state)
    write_report(state, destination)
    for entry in state["entries"]:
        if reusable(entry, destination):
            print(f"{entry['id']}: hasil terverifikasi, dilewati.", flush=True)
            continue
        entry["status"] = "running"
        entry.pop("error", None)
        atomic_json(journal_path, state)
        print(f"\n[{entry['id']}/{len(state['entries']):03}] {entry['name']}", flush=True)
        start = time.perf_counter()
        try:
            path = Path(entry["path"])
            if sha256(path) != entry["sha256"]:
                raise ValueError("Input berubah setelah inventarisasi.")
            run = runner(path, destination / "images" / entry["id"], device, tile, overlap)
            metadata = json.loads((run / "processing.json").read_text(encoding="utf-8"))
            entry["run"] = run.relative_to(destination).as_posix()
            entry["source_unchanged"] = sha256(path) == entry["sha256"]
            if not entry["source_unchanged"]:
                raise ValueError("Hash input berubah selama pemrosesan.")
            entry.update({"status": "success", "input_size": metadata["source"]["normalized_size"],
                          "output_size": metadata["output_size"], "inference_seconds": metadata["inference_seconds"],
                          "peak_allocated_bytes": metadata["peak_cuda_allocated_bytes"],
                          "peak_reserved_bytes": metadata["peak_cuda_reserved_bytes"],
                          "tile_used": metadata["tile_used"], "overlap_used": metadata["overlap_used"],
                          "oom_retries": sum(attempt["status"] == "cuda_oom" for attempt in metadata["attempts"]),
                          "warnings": metadata["source"]["warnings"]})
        except Exception as error:
            entry.update({"status": "failed", "error": str(error)})
            print(f"Gagal {entry['id']}: {error}", flush=True)
        entry["elapsed_seconds"] = time.perf_counter() - start
        atomic_json(journal_path, state)
        write_report(state, destination)
        print(f"Selesai {entry['id']}: {entry['status']}", flush=True)
    state["status"] = "complete" if all(e["status"] == "success" for e in state["entries"]) else "complete_with_failures"
    state["finished_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_json(journal_path, state)
    write_report(state, destination)
    return state


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--tile", type=int, default=128)
    parser.add_argument("--overlap", type=int, default=32)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    state = run_batch(args.input_dir, args.output_dir, args.device, args.tile, args.overlap, args.resume)
    print(f"Batch {state['status']}: {args.output_dir.resolve()}", flush=True)
    raise SystemExit(0 if state["status"] == "complete" else 1)
