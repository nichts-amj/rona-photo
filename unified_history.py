"""Shared history facade; the Upscale store and inference remain unchanged."""
import io
import json
import hashlib
import shutil
import threading
import time
import uuid
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from PIL import Image, ImageOps

HEX = re.compile(r'^[a-f0-9]{32}$')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


class SharedHistory:
    def __init__(self, studio, retouch, ai_edit):
        self.studio, self.retouch, self.ai_edit = studio, retouch, ai_edit
        self.root = studio.root / 'retouch-history'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.tickets = {}

    def busy(self):
        return bool(self.studio.active or self.retouch.active or self.ai_edit.active)

    def safe(self, *parts):
        root = self.root.resolve()
        path = self.root.joinpath(*parts)
        if not path.resolve().is_relative_to(root):
            raise ValueError('Lokasi riwayat tidak diizinkan.')
        current = path
        while current != self.root:
            if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
                raise ValueError('Tautan folder tidak diizinkan.')
            current = current.parent
        return path

    def photo(self, uid):
        if not isinstance(uid, str) or not HEX.fullmatch(uid):
            raise ValueError('ID foto tidak valid.')
        folder = self.safe(uid)
        if not self.safe(uid,'photo.json').is_file():
            raise ValueError('Foto riwayat tidak ditemukan.')
        return folder

    def files(self, folder):
        if folder.is_file():
            self.safe(*folder.relative_to(self.root).parts);return [folder]
        files = []
        for path in folder.rglob('*'):
            self.safe(*path.relative_to(self.root).parts)
            if path.is_file(): files.append(path)
        return files

    def source(self, raw, name, parent=None):
        with self.lock:
            if self.busy(): raise ValueError('Tunggu pemrosesan foto selesai.')
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 50_000_000:
                    raise ValueError('Foto maksimal 50 MP diperlukan.')
                canonical = ImageOps.exif_transpose(image).convert('RGBA')
            uid = uuid.uuid4().hex
            folder = self.safe(uid); folder.mkdir()
            try:
                (folder / 'source.bin').write_bytes(raw)
                canonical.save(folder / 'original.png')
                write(folder / 'photo.json', {'id':uid, 'name':str(name)[:150], 'created':time.time(), 'size':list(canonical.size), 'parent':parent})
            except Exception:
                shutil.rmtree(folder); raise
            finally: canonical.close()
            return {'id':uid}

    def url(self, uid, name):
        return f'/api/library/file/{uid}/{name}'

    def asset(self, url):
        # Copy only known managed snapshots. Never fetch arbitrary URLs/paths.
        parts = urlsplit(str(url))
        if parts.scheme or parts.netloc or parts.query or parts.fragment:
            raise ValueError('Alamat snapshot tidak valid.')
        path = parts.path.split('/')
        if len(path) == 6 and path[:4] in (['','api','retouch','result'], ['', 'api','ai-edit','result']):
            service = self.retouch if path[2] == 'retouch' else self.ai_edit
            if not re.fullmatch(r'result-[a-f0-9]{32}\.png', path[5]): raise ValueError('Snapshot harus berupa hasil yang diterapkan.')
            try:return service.result(path[4], path[5])
            except Exception as error:raise ValueError('Snapshot tidak tersedia: '+str(error)) from error
        if len(path) == 7 and path[:4] == ['', 'api','library','file']:
            return self.file(path[4], '/'.join(path[5:]))
        raise ValueError('Alamat snapshot tidak dikenali.')

    def state(self, request):
        with self.lock:
            if self.busy(): raise ValueError('Tunggu pemrosesan foto selesai.')
            uid=request['id'];folder=self.photo(uid)
            state=request['state']
            if not isinstance(state,dict) or not isinstance(state.get('operations'),list) or len(state['operations'])>500:
                raise ValueError('Resep edit tidak valid.')
            snapshots=request.get('snapshots', [])
            if not isinstance(snapshots,list) or len(snapshots)>500: raise ValueError('Daftar snapshot tidak valid.')
            needed={op['id'] for op in state['operations'] if op.get('type')=='retouch'}
            records={r['id']:r for r in snapshots}
            if not needed.issubset(records): raise ValueError('Snapshot AI untuk melanjutkan edit belum lengkap.')
            rid=uuid.uuid4().hex;run=self.safe(uid,rid);run.mkdir()
            try:
                saved=[]
                assets=self.safe(uid,'assets');assets.mkdir(exist_ok=True)
                for sid in needed:
                    if not isinstance(sid,str) or not HEX.fullmatch(sid):raise ValueError('ID snapshot tidak valid.')
                    filename='snapshot-'+sid+'.png';asset=self.safe(uid,'assets',filename)
                    if not asset.exists():
                        raw=self.asset(records[sid]['url']);temporary=asset.with_suffix('.tmp');temporary.write_bytes(raw);temporary.replace(asset)
                    saved.append({'id':sid,'url':self.url(uid,'assets/'+filename)})
                data={'id':rid,'created':time.time(),'module':'retouch','state':state,'snapshots':saved,
                      'settings':request.get('settings',{}),'tool':request.get('tool','adjust'),'status':'pending'}
                write(run/'project.json',data)
            except Exception:
                shutil.rmtree(run);raise
            return {'id':uid,'run':rid}

    def result(self, uid, rid, raw):
        with self.lock:
            folder=self.photo(uid)
            if not HEX.fullmatch(rid):raise ValueError('ID hasil tidak valid.')
            run=self.safe(uid,rid);data=read(self.safe(uid,rid,'project.json'))
            with Image.open(io.BytesIO(raw)) as image:
                if image.format!='PNG' or image.width*image.height>50_000_000:raise ValueError('Hasil PNG maksimal 50 MP diperlukan.')
                image.verify()
            self.safe(uid,rid,'result.png').write_bytes(raw)
            data.update(status='done',created=time.time())
            write(run/'project.json',data)
            return {'id':uid,'run':rid,'url':self.url(uid,rid+'/result.png')}

    def detail(self, module, uid):
        if module=='upscale':
            d=self.studio.history_detail(uid)
            runs=[{**r,'module':'upscale','owner':uid} for r in d['runs'] if r['results']]
            return {**d,'module':module,'key':module+':'+uid,'runs':runs,
                    'updated':max([r['created'] for r in runs] or [d['created']])}
        if module!='retouch':raise ValueError('Modul riwayat tidak valid.')
        folder=self.photo(uid);record=read(folder/'photo.json');runs=[]
        for run in folder.iterdir():
            if not HEX.fullmatch(run.name) or not run.is_dir():continue
            self.safe(uid,run.name)
            try:data=read(run/'project.json')
            except (OSError,ValueError):continue
            if data.get('status')!='done' or not (run/'result.png').is_file():continue
            labels={'adjust':'Adjust','filter':'Filter','crop':'Crop','retouch':'Retouch','ai':'AI Edit'}
            name='Rona Retouch · '+labels.get(data.get('tool'),'Retouch')
            if data.get('tool')=='retouch':name='Rona Retouch · '+{'codeformer':'CodeFormer','gfpgan':'GFPGAN'}.get(data.get('settings',{}).get('retouch',{}).get('model'),'Retouch')
            results=[{'label':name,'file':'result.png','url':self.url(uid,run.name+'/result.png'),
                      'bytes':(run/'result.png').stat().st_size,'config':data['settings']}]
            runs.append({'id':run.name,'created':data['created'],'results':results,'module':module,'owner':uid,
                         'project':self.url(uid,run.name+'/project.json'),'bytes':sum(p.stat().st_size for p in self.files(run))})
        runs.sort(key=lambda r:r['created'],reverse=True)
        return {**record,'module':module,'key':module+':'+uid,'original':self.url(uid,'original.png'),
                'source':self.url(uid,'source.bin'),'bytes':sum(p.stat().st_size for p in self.files(folder)),
                'cache_bytes':0,'result_count':len(runs),'runs':runs,'caches':[], 'editable':True,
                'updated':max([r['created'] for r in runs] or [record['created']])}

    def listing(self):
        with self.lock:
            items=[]
            for item in self.studio.history()['items']:
                try:items.append(self.detail('upscale',item['id']))
                except (OSError,ValueError):pass
            for folder in self.root.iterdir():
                if not HEX.fullmatch(folder.name):continue
                try:
                    detail=self.detail('retouch',folder.name)
                    items.append(detail)
                except (OSError,ValueError):pass
            items.sort(key=lambda i:i['updated'],reverse=True)
            return {'items':items,'bytes':sum(i['bytes'] for i in items),'cache_bytes':sum(i['cache_bytes'] for i in items),
                    'result_count':sum(i['result_count'] for i in items),'active':self.busy()}

    def file(self, uid, name):
        self.photo(uid)
        if name not in ('source.bin','original.png') and not re.fullmatch(r'(?:[a-f0-9]{32}/(?:result\.png|project\.json|snapshot-[a-f0-9]{32}\.png)|assets/snapshot-[a-f0-9]{32}\.png)',name):
            raise ValueError('Berkas riwayat tidak diizinkan.')
        path=self.safe(uid,*name.split('/'))
        return path.read_bytes()

    def edit(self, request):
        with self.lock:
            if self.busy():raise ValueError('Tunggu pemrosesan selesai sebelum Edit.')
            module,uid=request['module'],request['id'];target=request['target']
            if target not in ('retouch','upscale'):raise ValueError('Tujuan Edit tidak valid.')
            detail=self.detail(module,uid)
            run=next((r for r in detail['runs'] if r['id']==request.get('run')),None)
            if request.get('run') and run is None:raise ValueError('Hasil tidak ditemukan.')
            if run is None:run=next(iter(detail['runs']),None)
            result=next((r for r in run['results'] if r['file']==request.get('result')),None) if run else None
            if request.get('result') and result is None:raise ValueError('Hasil tidak ditemukan.')
            result=result or (run['results'][0] if run else None)
            parent={'module':module,'id':uid,'run':run['id'] if run else None}
            payload={'target':target,'name':detail['name'],'parent':parent}
            if module==target=='upscale':
                payload['upscale']=self.studio.history_edit({'upload':uid,'run':run['id'] if run else None,'result':result['file'] if result else None})
            elif module==target=='retouch' and run:
                payload.update(photo=uid,project=read(self.safe(uid,run['id'],'project.json')),source=detail['source'])
            else:
                url=result['url'] if result else detail['original'];payload['source']=url
                if target=='upscale':
                    raw=self.asset(url) if module=='retouch' and result else self.file(uid,'original.png')
                    with Image.open(io.BytesIO(raw)) as image:
                        transparent=image.convert('RGBA').getchannel('A').getextrema()[0]<255
                        oversized=image.width*image.height>50_000_000 or len(raw)>256*1024*1024 or transparent
                        if oversized and not request.get('prepare'):
                            return {'needs_prepare':True,'message':'Upscale mendukung foto opak maksimal 50 MP / 256 MB. Siapkan salinan yang sesuai (area transparan memakai latar putih)? Foto riwayat tetap utuh.'}
                        if oversized:
                            image=ImageOps.exif_transpose(image).convert('RGBA')
                            background=Image.new('RGBA',image.size,'white');background.alpha_composite(image);image=background.convert('RGB')
                            scale=min(1,(50_000_000/(image.width*image.height))**.5)
                            image=image.resize((max(1,int(image.width*scale)),max(1,int(image.height*scale))),Image.Resampling.LANCZOS)
                            buffer=io.BytesIO();image.save(buffer,'JPEG',quality=95);raw=buffer.getvalue()
                            name=Path(detail['name']).stem+'-upscale.jpg'
                        else:name=Path(detail['name']).stem+'-upscale.png'
                    photo=self.studio.upload(raw,name)
                    payload['upscale']=self.studio.history_edit({'upload':photo['id']})
            ticket=uuid.uuid4().hex
            self.tickets={k:v for k,v in self.tickets.items() if time.time()-v['created']<3600}
            if len(self.tickets)>=64:self.tickets.pop(next(iter(self.tickets)))
            self.tickets[ticket]={'created':time.time(),'data':payload}
            return {'url':'/'+target+'?edit='+ticket}

    def delete(self, request):
        with self.lock:
            if self.busy():raise ValueError('Penghapusan dinonaktifkan selama pemrosesan.')
            kind=request['kind'];plans=[];targets=[]
            if kind not in ('all','cache','photo','result'):raise ValueError('Jenis penghapusan tidak valid.')
            if kind in ('all','cache'):
                plans.append({'kind':'all' if kind=='all' else 'all-cache'})
                if kind=='all':targets=[self.photo(p.name) for p in self.root.iterdir() if HEX.fullmatch(p.name)]
            elif request['module']=='upscale':
                plans.append({'kind':'upload' if kind=='photo' else 'result','upload':request['id'],
                              'run':request.get('run'),'result':request.get('result')})
            elif request['module']=='retouch':
                folder=self.photo(request['id'])
                if kind=='photo':targets=[folder]
                elif kind=='result':
                    rid=request.get('run')
                    if not isinstance(rid,str) or not HEX.fullmatch(rid):raise ValueError('ID hasil tidak valid.')
                    targets=[self.safe(folder.name,rid)]
                    kept=set()
                    for sibling in folder.iterdir():
                        if sibling.name==rid or not HEX.fullmatch(sibling.name):continue
                        try:
                            data=read(self.safe(folder.name,sibling.name,'project.json'));kept.update(r['id'] for r in data.get('snapshots',[]))
                        except (OSError,ValueError,KeyError):continue
                    assets=self.safe(folder.name,'assets')
                    if assets.exists():targets.extend(p for p in assets.glob('snapshot-*.png') if p.stem.removeprefix('snapshot-') not in kept)
                else:raise ValueError('Jenis penghapusan tidak valid.')
            else:raise ValueError('Modul tidak valid.')
            previews=[self.studio.history_delete(p) for p in plans]
            files=[p for folder in targets for p in self.files(folder)]
            digest=hashlib.sha256(json.dumps([[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(files)],previews],sort_keys=True).encode()).hexdigest()
            result={'bytes':sum(p.stat().st_size for p in files)+sum(p['bytes'] for p in previews),'signature':digest}
            if not request.get('confirm'):return result
            if request.get('signature')!=digest:raise ValueError('Riwayat berubah. Konfirmasikan kembali.')
            for folder in targets:self.files(folder)  # preflight every owned descendant
            for plan,preview in zip(plans,previews):self.studio.history_delete({**plan,'confirm':True,'signature':preview['signature']})
            for folder in targets:
                self.safe(*folder.relative_to(self.root).parts)
                if folder.is_dir():shutil.rmtree(folder)
                elif folder.exists():folder.unlink()
            return {**result,'deleted':True}


