import unittest
from unittest.mock import patch

import numpy as np
import torch

from pipeline.tiling import infer_with_retries, official_pad, tiled_forward, validate_tiles


class Repeat2(torch.nn.Module):
    def forward(self, x):
        return x.repeat_interleave(2, dim=2).repeat_interleave(2, dim=3)


class TilingTests(unittest.TestCase):
    def test_grid_coverage_rgb_and_odd_size(self):
        rgb = np.random.default_rng(7).integers(0, 256, (139, 173, 3), dtype=np.uint8)
        result, info = tiled_forward(rgb, Repeat2(), "cpu", 64, 32)
        expected = np.repeat(np.repeat(rgb.astype(np.float32) / 255, 2, 0), 2, 1)
        np.testing.assert_allclose(result, expected, atol=2e-7, rtol=0)
        self.assertGreater(info["tiles"], 1)
        self.assertEqual(result.shape, (278, 346, 3))

    def test_tiny_input_and_overlap(self):
        rgb = np.array([[[7, 19, 250]]], dtype=np.uint8)
        result, info = tiled_forward(rgb, Repeat2(), "cpu", 128, 32)
        self.assertEqual(result.shape, (2, 2, 3))
        self.assertEqual(info["overlap_used"], 0)
        np.testing.assert_allclose(result[0, 0], rgb[0, 0] / 255, atol=1e-7)

    def test_padding_matches_official_flip(self):
        rgb = np.random.default_rng(5).integers(0, 256, (31, 40, 3), dtype=np.uint8)
        reference = np.concatenate([rgb, rgb[::-1]], 0)[:32]
        reference = np.concatenate([reference, reference[:, ::-1]], 1)[:, :48]
        np.testing.assert_array_equal(official_pad(rgb), reference)

    def test_oom_retries_restart_smaller(self):
        calls = []
        def fake(rgb, model, device, tile, overlap, progress):
            calls.append(tile)
            if tile > 64:
                raise torch.cuda.OutOfMemoryError("simulated for engineering test")
            return np.zeros((2, 2, 3)), {"tile_used": tile}
        with patch("pipeline.tiling.tiled_forward", side_effect=fake):
            _, stats = infer_with_retries(None, None, "cpu", 128, 32)
        self.assertEqual(calls, [128, 96, 64])
        self.assertEqual([item["status"] for item in stats["attempts"]], ["cuda_oom", "cuda_oom", "success"])

    def test_non_oom_is_not_swallowed(self):
        with patch("pipeline.tiling.tiled_forward", side_effect=ValueError("shape error")):
            with self.assertRaisesRegex(ValueError, "shape error"):
                infer_with_retries(None, None, "cpu", 128, 32)

    def test_exhausted_oom_retains_attempts(self):
        with patch("pipeline.tiling.tiled_forward", side_effect=torch.cuda.OutOfMemoryError("simulated")):
            with self.assertRaisesRegex(RuntimeError, "seluruh tile") as caught:
                infer_with_retries(None, None, "cpu", 128, 32)
        self.assertEqual(len(caught.exception.attempts), 3)

    def test_nonfinite_model_output_is_rejected(self):
        class BadModel(Repeat2):
            def forward(self, x):
                return super().forward(x) * float("nan")
        with self.assertRaisesRegex(RuntimeError, "NaN/Inf"):
            tiled_forward(np.zeros((16, 16, 3), dtype=np.uint8), BadModel(), "cpu", 128, 32)

    def test_invalid_tile_settings(self):
        for tile, overlap in ((65, 32), (32, 8), (128, 128), (128, 17), (128, -8)):
            with self.assertRaises(ValueError):
                validate_tiles(tile, overlap)


if __name__ == "__main__":
    unittest.main()
