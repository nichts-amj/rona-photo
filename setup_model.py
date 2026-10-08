"""Download the pinned official SwinIR architecture and x2 checkpoint."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMIT = "6545850fbf8df298df73d81f3e8cba638787c8bd"
CHECKPOINT = "002_lightweightSR_DIV2K_s64w8_SwinIR-S_x2.pth"
SOURCES = {
    "third_party/swinir/network_swinir.py": f"https://raw.githubusercontent.com/JingyunLiang/SwinIR/{COMMIT}/models/network_swinir.py",
    "third_party/swinir/LICENSE": f"https://raw.githubusercontent.com/JingyunLiang/SwinIR/{COMMIT}/LICENSE",
    "third_party/swinir/main_test_swinir_reference.py": f"https://raw.githubusercontent.com/JingyunLiang/SwinIR/{COMMIT}/main_test_swinir.py",
    f"models/{CHECKPOINT}": f"https://github.com/JingyunLiang/SwinIR/releases/download/v0.0/{CHECKPOINT}",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    manifest_path = ROOT / "models/provenance.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["commit"] != COMMIT:
            raise RuntimeError("Commit pada manifest berbeda; periksa sebelum mengganti sumber.")
        for relative, item in previous["files"].items():
            if not (ROOT / relative).is_file() or digest(ROOT / relative) != item["sha256"]:
                raise RuntimeError(f"Integritas file gagal: {relative}")
        print("Semua sumber/checkpoint sudah tersedia dan hash cocok.")
        return
    entries = {}
    for relative, url in SOURCES.items():
        destination = ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        print(f"Mengunduh {relative}", flush=True)
        request = urllib.request.Request(url, headers={"User-Agent": "photo-retouch-research"})
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        temporary.replace(destination)
        entries[relative] = {"url": url, "sha256": digest(destination), "bytes": destination.stat().st_size}
    manifest_path.write_text(json.dumps({"repository": "https://github.com/JingyunLiang/SwinIR",
        "commit": COMMIT, "checkpoint": CHECKPOINT, "files": entries,
        "hash_note": "SHA-256 dihitung setelah unduhan HTTPS; bukan checksum terbitan penulis."}, indent=2), encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
