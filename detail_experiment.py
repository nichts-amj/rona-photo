"""Version D: reuse four cached samples, no neural inference."""
import argparse
import importlib.metadata
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipeline.detail_fusion import detail_fuse
from pipeline.fusion import region_mask
from pipeline.io import save_png, sha256
from hybrid_candidates import sheet, write_json

ROOT = Path(__file__).resolve().parent
TEXT_REGIONS = {
    "010": [
        {"key":"jalur", "box":[30,425,350,493], "reference":"Jalur Reguler IV"},
        {"key":"tanggal", "box":[468,427,1130,493], "reference":"28 Agustus s.d 8 September 2026"},
        {"key":"kewirausahaan", "box":[648,674,1148,716], "reference":"S1 Kewirausahaan (Entrepreneurship)"},
        {"key":"sistem_informasi", "box":[870,943,1148,980], "reference":"S1 Sistem Informasi"}],
    "020": [
        {"key":"tingkat", "box":[430,509,820,571], "reference":"TINGKAT NASIONAL"},
        {"key":"syarat", "box":[353,806,667,857], "reference":"Syarat Pendaftaran :"},
        {"key":"usia", "box":[164,1108,410,1147], "reference":"USIA 9 - 12 TAHUN"},
        {"key":"kontak", "box":[172,1370,420,1411], "reference":"CONTACT PERSON :"}]
}


def text_sheet(source,c,d,box,path):
    w,h=(box[2]-box[0])*2,(box[3]-box[1])*2
    canvas=Image.new("RGB",(w,h*3+90),"#15344a")
    draw=ImageDraw.Draw(canvas)
    font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",18)
    box2=tuple(v*2 for v in box)
    panels=[source.crop(box).resize((w,h),Image.Resampling.NEAREST),c.crop(box2),d.crop(box2)]
    for index,(im,label) in enumerate(zip(panels,["Sumber: piksel asli diperbesar 2x","C: gabungan sebelumnya","D: detail terkontrol"])):
        y=index*(h+30)
        draw.text((8,y+4),label,font=font,fill="white")
        canvas.paste(im,(0,y+30))
    save_png(canvas,path)


