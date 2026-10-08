"""Package an existing complete portable build. No inference or user data copied."""
import argparse, hashlib, json, shutil, zipfile
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--portable-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
args=p.parse_args();source=args.portable_dir.resolve();out=args.output.resolve()
if out.exists():raise SystemExit('Output must be a new directory.')
out.mkdir(parents=True);starter=out/'starter';starter.mkdir()
entries=json.loads((source/'release-manifest.json').read_text(encoding='utf-8'))['files']
groups={'runtime':[], 'models-core':[], 'models-ai-edit':[], 'prerequisites':[], 'application':[]}
for item in entries:
    rel=item['path']
    if rel in ('build-report.json','release-manifest.json'):continue
    if rel.startswith(('runtime/','webview-runtime/')):group='runtime'
    elif rel.startswith('models/ai-edit/'):group='models-ai-edit'
    elif rel.startswith('models/'):group='models-core'
    elif rel.startswith('prerequisites/'):group='prerequisites'
    else:group='application'
    groups[group].append(item)
labels={'runtime':'Python / CUDA / WebView','models-core':'Upscale / Retouch / Background','models-ai-edit':'AI Edit','prerequisites':'Prasyarat Windows','application':'Aplikasi v1.3'}
components=[]
for group,items in groups.items():
    items.sort(key=lambda f:f['path'])
    identity=hashlib.sha256(json.dumps(items,sort_keys=True).encode()).hexdigest()[:16]
    parts=[[]];count=0
    for item in items:
        if item['bytes']>1_800_000_000:raise RuntimeError('Single file exceeds archive budget: '+item['path'])
        if count+item['bytes']>1_800_000_000 and parts[-1]:parts.append([]);count=0
        parts[-1].append(item);count+=item['bytes']
    assets=[]
    for number,part in enumerate(parts,1):
        name=f'rona-{group}-{identity}-{number:02}.zip';path=out/name
        print('Packaging',name,flush=True)
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
            for item in part:
                rel=item['path'];target=rel
                if rel=='Rona Photo.exe':target='Rona Photo Core.exe'
                elif rel=='Rona Photo.exe.config':target='Rona Photo Core.exe.config'
                archive.write(source/rel,target)
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if path.stat().st_size>=2*1024**3:raise RuntimeError('GitHub asset exceeds limit.')
        assets.append({'name':name,'bytes':path.stat().st_size,'sha256':digest,'url':''})
    components.append({'id':f'{group}-{identity}','label':labels[group],'assets':assets})
manifest={'product':'Rona Photo','version':'1.3','components':components,'private_repository_requires_manual_download':True}
(starter/'components.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(out/'components.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
shutil.copy2(source/'Panduan.txt',starter/'Panduan.txt')
(out/'package-report.json').write_text(json.dumps({'compressed_bytes':sum(a['bytes'] for c in components for a in c['assets']),'parts':sum(len(c['assets']) for c in components),'feature_tests':'Pending user manual testing'},indent=2),encoding='utf-8')
print('Components packaged',flush=True)
