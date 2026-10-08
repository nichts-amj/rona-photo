import tempfile
import io
import json
import time
import unittest
from unittest.mock import patch
import numpy as np
import torch
from PIL import Image
from local_engine import Studio, config_valid
from pipeline.performance import NonFiniteOutput, adaptive_tile, precision_for, run_with_fallback
from pipeline.realesrgan import tiled_x4
from pipeline.swin2sr import tiled_forward, infer_retry
from pipeline.extra_models import hat_tiles


class PerformanceTests(unittest.TestCase):
    def test_precision_by_device_and_capability(self):
        self.assertIsNone(precision_for('cpu','B'))
        self.assertIsNone(precision_for('cuda','B',False))
        with patch('torch.cuda.get_device_capability',return_value=(8,6)), patch('torch.cuda.is_bf16_supported',return_value=True):
            self.assertEqual(precision_for('cuda','B'),torch.float16)
            self.assertEqual(precision_for('cuda','S'),torch.bfloat16)
            self.assertEqual(precision_for('cuda','H'),torch.bfloat16)
        with patch('torch.cuda.get_device_capability',return_value=(7,5)), patch('torch.cuda.is_bf16_supported',return_value=False):
            self.assertIsNone(precision_for('cuda','S'))

    def test_adaptive_tile_preserves_manual_ceiling(self):
        with patch('torch.cuda.mem_get_info',return_value=(3*1024**3,4*1024**3)):
            self.assertEqual(adaptive_tile('cuda','B',128,torch.float16),128)
            self.assertEqual(adaptive_tile('cuda','H',128,torch.bfloat16),96)
        with patch('torch.cuda.mem_get_info',return_value=(512*1024**2,4*1024**3)):
            self.assertEqual(adaptive_tile('cuda','B',512,torch.float16),128)
        self.assertEqual(adaptive_tile('cpu','B',512,None),512)

    def test_precision_fallback_and_unrelated_errors(self):
        calls=[]
        def run(dtype):
            calls.append(dtype)
            if dtype is not None:raise NonFiniteOutput('overflow')
            return 'result',{}
        with patch('torch.cuda.empty_cache'):
            result,info=run_with_fallback(run,'cuda',torch.float16)
        self.assertEqual(calls,[torch.float16,None])
        self.assertEqual(result,'result')
        self.assertEqual(info['precision'],'float32')
        self.assertEqual(info['precision_fallback'],'overflow')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            run_with_fallback(lambda _: (_ for _ in ()).throw(RuntimeError('cancelled')),'cuda',torch.float16)

    def test_nonfinite_tiles_are_rejected_before_quantization(self):
        class Bad(torch.nn.Module):
            def forward(self,x):
                return x.repeat_interleave(4,2).repeat_interleave(4,3)*float('nan')
        class BadSwin(Bad):
            def forward(self,x):return super().forward(x),x
        image=np.zeros((32,32,3),dtype=np.uint8)
        for run in (lambda:tiled_x4(image,Bad(),'cpu',64),
                    lambda:hat_tiles(image,Bad(),'cpu',64),
                    lambda:tiled_forward(image,BadSwin(),'cpu',64,16)):
            with self.assertRaises(NonFiniteOutput):run()

    def test_oom_retry_does_not_shrink_requested_overlap(self):
        calls=[]
        def run(rgb,model,device,tile,overlap,progress):
            calls.append((tile,overlap))
            raise torch.cuda.OutOfMemoryError('test')
        with patch('pipeline.swin2sr.tiled_forward',side_effect=run):
            with self.assertRaisesRegex(RuntimeError,'exhausted'):
                infer_retry(None,None,'cpu',tile=128,overlap=64)
        self.assertEqual(calls,[(128,64),(96,64)])

    def test_one_engine_reused_and_released_on_switch_or_failure(self):
        class Engine:
            def __init__(self):self.closed=False
            def infer(self,image,*args,**kwargs):return image,{}
            def close(self):self.closed=True
        with tempfile.TemporaryDirectory() as folder:
            studio=Studio(folder)
            engines=[]
            def factory(*args):
                engine=Engine();engines.append(engine);return engine
            c=config_valid({'weights':{'B':100},'use_mask':False,'device':'cpu'})
            image=Image.new('RGB',(8,8))
            with patch.object(studio,'_make_engine',side_effect=factory):
                _,first=studio._infer('B',image,c,None)
                _,second=studio._infer('B',image,c,None)
                self.assertFalse(first['engine_reused'])
                self.assertTrue(second['engine_reused'])
                self.assertEqual(len(engines),1)
                studio._infer('B',image,{**c,'denoise':.8},None)
                self.assertTrue(engines[0].closed)
                studio._infer('S',image,c,None)
                self.assertTrue(engines[1].closed)
                with patch.object(engines[-1],'infer',side_effect=RuntimeError('cancelled')):
                    with self.assertRaises(RuntimeError):studio._infer('S',image,c,None)
                self.assertTrue(engines[-1].closed)
                self.assertIsNone(studio.engine)

    def test_cache_key_separates_optimized_from_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            studio=Studio(folder)
            c=config_valid({'weights':{'B':100},'use_mask':False})
            self.assertEqual(studio._settings('B',c)['version'],2)
            self.assertEqual(studio._settings('B',{**c,'gpu_optimization':False})['version'],1)

    def test_batch_reuses_engine_and_releases_after_queue(self):
        class Engine:
            closed=False
            def infer(self,image,*args,**kwargs):return image.resize((image.width*4,image.height*4)),{}
            def close(self):self.closed=True
        with tempfile.TemporaryDirectory() as folder:
            studio=Studio(folder)
            raw=io.BytesIO();Image.new('RGB',(8,8)).save(raw,'PNG')
            uploads=[studio.upload(raw.getvalue(),f'{i}.png') for i in range(2)]
            c=config_valid({'weights':{'B':100},'use_mask':False,'device':'cpu','output_scale':4})
            engine=Engine()
            with patch.object(studio,'_make_engine',return_value=engine) as factory:
                jid=studio.start_batch({'items':[{'upload':u['id'],'configs':[c]} for u in uploads]})
                deadline=time.monotonic()+5
                while studio.active and time.monotonic()<deadline:time.sleep(.01)
                self.assertIsNone(studio.active)
                status=studio.status(jid)
                self.assertTrue(all(item['status']=='done' for item in status['items']),status)
                self.assertEqual(factory.call_count,1)
                self.assertTrue(engine.closed)
                self.assertIsNone(studio.engine)
                last=status['items'][-1]
                manifest=json.loads((studio.root/last['upload']/last['id']/'processing.json').read_text())
                info=next(iter(manifest['models'].values()))
                self.assertTrue(info['engine_reused'])
                self.assertGreaterEqual(manifest['timings']['result_png_save_seconds'],0)
