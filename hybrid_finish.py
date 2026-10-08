"""Create auditable A/B/C comparisons from cached four-sample inference."""
import argparse
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hybrid_candidates import sheet, write_json
from pipeline.fusion import fuse, make_alpha
from pipeline.io import save_png, sha256

ROOT = Path(__file__).resolve().parent


def make_report(folder, manifest):
    rows = manifest["entries"]
    data = [{"id": r["id"], "title": r["fusion"]["config"]["title"],
             "assessment": r["fusion"]["config"]["assessment"], "crops": list(r["crops"]),
             "size": r["output_size"], "seconds": round(r["inference"]["inference_seconds"], 2)} for r in rows]
    total = sum(r["inference"]["inference_seconds"] for r in rows)
    page = '''<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Uji gabungan 4 sampel — SwinIR + Real-ESRGAN</title>
<style>
:root{font:16px/1.55 system-ui;color:#203048;background:#eef2f7}*{box-sizing:border-box}body{margin:0}main{max-width:1180px;margin:auto;padding:30px 24px 65px}h1{font-size:clamp(25px,4vw,38px);line-height:1.15;margin:12px 0}h2{font-size:23px}p{max-width:1000px}.tag{color:#087f7b;font-weight:750;letter-spacing:.07em;font-size:13px}.card{background:white;border:1px solid #d6e0e9;border-radius:14px;padding:20px;margin:18px 0;box-shadow:0 4px 15px #25375208}.muted{color:#526579}button,select,a.download{font:inherit;padding:9px 13px;border:1px solid #bccbd9;border-radius:8px;background:white;color:#173650;cursor:pointer}button.active{background:#173d53;color:white;border-color:#173d53}button:hover,a.download:hover{background:#e2f3f3;color:#143c51}nav,.controls,.downloads{display:flex;gap:9px;flex-wrap:wrap;align-items:center}label{display:flex;gap:7px;align-items:center}.viewport{overflow:auto;max-height:78vh;border-radius:9px;background:#cbd4dc;margin:14px 0}.stage{position:relative;line-height:0;margin:auto;width:100%;max-width:900px}.stage img{display:block;width:100%;height:auto}.stage .over{position:absolute;inset:0}.stage .divider{position:absolute;top:0;bottom:0;width:2px;background:#13dac5;pointer-events:none}input[type=range]{width:100%;accent-color:#0b8f89}.legends{display:flex;justify-content:space-between;font-weight:700;margin-top:10px}.cropview{overflow:auto}.cropview img{max-width:none;display:block}a{color:#096d80}a.download{text-decoration:none}.note{border-left:4px solid #dc9939;padding:10px 16px;background:#fff7e9}details{margin-top:18px}details img{max-width:100%}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:9px;border-bottom:1px solid #dce3eb}.small{font-size:14px}.stats{display:flex;gap:24px;flex-wrap:wrap}.stats b{font-size:22px;display:block}
</style><main>
<div class="tag">EKSPERIMEN • 4 SAMPEL • HASIL 2×</div>
<h1>Wajah dipertahankan.<br>Detail dipilih per area.</h1>
<p>Bandingkan hasil sebelumnya, kandidat baru, dan gabungan manual. Semua berasal dari foto yang sama. Geser pembatas untuk melihat perubahan pada posisi yang tepat.</p>
<div class="stats"><span><b>4 gambar</b>tanpa mengulang 21 sampel</span><span><b>__TOTAL__ detik</b>total inferensi kandidat, di luar ekspor</span><span><b>Tanpa penajaman tambahan</b>kontribusi gabungan dapat diperiksa</span></div>
<div class="card"><nav id="samples" aria-label="Pilih sampel"></nav><h2 id="title"></h2><p id="assessment" class="note"></p>
<div class="controls"><label>Kiri <select id="left"><option value="A_swinir_x2.png">A — SwinIR</option><option value="baseline_bicubic_x2.png">Asli diperbesar (bicubic)</option><option value="B_realesrgan_x2.png">B — Real-ESRGAN</option></select></label>
<label>Kanan <select id="right"><option value="C_hybrid_x2.png">C — Gabungan</option><option value="B_realesrgan_x2.png">B — Real-ESRGAN</option><option value="A_swinir_x2.png">A — SwinIR</option></select></label>
<button id="fit" class="active">Sesuai layar</button><button id="native">Ukuran piksel 100%</button></div>
<div class="legends"><span id="leftLabel"></span><span id="rightLabel"></span></div>
<div class="viewport" id="viewport"><div class="stage" id="stage"><img id="base" alt="Gambar pembanding kiri"><img id="over" class="over" alt="Gambar pembanding kanan"><div id="divider" class="divider"></div></div></div>
<label for="wipe">Pembatas perbandingan</label><input id="wipe" type="range" min="0" max="100" value="50">
<p class="muted small" id="size"></p><div class="downloads" id="downloads"></div>
<details><summary>Lihat area gabungan dan bobotnya</summary><p>Toska menunjukkan kontribusi kandidat B. Area tanpa warna memakai A. Masker ditentukan manual setelah pemeriksaan; bukan hasil segmentasi otomatis.</p><img id="mask" alt="Peta area gabungan"><p><a id="maskLink">Buka bobot kandidat: hitam = A, putih = B</a></p></details>
</div>
<div class="card"><h2>Potongan detail pada ukuran piksel asli</h2><label>Area <select id="crop"></select></label><p class="muted small">Urutan kolom: A, B, C. Geser mendatar bila tidak muat. Potongan berasal dari ekspor 2× tanpa perubahan skala.</p><div class="cropview"><img id="cropImage" alt="Perbandingan detail A B C"></div></div>
<div class="card"><h2>Cara membaca hasil</h2><p><b>A:</b> hasil SwinIR yang sudah tersedia. <b>B:</b> Real-ESRGAN general-x4v3 dengan denoise 0,5. <b>C:</b> perpaduan manual per area; sebagian area sengaja sama persis dengan A.</p>
<p>Periksa kejelasan pada tampilan normal, lalu bentuk huruf, kulit, bulu, pola kain, dan batas masker pada 100%. Detail lebih tajam belum tentu lebih akurat. Tidak ada foto resolusi tinggi sebagai acuan, sehingga eksperimen ini tidak melaporkan PSNR/SSIM sebagai bukti kualitas.</p>
<p class="note">Temuan awal: manfaat paling jelas terlihat pada teks poster. Pada potret dan bulu, kandidat juga menghilangkan tekstur. Gabungan ini merupakan hasil uji untuk ditinjau, belum menjadi pengganti otomatis SwinIR.</p>
<p class="small">Model baru bekerja pada 4×, kemudian hasil diperkecil ke 2× dengan Pillow Lanczos. Input tidak diperkecil. Pemrosesan FP32, satu model GPU; masker dan gabungan dikerjakan di CPU. Perbandingan hasil akhir ini bukan perbandingan arsitektur dengan skala native yang sama.</p>
<p><a href="SUMMARY.md">Catatan eksperimen</a> · <a href="experiment.json">Rincian pengaturan</a> · <a href="verification.json">Hasil pemeriksaan</a> · <a href="regions.json">Koordinat masker</a></p></div>
</main><script>
const samples=__DATA__;const $=id=>document.getElementById(id);let current=samples.find(s=>s.id==='010')||samples[0];let native=false;
function divider(){let x=$('wipe').value;$('over').style.clipPath=`inset(0 0 0 ${x}%)`;$('divider').style.left=x+'%'}
function zoom(){ $('stage').style.width=native?current.size[0]+'px':'100%';$('stage').style.maxWidth=native?'none':'900px';$('fit').classList.toggle('active',!native);$('native').classList.toggle('active',native)}
function images(){ $('base').src=current.id+'/'+$('left').value;$('over').src=current.id+'/'+$('right').value;$('leftLabel').textContent=$('left').selectedOptions[0].text;$('rightLabel').textContent=$('right').selectedOptions[0].text;divider();zoom()}
function crop(){ $('cropImage').src=current.id+'/review_'+$('crop').value+'_ABC.png' }
function choose(s){current=s;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.id===s.id));$('title').textContent=s.id+' · '+s.title;$('assessment').textContent=s.assessment;$('size').textContent=s.size.join(' × ')+' piksel untuk A, B, dan C. Waktu inferensi B: '+s.seconds+' detik.';$('mask').src=s.id+'/mask_overlay.png';$('maskLink').href=s.id+'/candidate_weight.png';$('crop').replaceChildren(...s.crops.map(c=>{let o=document.createElement('option');o.value=c;o.textContent=c;return o}));$('downloads').replaceChildren(...[['A — SwinIR','A_swinir_x2.png'],['B — Real-ESRGAN','B_realesrgan_x2.png'],['C — Gabungan','C_hybrid_x2.png'],['Foto asli','original.png']].map(([label,file])=>{let a=document.createElement('a');a.className='download';a.textContent='Buka '+label;a.href=s.id+'/'+file;a.target='_blank';return a}));$('viewport').scrollTo(0,0);images();crop()}
for(const s of samples){let b=document.createElement('button');b.textContent=s.id+' · '+s.title;b.dataset.id=s.id;b.onclick=()=>choose(s);$('samples').append(b)}
$('left').onchange=images;$('right').onchange=images;$('wipe').oninput=divider;$('crop').onchange=crop;$('fit').onclick=()=>{native=false;zoom()};$('native').onclick=()=>{native=true;zoom()};choose(current);
</script></html>'''
    page = page.replace("__TOTAL__", f"{total:.2f}").replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (folder/"report.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--regions", type=Path, default=ROOT/"hybrid_regions.json")
    args = parser.parse_args()
    folder = args.folder.resolve()
    config = json.loads(args.regions.read_text(encoding="utf-8"))
    manifest = json.loads((folder/"experiment.json").read_text(encoding="utf-8"))
    checks = []
    for row in manifest["entries"]:
        sid = row["id"]
        target = folder/sid
        for name, digest in row["files"].items():
            if sha256(target/name) != digest:
                raise RuntimeError(f"Cached image integrity failed: {sid}/{name}")
        a = Image.open(target/"A_swinir_x2.png").convert("RGB")
        b = Image.open(target/"B_realesrgan_x2.png").convert("RGB")
        alpha, protected = make_alpha(a.size, config[sid])
        c = fuse(a, b, alpha)
        save_png(c, target/"C_hybrid_x2.png")
        weight = Image.fromarray(np.rint(alpha*255).astype(np.uint8))
        weight.save(target/"candidate_weight.png")
        # Preview overlay only; not used for inference or fusion.
        preview = a.copy()
        preview.thumbnail((700, 850), Image.Resampling.LANCZOS)
        tint = Image.new("RGB", preview.size, "#00bfa6")
        opacity = weight.resize(preview.size, Image.Resampling.BILINEAR).point(lambda v: round(v*0.55))
        overlay = Image.composite(tint, preview, opacity)
        save_png(overlay, target/"mask_overlay.png")
        rgb_a, rgb_b = np.asarray(a), np.asarray(b)
        with Image.open(target/"C_hybrid_x2.png") as disk:
            rgb_c = np.asarray(disk).copy()
            icc = bool(disk.info.get("icc_profile"))
        protected_error = int(np.abs(rgb_c[protected].astype(np.int16)-rgb_a[protected].astype(np.int16)).max()) if protected.any() else 0
        old = Path(row["baseline_run"])
        check = {"id": sid, "source_unchanged": sha256(Path(row["source"]["source_path"])) == row["source"]["source_sha256"],
                 "baseline_copy_unchanged": sha256(old/"result_swinir_x2.png") == sha256(target/"A_swinir_x2.png"),
                 "dimensions_match": a.size == b.size == c.size == tuple(row["output_size"]),
                 "protected_core_pixels": int(protected.sum()), "protected_core_max_channel_error": protected_error,
                 "protected_core_identical_to_A": protected_error == 0, "output_srgb_profile_present": icc}
        for key in ("source_unchanged", "baseline_copy_unchanged", "dimensions_match", "protected_core_identical_to_A", "output_srgb_profile_present"):
            if not check[key]:
                raise RuntimeError(f"Verification failed: {sid} {key}")
        row["fusion"] = {"config": config[sid], "blend_space": "encoded sRGB RGB8, round to nearest",
                         "mean_candidate_weight": float(alpha.mean()), "protected_core_pixels": int(protected.sum()),
                         "fraction_pixels_exactly_A": float(np.all(rgb_c == rgb_a, axis=2).mean()),
                         "C_vs_A_mean_absolute_channel_difference": float(np.abs(rgb_c.astype(np.int16)-rgb_a.astype(np.int16)).mean()),
                         "B_vs_A_mean_absolute_channel_difference": float(np.abs(rgb_b.astype(np.int16)-rgb_a.astype(np.int16)).mean()),
                         "difference_note": "Differences are change magnitude, not quality scores.",
                         "post_sharpening": False, "automatic_region_detection": False}
        # Keep the float mask for exact reproducibility; PNG is a rounded preview.
        np.save(target/"candidate_weight_float32.npy", alpha, allow_pickle=False)
        for name in ("C_hybrid_x2.png", "candidate_weight.png", "candidate_weight_float32.npy", "mask_overlay.png"):
            row["files"][name] = sha256(target/name)
        for label, box in row["crops"].items():
            box2 = tuple(v*2 for v in box)
            sheet([i.crop(box2) for i in (a,b,c)], ["A - SwinIR", "B - Real-ESRGAN", "C - Gabungan"], target/f"review_{label}_ABC.png")
        checks.append(check)
        print(f"{sid}: protected error={protected_error}, mean B weight={alpha.mean():.3f}", flush=True)
    manifest["fusion_source"] = {str(path.relative_to(ROOT)): sha256(path) for path in
        (ROOT/"pipeline/fusion.py", ROOT/"pipeline/realesrgan.py", ROOT/"hybrid_candidates.py", ROOT/"hybrid_finish.py", args.regions)}
    write_json(folder/"regions.json", config)
    write_json(folder/"experiment.json", manifest)
    write_json(folder/"verification.json", {"passed": True, "entries": checks, "tiling_validation": manifest["tiling_validation"],
        "limits": ["Not proof of perceptual quality or correctness of reconstructed text.", "QR decoding not tested; protected pixels equal baseline A."]})
    total = sum(r["inference"]["inference_seconds"] for r in manifest["entries"])
    peak = max(r["inference"]["peak_cuda_reserved_bytes"] for r in manifest["entries"])/1024**2
    summary = ["# Uji gabungan empat sampel", "", "Tanggal: 29 September 2026.", "",
        "A: SwinIR lama. B: Real-ESRGAN general-x4v3 denoise 0,5. C: gabungan manual per area.",
        "Foto asli tidak diperkecil. B bekerja x4 lalu Pillow Lanczos ke x2; bukan model native x2. Semua ekspor utama PNG RGB8 sRGB.",
        "", f"Total inferensi B: {total:.3f} detik; tahap kandidat termasuk validasi, salin dan ekspor: {manifest['candidate_stage_seconds']:.2f} detik.",
        f"Puncak CUDA reserved yang dilaporkan PyTorch: {peak:.2f} MiB; angka ini bukan seluruh pemakaian VRAM sistem.",
        "FP32, TF32 mati, tile inti 256 dengan konteks 34 piksel, buffer gambar di CPU. Tidak ada penajaman tambahan atau model wajah generatif.",
        "", "## Pengamatan awal (penilaian visual asisten, belum penilaian pengguna)", ""]
    for row in manifest["entries"]:
        summary.append(f"- {row['id']} — {row['fusion']['config']['assessment']}")
    summary += ["", "## Verifikasi dan batasan", "",
        "Semua empat sumber dan salinan SwinIR tetap sama hash-nya. Ukuran A/B/C cocok. Area inti masker terlindungi sama persis pikselnya dengan A, termasuk keluarga, logo yang ditandai, dan QR.",
        "Perlindungan hanya berlaku pada area yang ditandai manual; bukan jaminan kualitas seluruh gambar. Masker dan bobot heuristik dipilih setelah melihat sampel yang sama, sehingga hasil ini bukan evaluasi buta atau pengujian generalisasi.",
        f"Validasi tiled vs full pada satu crop: max error {manifest['tiling_validation']['max_abs_error_0_1']:.9g} pada rentang 0–1.",
        "Tidak ada ground truth resolusi tinggi, sehingga PSNR/SSIM tidak dihitung. Semua huruf belum diverifikasi; QR belum diuji dengan pemindai.",
        "Selisih piksel dalam manifest mengukur besar perubahan, bukan kualitas. Gambar yang lebih tajam dapat mengandung tekstur atau huruf yang tidak sesuai.",
        "", "## Cara mengulang", "",
        "Gunakan hybrid_candidates.py dengan --output menuju folder baru, lalu hybrid_finish.py pada folder tersebut. Untuk mengubah gabungan dari hasil tersimpan, edit salinan regions.json dan berikan --regions; model tidak perlu dijalankan ulang.",
        "Sumber resmi dipin di models/realesrgan-provenance.json. Arsitektur hanya menghapus registrasi BasicSR, tanpa mengubah jaringan. Bobot DNI dicampur mengikuti implementasi resmi. Adaptasi inferensi: buffer CPU, konteks 34, serta Pillow Lanczos sebagai normalisasi ukuran akhir.",
        "", "Keputusan: pertahankan SwinIR sebagai hasil acuan. Gabungan layak ditinjau terutama pada poster, belum layak menggantikan seluruh jalur secara otomatis."]
    (folder/"SUMMARY.md").write_text("\n".join(summary)+"\n", encoding="utf-8")
    make_report(folder, manifest)
    # Four compact A/C full-image comparisons, deliberately fit-to-view.
    width = 450
    row_heights = [round((width-12)*r["output_size"][1]/r["output_size"][0])+65 for r in manifest["entries"]]
    overview = Image.new("RGB", (width*2, sum(row_heights)), "#eef2f7")
    draw = ImageDraw.Draw(overview)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    offset = 0
    for j, row in enumerate(manifest["entries"]):
        row_height = row_heights[j]
        for k, (name, label) in enumerate((("A_swinir_x2.png", "A - SwinIR"),("C_hybrid_x2.png", "C - Gabungan"))):
            im = Image.open(folder/row["id"]/name).convert("RGB")
            im.thumbnail((width-12,row_height-55), Image.Resampling.LANCZOS)
            draw.text((k*width+10,offset+10), row["id"]+" | "+label, font=font, fill="#18364c")
            overview.paste(im,(k*width+(width-im.width)//2,offset+45))
        offset += row_height
    save_png(overview, folder/"overview_AC.png")
    print(folder/"report.html", flush=True)


if __name__ == "__main__":
    main()
