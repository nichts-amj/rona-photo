"""Build a relocatable Windows folder; no developer venv or user data copied."""
import importlib.metadata as md
import json
import shutil
import sys
import sysconfig
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PIL import Image,ImageDraw
SOURCE=Path(__file__).resolve().parents[1]
DEST=SOURCE.parent/'Rona Photo v1.0'
if DEST.exists():raise SystemExit('Destination already exists; preserve it and choose another release folder.')
DEST.mkdir();runtime=DEST/'runtime';runtime.mkdir();app=DEST/'app';app.mkdir();licenses=DEST/'licenses';licenses.mkdir()
base=Path(sys.base_prefix);site=Path(sysconfig.get_path('purelib'))
for p in base.iterdir():
 if p.is_file() and (p.suffix.lower() in ('.exe','.dll') or p.name=='LICENSE.txt'):shutil.copy2(p,runtime/p.name)
for name in ['Lib','DLLs']:
 shutil.copytree(base/name,runtime/name,ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','ensurepip','idlelib','turtledemo'))
(runtime/'python312._pth').write_text('.\nLib\nDLLs\nLib/site-packages\nimport site\n')
queue=['torch','torchvision','timm','basicsr','facexlib','opencv-python','einops','numba','pillow','numpy','setuptools','packaging']
seen={};missing=[]
while queue:
 name=canonicalize_name(queue.pop())
 if name in seen:continue
 try:d=md.distribution(name)
 except md.PackageNotFoundError:missing.append(name);continue
 seen[name]=d
 for raw in d.requires or []:
  req=Requirement(raw)
  if req.marker is None or req.marker.evaluate({'extra':''}):queue.append(req.name)
if missing:raise RuntimeError('Missing runtime dependencies: '+str(missing))
targetsite=runtime/'Lib/site-packages';targetsite.mkdir(exist_ok=True)
for name,d in sorted(seen.items()):
 print('Bundle',name,d.version,flush=True)
 for rel in d.files or []:
  src=Path(d.locate_file(rel)).resolve()
  if not src.is_relative_to(site.resolve()) or not src.is_file() or '__pycache__' in src.parts:continue
  target=targetsite/src.relative_to(site.resolve());target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
  if any(part.lower().startswith(('license','copying','notice')) for part in Path(rel).parts):
   out=licenses/name/Path(rel);out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,out)
(DEST/'runtime-versions.json').write_text(json.dumps({n:d.version for n,d in sorted(seen.items())},indent=2))
for name in ['local_engine.py','history_store.py','resource_paths.py','web_app.py']:shutil.copy2(SOURCE/name,app/name)
shutil.copy2(SOURCE/'packaging/portable_start.py',app/'portable_start.py')
shutil.copytree(SOURCE/'pipeline',app/'pipeline',ignore=shutil.ignore_patterns('__pycache__'))
for name in ['models','third_party','web']:shutil.copytree(SOURCE/name,DEST/name,ignore=shutil.ignore_patterns('__pycache__','studio.js'))
for p in (DEST/'third_party').rglob('LICENSE*'):
 out=licenses/'models'/p.relative_to(DEST/'third_party');out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out)
shutil.copy2(base/'LICENSE.txt',licenses/'Python-LICENSE.txt')
# Rasterize our simple vector app mark into the Windows icon container.
im=Image.new('RGBA',(256,256),(0,0,0,0));dr=ImageDraw.Draw(im);dr.rounded_rectangle((0,0,255,255),radius=64,fill='#245849');dr.polygon([(128,40),(152,104),(216,128),(152,152),(128,216),(104,152),(40,128),(104,104)],fill='#dcebba');dr.ellipse((176,40,208,72),fill='white');im.save(DEST/'rona.ico',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
(DEST/'Panduan.txt').write_text('''RONA PHOTO v1.0 — Windows x64 portable

Ekstrak SELURUH folder, lalu buka Rona Photo.exe. Jangan menjalankan EXE dari dalam ZIP.
Python dan pustaka CUDA sudah dibundel; tidak perlu memasang Python atau CUDA Toolkit.
NVIDIA tetap memerlukan driver yang kompatibel. Jika pemeriksaan GPU gagal, aplikasi menggunakan CPU.
Target: Windows 10/11 64-bit, browser modern, .NET Framework 4.8 bawaan Windows yang diperbarui.
Microsoft Visual C++ Redistributable x64 mungkin diperlukan bila belum tersedia pada Windows.
Unduhan resmi: https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist
GPU yang didukung bergantung pada driver dan arsitektur yang didukung PyTorch 2.10 CUDA 12.6.

Alamat UI portable: http://127.0.0.1:8773 (berbeda dari proyek pengembangan 8772).
Biarkan jendela Rona Photo terbuka. Tutup aplikasi setelah semua pemrosesan selesai.
Foto/Riwayat/cache/preset disimpan di %LOCALAPPDATA%/Rona Photo/studio.
Tombol Folder data membuka folder tersebut beserta startup.log.
Riwayat pengembangan tidak disalin ke paket ini. Bobot model tidak dihapus oleh menu Riwayat.

LISENSI: Paket enam model ini ditujukan untuk penelitian/penggunaan NONKOMERSIAL.
CodeFormer menggunakan S-Lab License 1.0; izin terpisah diperlukan untuk penggunaan komersial.
Lisensi komponen lain ada di licenses, runtime, dan third_party.
Aplikasi belum ditandatangani secara digital.

Validasi pada komputer tanpa Python/CUDA Toolkit belum dilakukan; lihat VALIDATION.txt.
''',encoding='utf-8')
(DEST/'VALIDATION.txt').write_text('Build sedang divalidasi; lihat laporan akhir di file ini.\n',encoding='utf-8')
print('DESTINATION',DEST,flush=True)
