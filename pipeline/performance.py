"""Scoped CUDA optimization; CPU/reference inference remains float32."""
from contextlib import nullcontext
import gc
import time
import torch


class NonFiniteOutput(RuntimeError):
    """Retry a numerically unstable mixed-precision run in float32."""


def precision_for(device, model, enabled=True):
    if not enabled or not str(device).startswith('cuda'):
        return None
    # Tensor cores on Volta and newer. Transformer BF16 has FP32's exponent
    # range, avoiding FP16 overflow; older GPUs use the reference path.
    if torch.cuda.get_device_capability()[0] < 7:
        return None
    if model == 'B':
        return torch.float16
    return torch.bfloat16 if torch.cuda.is_bf16_supported() else None


def autocast(device, precision):
    return torch.autocast('cuda', dtype=precision) if precision is not None else nullcontext()


class TileProfiler:
    """CUDA events are read after the existing blocking output copy."""
    def __init__(self, device):
        self.device = device
        self.cuda = str(device).startswith('cuda')
        self.events = None
        self.times = {'upload_seconds': 0.0, 'forward_enqueue_seconds': 0.0,
                      'download_wait_seconds': 0.0, 'cpu_merge_seconds': 0.0,
                      'gpu_compute_seconds': 0.0 if self.cuda else None}

    def call(self, stage, function):
        start = time.perf_counter()
        result = function()
        self.times[stage] += time.perf_counter() - start
        return result

    def forward(self, model, tensor, precision):
        if self.cuda:
            self.events = (torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True))
            self.events[0].record()
        with autocast(self.device, precision):
            result = self.call('forward_enqueue_seconds', lambda: model(tensor))
        if self.cuda:
            self.events[1].record()
        return result

    def download(self, function):
        result = self.call('download_wait_seconds', function)
        if self.events is not None:
            self.times['gpu_compute_seconds'] += self.events[0].elapsed_time(self.events[1]) / 1000
            self.events = None
        return result

    def report(self):
        return {**self.times, 'note': 'CUDA compute overlaps download wait; do not sum GPU and wall times.'}


def adaptive_tile(device, model, requested, precision):
    """Configured tile is a ceiling; never enlarge it or reduce overlap."""
    if precision is None or not str(device).startswith('cuda'):
        return requested
    free, _ = torch.cuda.mem_get_info()
    gib = free / 1024**3
    limits = {'B': (128, 256, 512), 'S': (64, 96, 128), 'H': (64, 64, 96)}
    limit = limits[model][0 if gib < 1 else 1 if gib < 2 else 2]
    return min(requested, limit)


def run_with_fallback(run, device, precision):
    fallback = None
    try:
        output, info = run(precision)
    except NonFiniteOutput as error:
        if precision is None:
            raise
        fallback = str(error)
    # Exit the exception scope first so its traceback releases tile buffers.
    if fallback is not None:
        gc.collect()
        torch.cuda.empty_cache()
        output, info = run(None)
        precision = None
    info.update(precision=str(precision).removeprefix('torch.') if precision is not None else 'float32',
                precision_fallback=fallback)
    return output, info
