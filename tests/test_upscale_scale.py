import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from PIL import Image
import test_studio
from local_engine import config_valid
from pipeline.realesrgan import CompactRealESRGAN
from pipeline.swin2sr import Swin2SRCompressed
from pipeline.extra_models import ExtraModel

class ScaleTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown
    wait=test_studio.StudioTests.wait

    def test_legacy_and_invalid_scales(self):
        self.assertEqual(config_valid({'weights':{'B':100},'use_mask':False})['output_scale'],2)
        for raw in [{'weights':{'A':100},'use_mask':False},
                    {'weights':{'B':100},'use_mask':True,'reference':'A'},
                    {'weights':{'F':100},'use_mask':False}]:
            with self.assertRaises(ValueError):config_valid({**raw,'output_scale':4})
        for scale in [True,3,8]:
            with self.assertRaises(ValueError):config_valid({'weights':{'B':100},'use_mask':False,'output_scale':scale})

    def test_mixed_scale_comparison_cache_and_history(self):
        calls=[]
        def infer(m,im,c,progress):
            calls.append((m,c['output_scale']))
            return im.resize((im.width*c['output_scale'],im.height*c['output_scale'])),{}
        self.studio.infer_override=infer
        configs=[config_valid({'weights':{'B':100},'use_mask':False,'output_scale':s}) for s in (2,4)]
        request={'upload':self.upload['id'],'configs':configs}
        first=self.wait(self.studio.start(request))
        self.assertEqual(first['status'],'done',first['error'])
        self.assertEqual([r['size'] for r in first['results']],[[32,24],[64,48]])
        second=self.wait(self.studio.start(request))
        self.assertEqual(second['status'],'done',second['error'])
        self.assertEqual(calls,[('B',2),('B',4)])
        restored=self.studio.history_edit({'upload':self.upload['id'],'run':first['id']})
        self.assertEqual([c['output_scale'] for c in restored['configs']],[2,4])

    def test_4x_mask_and_face_addition(self):
        def infer(m,im,c,progress):
            size=(im.width*c['output_scale'],im.height*c['output_scale'])
            if m=='F':return Image.new('RGB',size),{'_face_layer':Image.new('RGB',size,(100,100,100)), '_transmission':Image.new('RGB',size,(128,128,128))}
            return Image.new('RGB',size,(30,30,30) if m=='B' else (80,80,80)),{}
        self.studio.infer_override=infer
        c=config_valid({'weights':{'B':50,'H':50},'reference':'B','use_mask':True,'output_scale':4,'face_model':'F','feather':0})
        result=self.wait(self.studio.start({'upload':self.upload['id'],'configs':[c], 'regions':[{'polygon':[[1,1],[4,1],[4,4],[1,4]]}]}))
        self.assertEqual(result['status'],'done',result['error'])
        self.assertTrue(result['results'][0]['protected_exact'])
        with Image.open(self.studio.root/result['results'][0]['url'].removeprefix('/files/')) as im:
            self.assertEqual(im.size,(64,48))
            self.assertEqual(im.getpixel((15,15)),(30,30,30))
            self.assertNotEqual(im.getpixel((30,30)),(30,30,30))

    def test_native_4x_and_optional_2x_adapters(self):
        im=Image.new('RGB',(3,5),(20,40,60))
        native=np.asarray(im).repeat(4,0).repeat(4,1)
        engines=[(CompactRealESRGAN,'pipeline.realesrgan.tiled_retry',native),
                 (Swin2SRCompressed,'pipeline.swin2sr.infer_retry',native.astype(np.float32)/255),
                 (ExtraModel,'pipeline.extra_models.hat_tiles',native)]
        for cls,target,array in engines:
            engine=cls.__new__(cls);engine.device=SimpleNamespace(type='cpu');engine.model=None;engine.load_seconds=0;engine.denoise=.5;engine.name='H';engine._load_restorer=lambda:None
            for scale in (2,4):
                with patch(target,return_value=(array.copy(),{})):
                    if cls is ExtraModel:out,info=engine.infer(im,{'output_scale':scale,'h_tile':64})
                    else:out,info=engine.infer(im,output_scale=scale)
                self.assertEqual(out.size,(3*scale,5*scale))
                self.assertEqual(info['output_scale'],scale)
                if scale==4:np.testing.assert_array_equal(np.asarray(out),native)
