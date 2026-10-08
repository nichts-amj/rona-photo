import io,json,tempfile,time,unittest
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from retouch_backend.models import ModelManager,RetouchError
from retouch_backend.processors import settings_valid,masks,process_image,SkinProcessor,BlemishProcessor
from retouch_backend.service import RetouchService

CONFIG={'device':'cpu','idle_unload_seconds':120,'analysis_edge':256,'preview_edge':128,'max_faces':16,'development_debug':True}
def fixture():
    rng=np.random.default_rng(7);rgb=np.clip(130+rng.normal(0,5,(512,512,3)),0,255).astype(np.uint8)
    labels=np.zeros((512,512),np.uint8);labels[50:462,50:462]=1
    labels[150:180,140:200]=4;labels[150:180,300:360]=5;labels[130:140,140:200]=2;labels[320:350,210:300]=12;labels[:70,:]=17;labels[220:260,240:270]=10
    face={'labels':labels,'aligned':rgb,'matrix':np.array([[1,0,0],[0,1,0]],float),'bbox':[50,50,462,462],'confidence':.99,'landmarks':[]}
    rgba=np.dstack([rgb,np.full((512,512),175,np.uint8)]);return rgba,face
class StubRestorer:
    def restoreFace(self,face,*args):return np.clip(face['aligned'].astype(int)+35,0,255).astype(np.uint8)

