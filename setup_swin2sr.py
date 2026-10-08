"""Download pinned official Swin2SR CompressedSR sources and checkpoint."""
import json
import urllib.request
from pathlib import Path
from pipeline.io import sha256

ROOT=Path(__file__).resolve().parent
COMMIT="6f25d7689813f7dd12c5a212b638066fa71bc9e6"
BASE=f"https://raw.githubusercontent.com/mv-lab/swin2sr/{COMMIT}"
SOURCES={"third_party/swin2sr/network_swin2sr.py":f"{BASE}/models/network_swin2sr.py",
         "third_party/swin2sr/inference_reference.py":f"{BASE}/main_test_swin2sr.py",
         "third_party/swin2sr/LICENSE":f"{BASE}/LICENSE",
         "models/Swin2SR_CompressedSR_X4_48.pth":"https://github.com/mv-lab/swin2sr/releases/download/v0.0.1/Swin2SR_CompressedSR_X4_48.pth"}


def main():
    dest=ROOT/"models/swin2sr-provenance.json"
    if dest.exists():
        data=json.loads(dest.read_text())
        for name,item in data["files"].items():
            if sha256(ROOT/name)!=item["sha256"]:
                raise RuntimeError(f"Hash mismatch {name}")
        print("Swin2SR sources/checkpoint verified")
        return
    entries={}
    for name,url in SOURCES.items():
        path=ROOT/name
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            raise FileExistsError(f"Unregistered file {name}")
        temporary=path.with_suffix(path.suffix+".part")
        print(f"Downloading {name}",flush=True)
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"photo-retouch-research"}),timeout=60) as response, temporary.open("wb") as stream:
            while block:=response.read(1024*1024):
                stream.write(block)
        temporary.replace(path)
        entries[name]={"url":url,"sha256":sha256(path),"bytes":path.stat().st_size}
    dest.write_text(json.dumps({"repository":"https://github.com/mv-lab/swin2sr","commit":COMMIT,"files":entries,
        "architecture":"unmodified official network_swin2sr.py",
        "hash_note":"Local SHA256 after official HTTPS download; not independently published author checksums."},indent=2),encoding="utf-8")
    print("Setup complete",flush=True)


if __name__=="__main__":
    main()
