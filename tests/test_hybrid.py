import unittest
from unittest.mock import patch

import numpy as np
import torch
from PIL import Image

from pipeline.fusion import fuse, make_alpha
from pipeline.realesrgan import tiled_x4, tiled_retry


class Repeat4(torch.nn.Module):
    def forward(self, x):
        return x.repeat_interleave(4, 2).repeat_interleave(4, 3)


class HybridTests(unittest.TestCase):
    def test_odd_dimensions_rgb_and_edge_tile_coverage(self):
        rgb = np.random.default_rng(11).integers(0, 256, (47, 63, 3), dtype=np.uint8)
        actual, _ = tiled_x4(rgb, Repeat4(), "cpu", tile=16)
        np.testing.assert_array_equal(actual, np.repeat(np.repeat(rgb, 4, 0), 4, 1))

    def test_nonfinite_prediction_rejected(self):
        class Bad(Repeat4):
            def forward(self, x):
                return super().forward(x)*float("nan")
        with self.assertRaisesRegex(RuntimeError, "NaN/Inf"):
            tiled_x4(np.zeros((3, 5, 3), dtype=np.uint8), Bad(), "cpu", tile=16)

    def test_oom_restarts_with_smaller_tiles(self):
        sizes = []
        def fake(rgb, model, device, tile, progress=None):
            sizes.append(tile)
            if tile > 128:
                raise torch.cuda.OutOfMemoryError("simulated")
            return np.zeros((4,4,3), dtype=np.uint8), {"tile_used": tile}
        with patch("pipeline.realesrgan.tiled_x4", side_effect=fake):
            _, stats = tiled_retry(None, None, "cpu", tile=256)
        self.assertEqual(sizes, [256,192,128])
        self.assertEqual([a["status"] for a in stats["attempts"]], ["cuda_oom", "cuda_oom", "success"])

    def test_protected_core_is_exact_despite_feather_and_overlapping_candidate(self):
        config = {"base_candidate_weight": 0.8,
                  "candidate_regions": [{"box": [0,0,20,20], "weight": 1, "feather": 2}],
                  "protected_regions": [{"box": [7,7,12,12], "feather": 3}]}
        alpha, core = make_alpha((40,40), config)
        self.assertTrue(np.all(alpha[core] == 0))
        self.assertTrue(np.any((alpha > 0) & (alpha < 1)))
        a = Image.fromarray(np.random.default_rng(9).integers(0,256,(40,40,3),dtype=np.uint8))
        b = Image.new("RGB", a.size, (255,0,19))
        actual = np.asarray(fuse(a,b,alpha))
        np.testing.assert_array_equal(actual[core], np.asarray(a)[core])

    def test_fusion_endpoints_and_size_guard(self):
        a, b = Image.new("RGB", (11,7), (1,120,244)), Image.new("RGB", (11,7), (255,0,18))
        np.testing.assert_array_equal(np.asarray(fuse(a,b,np.zeros((7,11),np.float32))), np.asarray(a))
        np.testing.assert_array_equal(np.asarray(fuse(a,b,np.ones((7,11),np.float32))), np.asarray(b))
        with self.assertRaises(ValueError):
            fuse(a, b.resize((12,7)), np.zeros((7,11),np.float32))


if __name__ == "__main__":
    unittest.main()
