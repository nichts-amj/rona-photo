"""Decode, orient and color-manage a photograph without resizing it."""
from __future__ import annotations

import hashlib
import io
import warnings
from pathlib import Path

from PIL import Image, ImageCms, ImageOps

MAX_PIXELS = 50_000_000


class PhotoError(ValueError):
    """An input cannot be processed without an unsupported conversion."""


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def srgb_profile() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def read_photo(path: Path) -> tuple[Image.Image, dict]:
    path = path.resolve(strict=True)
    # Pillow decodes some RGB 16-bit PNGs as RGB8. Reject before decoding.
    with path.open("rb") as handle:
        header = handle.read(26)
    if header[:8] == b"\x89PNG\r\n\x1a\n" and len(header) >= 25 and header[24] == 16:
        raise PhotoError("PNG 16-bit belum didukung; tidak dikonversi diam-diam ke 8-bit.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as raw:
            if raw.format not in {"JPEG", "PNG", "WEBP"}:
                raise PhotoError("Format yang didukung: JPEG, PNG, WebP statis 8-bit.")
            if getattr(raw, "n_frames", 1) != 1:
                raise PhotoError("Gambar animasi/multiframe belum didukung.")
            if raw.width * raw.height > MAX_PIXELS:
                raise PhotoError(f"Input melebihi batas {MAX_PIXELS:,} piksel; ukuran tidak diperkecil otomatis.")
            if raw.mode not in {"RGB", "RGBA", "L", "LA", "P", "CMYK"}:
                raise PhotoError(f"Mode {raw.mode} belum didukung.")
            orientation = raw.getexif().get(274)
            if orientation is not None and orientation not in range(1, 9):
                raise PhotoError(f"Orientasi EXIF tidak valid: {orientation}.")
            metadata = {
                "source_path": str(path), "source_format": raw.format,
                "source_mode": raw.mode, "source_size": list(raw.size),
                "exif_orientation": orientation, "source_sha256": sha256(path),
                "warnings": [],
            }
            expected = {"JPEG": {".jpg", ".jpeg", ".jpe"}, "PNG": {".png"}, "WEBP": {".webp"}}
            if path.suffix.lower() not in expected[raw.format]:
                metadata["warnings"].append(f"Ekstensi {path.suffix} berbeda dari isi {raw.format}; dibaca berdasarkan isi file.")
            embedded_icc = raw.info.get("icc_profile")
            raw.load()
            oriented = ImageOps.exif_transpose(raw)
            if "A" in oriented.getbands() or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                if rgba.getchannel("A").getextrema() != (255, 255):
                    raise PhotoError("Transparansi nyata belum didukung; pilih foto opak tanpa membuang alpha diam-diam.")
                metadata["opaque_alpha_removed"] = True
            else:
                metadata["opaque_alpha_removed"] = False
            if embedded_icc:
                try:
                    source_profile = ImageCms.ImageCmsProfile(io.BytesIO(embedded_icc))
                    # Keep grayscale/CMYK for the matching source profile.
                    cms_input = oriented if oriented.mode in {"RGB", "L", "CMYK"} else oriented.convert("RGB")
                    converted = ImageCms.profileToProfile(
                        cms_input, source_profile, ImageCms.createProfile("sRGB"),
                        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, outputMode="RGB",
                    )
                except (ImageCms.PyCMSError, OSError, ValueError) as error:
                    raise PhotoError(f"Konversi profil ICC gagal: {error}") from error
                metadata["color_handling"] = "ICC to sRGB; relative colorimetric"
                metadata["source_icc_sha256"] = hashlib.sha256(embedded_icc).hexdigest()
            else:
                if oriented.mode == "CMYK":
                    raise PhotoError("CMYK tanpa profil ICC tidak dapat dikonversi secara andal.")
                converted = oriented.convert("RGB")
                metadata["color_handling"] = "assumed sRGB (no embedded ICC)"
                metadata["warnings"].append("Profil ICC tidak tersedia; sRGB diasumsikan.")
            # Remove EXIF orientation and inherited metadata. Export has explicit sRGB.
            clean = Image.frombytes("RGB", converted.size, converted.tobytes())
    metadata["normalized_size"] = list(clean.size)
    metadata["working_color_space"] = "sRGB"
    metadata["working_bit_depth"] = 8
    return clean, metadata


def save_png(image: Image.Image, path: Path) -> None:
    image.save(path, format="PNG", icc_profile=srgb_profile())
