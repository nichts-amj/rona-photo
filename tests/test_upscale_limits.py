"""Upload limits without running restoration models or allocating 50 MP output."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
from local_engine import Studio
from pipeline.io import MAX_PIXELS, PhotoError, read_photo


class UpscaleLimitTests(unittest.TestCase):
    def test_25_mp_upload_preserves_input_dimensions(self):
        # Crosses both the former 12 MP upload and 24 MP decoder limits.
        stream = io.BytesIO()
        image = Image.new('RGB', (5000, 5000), (30, 60, 90))
        image.save(stream, 'PNG')
        image.close()
        with tempfile.TemporaryDirectory() as folder:
            studio = Studio(Path(folder))
            photo = studio.upload(stream.getvalue(), 'large.png')
            self.assertEqual(photo['size'], [5000, 5000])
            with Image.open(studio.uploads[photo['id']]['folder'] / 'original.png') as saved:
                self.assertEqual(saved.size, (5000, 5000))

    def test_more_than_50_mp_rejected_before_decode(self):
        self.assertEqual(MAX_PIXELS, 50_000_000)
        raw = MagicMock()
        raw.__enter__.return_value = raw
        raw.width, raw.height = 10000, 5001
        raw.format, raw.n_frames = 'PNG', 1
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'large.png'
            path.write_bytes(b'invalid; decoder is mocked')
            with patch('pipeline.io.Image.open', return_value=raw):
                with self.assertRaisesRegex(PhotoError, '50,000,000'):
                    read_photo(path)
            raw.load.assert_not_called()
            with patch('local_engine.Image.open', return_value=raw):
                with self.assertRaisesRegex(ValueError, '50 megapiksel'):
                    Studio(Path(folder) / 'studio').upload(b'input', 'large.png')


if __name__ == '__main__':
    unittest.main()
