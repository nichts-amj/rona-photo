"""Fetch pinned upstream architecture and released compact Real-ESRGAN weights."""
import json
import urllib.request
from pathlib import Path

from pipeline.io import sha256

ROOT = Path(__file__).resolve().parent
COMMIT = "fa4c8a03ae3dbc9ea6ed471a6ab5da94ac15c2ea"
BASE = f"https://raw.githubusercontent.com/xinntao/Real-ESRGAN/{COMMIT}"
SOURCES = {
    "third_party/realesrgan/srvgg_arch_upstream.py": f"{BASE}/realesrgan/archs/srvgg_arch.py",
    "third_party/realesrgan/LICENSE": f"{BASE}/LICENSE",
    "third_party/realesrgan/inference_reference.py": f"{BASE}/inference_realesrgan.py",
    "third_party/realesrgan/utils_reference.py": f"{BASE}/realesrgan/utils.py",
    **{f"models/{name}.pth": f"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/{name}.pth"
       for name in ("realesr-general-x4v3", "realesr-general-wdn-x4v3")},
}


def main():
    manifest = ROOT / "models/realesrgan-provenance.json"
    if manifest.exists():
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        if previous["commit"] != COMMIT:
            raise RuntimeError("Unexpected source commit")
        for rel, item in previous["files"].items():
            if sha256(ROOT / rel) != item["sha256"]:
                raise RuntimeError(f"Integrity failure: {rel}")
        print("Verified existing Real-ESRGAN sources and checkpoints.")
        return
    records = {}
    for rel, url in SOURCES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"Unregistered file: {path}")
        print(f"Download {rel}", flush=True)
        request = urllib.request.Request(url, headers={"User-Agent": "photo-retouch-research"})
        temporary = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        temporary.replace(path)
        records[rel] = {"url": url, "sha256": sha256(path), "bytes": path.stat().st_size}
    # The registry is unrelated to forward inference. Retain the upstream copy
    # and remove ONLY its BasicSR registration dependency in the importable copy.
    original = (ROOT / "third_party/realesrgan/srvgg_arch_upstream.py").read_text(encoding="utf-8")
    tokens = ["from basicsr.utils.registry import ARCH_REGISTRY\n", "@ARCH_REGISTRY.register()\n"]
    adapted = original
    for token in tokens:
        if adapted.count(token) != 1:
            raise RuntimeError("Unexpected upstream registration code")
        adapted = adapted.replace(token, "")
    rel = "third_party/realesrgan/srvgg_arch.py"
    (ROOT / rel).write_text(adapted, encoding="utf-8")
    records[rel] = {"sha256": sha256(ROOT / rel), "adaptation": "Removed BasicSR registry import and decorator only; network and forward unchanged."}
    manifest.write_text(json.dumps({"repository": "https://github.com/xinntao/Real-ESRGAN",
        "commit": COMMIT, "files": records,
        "hash_note": "Locally computed SHA-256 after official HTTPS downloads, not author-published checksums."}, indent=2), encoding="utf-8")
    print("Setup complete.", flush=True)


if __name__ == "__main__":
    main()
