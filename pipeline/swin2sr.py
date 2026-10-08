"""Official CompressedSR x4; primary tuple output, CPU overlap buffers, FP32."""
import ast
import gc
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from PIL import Image

from pipeline.io import sha256
from pipeline.tiling import official_pad, starts, validate_tiles

from pipeline.performance import NonFiniteOutput, TileProfiler, autocast, precision_for, adaptive_tile, run_with_fallback
from resource_paths import ROOT
CONFIG=dict(upscale=4,in_chans=3,img_size=48,window_size=8,img_range=1.,
            depths=[6]*6,embed_dim=180,num_heads=[6]*6,mlp_ratio=2,
            upsampler="pixelshuffle_aux",resi_connection="1conv")


def primary(prediction):
    # The checkpoint's auxiliary output is low resolution and must not be
    # mistaken for the restored image or added to the x4 accumulation buffer.
    if not isinstance(prediction,(tuple,list)) or len(prediction)!=2:
        raise RuntimeError("CompressedSR must return (restored_x4, auxiliary_x1)")
    return prediction[0]


def tiled_forward(rgb,model,device,tile=128,overlap=32,progress=None,precision=None):
    validate_tiles(tile,overlap)
    if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:
        raise ValueError("Expected RGB8 input")
    padded=official_pad(rgb)
    h,w=padded.shape[:2]
    size=min(tile,h,w)
    ov=min(overlap,size-8)
    rows,cols=starts(h,size,ov),starts(w,size,ov)
    output=np.zeros((h*4,w*4,3),dtype=np.float32)
    weight=np.zeros((h*4,w*4,1),dtype=np.float32)
    total=len(rows)*len(cols)
    profiler=TileProfiler(device)
    with torch.inference_mode(), autocast(device, precision):
        for index,(y,x) in enumerate(((y,x) for y in rows for x in cols),1):
            patch=np.ascontiguousarray(padded[y:y+size,x:x+size].transpose(2,0,1))
            tensor=profiler.call("upload_seconds",lambda: torch.from_numpy(patch).unsqueeze(0).to(device=device,dtype=torch.float32).div_(255))
            predictions=profiler.forward(model,tensor,precision)
            pred=primary(predictions)
            if tuple(pred.shape)!=(1,3,size*4,size*4):
                raise RuntimeError("Unexpected primary output shape")
            values=profiler.download(lambda: pred[0].permute(1,2,0).float().cpu().numpy())
            merge_start=time.perf_counter()
            if not np.isfinite(values).all():
                raise NonFiniteOutput("NaN/Inf in Swin2SR output")
            output[y*4:(y+size)*4,x*4:(x+size)*4]+=values
            weight[y*4:(y+size)*4,x*4:(x+size)*4]+=1
            profiler.times["cpu_merge_seconds"]+=time.perf_counter()-merge_start
            del predictions,pred,values,tensor
            if progress:
                progress(index,total,size)
    if np.any(weight==0):
        raise RuntimeError("Uncovered output pixels")
    merge_start=time.perf_counter()
    output/=weight
    profiler.times["cpu_merge_seconds"]+=time.perf_counter()-merge_start
    return output[:rgb.shape[0]*4,:rgb.shape[1]*4],{"tile_used":size,"overlap_used":ov,"tiles":total,
        "padded_input_size":[w,h],"timings":profiler.report(),"merge":"uniform overlap average, CPU float32; auxiliary output discarded"}


def infer_retry(rgb,model,device,tile=128,overlap=32,progress=None,precision=None):
    validate_tiles(tile,overlap)
    attempts=[]
    for size in sorted({tile,*(x for x in (128,96,64) if overlap<x<tile)},reverse=True):
        error_text=None
        try:
            output,info=tiled_forward(rgb,model,device,size,overlap,progress,**({"precision":precision} if precision is not None else {}))
            attempts.append({"tile":size,"status":"success"})
            return output,{**info,"attempts":attempts}
        except torch.cuda.OutOfMemoryError as error:
            error_text=str(error)
        attempts.append({"tile":size,"status":"cuda_oom","error":error_text})
        gc.collect()
        if str(device).startswith("cuda"):
            torch.cuda.empty_cache()
    raise RuntimeError(f"Swin2SR exhausted tile retries: {attempts}")


