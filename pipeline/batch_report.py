"""Local HTML review + measurements; manual ratings start blank."""
import csv
import html
import json
from pathlib import Path
from urllib.parse import quote

from PIL import Image

FIELDS = ["id", "name", "status", "detected_format", "input_size", "output_size", "inference_seconds",
          "peak_allocated_bytes", "peak_reserved_bytes", "tile_used", "overlap_used", "oom_retries", "source_unchanged", "error"]


def csv_safe(value):
    text = str(value if value is not None else "")
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def write_report(state, root: Path):
    with (root / "measurements.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({key: csv_safe(entry.get(key, "")) for key in FIELDS} for entry in state["entries"])
    cards = []
    successes = [entry for entry in state["entries"] if entry["status"] == "success"]
    previews = root / "previews"
    previews.mkdir(exist_ok=True)
    for entry in state["entries"]:
        ident = entry["id"]
        escape = html.escape
        title = escape(entry["name"])
        if entry["status"] == "success":
            run = entry["run"]
            preview = previews / f"{ident}.jpg"
            manifest = root / run / "processing.json"
            if not preview.exists() or preview.stat().st_mtime < manifest.stat().st_mtime:
                with Image.open(root / run / "comparison.png") as im:
                    im.thumbnail((1100, 700), Image.Resampling.LANCZOS)
                    im.save(preview, quality=90, icc_profile=im.info.get("icc_profile"))
            stats = f"{entry['input_size'][0]}×{entry['input_size'][1]} → {entry['output_size'][0]}×{entry['output_size'][1]} · {entry['inference_seconds']:.2f} detik"
            stats += f" · allocated {entry['peak_allocated_bytes']/1048576:.1f} MiB" if entry.get("peak_allocated_bytes") is not None else " · CPU"
            links = " · ".join(f'<a href="{quote(run + "/" + filename)}" target="_blank">{label}</a>' for filename, label in
                                [("input_normalized.png", "Input"), ("baseline_bicubic_x2.png", "Bicubic ×2"), ("result_swinir_x2.png", "SwinIR ×2"), ("processing.json", "Log")])
            controls = ''.join(f'<label>{label}<select data-field="{field}"><option value="">Belum dinilai</option><option value="better">Lebih baik</option><option value="same">Setara</option><option value="worse">Lebih buruk</option><option value="na">Tidak berlaku</option></select></label>' for field, label in
                               [("overall", "Keseluruhan"), ("sharpness", "Ketajaman"), ("skin", "Kealamian kulit"), ("texture", "Kesetiaan tekstur"), ("shape", "Bentuk/identitas"), ("text", "Tulisan/logo"), ("color", "Warna"), ("halos_seams", "Halo/sambungan")])
            warnings = '<br>'.join(escape(w) for w in entry.get("warnings", []))
            content = f'<p class="stats">{stats}</p><p>{links}</p><img class="preview" loading="lazy" src="previews/{ident}.jpg" alt="{ident}: bicubic kiri, SwinIR kanan"><button class="inspect" data-id="{ident}">Periksa detail 100%</button><details><summary>Catatan pembacaan</summary>{warnings}</details><div class="ratings">{controls}</div><label>Catatan perubahan merugikan / area yang perlu dicek<textarea data-field="notes" rows="2"></textarea></label>'
        else:
            content = f'<p>{escape(entry["status"])} — {escape(entry.get("error", "Menunggu pemrosesan"))}</p>'
        cards.append(f'<article data-id="{ident}" data-status="{entry["status"]}"><h2><span>{ident}</span> {title}</h2>{content}</article>')
    payload = json.dumps({"batch_id": root.name, "config": state["config"], "entries": state["entries"]}, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    total_seconds = sum(entry["inference_seconds"] for entry in successes)
    page = TEMPLATE.replace("__DATA__", payload).replace("__CARDS__", '\n'.join(cards))
    page = page.replace("__COUNT__", str(len(state["entries"]))).replace("__SUCCESS__", str(len(successes)))
    page = page.replace("__SECONDS__", f"{total_seconds:.1f}").replace("__STATE__", html.escape(state["status"]))
    page = page.replace("__TILES__", f"{state['config']['tile']} / {state['config']['overlap']}")
    temporary = root / "report.html.tmp"
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(root / "report.html")


TEMPLATE = '''<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evaluasi foto · SwinIR ×2</title><style>
:root{color-scheme:light;--ink:#172c36;--muted:#526772;--line:#d8e1df;--accent:#146b62}*{box-sizing:border-box}body{margin:0;background:#eef3f0;color:var(--ink);font:16px/1.55 system-ui,sans-serif}header{padding:40px max(24px,calc((100vw - 1160px)/2));background:#142f35;color:#f2f8f4}header p{max-width:850px;color:#c9dad7}h1{font-size:clamp(26px,4vw,42px);line-height:1.15;margin:8px 0 16px}.eyebrow{letter-spacing:.15em;font-size:12px;font-weight:700}.summary{display:flex;gap:20px;flex-wrap:wrap}.summary b{font-size:26px;display:block}.summary div{min-width:160px}main{max-width:1200px;padding:24px 20px;margin:auto}.toolbar{position:sticky;top:0;background:#eef3f0ee;backdrop-filter:blur(10px);padding:14px 0;display:flex;gap:10px;flex-wrap:wrap;z-index:2}button,.toolbar a{font:inherit;cursor:pointer;padding:9px 14px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink);text-decoration:none}button.primary{background:var(--accent);color:white;border-color:var(--accent)}input,select,textarea{font:inherit;padding:8px;border:1px solid var(--line);border-radius:6px;background:white;color:var(--ink)}input[type=search]{flex:1;min-width:200px}article{background:white;border:1px solid var(--line);border-radius:14px;padding:22px;margin:20px 0;overflow:hidden}article[hidden]{display:none}h2{font-size:18px;overflow-wrap:anywhere}h2 span{display:inline-block;background:#e0efea;color:#125e56;border-radius:6px;padding:2px 9px;margin-right:6px}.stats,details,.hint{color:var(--muted);font-size:14px}a{color:#146b62}.preview{display:block;width:100%;max-height:570px;object-fit:contain;background:#152028;margin:14px 0;border-radius:8px}.ratings{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:18px 0}label{display:flex;flex-direction:column;font-size:14px;gap:4px}textarea{width:100%}details{margin:12px 0}#notice{min-height:26px;font-size:14px}dialog{width:96vw;max-width:none;height:94vh;border:0;border-radius:12px;padding:16px}dialog::backdrop{background:#071519bb}.viewerbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.views{display:grid;grid-template-columns:1fr 1fr;gap:10px;height:calc(100% - 110px)}.view{min-width:0;overflow:auto;background:#101e24}.view img{display:block;max-width:none}.viewlabels{display:grid;grid-template-columns:1fr 1fr;font-weight:600;margin:10px 0}.inspecting{font-weight:600}footer{padding:20px;font-size:14px;color:var(--muted)}@media(max-width:600px){article{padding:14px}.views{gap:4px}.toolbar{position:static}}
</style></head><body>
<header id="top"><div class="eyebrow">AI PHOTO RETOUCH · SET PENGEMBANGAN</div><h1>Periksa detail, bukan hanya ketajaman.</h1><p>Bicubic ×2 di kiri, SwinIR lightweight ×2 di kanan. Semua foto diproses tanpa degradasi tambahan. Penilaian Anda membandingkan hasil pada ukuran keluaran yang sama.</p><div class="summary"><div><b>__SUCCESS__ / __COUNT__</b>foto berhasil</div><div><b>__SECONDS__ dtk</b>total inferensi tercatat</div><div><b>FP32 · __TILES__</b>tile / overlap input</div></div><p>Status batch: __STATE__. Angka memori adalah allocator PyTorch, bukan total VRAM sistem.</p></header>
<main><div class="toolbar"><input id="search" type="search" aria-label="Cari foto" placeholder="Cari nama atau nomor foto"><button id="export" class="primary">Ekspor penilaian JSON</button><button id="import">Muat penilaian</button><a href="measurements.csv">Unduh pengukuran CSV</a><input id="importfile" type="file" accept="application/json,.json" hidden></div>
<p class="hint">Preview diperkecil hanya untuk tampilan laporan; input model dan PNG hasil tetap resolusi penuh. Gunakan “Periksa detail 100%” untuk melihat piksel keluaran. Kolom kosong berarti belum dinilai; tidak ada skor kualitas otomatis. PSNR/SSIM/LPIPS tidak dihitung karena belum ada referensi yang sesuai.</p>
<p class="hint">Pilih “lebih baik/setara/lebih buruk” relatif terhadap bicubic. Untuk halo/sambungan, lebih baik berarti artefak lebih sedikit. Pilih “tidak berlaku” bila area tersebut tidak ada. Nilai disimpan di browser bila tersedia; ekspor JSON agar catatan tidak hilang saat berganti browser/perangkat.</p><div id="notice" role="status" aria-live="polite"></div>
__CARDS__
</main><dialog id="viewer"><div class="viewerbar"><span id="viewtitle" class="inspecting"></span><label>Zoom <input id="zoom" type="range" min="20" max="200" value="100" step="10"></label><span id="zoomvalue">100%</span><button id="close">Tutup</button></div><div class="viewlabels"><span>Bicubic ×2</span><span>SwinIR ×2</span></div><div class="views"><div id="leftview" class="view"><img id="leftimage" alt="Baseline bicubic"></div><div id="rightview" class="view"><img id="rightimage" alt="Hasil SwinIR"></div></div></dialog>
<dialog id="exportdialog"><h2>Salinan penilaian JSON</h2><p>Unduhan telah diminta. Jika browser tidak menyimpannya, salin teks di bawah ke berkas .json. Catatan ini tidak dikirim ke server.</p><textarea id="exporttext" aria-label="JSON penilaian" readonly style="height:65vh"></textarea><button id="closeexport">Tutup ekspor</button></dialog>
<footer>Laporan lokal. Foto tidak diunggah. Perubahan identitas, huruf/logo, tekstur palsu, warna, halo dan sambungan harus dicatat sebagai potensi kegagalan.</footer>
<script type="application/json" id="dataset">__DATA__</script><script>
const data=JSON.parse(document.querySelector('#dataset').textContent), key='retouch-review:'+data.batch_id;
let reviews={};const notice=document.querySelector('#notice');
try{reviews=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){notice.textContent='Penyimpanan browser tidak tersedia. Gunakan ekspor JSON sebelum menutup laporan.'}
function restore(){document.querySelectorAll('article').forEach(card=>card.querySelectorAll('[data-field]').forEach(el=>{el.value=(reviews[card.dataset.id]||{})[el.dataset.field]||''}))}
restore();
document.querySelectorAll('article [data-field]').forEach(el=>el.addEventListener('input',()=>{const id=el.closest('article').dataset.id;reviews[id]??={};reviews[id][el.dataset.field]=el.value;try{localStorage.setItem(key,JSON.stringify(reviews));notice.textContent='Catatan tersimpan di browser. Ekspor JSON untuk salinan permanen.'}catch(e){notice.textContent='Catatan belum tersimpan di disk. Gunakan ekspor JSON.'}}));
document.querySelector('#search').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('article').forEach(card=>{card.hidden=!card.querySelector('h2').textContent.toLowerCase().includes(q)})});
document.querySelector('#export').onclick=()=>{const value={schema_version:1,batch_id:data.batch_id,config:data.config,exported_utc:new Date().toISOString(),reviews:data.entries.map(e=>({id:e.id,name:e.name,sha256:e.sha256,ratings:reviews[e.id]||{}}))};const text=JSON.stringify(value,null,2);document.querySelector('#exporttext').value=text;document.querySelector('#exportdialog').showModal();const url=URL.createObjectURL(new Blob([text],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=data.batch_id+'-penilaian.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice.textContent='Unduhan diminta. Salinan JSON juga tersedia dalam dialog ekspor.'};
document.querySelector('#closeexport').onclick=()=>document.querySelector('#exportdialog').close();
document.querySelector('#import').onclick=()=>document.querySelector('#importfile').click();
document.querySelector('#importfile').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;const saved=JSON.parse(await file.text());if(saved.schema_version!==1||saved.batch_id!==data.batch_id||!Array.isArray(saved.reviews))throw Error('Berkas bukan penilaian batch ini');const next={};for(const item of saved.reviews){const match=data.entries.find(x=>x.id===item.id);if(!match||match.sha256!==item.sha256)throw Error('Hash/ID foto berbeda');next[item.id]=item.ratings||{}}reviews=next;restore();try{localStorage.setItem(key,JSON.stringify(reviews))}catch(e){}notice.textContent='Penilaian berhasil dimuat.'}catch(error){notice.textContent='Gagal memuat: '+error.message}finally{e.target.value=''}};
const viewer=document.querySelector('#viewer'),left=document.querySelector('#leftview'),right=document.querySelector('#rightview'),li=document.querySelector('#leftimage'),ri=document.querySelector('#rightimage'),zoom=document.querySelector('#zoom');let width=0;
function applyZoom(){li.style.width=ri.style.width=(width*Number(zoom.value)/100)+'px';document.querySelector('#zoomvalue').textContent=zoom.value+'%'}
document.querySelectorAll('.inspect').forEach(button=>button.onclick=()=>{const entry=data.entries.find(x=>x.id===button.dataset.id);document.querySelector('#viewtitle').textContent=entry.id+' · '+entry.name;width=entry.output_size[0];zoom.value=100;li.src=entry.run+'/baseline_bicubic_x2.png';ri.src=entry.run+'/result_swinir_x2.png';applyZoom();viewer.showModal();left.scrollTop=right.scrollTop=left.scrollLeft=right.scrollLeft=0});
zoom.oninput=applyZoom;document.querySelector('#close').onclick=()=>{viewer.close();li.removeAttribute('src');ri.removeAttribute('src')};
left.onscroll=()=>{if(right.scrollTop!==left.scrollTop)right.scrollTop=left.scrollTop;if(right.scrollLeft!==left.scrollLeft)right.scrollLeft=left.scrollLeft};right.onscroll=()=>{if(left.scrollTop!==right.scrollTop)left.scrollTop=right.scrollTop;if(left.scrollLeft!==right.scrollLeft)left.scrollLeft=right.scrollLeft};
</script></body></html>'''
