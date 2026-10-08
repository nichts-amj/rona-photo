"""Session, analysis cache and serial jobs for Retouch only."""
import io
import json
import os
import secrets
import shutil
import tempfile
import threading
from pathlib import Path
from PIL import Image
from resource_paths import ROOT
from .models import ModelManager,FaceDetector,FaceParser,FaceRestorer,RetouchError


class RetouchService:
    def __init__(self,config=None,manager=None,root=None):
        self.config=config or json.loads((Path(__file__).parent/'config.json').read_text())
        self.manager=manager or ModelManager(self.config)
        self.detector=FaceDetector(self.manager);self.parser=FaceParser(self.manager);self.restorer=FaceRestorer(self.manager)
        self.documents={};self.jobs={};self.active=None;self.lock=threading.RLock();self._temp=None;self.root=Path(root) if root else None
        self.debug=bool(self.config.get('development_debug')) and not os.environ.get('RONA_RESOURCE_DIR')

    def status(self):return {'app':'rona-retouch','busy':bool(self.active),'models':self.manager.status(),'debug':self.debug}

    def upload(self,raw,document=None):
        with self.lock:
            if self.active:raise RetouchError('busy','AI Retouch sedang bekerja. Tunggu atau Cancel proses terlebih dahulu.')
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in ['PNG','JPEG','WEBP'] or image.width*image.height>50_000_000:raise ValueError('Format/resolusi tidak didukung (maksimal 50 MP).')
                    image.load();source=image.convert('RGBA')
            except (OSError,ValueError,Image.DecompressionBombError) as e:raise RetouchError('image','Foto Retouch tidak didukung: '+str(e)) from e
            if document:
                data=self.document(document)
            else:
                if len(self.documents)>=4:raise RetouchError('memory','Maksimal empat dokumen Retouch aktif. Tutup dokumen lama terlebih dahulu.')
                if self.root is None:
                    self._temp=tempfile.TemporaryDirectory(prefix='rona-retouch-');self.root=Path(self._temp.name)
                self.root.mkdir(parents=True,exist_ok=True);document=secrets.token_hex(16);folder=self.root/document;folder.mkdir()
                data={'id':document,'folder':folder,'revision':0,'faces':None,'results':{},'bytes':0};self.documents[document]=data
            data['revision']+=1;data['faces']=None
            source.save(data['folder']/'source.png');source.close()
            # Only temporary preview/debug data is replaced; committed history results stay.
            for path in data['folder'].glob('preview-*.png'):path.unlink()
            for path in data['folder'].glob('mask-*.png'):path.unlink()
            return {'document':document,'revision':data['revision']}

    def document(self,document):
        if document not in self.documents:raise RetouchError('session','Dokumen Retouch tidak ditemukan. Analyze Face kembali.')
        return self.documents[document]

    def start(self,kind,request):
        if kind not in ['analyze','preview','apply','segment']:raise RetouchError('request','Operasi Retouch tidak valid.')
        with self.lock:
            if self.active:raise RetouchError('busy','Proses Retouch lain sedang berjalan.')
            data=self.document(request.get('document'))
            if request.get('revision')!=data['revision']:raise RetouchError('revision','Foto berubah. Analyze Face kembali.')
            from .processors import settings_valid
            settings=settings_valid(request.get('settings',{}))
            if kind not in ('analyze','segment') and data['faces'] is None:raise RetouchError('analysis','Analyze Face terlebih dahulu.')
            if kind=='apply' and len(data['results'])>=20:raise RetouchError('memory','Batas 20 hasil AI per dokumen tercapai. Export lalu buka hasil sebagai foto baru.')
            jid=secrets.token_hex(16);job={'id':jid,'document':data['id'],'status':'running','stage':'Menyiapkan AI Retouch','progress':0,'cancel':False,'kind':kind};self.jobs[jid]=job;self.active=jid
            for key in list(self.jobs)[:-32]:
                if key!=self.active:self.jobs.pop(key,None)
            threading.Thread(target=self._work,args=(job,data,settings),daemon=True).start()
            return {'job':jid}

    def _work(self,job,data,settings):
        path=None;rid=None;size=0
        def progress(stage,percent):
            if job['cancel']:raise RetouchError('cancelled','Proses dibatalkan; edit sebelumnya tetap utuh.')
            job.update(stage=stage,progress=percent)
        try:
            import numpy as np
            from .processors import process_image
            with Image.open(data['folder']/'source.png') as source:rgba=np.array(source.convert('RGBA'))
            if job['kind']=='segment':
                from .person import person_mask
                result=person_mask(rgba,self.manager,progress)
            elif job['kind']=='analyze':
                was_cached=data['faces'] is not None
                if data['faces'] is None:
                    progress('Memuat detector wajah',10)
                    faces=self.detector.detectFaces(rgba[:,:,:3],self.config['analysis_edge'],self.config['max_faces'])
                    progress('Membentuk semantic masks',45)
                    parsed=self.parser.createFaceMask(rgba[:,:,:3],faces)
                    progress('Analisis wajah selesai',95);data['faces']=parsed
                result={'faces':[{'bbox':f['bbox'],'confidence':f['confidence'],'landmarks':f['landmarks']} for f in data['faces']],
                        'document':data['id'],'revision':data['revision'],'size':[rgba.shape[1],rgba.shape[0]],'cached':was_cached,'models':self.manager.status()}
                if self.debug:result['masks']=self._debug_masks(data,rgba.shape)
            else:
                edge=None # Full detail preview, matching Apply; model inference stays face-local.
                progress('Menyiapkan mask dan kekuatan efek',10)
                output=process_image(rgba,data['faces'],settings,self.restorer,edge,progress)
                progress('Menyimpan hasil Retouch',96)
                rid=secrets.token_hex(16);prefix='preview-' if job['kind']=='preview' else 'result-';path=data['folder']/(prefix+rid+'.png')
                Image.fromarray(output).save(path);size=path.stat().st_size
                if job['kind']=='apply':
                    if data['bytes']+size>256*1024*1024:path.unlink();raise RetouchError('memory','Penyimpanan hasil Retouch sementara penuh. Export lalu buka dokumen baru.')
                    data['results'][rid]=path;data['bytes']+=size
                else:
                    for old in data['folder'].glob('preview-*.png'):
                        if old!=path:old.unlink()
                result={'url':f'/api/retouch/result/{data["id"]}/{path.name}','id':rid,'width':output.shape[1],'height':output.shape[0],
                        'faces':len(data['faces']),'models':self.manager.status(),'kind':job['kind']}
            progress('Selesai',100);job.update(status='done',result=result)
        except Exception as error:
            if path is not None and path.is_file():path.unlink()
            if rid in data['results']:data['results'].pop(rid);data['bytes']-=size
            code=getattr(error,'code','inference');job.update(status='cancelled' if code=='cancelled' else 'failed',error={'code':code,'message':str(error)})
        finally:
            with self.lock:
                if data.get('release_pending'):
                    self.documents.pop(data['id'],None);shutil.rmtree(data['folder'])
                self.active=None

    def _debug_masks(self,data,shape):
        import cv2,numpy as np
        from .processors import CLASSES
        h,w=shape[:2];scale=min(1,1024/max(h,w));width,height=max(1,round(w*scale)),max(1,round(h*scale));urls={}
        colors={'skin':(95,200,130),'eyes':(80,155,255),'eyebrows':(230,175,60),'lips':(225,105,160),'hair':(160,115,230)}
        for name in ['skin','eyes','eyebrows','lips','hair']:
            mask=np.zeros((height,width),np.uint8)
            for face in data['faces']:
                local=np.isin(face['labels'],CLASSES[name]).astype(np.uint8)*160
                inverse=cv2.invertAffineTransform(face['matrix'])*scale
                mask=np.maximum(mask,cv2.warpAffine(local,inverse,(width,height)))
            overlay=np.zeros((height,width,4),np.uint8);overlay[:,:,:3]=colors[name];overlay[:,:,3]=mask
            path=data['folder']/('mask-'+name+'.png');Image.fromarray(overlay).save(path)
            urls[name]=f'/api/retouch/result/{data["id"]}/{path.name}?revision={data["revision"]}'
        return urls

    def cancel(self,jid):
        job=self.jobs.get(jid)
        if not job:raise RetouchError('job','Job tidak ditemukan.')
        job['cancel']=True;return {'ok':True}

    def job(self,jid):
        if jid not in self.jobs:raise RetouchError('job','Job tidak ditemukan.')
        return {k:v for k,v in self.jobs[jid].items() if k!='cancel'}

    def result(self,document,name):
        data=self.document(document)
        import re
        if not re.fullmatch(r'(?:result-[a-f0-9]{32}|preview-[a-f0-9]{32}|mask-(?:skin|eyes|eyebrows|lips|hair))\.png',name):raise RetouchError('path','Nama hasil tidak valid.')
        if name.startswith('mask-') and not self.debug:raise RetouchError('debug','Debug hanya tersedia pada development.')
        path=data['folder']/name
        if not path.is_file():raise RetouchError('result','Hasil Retouch tidak ditemukan.')
        return path.read_bytes()

    def release(self,document):
        with self.lock:
            if self.active and self.jobs[self.active]['document']==document:
                self.jobs[self.active]['cancel']=True
                self.document(document)['release_pending']=True
                return {'ok':True,'pending':True}
            data=self.documents.pop(document,None)
            if data:shutil.rmtree(data['folder'])
        return {'ok':True}

    def close(self):
        if self.manager.timer:self.manager.timer.cancel()
        self.manager.unload()
        if self._temp:self._temp.cleanup()