class Swin2SRCompressed:
    def __init__(self,device="cuda"):
        if device not in ("cuda","cpu") or device=="cuda" and not torch.cuda.is_available():
            raise RuntimeError("Requested device unavailable")
        self.provenance=json.loads((ROOT/"models/swin2sr-provenance.json").read_text())
        for rel,item in self.provenance["files"].items():
            if sha256(ROOT/rel)!=item["sha256"]:
                raise RuntimeError(f"Integrity mismatch {rel}")
        from third_party.swin2sr.network_swin2sr import Swin2SR
        torch.backends.cuda.matmul.allow_tf32=False
        torch.backends.cudnn.allow_tf32=False
        torch.backends.cudnn.benchmark=False
        self.device=torch.device(device)
        start=time.perf_counter()
        self.model=Swin2SR(**CONFIG)
        state=torch.load(ROOT/"models/Swin2SR_CompressedSR_X4_48.pth",map_location="cpu",weights_only=True)
        self.model.load_state_dict(state.get("params",state),strict=True)
        self.model.eval().to(self.device)
        if device=="cuda":
            torch.cuda.synchronize()
        self.load_seconds=time.perf_counter()-start

    def validate(self,image):
        rgb=np.asarray(image.crop((0,0,72,64)))
        adapted,_=tiled_forward(rgb,self.model,self.device,tile=64,overlap=16)
        # Extract only the pinned official test function, without importing its
        # cv2/metrics/degradation CLI. Wrap tuple output so official tile helper
        # receives the primary tensor it expects. Network stays unchanged.
        tree=ast.parse((ROOT/"third_party/swin2sr/inference_reference.py").read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="test")
        module=ast.Module(body=[fn],type_ignores=[])
        scope={"torch":torch}
        exec(compile(module,"pinned_swin2sr_test","exec"),scope)
        class PrimaryOnly(torch.nn.Module):
            def __init__(self,model):
                super().__init__();self.model=model
            def forward(self,x):
                return primary(self.model(x))
        tensor=torch.from_numpy(official_pad(rgb).copy().transpose(2,0,1)).unsqueeze(0).to(self.device,torch.float32)/255
        with torch.inference_mode():
            reference=scope["test"](tensor,PrimaryOnly(self.model),SimpleNamespace(tile=64,tile_overlap=16,scale=4),8)
            reference=reference[0,:,:rgb.shape[0]*4,:rgb.shape[1]*4].permute(1,2,0).cpu().numpy()
            full=primary(self.model(tensor))[0,:,:rgb.shape[0]*4,:rgb.shape[1]*4].permute(1,2,0).cpu().numpy()
        delta=np.abs(adapted-reference)
        full_delta=np.abs(adapted-full)
        data={"crop_input_size":[72,64],"reference_tile_max_error":float(delta.max()),
              "reference_tile_mean_error":float(delta.mean()),"tolerance":2e-5,"passed":bool(delta.max()<2e-5),
              "tile_vs_full_max_error":float(full_delta.max()),"tile_vs_full_mean_error":float(full_delta.mean()),
              "reference_adaptation":"Primary tuple output wrapper only; official averaging function unchanged.",
              "note":"Tiled and full-image attention are not assumed identical; no ground-truth quality claim."}
        if not data["passed"]:
            raise RuntimeError(f"Reference tiling mismatch {data}")
        return data

    def infer(self,image,progress=None,tile=128,overlap=32,output_scale=2):
        if output_scale not in (2,4):raise ValueError("Output scale must be 2 or 4")
        if image.mode!="RGB" or image.width*image.height>50_000_000:
            raise ValueError("RGB image <=50 megapixels required")
        if self.device.type=="cuda":
            torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
        start=time.perf_counter()
        from pipeline.tiling import validate_tiles
        validate_tiles(tile,overlap)
        precision=precision_for(self.device,"S",getattr(self,"gpu_optimization",False))
        requested_tile=tile
        tile=adaptive_tile(self.device,"S",tile,precision)
        # Keep enough room for the configured overlap, even under memory pressure.
        tile=max(tile,overlap+8)
        native,info=run_with_fallback(
            lambda dtype: infer_retry(np.asarray(image),self.model,self.device,tile=tile,overlap=overlap,progress=progress,precision=dtype),
            self.device,precision)
        info.update(tile_requested=requested_tile)
        if self.device.type=="cuda":
            torch.cuda.synchronize()
        infer_seconds=time.perf_counter()-start
        np.clip(native,0,1,out=native)
        native*=255
        np.rint(native,out=native)
        result=Image.fromarray(native.astype(np.uint8))
        if output_scale==2:
            result=result.resize((image.width*2,image.height*2),Image.Resampling.LANCZOS)
        info.update({"inference_seconds":infer_seconds,"including_export_resize_seconds":time.perf_counter()-start,
            "model_load_seconds":self.load_seconds,"native_scale":4,"output_scale":output_scale,"input_resized":False,
            "resize":"none (native x4)" if output_scale==4 else "Pillow LANCZOS x4 RGB8 to x2","tf32":False,"device":str(self.device),
            "peak_cuda_allocated_bytes":torch.cuda.max_memory_allocated() if self.device.type=="cuda" else None,
            "peak_cuda_reserved_bytes":torch.cuda.max_memory_reserved() if self.device.type=="cuda" else None,
            "gpu_name":torch.cuda.get_device_name() if self.device.type=="cuda" else None})
        return result,info

    def close(self):
        self.model=None;gc.collect()
        if self.device.type=="cuda":
            torch.cuda.empty_cache()
