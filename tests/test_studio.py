import io
import json
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from PIL import Image
from local_engine import Studio, config_valid
from web_app import make_server


def photo_bytes():
    stream=io.BytesIO()
    Image.new('RGB',(16,12),(15,25,35)).save(stream,'PNG')
    return stream.getvalue()


def config(**kwargs):
    return config_valid({'weights':{'A':65,'B':35},**kwargs})


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.calls=[]
        def inference(m,im,c,progress):
            self.calls.append((m,c['denoise']))
            progress(1,1,128)
            return Image.new('RGB',(im.width*2,im.height*2),{'A':20,'B':100,'S':180}[m]),{'test':True}
        self.studio=Studio(Path(self.temp.name),inference)
        self.upload=self.studio.upload(photo_bytes(),'foto.png')

    def tearDown(self):
        self.temp.cleanup()

    def wait(self,jid):
        deadline=time.monotonic()+5
        while self.studio.active and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertIsNone(self.studio.active)
        return self.studio.status(jid)

    def test_dedup_cache_and_mask_reference(self):
        cfg=config()
        request={'upload':self.upload['id'],'configs':[cfg,config(weights={'B':100},use_mask=False)],
                 'regions':[{'polygon':[[0,0],[5,0],[5,5],[0,5]]}]}
        jid=self.studio.start(request)
        result=self.wait(jid)
        self.assertEqual(result['status'],'done',result['error'])
        self.assertEqual(self.calls,[('A',.5),('B',.5)])
        self.assertTrue(result['results'][0]['protected_exact'])
        with Image.open(self.studio.root/result['results'][0]['url'].removeprefix('/files/')) as im:
            self.assertEqual(im.getpixel((2,2)),(20,0,0))
        result=self.wait(self.studio.start(request))
        self.assertEqual(len(self.calls),2)
        self.assertEqual(result['reused'],2)
        # Changing only B's denoise invalidates B, not A.
        request['configs']=[config(denoise=.2)]
        result=self.wait(self.studio.start(request))
        self.assertEqual(self.calls[-1],('B',.2))
        self.assertEqual(len(self.calls),3)

    def test_reference_with_zero_weight(self):
        result=self.wait(self.studio.start({'upload':self.upload['id'],
             'configs':[config(weights={'B':100},feather=0)],
             'regions':[{'polygon':[[0,0],[5,0],[5,5],[0,5]]}]}))
        self.assertEqual(result['status'],'done',result['error'])
        self.assertEqual([m for m,d in self.calls],['B','A'])
        self.assertTrue(result['results'][0]['protected_exact'])

    def test_reject_bad_parameters_and_preset_persistence(self):
        for raw in [{'weights':{'A':float('nan')}},{'weights':{}},{'weights':{'A':100},'tile':64,'overlap':64}]:
            with self.assertRaises(ValueError):
                config_valid(raw)
        self.studio.save_preset('Foto lembut',[config()])
        fresh=Studio(self.studio.root)
        self.assertEqual(fresh.presets()[0]['name'],'Foto lembut')
        self.assertNotIn('regions',fresh.presets()[0])
        fresh.delete_preset(fresh.presets()[0]['id'])
        self.assertEqual(fresh.presets(),[])

    def test_cancel_and_double_submission(self):
        entered=threading.Event();release=threading.Event()
        def blocking(m,im,c,progress):
            entered.set();release.wait(3);progress(1,1,64)
            return im.resize((32,24)),{}
        self.studio.infer_override=blocking
        req={'upload':self.upload['id'],'configs':[config()]}
        jid=self.studio.start(req)
        self.assertTrue(entered.wait(2))
        with self.assertRaises(ValueError):
            self.studio.start(req)
        self.studio.cancel(jid);release.set()
        self.assertEqual(self.wait(jid)['status'],'cancelled')

    def test_failure_releases_worker(self):
        def fail(*args):
            raise RuntimeError('Kesalahan model uji')
        self.studio.infer_override=fail
        result=self.wait(self.studio.start({'upload':self.upload['id'],'configs':[config()]}))
        self.assertEqual(result['status'],'failed')
        self.assertIn('Kesalahan model',result['error'])

    def test_http_auth_host_and_paths(self):
        server=make_server(0,self.studio)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(base+'/api/bootstrap') as r:
                token=json.load(r)['token']
            bad=urllib.request.Request(base+'/api/jobs',data=b'{}',headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(bad)
            self.assertEqual(e.exception.code,403)
            for path in ['/files/../../app.py','/%2e%2e/app.py']:
                with self.assertRaises(urllib.error.HTTPError) as e:
                    urllib.request.urlopen(base+path)
                self.assertEqual(e.exception.code,404)
            req=urllib.request.Request(base+'/api/presets',data=json.dumps({'name':'HTTP','configs':[config()]}).encode(),headers={'X-Studio-Token':token})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(json.load(r)[0]['name'],'HTTP')
            req=urllib.request.Request(base+'/',headers={'Host':'evil.test'})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req)
            self.assertEqual(e.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_batch_limit_failure_continuation_and_order(self):
        u2=self.studio.upload(photo_bytes(),'second.png')
        calls=[]
        def inference(model,image,c,progress):
            calls.append(model)
            if model=='S':raise RuntimeError('S gagal untuk pengujian')
            progress(1,1,64)
            return image.resize((32,24)),{}
        self.studio.infer_override=inference
        item={'upload':self.upload['id'],'configs':[config(weights={'S':100},use_mask=False)]}
        with self.assertRaises(ValueError):self.studio.start({'items':[item]*11})
        second={'upload':u2['id'],'configs':[config(weights={'A':100},use_mask=False)]}
        state=self.wait(self.studio.start({'items':[item,second]}))
        self.assertEqual([r['status'] for r in state['items']],['failed','done'])
        self.assertEqual(calls,['S','A'])
        self.assertTrue(state['batch'])

    def test_batch_cancel_skips_remaining(self):
        entered=threading.Event();release=threading.Event()
        def blocking(m,im,c,progress):
            entered.set();release.wait(3);progress(1,1,64)
            return im.resize((32,24)),{}
        self.studio.infer_override=blocking
        item={'upload':self.upload['id'],'configs':[config()]}
        jid=self.studio.start({'items':[item,item]})
        self.assertTrue(entered.wait(2))
        self.studio.cancel(jid);release.set()
        state=self.wait(jid)
        self.assertEqual([r['status'] for r in state['items']],['cancelled','cancelled'])

    def test_face_layer_cache_and_mix(self):
        calls=[]
        def infer(m,im,c,progress):
            calls.append(m)
            size=(im.width*2,im.height*2)
            if m=='F':
                return Image.new('RGB',size,(200,200,200)),{
                    '_face_layer':Image.new('RGB',size,(100,100,100)),
                    '_transmission':Image.new('RGB',size,(128,128,128))}
            return Image.new('RGB',size,(30,30,30)),{}
        self.studio.infer_override=infer
        c=config(weights={'A':100},face_model='F',face_mix=0,use_mask=False)
        req={'upload':self.upload['id'],'configs':[c]}
        first=self.wait(self.studio.start(req))
        self.assertEqual(first['status'],'done',first['error'])
        with Image.open(self.studio.root/first['results'][0]['url'].removeprefix('/files/')) as im:
            self.assertEqual(im.getpixel((1,1)),(30,30,30))
        req['configs'][0]['face_mix']=1
        second=self.wait(self.studio.start(req))
        self.assertEqual(second['status'],'done',second['error'])
        self.assertEqual(calls,['A','F'])
        with Image.open(self.studio.root/second['results'][0]['url'].removeprefix('/files/')) as im:
            self.assertEqual(im.getpixel((1,1)),(115,115,115))

    def test_face_models_not_uniform_blended(self):
        with self.assertRaises(ValueError):config(weights={'A':50,'F':50})
        with self.assertRaises(ValueError):config(weights={'F':50,'G':50})
        self.assertEqual(config(weights={'H':100},use_mask=False)['label'],'HAT')
        self.assertEqual(config(weights={'B':100},use_mask=True)['label'],'SwinIR + Real-ESRGAN')

    def test_live_batch_progress_before_image_finishes(self):
        entered=threading.Event();release=threading.Event()
        def inference(model,image,c,progress):
            progress(1,2,64)
            entered.set();release.wait(3)
            return image.resize((32,24)),{}
        self.studio.infer_override=inference
        item={'upload':self.upload['id'],'configs':[config(weights={'A':100},use_mask=False)]}
        jid=self.studio.start({'items':[item,item]})
        try:
            self.assertTrue(entered.wait(2))
            state=self.studio.status(jid)
            self.assertEqual(state['items'][0]['percent'],45)
            self.assertEqual(state['percent'],22)
            self.assertEqual(state['status'],'running')
        finally:
            release.set()
            state=self.wait(jid)
        self.assertEqual(state['percent'],100)

    def test_standard_models_with_each_face_addon_run_sequentially(self):
        calls=[]
        def infer(model,image,c,progress):
            calls.append(model)
            size=(32,24)
            if model in ('F','G'):
                return Image.new('RGB',size),{'_face_layer':Image.new('RGB',size,(50,50,50)),
                    '_transmission':Image.new('RGB',size,(128,128,128))}
            return Image.new('RGB',size,(30,30,30)),{}
        self.studio.infer_override=infer
        for model in ('A','B','S','H'):
            for face in ('F','G'):
                upload=self.studio.upload(photo_bytes(),model+face+'.png')
                calls.clear()
                result=self.wait(self.studio.start({'upload':upload['id'],'configs':[
                    config(weights={model:100},use_mask=False,face_model=face)]}))
                self.assertEqual(result['status'],'done',result['error'])
                self.assertEqual(calls,[model,face])
