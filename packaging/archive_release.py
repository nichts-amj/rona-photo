from pathlib import Path
import zipfile,hashlib,time
root=Path('../Rona Photo v1.0').resolve()
archive=root.with_name('Rona Photo v1.0 Windows x64.zip')
if archive.exists():raise SystemExit('ZIP already exists; refusing overwrite.')
start=time.monotonic()
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
 for index,p in enumerate(root.rglob('*')):
  if p.is_file():z.write(p,Path(root.name)/p.relative_to(root))
  if index%2500==0:print('Archived entries',index,flush=True)
hash=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
archive.with_suffix('.zip.sha256').write_text(hash+'  '+archive.name+'\n')
print({'zip':str(archive),'bytes':archive.stat().st_size,'seconds':round(time.monotonic()-start,1),'sha256':hash},flush=True)
