import io
import tempfile
import time
import unittest
import numpy as np
from PIL import Image
from ai_edit_backend.processors import validate,make_mask,process,MASK_POINT_LIMIT
from ai_edit_backend.service import AIEditService
from retouch_backend.models import RetouchError

def settings(**extra):return validate({'strokes':[{'x':.5,'y':.5,'r':.12}],**extra})
class Stub:
    timer=None
    def status(self):return {'device':'cpu'}
    def unload(self):pass
    def infer(self,image,mask,settings,progress):
        assert max(image.shape[:2])<=settings.get('resolution',512)
        progress('Test inference',50)
        return np.full_like(image,230)

class AIEditTests(unittest.TestCase):
    def test_processing_resolutions_preserve_final_size_and_unmarked_pixels(self):
        rgba=np.full((400,600,4),90,np.uint8);rgba[:,:,3]=255
        for model in ('lama','sd15'):
            for resolution in (512,768,1024):
                s=settings(model=model,prompt='empty background',resolution=resolution);seen=[]
                class Recorder(Stub):
                    def infer(self,image,mask,settings,progress):
                        seen.append(image.shape[:2]);return super().infer(image,mask,settings,progress)
                out=process(rgba,s,Recorder(),lambda *a:None)
                self.assertEqual(max(seen[0]),resolution);self.assertTrue(all(n%8==0 for n in seen[0]));self.assertEqual(out.shape,rgba.shape)
                mask=make_mask(rgba.shape,s['strokes']);np.testing.assert_array_equal(out[mask==0],rgba[mask==0]);np.testing.assert_array_equal(out[:,:,3],rgba[:,:,3])
        self.assertEqual(settings()['resolution'],512)
        for resolution in (0,513,2048,'768',True,float('nan')):
            with self.assertRaises(ValueError):settings(resolution=resolution)
    def test_larger_mask_budget_has_independent_eraser_reserve(self):
        paint={'x':.5,'y':.5,'r':.1,'erase':False};erase={**paint,'erase':True}
        result=settings(strokes=[paint]*MASK_POINT_LIMIT+[erase]*MASK_POINT_LIMIT)
        self.assertEqual(len(result['strokes']),40000)
        self.assertFalse(make_mask((8,8),result['strokes']).any())
        for points in ([paint]*(MASK_POINT_LIMIT+1),[erase]*(MASK_POINT_LIMIT+1)):
            with self.assertRaises(ValueError):settings(strokes=points)
    def test_erased_area_can_be_painted_again_in_sequence(self):
        paint={'x':.5,'y':.5,'r':.2,'erase':False};erase={**paint,'erase':True}
        mask=make_mask((32,32),[paint,erase,paint]);self.assertEqual(mask[16,16],255)
    def test_validation_rejects_invalid_settings(self):
        for extra in [{'model':'unknown'},{'model':'sd15','prompt':''},{'steps':float('nan')},{'seed':.5},{'low_memory':'yes'},{'strokes':[]},{'strokes':[{'x':2,'y':0,'r':.2}]}]:
            with self.assertRaises(ValueError):settings(**extra)
    def test_mask_eraser_and_empty_area(self):
        s=settings();s['strokes'].append({**s['strokes'][0],'erase':True})
        self.assertFalse(make_mask((100,100),s['strokes']).any())
        with self.assertRaises(ValueError):process(np.zeros((100,100,4),np.uint8),s,Stub(),lambda *a:None)
    def test_preserves_unmarked_pixels_alpha_original_and_dimensions(self):
        rng=np.random.default_rng(2);rgba=rng.integers(0,256,(700,1200,4),dtype=np.uint8);before=rgba.copy();s=settings()
        mask=make_mask(rgba.shape,s['strokes']);out=process(rgba,s,Stub(),lambda *a:None)
        np.testing.assert_array_equal(rgba,before);np.testing.assert_array_equal(out[:,:,3],rgba[:,:,3])
        np.testing.assert_array_equal(out[mask==0],rgba[mask==0]);self.assertEqual(out.shape,rgba.shape);self.assertTrue(np.any(out!=rgba))
    def test_edge_masks_preserve_bounds_and_tiny_images(self):
        for h,w in [(1,1),(10,500),(500,10)]:
            rgba=np.full((h,w,4),150,np.uint8);rgba[:,:,3]=255
            out=process(rgba,settings(strokes=[{'x':1,'y':1,'r':.1}]),Stub(),lambda *a:None)
            self.assertEqual(out.shape,rgba.shape)
    def test_cancellation_prevents_output(self):
        def cancel(*args):raise RetouchError('cancelled','Cancel')
        with self.assertRaises(RetouchError):process(np.full((32,32,4),255,np.uint8),settings(),Stub(),cancel)
    def test_session_preview_apply_revision_release_and_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=AIEditService(Stub(),tmp);data=io.BytesIO();Image.new('RGBA',(32,32),(60,70,80,255)).save(data,format='PNG')
            upload=service.upload(data.getvalue());request={**upload,'settings':settings()}
            for kind in ('preview','apply'):
                jid=service.start(kind,request)['job']
                for _ in range(100):
                    job=service.job(jid)
                    if job['status']!='running':break
                    time.sleep(.02)
                self.assertEqual(job['status'],'done',job);result=job['result'];self.assertTrue(result['url'].startswith('/api/ai-edit/result/'))
                self.assertTrue(service.result(upload['document'],result['url'].rsplit('/',1)[1]).startswith(b'\x89PNG'))
            self.assertEqual(len(service.document(upload['document'])['results']),1)
            with self.assertRaises(RetouchError):service.result(upload['document'],'../../source.png')
            with self.assertRaises(RetouchError):service.start('apply',{**request,'revision':0})
            service.release(upload['document']);self.assertFalse(service.documents);service.close()

    def test_http_auth_routes_and_shared_gpu_reservation(self):
        import json,threading,urllib.request,urllib.error
        from unittest.mock import patch
        from web_app import make_server
        from local_engine import Studio
        with tempfile.TemporaryDirectory() as tmp:
            service=AIEditService(Stub(),root=__import__('pathlib').Path(tmp)/'edit')
            with patch('ai_edit_backend.api.AIEditService',return_value=service):server=make_server(0,Studio(__import__('pathlib').Path(tmp)/'upscale'))
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base=f'http://127.0.0.1:{server.server_port}'
            def post(path,data,token):
                req=urllib.request.Request(base+path,json.dumps(data).encode(),headers={'X-Studio-Token':token,'Content-Type':'application/json'})
                with urllib.request.urlopen(req) as response:return json.load(response)
            try:
                with urllib.request.urlopen(base+'/api/ai-edit/status') as response:status=json.load(response)
                self.assertEqual(status['app'],'rona-ai-edit');token=status['token']
                with self.assertRaises(urllib.error.HTTPError) as error:post('/api/ai-edit/release',{'document':'invalid'},'bad-token')
                self.assertEqual(error.exception.code,403)
                stream=io.BytesIO();Image.new('RGB',(32,32),(90,110,130)).save(stream,format='PNG');upload=service.upload(stream.getvalue())
                # An active Edit worker must reserve GPU against both other modules.
                service.active='reserved'
                for path in ('/api/jobs','/api/retouch/analyze','/api/ai-edit/preview'):
                    with self.assertRaises(urllib.error.HTTPError) as error:post(path,{},token)
                    self.assertEqual(error.exception.code,409)
                service.active=None
                # Payload above the old 256 KB ceiling must be accepted by AI Edit.
                large=settings(strokes=[{'x':.5,'y':.5,'r':.12}]*MASK_POINT_LIMIT)
                self.assertGreater(len(json.dumps(large)),256*1024)
                jid=post('/api/ai-edit/apply',{**upload,'settings':large},token)['job']
                for _ in range(100):
                    with urllib.request.urlopen(base+'/api/ai-edit/status?job='+jid) as response:state=json.load(response)
                    if state['status']!='running':break
                    time.sleep(.02)
                self.assertEqual(state['status'],'done',state)
                with urllib.request.urlopen(base+state['result']['url']) as response:self.assertTrue(response.read().startswith(b'\x89PNG'))
                post('/api/ai-edit/release',{'document':upload['document']},token)
            finally:
                service.active=None;server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
