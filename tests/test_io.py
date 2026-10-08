import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageCms

from pipeline.io import PhotoError, read_photo, sha256
from pipeline.run import run_control


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_control_roundtrip_and_no_overwrite(self):
        source = self.root / "foto uji.png"
        image = Image.new("RGB", (17, 11))
        image.putdata([(x % 256, (x * 11) % 256, (x * 23) % 256) for x in range(187)])
        image.save(source)
        original_hash = sha256(source)
        first = run_control(source, self.root)
        second = run_control(source, self.root)
        self.assertNotEqual(first, second)
        self.assertEqual(sha256(source), original_hash)
        with Image.open(first / "result_control.png") as saved:
            self.assertEqual(saved.size, (17, 11))
            self.assertEqual(saved.tobytes(), image.tobytes())
            self.assertTrue(saved.info.get("icc_profile"))
        report = json.loads((first / "processing.json").read_text(encoding="utf-8"))
        self.assertFalse(report["restoration_applied"])
        self.assertIsNone(report["peak_cuda_allocated_bytes"])

    def test_exif_rotation_is_applied_once(self):
        source = self.root / "oriented.png"
        image = Image.new("RGB", (13, 9), "red")
        image.putpixel((0, 0), (0, 255, 0))
        exif = Image.Exif()
        exif[274] = 6
        image.save(source, exif=exif)
        normalized, _ = read_photo(source)
        self.assertEqual(normalized.size, (9, 13))
        self.assertEqual(normalized.getpixel((8, 0)), (0, 255, 0))
        run = run_control(source, self.root / "runs")
        reread, _ = read_photo(run / "result_control.png")
        self.assertEqual(reread.tobytes(), normalized.tobytes())
        self.assertEqual(reread.size, normalized.size)

    def test_srgb_profile_and_jpeg_decode(self):
        source = self.root / "profile.jpg"
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        Image.new("RGB", (16, 12), (120, 80, 40)).save(source, icc_profile=profile)
        result, report = read_photo(source)
        with Image.open(source) as decoded:
            self.assertEqual(result.tobytes(), decoded.convert("RGB").tobytes())
        self.assertIn("ICC to sRGB", report["color_handling"])

    def test_invalid_icc_fails_explicitly(self):
        source = self.root / "bad.png"
        Image.new("RGB", (10, 10)).save(source, icc_profile=b"invalid profile")
        with self.assertRaisesRegex(PhotoError, "ICC"):
            read_photo(source)

    def test_webp_lossless_and_disguised_jpeg(self):
        source = self.root / "webp.webp"
        image = Image.new("RGB", (17, 11), (91, 37, 205))
        image.save(source, format="WEBP", lossless=True)
        decoded, info = read_photo(source)
        self.assertEqual(decoded.tobytes(), image.tobytes())
        self.assertEqual(info["source_format"], "WEBP")
        disguised = self.root / "photo.heic"
        image.save(disguised, format="JPEG")
        _, info = read_photo(disguised)
        self.assertEqual(info["source_format"], "JPEG")
        self.assertTrue(any("Ekstensi" in warning for warning in info["warnings"]))

    def test_animated_webp_rejected(self):
        source = self.root / "animation.webp"
        Image.new("RGB", (17, 11), "red").save(source, format="WEBP", save_all=True,
            append_images=[Image.new("RGB", (17, 11), "blue")], duration=100, loop=0)
        with self.assertRaisesRegex(PhotoError, "multiframe"):
            read_photo(source)

    def test_alpha_policy(self):
        source = self.root / "alpha.png"
        Image.new("RGBA", (12, 9), (1, 2, 3, 255)).save(source)
        result, report = read_photo(source)
        self.assertEqual(result.getpixel((0, 0)), (1, 2, 3))
        self.assertTrue(report["opaque_alpha_removed"])
        Image.new("RGBA", (12, 9), (1, 2, 3, 128)).save(source)
        with self.assertRaisesRegex(PhotoError, "Transparansi"):
            read_photo(source)

    def test_16bit_rejected(self):
        source = self.root / "depth.png"
        Image.new("I;16", (12, 9), 40000).save(source)
        with self.assertRaisesRegex(PhotoError, "16-bit"):
            read_photo(source)

    def test_cmyk_without_profile_rejected(self):
        source = self.root / "cmyk.jpg"
        Image.new("CMYK", (12, 9)).save(source)
        with self.assertRaisesRegex(PhotoError, "CMYK"):
            read_photo(source)

    def test_corrupt_file_creates_no_result(self):
        source = self.root / "broken.png"
        source.write_bytes(b"not an image")
        destination = self.root / "runs"
        with self.assertRaises(Exception):
            run_control(source, destination)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