class LibraryAPI:
    def __init__(self, studio, retouch, ai_edit, token):
        self.store=SharedHistory(studio,retouch,ai_edit);self.token=token

    def get(self, handler, path):
        if not path.startswith('/api/library/'):return False
        try:
            parts=path.split('/')
            if path=='/api/library/list':handler.send(self.store.listing())
            elif len(parts)==6 and parts[3]=='item':handler.send(self.store.detail(parts[4],parts[5]))
            elif len(parts)>=6 and parts[3]=='file':
                name='/'.join(parts[5:]);raw=self.store.file(parts[4],name)
                handler.send(raw,'application/json' if name.endswith('.json') else 'application/octet-stream' if name=='source.bin' else 'image/png')
            elif len(parts)==5 and parts[3]=='handoff':
                item=self.store.tickets.get(parts[4])
                if not item or time.time()-item['created']>3600:raise ValueError('Sesi Edit kedaluwarsa. Buka kembali dari Riwayat.')
                handler.send(item['data'])
            else:handler.send({'error':'Alamat Riwayat tidak ditemukan.'},status=404)
        except (OSError,ValueError,KeyError,TypeError) as e:handler.send({'error':str(e)},status=400)
        return True

    def post(self, handler, path):
        if not path.startswith('/api/library/'):return False
        try:
            limit=256*1024*1024 if path=='/api/library/retouch/source' or path.startswith('/api/library/retouch/result/') else 64*1024*1024 if path=='/api/library/retouch/state' else 8*1024*1024
            length=int(handler.headers.get('Content-Length','0'))
            if not 0<length<=limit:raise ValueError('Berkas/request Riwayat terlalu besar atau kosong.')
            raw=handler.rfile.read(length)
            if path=='/api/library/retouch/source':
                from urllib.parse import unquote
                parent=handler.headers.get('X-History-Parent');parent=json.loads(unquote(parent)) if parent else None
                result=self.store.source(raw,unquote(handler.headers.get('X-Filename','foto.png')),parent)
            elif path.startswith('/api/library/retouch/result/'):
                parts=path.split('/')
                if len(parts)!=7:raise ValueError('Alamat hasil tidak valid.')
                result=self.store.result(parts[5],parts[6],raw)
            else:
                request=json.loads(raw)
                if not isinstance(request,dict):raise ValueError('Request harus berupa object.')
                if path=='/api/library/retouch/state':result=self.store.state(request)
                elif path=='/api/library/edit':result=self.store.edit(request)
                elif path=='/api/library/delete':result=self.store.delete(request)
                else:raise ValueError('Alamat Riwayat tidak ditemukan.')
            handler.send(result)
        except (OSError,ValueError,KeyError,TypeError) as e:handler.send({'error':str(e)},status=400)
        return True
