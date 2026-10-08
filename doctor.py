"""Inspect only the interpreter actually running this command."""
import argparse
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def inspect_environment(probe_cuda=False):
    packages = {}
    for name in ("Pillow", "numpy", "torch", "torchvision", "timm", "scikit-image", "lpips"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    report = {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
              "packages": packages, "nvidia_smi": None, "cuda_probe": "not_requested"}
    executable = shutil.which("nvidia-smi")
    if executable:
        try:
            query = subprocess.run([executable, "--query-gpu=name,driver_version,memory.total,memory.used", "--format=csv"],
                                   capture_output=True, text=True, timeout=15, check=False)
            report["nvidia_smi"] = {"exit_code": query.returncode, "stdout": query.stdout.strip(), "stderr": query.stderr.strip()}
        except (OSError, subprocess.TimeoutExpired) as error:
            report["nvidia_smi"] = {"error": str(error)}
    if probe_cuda:
        if packages["torch"] is None:
            report["cuda_probe"] = {"status": "unavailable", "reason": "PyTorch tidak terpasang pada interpreter ini."}
        else:
            try:
                import torch
                available = torch.cuda.is_available()
                report["cuda_probe"] = {"available": available, "torch_cuda": torch.version.cuda}
                if available:
                    value = torch.ones((8, 8), device="cuda")
                    result = (value @ value).sum().item()
                    report["cuda_probe"].update({"device": torch.cuda.get_device_name(0), "small_matmul_passed": result == 512.0})
            except Exception as error:
                report["cuda_probe"] = {"status": "failed", "error": str(error)}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-cuda", action="store_true")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    payload = json.dumps(inspect_environment(arguments.probe_cuda), ensure_ascii=False, indent=2)
    print(payload)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8")