class RetouchProcessorTests(unittest.TestCase):
    def test_automatic_restores_features_preserves_size_background_and_alpha(self):
        im,face=fixture();before=im.copy()
        settings=settings_valid({'mode':'automatic','model':'gfpgan','strength':70,'eyes':False,'identity':False,'texture':False})
        out=process_image(im,[face],settings,StubRestorer(),edge=128)
        self.assertEqual(out.shape,im.shape)
        for label in [4,5,10,12]:self.assertTrue(np.any(out[face['labels']==label]!=im[face['labels']==label]))
        for label in [0,17]:np.testing.assert_array_equal(out[face['labels']==label],im[face['labels']==label])
        np.testing.assert_array_equal(out[:,:,3],im[:,:,3]);np.testing.assert_array_equal(im,before)
        settings['strength']=0
        np.testing.assert_array_equal(process_image(im,[face],settings,StubRestorer()),im)
    def test_automatic_strength_blends_predictably_and_rejects_invalid_model(self):
        im,face=fixture()
        a=process_image(im,[face],settings_valid({'mode':'automatic','strength':30}),StubRestorer())
        b=process_image(im,[face],settings_valid({'mode':'automatic','strength':100}),StubRestorer())
        self.assertGreater(np.abs(b.astype(float)-im).sum(),np.abs(a.astype(float)-im).sum())
        for raw in [{'model':'other'},{'mode':'other'},{'fidelity':float('nan')},{'fidelity':1.1}]:
            with self.assertRaises(ValueError):settings_valid(raw)

    def test_automatic_defaults_preserve_eyes_hair_alpha_and_reduce_identity_mix(self):
        im,face=fixture();settings=settings_valid({'mode':'automatic','strength':100})
        self.assertEqual(settings['model'],'gfpgan')
        out=process_image(im,[face],settings,StubRestorer())
        for label in [0,4,5,17]:np.testing.assert_array_equal(out[face['labels']==label],im[face['labels']==label])
        np.testing.assert_array_equal(out[:,:,3],im[:,:,3])
        stronger=process_image(im,[face],{**settings,'identity':False},StubRestorer())
        self.assertGreater(np.abs(stronger.astype(float)-im).sum(),np.abs(out.astype(float)-im).sum())
    def test_automatic_texture_keeps_source_skin_detail(self):
        im,face=fixture()
        class FlatRestorer:
            def restoreFace(self,*args):return np.full((512,512,3),160,np.uint8)
        options=settings_valid({'mode':'automatic','strength':100,'identity':False})
        a=process_image(im,[face],options,FlatRestorer())
        b=process_image(im,[face],{**options,'texture':False},FlatRestorer())
        area=(slice(380,440),slice(100,180),slice(0,3))
        self.assertGreater(a[area].std(),b[area].std())
    def test_manual_restoration_reaches_new_blend_limits(self):
        im,face=fixture()
        for identity,limit in [(True,.4),(False,.85)]:
            settings=settings_valid({'smooth':0,'blemish':0,'restore':100,'identity':identity})
            out=process_image(im,[face],settings,StubRestorer())
            # Interior cheek receives the new blend, excluding mask feather edges.
            delta=out[400,150,:3].astype(float)-im[400,150,:3]
            np.testing.assert_allclose(delta,35*limit,atol=1)

    def test_unified_defaults_and_125_strength_preserve_regions_and_increase_effect(self):
        defaults=settings_valid({})
        self.assertEqual([defaults[k] for k in ['smooth','restore','strength']],[50,50,100])
        im,face=fixture()
        a=process_image(im,[face],settings_valid({'smooth':0,'restore':100}),StubRestorer())
        b=process_image(im,[face],settings_valid({'smooth':0,'restore':125}),StubRestorer())
        self.assertGreater(np.abs(b.astype(float)-im).sum(),np.abs(a.astype(float)-im).sum())
        np.testing.assert_array_equal(b[face['labels']==4],im[face['labels']==4])
        c=process_image(im,[face],settings_valid({'smooth':0,'restore':125,'identity':False}),StubRestorer())
        np.testing.assert_array_equal(c[400,150,:3],StubRestorer().restoreFace(face)[400,150])
        mask=masks(face['labels'],defaults)[0]
        a=SkinProcessor().smoothSkin(im[:,:,:3],mask,{**defaults,'smooth':100})
        b=SkinProcessor().smoothSkin(im[:,:,:3],mask,{**defaults,'smooth':125})
        self.assertGreater(np.abs(b-im[:,:,:3]).sum(),np.abs(a-im[:,:,:3]).sum())
        for raw in [{'smooth':126},{'restore':126},{'strength':101}]:
            with self.assertRaises(ValueError):settings_valid(raw)

    def test_zero_strength_is_exact_and_original_is_not_mutated(self):
        im,face=fixture();before=im.copy();s=settings_valid({'strength':0})
        np.testing.assert_array_equal(process_image(im,[face],s,StubRestorer()),im);np.testing.assert_array_equal(before,im)
        np.testing.assert_array_equal(process_image(im,[face],s,StubRestorer(),edge=128),im)
    def test_protected_features_hair_background_alpha_exact(self):
        im,face=fixture();s=settings_valid({'smooth':100,'restore':100,'blemish':100,'auto':True})
        out=process_image(im,[face],s,StubRestorer());blocked=np.isin(face['labels'],[0,2,3,4,5,10,12,17])
        np.testing.assert_array_equal(out[blocked],im[blocked]);np.testing.assert_array_equal(out[:,:,3],im[:,:,3]);self.assertTrue(np.any(out!=im))
    def test_texture_preservation_keeps_more_high_frequency_detail(self):
        im,face=fixture();s=settings_valid({'smooth':100,'restore':0,'blemish':0});mask=masks(face['labels'],s)[0]
        a=SkinProcessor().smoothSkin(im[:,:,:3],mask,s);s['texture']=False;b=SkinProcessor().smoothSkin(im[:,:,:3],mask,s)
        region=(slice(380,440),slice(100,180));self.assertGreater(a[region].std(),b[region].std())
    def test_manual_blemish_never_edits_non_skin(self):
        im,face=fixture();s=settings_valid({'smooth':0,'restore':0,'blemish':100,'strokes':[{'x':.33,'y':.32,'r':.07}]})
        out=process_image(im,[face],s,StubRestorer());np.testing.assert_array_equal(out[face['labels']!=1],im[face['labels']!=1])
    def test_no_faces_preserves_original_and_validation(self):
        im,_=fixture();np.testing.assert_array_equal(process_image(im,[],settings_valid({}),StubRestorer()),im)
        for raw in [{'strength':float('nan')},{'smooth':126},{'eyes':'yes'},{'strokes':[{'x':2,'y':0,'r':.1}]}]:
            with self.assertRaises(ValueError):settings_valid(raw)
    def test_preserve_switches_protect_restoration_regions(self):
        im,face=fixture();off=settings_valid({'smooth':0,'blemish':0,'restore':100,'identity':False,'eyes':False,'hair':False})
        out=process_image(im,[face],off,StubRestorer());self.assertTrue(np.any(out[face['labels']==4]!=im[face['labels']==4]));self.assertTrue(np.any(out[face['labels']==17]!=im[face['labels']==17]))
        on={**off,'eyes':True,'hair':True};out=process_image(im,[face],on,StubRestorer());np.testing.assert_array_equal(out[face['labels']==4],im[face['labels']==4]);np.testing.assert_array_equal(out[face['labels']==17],im[face['labels']==17])
    def test_auto_and_manual_blemish_change_selected_skin_spot(self):
        im,face=fixture();im[:,:,:3]=130;face['aligned'][:]=130
        cv2.circle(face['aligned'],(110,300),2,(180,80,80),-1);im[:,:,:3]=face['aligned']
        for options in [{'auto':True},{'strokes':[{'x':110/512,'y':300/512,'r':4/512}]}]:
            s=settings_valid({'smooth':0,'restore':0,'blemish':100,**options});out=process_image(im,[face],s,StubRestorer());self.assertTrue(np.any(out[298:303,108:113]!=im[298:303,108:113]))

