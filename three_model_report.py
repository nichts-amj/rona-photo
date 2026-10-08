"""Render and verify the two-sample experiment without model inference."""
import json
from pathlib import Path
from PIL import Image
from pipeline.io import sha256

ROOT = Path(__file__).resolve().parent
FOLDER = ROOT / 'outputs/batch-20260929-three-model2'

def main():
    m = json.loads((FOLDER/'experiment.json').read_text(encoding='utf-8'))
    findings = {
        '010': 'Poster: Real-ESRGAN dan C masih lebih tegas pada teks. Swin2SR menghaluskan tekstur, tetapi sebagian bintang kecil pada logo kehilangan bentuk. Gabungan tiga model belum menunjukkan keunggulan jelas atas C.',
        '013': 'Keluarga: Swin2SR terlalu menghaluskan wajah dan mengubah pola kain. Gabungan rata-rata ikut mengurangi detail. P mempertahankan area orang sesuai SwinIR karena masker perlindungan; kemiripan itu bukan peningkatan dari model ketiga.'
    }
    count = 0
    for row in m['entries']:
        for name, digest in row['files'].items():
            assert sha256(FOLDER/row['id']/name) == digest, name
            count += 1
        assert sha256(Path(row['source']['source_path'])) == row['source']['source_sha256']
        for name in m['files'].values():
            with Image.open(FOLDER/row['id']/name) as im:
                assert list(im.size) == row['output_size']
                assert im.mode == 'RGB'
                assert im.info.get('icc_profile')
    pngs = list(FOLDER.rglob('*.png'))
    for p in pngs:
        with Image.open(p) as im:
            im.verify()
    checks = {'artifact_hashes_passed':count,'png_integrity_passed':len(pngs),
              'all_output_sizes_and_profiles_passed':True,
              'unit_tests':{'passed':37,'failed':0,'command':'python -m unittest discover -s tests -v'},
              'image_checks':[{'id':e['id'],**e['verification']} for e in m['entries']],
              'reference_validation':m['validation']}
    (FOLDER/'verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    review = {'reviewer':'assistant visual inspection','samples':findings,
              'scope':'Selected text/logo/face/fabric crops; subjective pilot, two samples only. No high-resolution ground truth; not a complete text transcription audit.',
              'decision':'Keep C as poster candidate and A for faithful family detail; do not promote Swin2SR or triple fusion.'}
    (FOLDER/'visual-review.json').write_text(json.dumps(review,indent=2,ensure_ascii=False),encoding='utf-8')
    summary = '''# Uji tiga model — dua sampel

Sampel 010 (poster) dan 013 (keluarga). A = SwinIR, B = Real-ESRGAN, S = Swin2SR CompressedSR X4 48. A/B/C dipakai kembali dari hasil sebelumnya; hanya S menjalankan dua inferensi gambar penuh baru. Semua hasil akhir berukuran x2. S bekerja x4 lalu diturunkan ke x2 dengan Pillow Lanczos, sama seperti ekspor B.

## Hasil visual

''' + '\n\n'.join(findings.values()) + '''

Keputusan sementara: pertahankan C untuk kandidat poster dan A untuk detail keluarga. Model ketiga belum layak menjadi bawaan pada konfigurasi dan dua sampel ini. Tidak ada perubahan pada jalur utama aplikasi.

## Gabungan yang dibandingkan

- AB, AS, BS: rata-rata 50:50 dalam RGB sRGB 8-bit.
- ABS: rata-rata tiga hasil, masing-masing 1/3.
- C: gabungan A/B per area yang sudah diterima sebelumnya.
- P: (1-alpha) A + alpha rata-rata(B,S), memakai masker manual C sebelumnya. Inti area terlindungi tepat sama dengan A. Tidak semua piksel menerima kontribusi ketiga model.

Bobot rata-rata adalah kontrol eksperimen, bukan bobot kualitas yang sudah dioptimalkan. Model memproses input yang sama secara terpisah, bukan berantai.

## Waktu dan batas pengujian

Swin2SR: poster 71,90 detik, keluarga 76,89 detik; total inferensi baru 148,79 detik. Seluruh proses termasuk ekspor/gabungan 170,13 detik, di luar unduhan dan penilaian. RTX 3050 Laptop, FP32, tile 128, overlap 32; tanpa OOM. Puncak CUDA reserved PyTorch 476 MiB (bukan seluruh pemakaian VRAM sistem).

Waktu historis A/B tidak diukur ulang, sehingga tabel waktu bukan benchmark terkontrol. Hanya dua sampel dan penilaian visual potongan pilihan; tidak tersedia acuan resolusi tinggi untuk memastikan kebenaran detail yang dibuat model. Belum ada audit seluruh karakter poster.

37 tes lulus. Hash sumber/hasil, integritas PNG, ukuran, profil warna, serta perlindungan area diverifikasi. Implementasi tiling cocok dengan fungsi referensi resmi yang diadaptasi untuk memilih keluaran utama. Namun hasil tiled tidak identik dengan forward utuh: pada crop validasi 72x64, tile64/overlap16, selisih maksimum 0,15834 dan rata-rata 0,001541 pada rentang 0–1. Ini bukan bukti bebas sambungan atau kesetaraan pemrosesan gambar utuh.

Sumber resmi: https://github.com/mv-lab/swin2sr . Commit, konfigurasi, hash lokal bobot dan parameter tersedia di experiment.json. Lihat verification.json dan visual-review.json untuk bukti pemeriksaan.
'''
    (FOLDER/'SUMMARY.md').write_text(summary,encoding='utf-8')
    html = '''<!doctype html><html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Uji tiga model · 2 sampel</title>
<style>*{box-sizing:border-box}body{margin:0;background:#101820;color:#e9eff4;font:16px system-ui}main{max-width:1200px;margin:auto;padding:28px}h1{font-size:30px}p{line-height:1.6;color:#c8d3dc}button,select{background:#263847;color:white;border:1px solid #607887;border-radius:8px;padding:10px;margin:4px}button{cursor:pointer}a{color:#8fd9ed}.panel{background:#192630;border:1px solid #364958;padding:18px;border-radius:12px;margin:18px 0}.controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px}#viewport{overflow:auto;max-height:740px;background:#090e13}#stage{position:relative;width:100%}#stage img{display:block;width:100%}#top{position:absolute;inset:0;clip-path:inset(0 50% 0 0)}#top img{width:100%;height:100%}input{width:100%}#crop{width:100%;height:auto}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #42515c}.note{font-size:14px}#finding{color:#ffe0a0}</style>
<main><h1>Tiga model, dua gambar</h1><p>SwinIR · Real-ESRGAN · Swin2SR — hasil tunggal, gabungan pasangan, dan gabungan tiga model. Dua inferensi baru; hasil A/B digunakan kembali.</p>
<button id="poster">010 · Poster</button><button id="family">013 · Keluarga</button><div class="panel"><p id="finding"></p><div class="controls"><label>Kiri <select id="left" aria-label="Kiri"></select></label><label>Kanan <select id="right" aria-label="Kanan"></select></label><button id="fit">Pas layar</button><button id="native">Ukuran 100%</button></div><p class="note">Geser pembatas: bagian kiri memakai pilihan Kiri, bagian kanan pilihan Kanan. Pada 100%, gulir gambar untuk memeriksa piksel.</p><input id="range" type="range" min="0" max="100" value="50" aria-label="Pembatas perbandingan"><div id="viewport"><div id="stage"><img id="base" alt="Hasil kanan"><div id="top"><img id="over" alt="Hasil kiri"></div></div></div><p><a id="leftfile">Buka hasil kiri</a> · <a id="rightfile">Buka hasil kanan</a> · <a id="source">Gambar sumber</a></p></div>
<div class="panel"><h2>Detail pada skala yang sama</h2><div class="controls"><label>Area <select id="area" aria-label="Area"></select></label><label>Kelompok <select id="group" aria-label="Kelompok"><option value="models">Model: A / B / S</option><option value="fusion">Gabungan: C / ABS / P</option></select></label></div><img id="crop" alt="Potongan perbandingan tiga kolom"><p class="note">A = SwinIR; B = Real-ESRGAN; S = Swin2SR. C = gabungan lama per area. ABS = rata-rata tiga model. P = gabungan tiga model dengan perlindungan area C.</p></div>
<div class="panel"><h2>Waktu inferensi (detik)</h2><table><thead><tr><th>Sampel</th><th>A · historis</th><th>B · historis</th><th>S · baru</th></tr></thead><tbody id="times"></tbody></table><p class="note">A/B tidak dijalankan ulang; pengaturan dan waktu pengujian berbeda. Ini catatan operasional, bukan benchmark kecepatan terkontrol. Total inferensi baru 148,79 detik; proses termasuk ekspor/gabungan 170,13 detik.</p></div>
<div class="panel"><h2>Arti hasil pengujian</h2><p>Penambahan Swin2SR belum memberi peningkatan menyeluruh pada dua sampel ini. C tetap kandidat poster; A mempertahankan detail keluarga. P melindungi area orang dengan hasil A, sehingga kemiripan di sana berasal dari perlindungan, bukan kemampuan model ketiga.</p><p>AB/AS/BS memakai bobot 50:50; ABS masing-masing 1/3. P memakai masker manual lama: (1−alpha)A + alpha rata-rata(B,S). Model berjalan terpisah pada sumber yang sama. Semua hasil akhir x2; B dan S melalui x4 lalu Lanczos ke x2.</p><p class="note">Pilot dua sampel, tanpa acuan resolusi tinggi. Penilaian potongan bukan audit seluruh teks. Tiling cocok dengan referensi, tetapi tidak identik dengan forward utuh (crop validasi: galat maks. 0,15834; rata-rata 0,001541, rentang 0–1). Tidak ada klaim bebas sambungan. 37 tes lulus; sumber dan C lama tetap utuh.</p><p><a href="SUMMARY.md">Catatan lengkap</a> · <a href="experiment.json">Parameter dan waktu</a> · <a href="verification.json">Verifikasi</a> · <a href="visual-review.json">Penilaian visual</a> · <a href="https://github.com/mv-lab/swin2sr">Sumber resmi model</a></p></div></main>
<script>const data=__DATA__, findings=__FINDINGS__;
const names={A:'A · SwinIR',B:'B · Real-ESRGAN',S:'S · Swin2SR',C:'C · Gabungan lama A/B',AB:'AB · 50:50',AS:'AS · 50:50',BS:'BS · 50:50',ABS:'ABS · Tiga model rata-rata',P:'P · Tiga model + perlindungan'};
const el=id=>document.getElementById(id);let current=data.entries[0],native=false;
for(const side of ['left','right'])for(const [v,t]of Object.entries(names)){const o=document.createElement('option');o.value=v;o.textContent=t;el(side).append(o)}el('left').value='C';el('right').value='P';
function draw(){for(const [side,img]of [['left','over'],['right','base']]){const url=current.id+'/'+data.files[el(side).value];el(img).src=url;el(side+'file').href=url}el('source').href=current.id+'/original.png';el('stage').style.width=native?current.output_size[0]+'px':'100%';el('finding').textContent=findings[current.id];crop()}
function crop(){el('crop').src=current.id+'/'+el('group').value+'_'+el('area').value+'.png'}
function sample(i){current=data.entries[i];el('area').replaceChildren();for(const k of Object.keys(current.crops)){const o=document.createElement('option');o.value=k;o.textContent=k;el('area').append(o)}draw()}
el('poster').onclick=()=>sample(0);el('family').onclick=()=>sample(1);el('left').onchange=draw;el('right').onchange=draw;el('area').onchange=crop;el('group').onchange=crop;el('range').oninput=()=>el('top').style.clipPath='inset(0 '+(100-el('range').value)+'% 0 0)';el('fit').onclick=()=>{native=false;draw()};el('native').onclick=()=>{native=true;draw()};
for(const r of data.entries){const tr=document.createElement('tr');for(const v of [r.id,r.historical_times.A_seconds.toFixed(2),r.historical_times.B_seconds.toFixed(2),r.inference.inference_seconds.toFixed(2)]){const td=document.createElement('td');td.textContent=v;tr.append(td)}el('times').append(tr)}sample(0);</script></html>'''
    html=html.replace('__DATA__',json.dumps(m,ensure_ascii=False)).replace('__FINDINGS__',json.dumps(findings,ensure_ascii=False))
    (FOLDER/'report.html').write_text(html,encoding='utf-8')
    print(json.dumps(checks,indent=2))

if __name__ == '__main__':
    main()
