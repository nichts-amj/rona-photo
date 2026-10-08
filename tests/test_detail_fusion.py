import unittest
import numpy as np
from PIL import Image
from pipeline.detail_fusion import detail_fuse, gaussian


class DetailTests(unittest.TestCase):
    def test_identical_inputs_are_identity(self):
        a = Image.fromarray(np.random.default_rng(4).integers(0,256,(37,43,3),dtype=np.uint8))
        d,_ = detail_fuse(a,a,np.ones((37,43),np.float32))
        np.testing.assert_array_equal(np.asarray(d), np.asarray(a))

    def test_zero_alpha_protected_exact_and_chroma_preserved(self):
        ar = np.random.default_rng(12).integers(20,230,(31,39,3),dtype=np.uint8)
        br = np.roll(ar,1,axis=0)
        mask = np.ones((31,39),np.float32)
        mask[8:21,10:26] = 0
        d,_ = detail_fuse(Image.fromarray(ar),Image.fromarray(br),mask)
        dr = np.asarray(d)
        np.testing.assert_array_equal(dr[mask==0], ar[mask==0])
        change = dr.astype(np.int16)-ar.astype(np.int16)
        np.testing.assert_array_equal(change[:,:,0],change[:,:,1])
        np.testing.assert_array_equal(change[:,:,1],change[:,:,2])
        self.assertLessEqual(np.abs(change).max(),24)

    def test_global_tone_offset_is_not_transferred(self):
        ar = np.tile(np.arange(20,140,dtype=np.uint8),(45,1))
        ar = np.repeat(ar[:,:,None],3,axis=2)
        d,_ = detail_fuse(Image.fromarray(ar),Image.fromarray(ar+30),np.ones(ar.shape[:2],np.float32))
        np.testing.assert_array_equal(np.asarray(d), ar)

    def test_constant_and_tiny_gaussian(self):
        np.testing.assert_allclose(gaussian(np.full((1,2),0.7,np.float32),4),0.7,atol=1e-6)

    def test_invalid_mask_rejected(self):
        a=Image.new("RGB",(9,7))
        with self.assertRaises(ValueError):
            detail_fuse(a,a,np.full((7,9),float("nan")))


if __name__ == "__main__":
    unittest.main()
