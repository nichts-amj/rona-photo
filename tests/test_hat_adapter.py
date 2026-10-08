import unittest
import numpy as np
import torch
from pipeline.extra_models import hat_tiles

class Upsample(torch.nn.Module):
    def forward(self,x):
        return x.repeat_interleave(4,2).repeat_interleave(4,3)

class HatAdapterTests(unittest.TestCase):
    def test_context_stitch_covers_odd_image_without_channel_swap(self):
        image=np.random.default_rng(13).integers(0,256,(81,145,3),dtype=np.uint8)
        actual,info=hat_tiles(image,Upsample(),'cpu',64)
        np.testing.assert_array_equal(actual,image.repeat(4,0).repeat(4,1))
        self.assertEqual(info['tiles'],6)

    def test_cancellation_propagates(self):
        def cancel(*args):raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            hat_tiles(np.zeros((80,80,3),dtype=np.uint8),Upsample(),'cpu',64,cancel)
