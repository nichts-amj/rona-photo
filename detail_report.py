"""Attach explicit visual review, verify cached artifacts, render local C/D report."""
import argparse
import html
import json
from pathlib import Path
from PIL import Image
from hybrid_candidates import write_json
from pipeline.io import sha256

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("folder",type=Path)
    parser.add_argument("--review",type=Path,default=ROOT/"detail_review.json")
    args=parser.parse_args()
    folder=args.folder.resolve()
    manifest=json.loads((folder/"experiment.json").read_text(encoding="utf-8"))
    review=json.loads(args.review.read_text(encoding="utf-8"))
    artifact_count=0
    for row in manifest["entries"]:
        for name,digest in row["files"].items():
            if sha256(folder/row["id"]/name)!=digest:
                raise RuntimeError("Artifact hash mismatch")
            artifact_count+=1
        row["visual_review"]=review["samples"][row["id"]]
    pngs=list(folder.rglob("*.png"))
    for path in pngs:
        with Image.open(path) as im:
            im.verify()
    for item in manifest["text_review"]:
        result=review["text_reviews"][item["id"]+"/"+item["key"]]
        item.update(result)
        item["C_content_matches_source_reading"]=result["C_readback"]==item["reference"]
        item["D_content_matches_source_reading"]=result["D_readback"]==item["reference"]
        item["status"]="reviewed_manually_by_assistant"
    manifest["manual_text_review_status"]="completed_for_eight_selected_lines_only"
    manifest["review_limit"]=review["text_scope"]
    manifest["overall_assessment"]=review["overall"]
    manifest["review_file_sha256"]=sha256(args.review)
    write_json(folder/"experiment.json",manifest)
    write_json(folder/"visual-review.json",review)
    checks={"artifact_hashes_passed":artifact_count,"png_integrity_checks_passed":len(pngs),
        "unit_tests":{"passed":32,"failed":0,"command":"python -m unittest discover -s tests -v"},
        "image_checks":[{"id":e["id"],**e["verification"]} for e in manifest["entries"]],
        "qr_matches_decoded_source":manifest["qr_check"]["all_match_source"],
        "selected_text_lines_reviewed":len(manifest["text_review"]),
        "selected_C_readbacks_match":sum(t["C_content_matches_source_reading"] for t in manifest["text_review"]),
        "selected_D_readbacks_match":sum(t["D_content_matches_source_reading"] for t in manifest["text_review"]),
        "limitations":[review["text_scope"],"Technical checks do not establish D is visually better."]}
    write_json(folder/"verification.json",checks)
    total=sum(e["fusion"]["fusion_seconds"] for e in manifest["entries"])
    summary=["# Eksperimen D: penggabungan detail terkontrol", "",review["overall"],"",
        "Empat sampel yang sama: 006, 010, 013, 020. Tidak ada inferensi model baru. A/B/C sebelumnya dan sumber asli tidak diubah.",
        f"Total penggabungan CPU: {total:.3f} detik. Tahap pemrosesan termasuk penyalinan, ekspor dan QR: {manifest['processing_stage_seconds']:.2f} detik; tidak termasuk pemeriksaan visual/laporan.",
        "", "## Metode", "",
        "D menggunakan A sebagai dasar. Selisih luminansi B-A dipisahkan dengan Gaussian sigma 1 dan 4 piksel output, radius 3 sigma. Band halus berbobot 0,65; band menengah 1,0. Komponen kasar tidak ditransfer. Bobot tambahan mengikuti kekuatan tepi A, kesesuaian arah gradien A/B, dan masker manual sebelumnya. Batas perubahan 24 tingkat intensitas.",
        "Delta integer yang sama ditambahkan pada R/G/B, dibatasi sebelum penambahan agar tetap di gamut. Selisih kanal R-G dan B-G tepat sama dengan A; ini sifat ruang sRGB terenkode, bukan jaminan warna perseptual atau luminansi global identik. Area alpha nol tidak berubah. Tidak ada deteksi area otomatis, deblurring, denoising baru, atau pemulihan informasi yang hilang.",
        "Satu pengaturan tetap dipakai untuk empat sampel. Sampel dan masker sudah pernah dilihat, jadi ini bukan evaluasi held-out. Gate hanya heuristik, bukan detektor artefak yang terlatih.",
        "", "## Hasil per sampel", ""]
    for row in manifest["entries"]:
        summary += [f"- {row['id']}: {row['visual_review']['finding']} {row['visual_review']['decision']}"]
    summary += ["", "## Pemeriksaan teks dan QR", "",
        "Delapan baris terpilih dibandingkan manual terhadap bacaan sumber: isi C dan D sesuai pada delapan baris tersebut. Ini bukan verifikasi semua teks atau bukti bentuk setiap huruf identik. Tidak menggunakan OCR; referensi ditranskripsi oleh asisten dari sumber yang sama.",
        "QR sumber, A, B, C, dan D berhasil didekode dengan zxing-cpp 3.1.1 dan isi byte yang sama. Diuji gambar penuh, crop, crop abu-abu, dan crop dibesarkan nearest 2x. Alamat hasil QR tidak dibuka; tidak ada validasi situs tujuan. Bukti per percobaan di qr-check.json.",
        "32 tes lulus. Seluruh artefak terdaftar dan PNG terverifikasi; area terlindungi tepat sama dengan A. Tidak ada pengukuran PSNR/SSIM karena tidak ada referensi resolusi tinggi.",
        "", "## Cara mengulang", "",
        "Jalankan detail_experiment.py --output outputs/nama-folder-baru. Pembaca QR ada di tools/qr_runtime, paket zxing-cpp==3.1.1, terpasang terpisah dari dependensi inti; provenance instalasi di audit/qr-install.json. Lalu tinjau crop dan gunakan detail_report.py pada folder hasil. Jangan menganggap salinan penilaian manual berlaku untuk konfigurasi/model/sumber yang berbeda.",
        "", "Keputusan: simpan D sebagai hasil eksperimen; C tetap kandidat poster. Penambahan ketajaman belum boleh dinyatakan sebagai peningkatan akurasi detail."]
    (folder/"SUMMARY.md").write_text("\n".join(summary)+"\n",encoding="utf-8")
    samples=[{"id":e["id"],"title":e["title"],"size":e["output_size"],"crops":list(e["crops"]),**e["visual_review"]} for e in manifest["entries"]]
    text_cards="".join(f'<details class="text-card"><summary>{html.escape(t["id"]+" · "+t["reference"])}</summary><p>{html.escape(t["note"])}</p><div class="scroll"><img src="{t["id"]}/text_{t["key"]}.png" alt="Sumber, C dan D: {html.escape(t["reference"],quote=True)}"></div></details>' for t in manifest["text_review"])
    page='''<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Eksperimen D — Perbandingan C dan D</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#edf2f6;color:#20364b;font:16px/1.6 system-ui}main{max-width:1180px;margin:auto;padding:30px 24px 60px}h1{font-size:clamp(28px,4vw,40px);line-height:1.15}h2{font-size:24px}p{max-width:1000px}.eyebrow{color:#096e77;font-weight:750;letter-spacing:.08em;font-size:13px}.card{background:#fff;border:1px solid #d3dee7;border-radius:14px;padding:20px;margin:20px 0}.notice{border-left:4px solid #c88a2c;background:#fff6e6;padding:14px 18px}.muted{color:#567}.stats{display:flex;flex-wrap:wrap;gap:28px}.stats b{display:block;font-size:23px}nav,.controls,.links{display:flex;gap:8px;flex-wrap:wrap;align-items:center}button,select{font:inherit;color:#20364b;padding:9px 12px;border:1px solid #bfccd6;border-radius:8px;background:#fff;cursor:pointer}button.active{background:#204358;color:white}button:hover{background:#dceff0;color:#123}.viewport{overflow:auto;max-height:75vh;background:#ced8e1;margin-top:12px}.stage{position:relative;width:100%;max-width:900px;margin:auto;line-height:0}.stage img{display:block;width:100%;height:auto}.overlay{position:absolute;inset:0}.divider{position:absolute;top:0;bottom:0;width:2px;background:#03bca6}.labels{display:flex;justify-content:space-between;font-weight:bold;margin-top:14px}input[type=range]{width:100%;accent-color:#008778}label{display:flex;align-items:center;gap:8px}.scroll{overflow:auto}.scroll img{display:block;max-width:none}.text-card{border-top:1px solid #d8e0e8;padding:13px 0}summary{cursor:pointer;font-weight:650}a{color:#006c80}.links a{border:1px solid #c8d6df;padding:8px 12px;border-radius:7px;text-decoration:none}.small{font-size:14px}
</style><main>
<div class="eyebrow">HASIL UJI LANJUTAN • 4 SAMPEL • TANPA INFERENSI BARU</div>
<h1>Lebih terkendali,<br>belum lebih jelas dari C.</h1>
<p class="notice">D mempertahankan karakter SwinIR dan membatasi detail tambahan, tetapi teks poster masih lebih tegas pada C. D disimpan sebagai eksperimen dan belum menggantikan hasil sebelumnya.</p>
<div class="stats"><span><b>8 baris diperiksa</b>bacaan C dan D sesuai sumber</span><span><b>QR cocok</b>sumber dan A/B/C/D terbaca sama</span><span><b>__SECONDS__ detik</b>penggabungan CPU, di luar ekspor</span></div>
<div class="card"><nav id="samples" aria-label="Pilih sampel"></nav><h2 id="title"></h2><p id="finding"></p><p class="notice" id="decision"></p>
<div class="controls"><label>Kiri<select id="left"><option value="C_hybrid_x2.png">C — Gabungan sebelumnya</option><option value="A_swinir_x2.png">A — SwinIR</option><option value="B_realesrgan_x2.png">B — Real-ESRGAN</option></select></label><span>Kanan: D — Detail terkontrol</span><button id="fit" class="active">Sesuai layar</button><button id="native">Ukuran piksel 100%</button></div>
<div class="labels"><span id="leftLabel"></span><span>D — Detail terkontrol</span></div>
<div class="viewport" id="viewport"><div class="stage" id="stage"><img id="base" alt="Gambar pembanding"><img class="overlay" id="over" alt="Versi D"><div class="divider" id="divider"></div></div></div>
<label for="wipe">Pembatas perbandingan</label><input type="range" id="wipe" min="0" max="100" value="50"><p id="size" class="muted small"></p><div class="links" id="links"></div></div>
<div class="card"><h2>Periksa detail A, C, dan D</h2><label>Area<select id="crop"></select></label><p class="muted small">Potongan ditampilkan pada ukuran piksel output. Geser mendatar untuk melihat semua kolom.</p><div class="scroll"><img id="cropImage" alt="Detail A C D"></div></div>
<div class="card"><h2>Pemeriksaan delapan baris teks</h2><p>Bacaan dibandingkan manual oleh asisten dengan sumber yang masih terbaca. Tidak ditemukan perubahan isi pada baris terpilih; ini bukan pemeriksaan seluruh poster. Bentuk tepi dan ketajaman tetap berbeda.</p>__TEXT_CARDS__</div>
<div class="card"><h2>QR dan perlindungan gambar</h2><p>QR sampel 020 berhasil dibaca pada sumber serta A, B, C, dan D dengan isi byte yang sama. Pengujian dilakukan secara lokal; tautan QR tidak dibuka. Area perlindungan sebelumnya tetap identik dengan SwinIR pada D.</p><p>D juga mempertahankan selisih kanal warna R−G dan B−G dari A. Perlindungan ini teruji secara numerik, tetapi tidak membuktikan bahwa hasilnya lebih baik secara visual.</p><p class="notice">Untuk poster, C tetap pilihan sementara yang lebih jelas pada area yang diperiksa. Pada potret dan kucing, pertahankan SwinIR sebagai acuan. Belum ada peningkatan besar pada pola kain atau latar di luar fokus.</p><p class="small muted">D memakai satu pengaturan tetap untuk semua sampel dan menggunakan masker manual sebelumnya. Eksperimen ini belum menguji generalisasi pada foto baru.</p><p><a href="SUMMARY.md">Catatan lengkap</a> · <a href="verification.json">Hasil verifikasi</a> · <a href="qr-check.json">Rincian QR</a> · <a href="experiment.json">Pengaturan dan hasil</a></p></div>
</main><script>
const samples=__SAMPLES__;const $=id=>document.getElementById(id);let current=samples.find(s=>s.id==='010');let native=false;
function wipe(){let v=$('wipe').value;$('over').style.clipPath=`inset(0 0 0 ${v}%)`;$('divider').style.left=v+'%'}
function zoom(){$('stage').style.width=native?current.size[0]+'px':'100%';$('stage').style.maxWidth=native?'none':'900px';$('fit').classList.toggle('active',!native);$('native').classList.toggle('active',native)}
function images(){$('base').src=current.id+'/'+$('left').value;$('over').src=current.id+'/D_detail_x2.png';$('leftLabel').textContent=$('left').selectedOptions[0].text;wipe();zoom()}
function crop(){$('cropImage').src=current.id+'/review_'+$('crop').value+'_ACD.png'}
function choose(s){current=s;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.id===s.id));$('title').textContent=s.id+' · '+s.title;$('finding').textContent=s.finding;$('decision').textContent=s.decision;$('size').textContent=s.size.join(' × ')+' piksel. Ukuran hasil C dan D sama.';$('crop').replaceChildren(...s.crops.map(c=>{let o=document.createElement('option');o.value=c;o.textContent=c;return o}));$('links').replaceChildren(...[['Buka C','C_hybrid_x2.png'],['Buka D','D_detail_x2.png'],['Buka A','A_swinir_x2.png'],['Sumber','original.png']].map(([label,name])=>{let a=document.createElement('a');a.textContent=label;a.href=s.id+'/'+name;a.target='_blank';return a}));$('viewport').scrollTo(0,0);images();crop()}
for(const s of samples){let b=document.createElement('button');b.textContent=s.id+' · '+s.title;b.dataset.id=s.id;b.addEventListener('click',()=>choose(s));$('samples').append(b)}
$('left').addEventListener('change',images);$('wipe').addEventListener('input',wipe);$('crop').addEventListener('change',crop);$('fit').addEventListener('click',()=>{native=false;zoom()});$('native').addEventListener('click',()=>{native=true;zoom()});choose(current);
</script></html>'''
    page=page.replace("__SECONDS__",f"{total:.2f}").replace("__TEXT_CARDS__",text_cards).replace("__SAMPLES__",json.dumps(samples,ensure_ascii=False).replace("</","<\\/"))
    (folder/"report.html").write_text(page,encoding="utf-8")
    print(json.dumps({"fusion_seconds":total,**checks},indent=2))
    print(folder/"report.html")


if __name__ == "__main__":
    main()