class RetouchModelTests(unittest.TestCase):
    def test_restorer_cache_tracks_model_fidelity_and_ignores_blend(self):
        import torch
        from retouch_backend.models import FaceRestorer
        calls=[]
        class Manager:
            config={'face_restorer':'codeformer'}
            device='cpu'
            def run(self,role,action):
                def model(tensor,**options):
                    calls.append((role,options))
                    return (tensor.clone(),)
                return action(model)
        _,face=fixture();restorer=FaceRestorer(Manager())
        first=restorer.restoreFace(face,'codeformer',.8)
        self.assertIs(restorer.restoreFace(face,'codeformer',.8),first)
        restorer.restoreFace(face,'codeformer',.2)
        restorer.restoreFace(face,'gfpgan',.2)
        restorer.restoreFace(face,'gfpgan',.9)
        restorer.restoreFace(face,'codeformer',.8)
        self.assertEqual([c[0] for c in calls],['restorer:codeformer','restorer:codeformer','restorer:gfpgan','restorer:codeformer'])
        self.assertEqual(calls[0][1]['w'],.8)
        self.assertEqual(calls[1][1]['w'],.2)

    def test_lazy_cache_single_model_and_explicit_unload(self):
        calls=[];manager=ModelManager(CONFIG,lambda role,device:calls.append((role,device)) or object())
        self.assertEqual(manager.status()['loaded'],[]);a=manager.get('detector');self.assertIs(a,manager.get('detector'))
        manager.get('parser');self.assertEqual(calls,[('detector','cpu'),('parser','cpu')]);self.assertEqual(manager.status()['loaded'],['parser']);manager.unload();self.assertEqual(manager.status()['loaded'],[])
    def test_cuda_oom_fallback_does_not_touch_input(self):
        manager=ModelManager({**CONFIG,'device':'auto'},lambda role,device:device);manager.device='cuda'
        def fn(device):
            if device=='cuda':raise RuntimeError('CUDA out of memory')
            return 'cpu-success'
        self.assertEqual(manager.run('detector',fn),'cpu-success');self.assertEqual(manager.device,'cpu');manager.timer.cancel();manager.unload()

