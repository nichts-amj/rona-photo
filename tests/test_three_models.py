import unittest
from unittest.mock import patch
import numpy as np
import torch
from PIL import Image
from pipeline.swin2sr import tiled_forward, primary, infer_retry
from three_model_experiment import weighted_images


class TupleRepeat(torch.nn.Module):
    def forward(self,x):
        return x.repeat_interleave(4,2).repeat_interleave(4,3), torch.zeros_like(x)


class ThreeModelTests(unittest.TestCase):
    def test_tuple_primary_rgb_odd_dimensions_coverage(self):
        rgb=np.random.default_rng(33).integers(0,256,(79,91,3),dtype=np.uint8)
        out,_=tiled_forward(rgb,TupleRepeat(),"cpu",64,16)
        expected=np.repeat(np.repeat(rgb.astype(np.float32)/255,4,0),4,1)
        np.testing.assert_allclose(out,expected,atol=2e-7,rtol=0)

    def test_primary_requires_aux_tuple(self):
        with self.assertRaises(RuntimeError):
            primary(torch.zeros(1,3,8,8))

    def test_nonfinite_primary_rejected(self):
        class Bad(TupleRepeat):
            def forward(self,x):
                a,b=super().forward(x)
                return a*float("nan"),b
        with self.assertRaisesRegex(RuntimeError,"NaN/Inf"):
            tiled_forward(np.zeros((9,17,3),np.uint8),Bad(),"cpu",64,16)

    def test_oom_restarts_and_other_errors_propagate(self):
        calls=[]
        def fake(rgb,model,device,tile,overlap,progress):
            calls.append(tile)
            if tile>64:
                raise torch.cuda.OutOfMemoryError("simulated")
            return None,{}
        with patch("pipeline.swin2sr.tiled_forward",side_effect=fake):
            _,data=infer_retry(None,None,"cpu")
        self.assertEqual(calls,[128,96,64])
        with patch("pipeline.swin2sr.tiled_forward",side_effect=ValueError("bad input")):
            with self.assertRaises(ValueError):
                infer_retry(None,None,"cpu")

    def test_fusion_values_and_invalid_weights(self):
        ims=[Image.new("RGB",(11,9),c) for c in [(0,30,255),(120,60,0),(240,90,120)]]
        out=weighted_images(ims,[1/3]*3)
        np.testing.assert_array_equal(np.asarray(out)[0,0],np.array([120,60,125]))
        np.testing.assert_array_equal(np.asarray(weighted_images(ims,[1,0,0])),np.asarray(ims[0]))
        with self.assertRaises(ValueError):
            weighted_images(ims,[0.5]*3)


if __name__=="__main__":
    unittest.main()
