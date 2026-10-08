"""Exactly two samples, two new full-image Swin2SR inferences, cached A/B/C."""
import argparse
import json
import shutil
import time
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
from PIL import Image

from hybrid_candidates import sheet,write_json
from pipeline.fusion import fuse,region_mask
from pipeline.io import read_photo,save_png,sha256
from pipeline.swin2sr import Swin2SRCompressed,CONFIG

ROOT=Path(__file__).resolve().parent
FILES={"A":"A_swinir_x2.png","B":"B_realesrgan_x2.png","S":"S_swin2sr_x2.png","C":"C_hybrid_x2.png",
       "AB":"F_AB_equal.png","AS":"F_AS_equal.png","BS":"F_BS_equal.png","ABS":"F_ABS_equal.png","P":"F_ABS_protected.png"}


def weighted_images(images,weights):
    if len(images)!=len(weights) or not np.isclose(sum(weights),1) or any(w<0 for w in weights):
        raise ValueError("Weights must sum to one")
    if any(im.mode!="RGB" or im.size!=images[0].size for im in images):
        raise ValueError("Mismatched images")
    arrays=[np.asarray(im) for im in images]
    out=np.empty_like(arrays[0])
    for y in range(0,out.shape[0],128):
        chunk=sum(a[y:y+128].astype(np.float32)*w for a,w in zip(arrays,weights))
        out[y:y+128]=np.rint(np.clip(chunk,0,255)).astype(np.uint8)
    return Image.fromarray(out)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",type=Path,default=ROOT/"outputs/batch-20260929-hybrid4")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    old=json.loads((args.baseline/"experiment.json").read_text(encoding="utf-8"))
    entries=[r for r in old["entries"] if r["id"] in ("010","013")]
    if len(entries)!=2:
        raise ValueError("Exactly 010 and 013 required")
    args.output.mkdir(parents=True,exist_ok=False)
    data={"created_utc":datetime.now(timezone.utc).isoformat(),"source_batch":str(args.baseline.resolve()),
          "sample_ids":["010","013"],"new_full_image_inferences":0,"files":FILES,"entries":[],
          "fusion_protocol":{"AB":[0.5,0.5,0],"AS":[0.5,0,0.5],"BS":[0,0.5,0.5],"ABS":[1/3,1/3,1/3],
            "P":"(1-alpha)A + alpha * quantized_average(B,S); alpha is C's previous float32 manual mask",
            "C":"cached previous region-based A/B fusion; unequal weights, not the equal AB control",
            "note":"Uniform averages are controlled experimental baselines, not optimized quality fusion; P is manually protected, not automatic."}}
    start=time.perf_counter()
    engine=Swin2SRCompressed()
    data["model"]={"name":"Swin2SR CompressedSR X4 48","config":CONFIG,"provenance":engine.provenance}
    try:
        for row in entries:
            sid=row["id"]
            source=Path(row["source"]["source_path"])
            if sha256(source)!=row["source"]["source_sha256"]:
                raise RuntimeError("Source changed")
            original,source_meta=read_photo(source)
            prev=args.baseline/sid
            for name,digest in row["files"].items():
                if sha256(prev/name)!=digest:
                    raise RuntimeError(f"Cached artifact changed: {sid}/{name}")
            with Image.open(prev/"original.png") as cached:
                if not np.array_equal(np.asarray(cached),np.asarray(original)):
                    raise RuntimeError("Normalized input mismatch")
            folder=args.output/sid
            folder.mkdir()
            for name in ("original.png",FILES["A"],FILES["B"],FILES["C"],"candidate_weight_float32.npy"):
                shutil.copy2(prev/name,folder/name)
            if "validation" not in data:
                data["validation"]=engine.validate(original)
                print("VALIDATION "+json.dumps(data["validation"]),flush=True)
            print(f"SAMPLE {sid} start Swin2SR",flush=True)
            s,info=engine.infer(original,progress=lambda i,n,t:print(f"{sid}: {i}/{n} tiles size={t}",flush=True))
            save_png(s,folder/FILES["S"])
            data["new_full_image_inferences"]+=1
            a=Image.open(folder/FILES["A"]).convert("RGB")
            b=Image.open(folder/FILES["B"]).convert("RGB")
            c=Image.open(folder/FILES["C"]).convert("RGB")
            mixes={key:weighted_images([a,b,s],weights) for key,weights in data["fusion_protocol"].items() if isinstance(weights,list)}
            alpha=np.load(folder/"candidate_weight_float32.npy",allow_pickle=False)
            mixes["P"]=fuse(a,mixes["BS"],alpha)
            for key,im in mixes.items():
                save_png(im,folder/FILES[key])
            protected=np.zeros(alpha.shape,bool)
            for region in row["fusion"]["config"]["protected_regions"]:
                protected |= np.asarray(region_mask(a.size,region))==255
            with Image.open(folder/FILES["P"]) as disk:
                protected_ok=np.array_equal(np.asarray(disk)[protected],np.asarray(a)[protected])
            if not protected_ok:
                raise RuntimeError("Protected core changed")
            for label,box in row["crops"].items():
                box2=tuple(v*2 for v in box)
                sheet([im.crop(box2) for im in (a,b,s)],["A - SwinIR","B - Real-ESRGAN","S - Swin2SR"],folder/f"models_{label}.png")
                sheet([im.crop(box2) for im in (c,mixes["ABS"],mixes["P"])],["C - Gabungan lama","ABS - Rata-rata 3 model","P - 3 model terlindungi"],folder/f"fusion_{label}.png")
            old_sr=json.loads((Path(row["baseline_run"])/"processing.json").read_text(encoding="utf-8"))
            record={"id":sid,"title":row["fusion"]["config"]["title"],"source":source_meta,
                "output_size":list(s.size),"crops":row["crops"],"inference":info,
                "historical_times":{"A_seconds":old_sr["inference_seconds"],"B_seconds":row["inference"]["inference_seconds"],
                    "note":"A/B reused from earlier runs with different model/tile/native scale. Single-run operational observations, not controlled speed benchmark."},
                "verification":{"source_unchanged":sha256(source)==source_meta["source_sha256"],"P_protected_core_exact_A":protected_ok,
                    "C_copy_exact":sha256(folder/FILES["C"])==row["files"][FILES["C"]]},
                "files":{name:sha256(folder/name) for name in ["original.png","candidate_weight_float32.npy",*FILES.values()]}}
            data["entries"].append(record)
            write_json(args.output/"experiment.json",data)
            print(f"SAMPLE {sid} done {info['inference_seconds']:.2f}s",flush=True)
    finally:
        engine.close()
    data["processing_seconds"]=time.perf_counter()-start
    data["code_hashes"]={str(p.relative_to(ROOT)):sha256(p) for p in (ROOT/"pipeline/swin2sr.py",ROOT/"three_model_experiment.py")}
    write_json(args.output/"experiment.json",data)
    print("DONE "+str(args.output),flush=True)


if __name__=="__main__":
    main()
