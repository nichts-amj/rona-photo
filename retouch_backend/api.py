"""Small dispatch extension; all endpoints belong to /api/retouch/."""
import json
from urllib.parse import urlsplit,parse_qs
from .models import RetouchError
from .service import RetouchService

class RetouchAPI:
    def __init__(self,token,studio,service=None):self.token=token;self.studio=studio;self.service=service or RetouchService()
    def get(self,handler,path):
        if not path.startswith('/api/retouch/'):return False
        try:
            if path=='/api/retouch/status':
                jid=parse_qs(urlsplit(handler.path).query).get('job',[None])[0]
                handler.send(self.service.job(jid) if jid else {**self.service.status(),'token':self.token})
            elif path.startswith('/api/retouch/result/'):
                parts=path.split('/')
                if len(parts)!=6:raise RetouchError('path','Alamat hasil tidak valid.')
                handler.send(self.service.result(parts[4],parts[5]),'image/png')
            else:handler.send({'error':{'code':'route','message':'Alamat Retouch tidak ditemukan.'}},status=404)
        except (RetouchError,ValueError,OSError) as e:handler.send({'error':{'code':getattr(e,'code','request'),'message':str(e)}},status=400)
        return True
    def post(self,handler,path):
        if not path.startswith('/api/retouch/'):return False
        try:
            length=int(handler.headers.get('Content-Length','0'));limit=256*1024*1024 if path=='/api/retouch/image' else getattr(self,'request_limit',256*1024)
            if not 0<length<=limit:raise RetouchError('size','Berkas/request Retouch terlalu besar atau kosong.')
            raw=handler.rfile.read(length)
            if path=='/api/retouch/image':result=self.service.upload(raw,handler.headers.get('X-Retouch-Document') or None)
            else:
                request=json.loads(raw)
                if not isinstance(request,dict):raise ValueError('Request harus berupa object.')
                if path in ['/api/retouch/analyze','/api/retouch/preview','/api/retouch/apply','/api/retouch/segment']:
                    if self.studio.active:raise RetouchError('busy','Upscale sedang memproses foto. AI Retouch dapat dijalankan setelah selesai.')
                    result=self.service.start(path.rsplit('/',1)[1],request)
                elif path=='/api/retouch/cancel':result=self.service.cancel(request['job'])
                elif path=='/api/retouch/release':result=self.service.release(request['document'])
                elif path=='/api/retouch/unload':
                    if self.service.active:raise RetouchError('busy','Tunggu inference selesai sebelum unload model.')
                    self.service.manager.unload();result={'ok':True}
                else:raise RetouchError('route','Alamat Retouch tidak ditemukan.')
            handler.send(result)
        except (RetouchError,ValueError,KeyError,TypeError,OSError) as e:
            handler.send({'error':{'code':getattr(e,'code','request'),'message':str(e)}},status=409 if getattr(e,'code','')=='busy' else 400)
        return True
