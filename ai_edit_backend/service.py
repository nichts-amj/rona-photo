import secrets
import threading
from PIL import Image
from retouch_backend.service import RetouchService
from retouch_backend.models import RetouchError
from .models import EditModels
from .processors import validate,process

class AIEditService(RetouchService):
    def __init__(self,manager=None,root=None):
        super().__init__(config={'development_debug':False},manager=manager or EditModels(),root=root)
        self.closing=False
    def status(self):return {**super().status(),'app':'rona-ai-edit'}
    def close(self):
        with self.lock:
            self.closing=True
            if self.active:
                self.jobs[self.active]['cancel']=True
                for data in self.documents.values():data['release_pending']=True
                return
        super().close()
    def start(self,kind,request):
        if kind not in ('preview','apply'):raise RetouchError('request','Operasi AI Edit tidak valid.')
        settings=validate(request.get('settings',{}))
        with self.lock:
            if self.active:raise RetouchError('busy','AI Edit masih memproses foto.')
            data=self.document(request.get('document'))
            if request.get('revision')!=data['revision']:raise RetouchError('revision','Foto berubah. Ulangi Preview.')
            if kind=='apply' and len(data['results'])>=20:raise RetouchError('memory','Batas 20 hasil AI Edit tercapai. Export lalu buka hasil sebagai foto baru.')
            jid=secrets.token_hex(16);job={'id':jid,'document':data['id'],'status':'running','stage':'Menyiapkan area','progress':0,'cancel':False,'kind':kind}
            self.jobs[jid]=job;self.active=jid
            for old in list(self.jobs)[:-32]:self.jobs.pop(old,None)
            threading.Thread(target=self._work,args=(job,data,settings),daemon=True).start()
            return {'job':jid}
    def _work(self,job,data,settings):
        import numpy as np
        path=None;rid=None;size=0
        def progress(stage,percent):
            if job['cancel']:raise RetouchError('cancelled','AI Edit dibatalkan. Foto sebelumnya tetap utuh.')
            job.update(stage=stage,progress=percent)
        try:
            with Image.open(data['folder']/'source.png') as source:rgba=np.array(source.convert('RGBA'))
            output=process(rgba,settings,self.manager,progress)
            progress('Menyimpan hasil',98);rid=secrets.token_hex(16)
            path=data['folder']/(('result-' if job['kind']=='apply' else 'preview-')+rid+'.png')
            Image.fromarray(output).save(path);size=path.stat().st_size
            if job['kind']=='apply':
                if data['bytes']+size>256*1024*1024:raise RetouchError('memory','Penyimpanan sementara penuh. Export hasil terlebih dahulu.')
                data['results'][rid]=path;data['bytes']+=size
            else:
                for old in data['folder'].glob('preview-*.png'):
                    if old!=path:old.unlink()
            progress('Selesai',100)
            job.update(status='done',result={'url':f'/api/ai-edit/result/{data["id"]}/{path.name}','id':rid,'width':output.shape[1],'height':output.shape[0],'models':self.manager.status(),'kind':job['kind']})
        except Exception as e:
            if path and path.is_file():path.unlink()
            if rid in data['results']:data['results'].pop(rid);data['bytes']-=size
            code=getattr(e,'code','inference');job.update(status='cancelled' if code=='cancelled' else 'failed',error={'code':code,'message':str(e)})
        finally:
            self.manager.unload()
            with self.lock:
                if data.get('release_pending'):
                    import shutil
                    self.documents.pop(data['id'],None);shutil.rmtree(data['folder'])
                self.active=None
                if self.closing and self._temp:self._temp.cleanup()
