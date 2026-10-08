import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from pipeline.hybrid_run import resolve_regions, run_hybrid
from pipeline.io import sha256


class Engine:
    calls = []
    def __init__(self, *args, **kwargs):
        self.provenance = {'test':True}
    def metadata(self):
        return self.provenance
    def infer(self, image, *args):
        self.calls.append('infer')
        return image.resize((image.width*2, image.height*2)), {'test':True}
    def close(self):
        self.calls.append('close')


class HybridRunTests(unittest.TestCase):
    def test_source_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'regions.json'
            p.write_text(json.dumps({'source_sha256':'abc','source_size':[4,5],
                                    'config':{'base_candidate_weight':0.5}}))
            self.assertEqual(resolve_regions('abc',(4,5),p)['base_candidate_weight'],0.5)
            with self.assertRaises(ValueError):
                resolve_regions('wrong',(4,5),p)
            with self.assertRaises(ValueError):
                resolve_regions('abc',(5,4),p)

    def test_default_and_optional_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root/'input.png'
            Image.new('RGB',(8,8),(30,60,90)).save(photo)
            regions = root/'regions.json'
            regions.write_text(json.dumps({'source_sha256':sha256(photo),'source_size':[8,8],
                'config':{'base_candidate_weight':0.5,'protected_regions':[{'box':[0,0,3,3],'feather':0}]}}))
            for optional in (False,True):
                Engine.calls = []
                with patch('pipeline.upscale.SwinIRX2',Engine), patch('pipeline.realesrgan.CompactRealESRGAN',Engine), patch('pipeline.swin2sr.Swin2SRCompressed',Engine):
                    folder = run_hybrid(photo,root,regions=regions,compare_swin2sr=optional)
                self.assertEqual(Engine.calls,['infer','close']*(3 if optional else 2))
                self.assertTrue((folder/'result_C_x2.png').exists())
                self.assertEqual((folder/'S_swin2sr_comparison_x2.png').exists(),optional)
                self.assertEqual(json.loads((folder/'processing.json').read_text())['default_result'],'result_C_x2.png')