class RetouchServiceTests(unittest.TestCase):
    def wait(self,s,jid):
        deadline=time.monotonic()+5
        while s.active and time.monotonic()<deadline:time.sleep(.01)
        self.assertFalse(s.active);return s.job(jid)
    def test_analysis_reused_preview_apply_revision_and_result_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=RetouchService(CONFIG,root=Path(tmp));raw=io.BytesIO();Image.new('RGBA',(20,16),(100,120,140,120)).save(raw,'PNG');upload=s.upload(raw.getvalue())
            calls=[];s.detector.detectFaces=lambda *a:calls.append('detect') or [];s.parser.createFaceMask=lambda *a:[]
            self.assertEqual(self.wait(s,s.start('analyze',upload)['job'])['status'],'done');self.wait(s,s.start('analyze',upload)['job']);self.assertEqual(calls,['detect'])
            result=self.wait(s,s.start('apply',{**upload,'settings':{'strength':0}})['job'])['result'];self.assertEqual(result['width'],20)
            self.assertTrue(s.result(upload['document'],result['url'].rsplit('/',1)[1]).startswith(b'\x89PNG'))
            revised=s.upload(raw.getvalue(),upload['document']);self.assertIsNone(s.document(upload['document'])['faces'])
            with self.assertRaises(RetouchError):s.start('preview',upload)
            self.assertIn(result['id'],s.document(upload['document'])['results']);s.release(upload['document']);self.assertEqual(s.documents,{})
    def test_failure_is_structured_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=RetouchService(CONFIG,root=Path(tmp));raw=io.BytesIO();Image.new('RGB',(16,16)).save(raw,'PNG');upload=s.upload(raw.getvalue())
            def fail(*a):raise RetouchError('segmentation','Mask gagal')
            s.detector.detectFaces=fail;state=self.wait(s,s.start('analyze',upload)['job']);self.assertEqual(state['error']['code'],'segmentation');self.assertTrue((s.document(upload['document'])['folder']/'source.png').exists())
    def test_release_during_inference_cancels_and_cleans_session(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            s=RetouchService(CONFIG,root=Path(tmp));raw=io.BytesIO();Image.new('RGB',(16,16)).save(raw,'PNG');upload=s.upload(raw.getvalue());folder=s.document(upload['document'])['folder']
            entered=threading.Event();resume=threading.Event()
            def detect(*args):entered.set();resume.wait(2);return []
            s.detector.detectFaces=detect;jid=s.start('analyze',upload)['job'];self.assertTrue(entered.wait(2));self.assertTrue(s.release(upload['document'])['pending']);resume.set()
            self.assertEqual(self.wait(s,jid)['status'],'cancelled');self.assertFalse(folder.exists());self.assertNotIn(upload['document'],s.documents)
    def test_debug_disabled_in_production_and_paths_rejected(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'RONA_RESOURCE_DIR':tmp}):
            s=RetouchService(CONFIG,root=Path(tmp));self.assertFalse(s.status()['debug']);raw=io.BytesIO();Image.new('RGB',(8,8)).save(raw,'PNG');upload=s.upload(raw.getvalue())
            for name in ['../source.png','source.png','mask-skin.png']:
                with self.assertRaises(RetouchError):s.result(upload['document'],name)
            s.close()

class RetouchHTTPTests(unittest.TestCase):
    def test_authenticated_upload_revision_and_csrf_without_loading_models(self):
        import threading,urllib.request,urllib.error
        from unittest.mock import patch
        from local_engine import Studio
        from web_app import make_server
        with tempfile.TemporaryDirectory() as tmp:
            service=RetouchService(CONFIG,root=Path(tmp)/'retouch')
            with patch('retouch_backend.api.RetouchService',return_value=service):server=make_server(0,Studio(Path(tmp)/'upscale'))
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base=f'http://127.0.0.1:{server.server_port}'
            def post(path,body,headers):
                request=urllib.request.Request(base+path,data=body,headers=headers)
                try:
                    with urllib.request.urlopen(request) as response:return response.status,json.load(response)
                except urllib.error.HTTPError as error:return error.code,json.load(error)
            try:
                with urllib.request.urlopen(base+'/api/retouch/status') as response:status=json.load(response)
                self.assertEqual(status['models']['loaded'],[]);token=status['token'];raw=io.BytesIO();Image.new('RGBA',(20,16)).save(raw,'PNG')
                self.assertEqual(post('/api/retouch/image',raw.getvalue(),{})[0],403)
                self.assertEqual(post('/api/retouch/image',raw.getvalue(),{'X-Studio-Token':token,'Origin':'https://invalid.example'})[0],403)
                code,upload=post('/api/retouch/image',raw.getvalue(),{'X-Studio-Token':token});self.assertEqual(code,200);self.assertEqual(service.manager.status()['loaded'],[])
                code,error=post('/api/retouch/preview',json.dumps({**upload,'revision':0}).encode(),{'X-Studio-Token':token});self.assertEqual(code,400);self.assertEqual(error['error']['code'],'revision')
            finally:server.shutdown();server.server_close();worker.join();service.close()