def check_qr(folder):
    sys.path.insert(0,str(ROOT/"tools/qr_runtime"))
    import zxingcpp
    from PIL import ImageOps
    records=[]
    crop=(778,778,1025,1055)
    for key,name,scale in [("source","original.png",1),("A","A_swinir_x2.png",2),("B","B_realesrgan_x2.png",2),
                            ("C","C_hybrid_x2.png",2),("D","D_detail_x2.png",2)]:
        im=Image.open(folder/"020"/name).convert("RGB")
        cut=im.crop(tuple(v*scale for v in crop))
        tries=[]
        views=[("full",im),("crop",cut),("crop_gray",ImageOps.grayscale(cut)),
               ("crop_nearest_2x",cut.resize((cut.width*2,cut.height*2),Image.Resampling.NEAREST))]
        for label,view in views:
            found=zxingcpp.read_barcodes(view,formats=zxingcpp.BarcodeFormat.QRCode,
                try_rotate=True,try_downscale=True,try_invert=True)
            tries.append({"variant":label,"decoded":[{"text":x.text,"bytes_hex":x.bytes.hex(),"format":str(x.format)} for x in found]})
        payloads=sorted({v["bytes_hex"] for t in tries for v in t["decoded"]})
        records.append({"image":key,"attempts":tries,"unique_payloads_hex":payloads,"decoded":bool(payloads)})
    original=records[0]["unique_payloads_hex"]
    return {"library":"zxing-cpp", "version":importlib.metadata.version("zxing-cpp"),"records":records,
        "reference_decoded":bool(original),"all_match_source":all(r["unique_payloads_hex"]==original for r in records) if original else None,
        "note":"No URL was opened. If source does not decode, equality of decoded content cannot be established; pixel preservation is checked separately."}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--baseline",type=Path,default=ROOT/"outputs/batch-20260929-hybrid4")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    previous=json.loads((args.baseline/"experiment.json").read_text(encoding="utf-8"))
    if [e["id"] for e in previous["entries"]] != ["006","010","013","020"]:
        raise ValueError("Expected exactly the approved four samples")
    args.output.mkdir(parents=True,exist_ok=False)
    manifest={"created_utc":datetime.now(timezone.utc).isoformat(),"baseline":str(args.baseline.resolve()),
        "neural_inference_runs":0,"selection":"One fixed parameter set across all four previously inspected samples; pilot, not held-out evaluation.",
        "entries":[],"text_review":[],"manual_text_review_status":"pending"}
    begin=time.perf_counter()
    for row in previous["entries"]:
        sid=row["id"]
        print(f"{sid}: verify cached files",flush=True)
        old=args.baseline/sid
        for name,digest in row["files"].items():
            if sha256(old/name) != digest:
                raise RuntimeError(f"Input cache mismatch: {sid}/{name}")
        source=Path(row["source"]["source_path"])
        if sha256(source) != row["source"]["source_sha256"]:
            raise RuntimeError("Original source changed")
        folder=args.output/sid
        folder.mkdir()
        copies=["original.png","A_swinir_x2.png","B_realesrgan_x2.png","C_hybrid_x2.png","candidate_weight_float32.npy"]
        for name in copies:
            shutil.copy2(old/name,folder/name)
        a=Image.open(folder/"A_swinir_x2.png").convert("RGB")
        b=Image.open(folder/"B_realesrgan_x2.png").convert("RGB")
        c=Image.open(folder/"C_hybrid_x2.png").convert("RGB")
        alpha=np.load(folder/"candidate_weight_float32.npy",allow_pickle=False)
        start=time.perf_counter()
        d,info=detail_fuse(a,b,alpha)
        info["fusion_seconds"]=time.perf_counter()-start
        save_png(d,folder/"D_detail_x2.png")
        with Image.open(folder/"D_detail_x2.png") as check:
            dr=np.asarray(check).copy()
            assert check.info.get("icc_profile")
        ar=np.asarray(a).astype(np.int16)
        change=dr.astype(np.int16)-ar
        protected=np.zeros(alpha.shape,bool)
        for region in row["fusion"]["config"]["protected_regions"]:
            protected |= np.asarray(region_mask(a.size,region)) == 255
        checks={"protected_core_pixels":int(protected.sum()),"protected_core_exact_A":bool(np.all(change[protected]==0)),
            "chroma_channel_differences_exact_A":bool(np.array_equal(change[:,:,0],change[:,:,1]) and np.array_equal(change[:,:,1],change[:,:,2])),
            "output_size_exact_2x_source":list(d.size)==[v*2 for v in row["source"]["normalized_size"]],
            "source_unchanged":sha256(source)==row["source"]["source_sha256"],
            "previous_C_unchanged":sha256(old/"C_hybrid_x2.png")==row["files"]["C_hybrid_x2.png"],
            "rgb_range":[int(dr.min()),int(dr.max())]}
        for key in ("protected_core_exact_A","chroma_channel_differences_exact_A","output_size_exact_2x_source","source_unchanged","previous_C_unchanged"):
            if not checks[key]:
                raise RuntimeError(f"Verification failed: {sid} {key}")
        for label,box in row["crops"].items():
            box2=tuple(v*2 for v in box)
            sheet([im.crop(box2) for im in (a,c,d)],["A - SwinIR","C - Gabungan lama","D - Detail terkontrol"],folder/f"review_{label}_ACD.png")
        original=Image.open(folder/"original.png").convert("RGB")
        for region in TEXT_REGIONS.get(sid,[]):
            text_sheet(original,c,d,region["box"],folder/f"text_{region['key']}.png")
            manifest["text_review"].append({"id":sid,**region,"status":"pending", "reference_type":"assistant transcription of readable source pixels; not original design file or independent ground truth"})
        manifest["entries"].append({"id":sid,"title":row["fusion"]["config"]["title"],"source":row["source"],
            "output_size":list(d.size),"crops":row["crops"],"fusion":info,"verification":checks,
            "files":{name:sha256(folder/name) for name in [*copies,"D_detail_x2.png"]}})
        write_json(args.output/"experiment.json",manifest)
        print(f"{sid}: D saved; fusion {info['fusion_seconds']:.2f}s; changed {info['fraction_changed_pixels']:.1%}",flush=True)
    manifest["qr_check"]=check_qr(args.output)
    manifest["processing_stage_seconds"]=time.perf_counter()-begin
    manifest["code_hashes"]={str(p.relative_to(ROOT)):sha256(p) for p in [ROOT/"pipeline/detail_fusion.py",ROOT/"detail_experiment.py"]}
    write_json(args.output/"experiment.json",manifest)
    write_json(args.output/"qr-check.json",manifest["qr_check"])
    print("QR: "+json.dumps({r["image"]:r["decoded"] for r in manifest["qr_check"]["records"]}),flush=True)
    print(args.output,flush=True)


if __name__ == "__main__":
    main()
