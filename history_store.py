"""Disk-backed studio history. Deletion is scoped to owned upload folders only."""
import copy
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from PIL import Image

ID = re.compile(r'^[0-9a-f]{32}$')
KEY = re.compile(r'^[0-9a-f]{24}$')
RESULT = re.compile(r'^result_[1-9][0-9]*\.png$')


def read_json(path, default=None):
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else (default or {})
    except (OSError,ValueError):
        return default or {}


class HistoryMixin:
    def _safe(self,path):
        root=self.root.resolve()
        path=Path(path).absolute()
        if path==root or not path.resolve().is_relative_to(root):
            raise ValueError('Lokasi riwayat tidak diizinkan.')
        current=path
        while current!=root:
            if current.is_symlink() or (hasattr(current,'is_junction') and current.is_junction()):
                raise ValueError('Tautan folder tidak dapat digunakan sebagai riwayat.')
            if current.parent==current:
                raise ValueError('Lokasi riwayat tidak valid.')
            current=current.parent
        return path

    def _upload_folder(self,uid):
        if not isinstance(uid,str) or not ID.fullmatch(uid):
            raise ValueError('ID unggahan tidak valid.')
        folder=self._safe(self.root/uid)
        if not folder.is_dir():
            raise ValueError('Unggahan tidak ditemukan.')
        return folder

    def _folders(self):
        for path in self.root.iterdir():
            if ID.fullmatch(path.name) and path.is_dir():
                try:
                    yield self._safe(path)
                except ValueError:
                    continue

    def _files(self,path):
        path=self._safe(path)
        if path.is_file():
            return [path]
        files=[]
        if path.is_dir():
            for base,dirs,names in os.walk(path,followlinks=False):
                for name in dirs+names:
                    checked=self._safe(Path(base)/name)
                    if checked.is_file():files.append(checked)
        return files

    def _bytes(self,path):
        return sum(p.stat().st_size for p in self._files(path))

    def _public_photo(self,item):
        return {k:copy.deepcopy(item[k]) for k in ('id','name','size','known_config')} | {
            'original':f'/files/{item["id"]}/original.png'}

    def restore_upload(self,uid):
        from local_engine import write_json
        from pipeline.io import read_photo
        with self.lock:
            folder=self._upload_folder(uid)
            if uid in self.uploads:return self.uploads[uid]
            record=read_json(self._safe(folder/'upload.json'))
            sources=[self._safe(p) for p in folder.glob('source.*') if p.suffix.lower() in ('.png','.jpg','.jpeg','.webp')]
            if not sources:raise ValueError('Salinan foto sumber tidak ditemukan.')
            source=sources[0]
            # Older uploads did not persist their names; recover metadata from disk.
            image,metadata=read_photo(source)
            original=self._safe(folder/'original.png')
            if not original.exists():image.save(original)
            known=record.get('known_config')
            if known is None:
                try:
                    from pipeline.hybrid_run import resolve_regions
                    known=resolve_regions(metadata['source_sha256'],image.size)
                except ValueError:pass
            item={'id':uid,'name':record.get('name') or f'Foto {uid[:8]}{source.suffix}',
                  'size':list(image.size),'source':metadata,'known_config':known,'folder':folder}
            self.uploads[uid]=item
            if not record:
                write_json(folder/'upload.json',self._public_photo(item)|{'created':source.stat().st_mtime})
            return item

    def history(self):
        with self.lock:
            items=[]
            for folder in self._folders():
                try:
                    detail=self.history_detail(folder.name)
                    items.append({k:detail[k] for k in ('id','name','original','created','bytes','result_count','cache_bytes','editable')})
                except (OSError,ValueError):continue
            items.sort(key=lambda i:i['created'],reverse=True)
            return {'items':items,'bytes':sum(i['bytes'] for i in items),
                    'cache_bytes':sum(i['cache_bytes'] for i in items),
                    'result_count':sum(i['result_count'] for i in items),'active':bool(self.active)}

    def history_detail(self,uid):
        with self.lock:
            folder=self._upload_folder(uid)
            record=read_json(self._safe(folder/'upload.json'))
            source=next((self._safe(p) for p in folder.glob('source.*') if p.suffix.lower() in ('.png','.jpg','.jpeg','.webp')),None)
            original=self._safe(folder/'original.png')
            url=lambda p:f'/files/{uid}/{p.relative_to(folder).as_posix()}'
            runs=[]
            for run in folder.iterdir():
                if not ID.fullmatch(run.name) or not run.is_dir():continue
                self._safe(run)
                manifest=self._safe(run/'processing.json')
                data=read_json(manifest)
                results=[]
                for index,r in enumerate(data.get('results',[])):
                    filename=str(r.get('url','')).rsplit('/',1)[-1]
                    if not RESULT.fullmatch(filename):continue
                    file=self._safe(run/filename)
                    if file.exists():
                        results.append({**r,'url':url(file),'file':filename,'index':index,'bytes':file.stat().st_size,
                                        'config':data.get('configs',[])[index] if index<len(data.get('configs',[])) else {}})
                runs.append({'id':run.name,'created':run.stat().st_mtime,'bytes':self._bytes(run),
                    'results':results,'configs':data.get('configs',[]),'regions':data.get('regions',[]),
                    'known_mask_config':data.get('known_mask_config'),'seconds':data.get('seconds',0),
                    'manifest':url(manifest) if manifest.exists() else None,
                    'error':read_json(self._safe(run/'failure.json')).get('error'),
                    'status':'done' if results else 'incomplete',
                    'reused':sum(bool(m.get('reused')) for m in data.get('models',{}).values()),
                    'model_runs':len(data.get('models',{}))})
            runs.sort(key=lambda r:r['created'],reverse=True)
            cache=self._safe(folder/'cache');caches=[]
            if cache.is_dir():
                keys={p.name[:24] for p in cache.iterdir() if KEY.fullmatch(p.name[:24])}
                for key in sorted(keys):
                    files=self._cache_files(folder,key)
                    meta=read_json(self._safe(cache/(key+'.json')))
                    preview=self._safe(cache/(key+'.png'))
                    settings=meta.get('settings',{})
                    from local_engine import NAMES
                    caches.append({'key':key,'label':NAMES.get(settings.get('model'),'Cache model'),
                                   'settings':settings,'info':meta.get('info',{}),
                                   'bytes':sum(p.stat().st_size for p in files),
                                   'url':url(preview) if preview.exists() else None})
            return {'id':uid,'name':record.get('name') or f'Foto {uid[:8]}',
                    'created':record.get('created',source.stat().st_mtime if source else folder.stat().st_mtime),
                    'source':url(source) if source else None,'original':url(original) if original.exists() else None,
                    'bytes':self._bytes(folder),'cache_bytes':self._bytes(cache) if cache.exists() else 0,
                    'result_count':sum(len(r['results']) for r in runs),'runs':runs,'caches':caches,
                    'editable':bool(source),'active':bool(self.active)}

    def history_edit(self,request):
        from local_engine import config_valid
        with self.lock:
            if self.active:raise ValueError('Tunggu proses selesai sebelum membuka foto untuk diedit.')
            uid=request.get('upload');item=self.restore_upload(uid)
            detail=self.history_detail(uid)
            run=next((r for r in detail['runs'] if r['id']==request.get('run')),None)
            if request.get('run') and run is None:raise ValueError('Hasil tidak ditemukan.')
            if run is None:run=next((r for r in detail['runs'] if r['results']),None)
            configs=run['configs'] if run else [config_valid({'weights':{'B':100},'use_mask':False,'output_scale':4})]
            if request.get('result'):
                chosen=next((r for r in run['results'] if r['file']==request['result']),None) if run else None
                if chosen is None:raise ValueError('Hasil tidak ditemukan.')
                configs=[chosen['config']]
            mask=read_json(self._safe(item['folder']/'mask.json'))
            return {'photo':self._public_photo(item),'configs':[config_valid(c) for c in configs],
                    'regions':run['regions'] if run else mask.get('regions',[]),
                    'known':bool(run['known_mask_config']) if run else mask.get('use_known',False)}

    def _cache_files(self,folder,key):
        if not isinstance(key,str) or not KEY.fullmatch(key):raise ValueError('ID cache tidak valid.')
        return [p for suffix in ('.png','.json','_face.png','_transmission.png')
                if (p:=self._safe(folder/'cache'/(key+suffix))).is_file()]

    def _delete_plan(self,request):
        kind=request.get('kind');uid=request.get('upload');targets=[];rewrite=None
        if kind in ('all','all-cache'):
            for folder in self._folders():
                target=folder if kind=='all' else self._safe(folder/'cache')
                if target.exists():targets.append(target)
        else:
            folder=self._upload_folder(uid)
            if kind=='upload':targets=[folder]
            elif kind=='cache':targets=self._cache_files(folder,request.get('key'))
            elif kind in ('result','run'):
                jid=request.get('run')
                if not isinstance(jid,str) or not ID.fullmatch(jid):raise ValueError('ID hasil tidak valid.')
                run=self._safe(folder/jid)
                if not run.is_dir():raise ValueError('Hasil tidak ditemukan.')
                if kind=='run':targets=[run]
                else:
                    filename=request.get('result')
                    if not isinstance(filename,str) or not RESULT.fullmatch(filename):raise ValueError('Nama hasil tidak valid.')
                    manifest=self._safe(run/'processing.json');data=read_json(manifest)
                    index=next((i for i,r in enumerate(data.get('results',[])) if str(r.get('url','')).rsplit('/',1)[-1]==filename),None)
                    if index is None:raise ValueError('Hasil tidak ditemukan.')
                    if len(data['results'])==1:targets=[run]
                    else:
                        targets=[self._safe(run/filename)]
                        data['results'].pop(index);data['configs'].pop(index)
                        rewrite=(manifest,data)
            else:raise ValueError('Jenis penghapusan tidak valid.')
        files=[p for target in targets for p in self._files(target)]
        fingerprint_files=files+([rewrite[0]] if rewrite else [])
        signature=hashlib.sha256(json.dumps([(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(fingerprint_files)],sort_keys=True).encode()).hexdigest()
        return targets,files,rewrite,signature

    def history_delete(self,request):
        from local_engine import write_json
        with self.lock:
            if self.active:raise ValueError('Penghapusan dinonaktifkan selama pemrosesan. Tunggu selesai atau batalkan proses.')
            targets,files,rewrite,signature=self._delete_plan(request)
            summary={'bytes':sum(p.stat().st_size for p in files),'files':len(files),'signature':signature}
            if not request.get('confirm'):return summary
            if request.get('signature')!=signature:raise ValueError('Isi riwayat berubah. Periksa dan konfirmasi penghapusan kembali.')
            # Preflight all resolved paths, including descendants, before any destructive operation.
            for target in targets:self._files(target)
            if rewrite:write_json(*rewrite)
            for target in targets:
                self._safe(target)
                if target.is_dir():shutil.rmtree(target)
                elif target.exists():target.unlink()
            removed=[]
            if request['kind']=='all':removed=list(self.uploads)
            elif request['kind']=='upload':removed=[request['upload']]
            for uid in removed:self.uploads.pop(uid,None)
            # Completed in-memory jobs must not retain links to deleted results.
            affected=request.get('upload')
            if request['kind'] in ('all','upload','run','result'):
                self.jobs={k:v for k,v in self.jobs.items() if not (request['kind']=='all' or v.get('upload')==affected or any(c.get('upload')==affected for c in v.get('items',[])))}
            return {**summary,'deleted':True,'removed_uploads':removed}
