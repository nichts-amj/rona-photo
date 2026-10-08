import io
import base64
import unittest
import numpy as np
import torch
from PIL import Image
from retouch_backend.person import person_mask
from retouch_backend.models import RetouchError

class FakeManager:
    device='cpu'
    def __init__(self,person=True,invalid=False):self.person=person;self.invalid=invalid
    def run(self,role,action):
        assert role=='person'
        def model(tensor):
            _,_,h,w=tensor.shape;out=torch.zeros((1,21,h,w));out[:,0]=4
            if self.person:out[:,15,:,w//3:2*w//3]=12
            if self.invalid:out[:]=float('nan')
            return {'out':out}
        return action(model)

class PersonAdjustTests(unittest.TestCase):
    def test_mask_feathers_edges_keeps_transparency_and_source_unchanged(self):
        source=np.full((32,48,4),128,np.uint8);source[:,:,3]=255;source[:3,:,3]=0;before=source.copy()
        result=person_mask(source,FakeManager(),lambda *_:None)
        mask=np.array(Image.open(io.BytesIO(base64.b64decode(result['mask']))))
        self.assertTrue(result['found']);self.assertEqual((result['width'],result['height']),(48,32))
        self.assertEqual(mask[16,24],255);self.assertEqual(mask[16,1],0)
        self.assertTrue(np.any((mask>0)&(mask<255)));self.assertTrue(np.all(mask[:3]==0))
        np.testing.assert_array_equal(source,before)
    def test_no_person_is_explicit_and_invalid_predictions_fail(self):
        source=np.full((32,48,4),255,np.uint8)
        self.assertFalse(person_mask(source,FakeManager(False),lambda *_:None)['found'])
        with self.assertRaises(RetouchError):person_mask(source,FakeManager(invalid=True),lambda *_:None)
    def test_inference_size_is_bounded_without_changing_working_dimensions(self):
        source=np.full((1000,2000,4),255,np.uint8)
        result=person_mask(source,FakeManager(),lambda *_:None)
        self.assertEqual((result['width'],result['height']),(2000,1000));self.assertEqual((result['maskWidth'],result['maskHeight']),(768,384))

if __name__=='__main__':unittest.main()
