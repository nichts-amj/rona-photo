"""Explicit control path. No restoration model is loaded at this stage."""
from PIL import Image


def control(image: Image.Image) -> Image.Image:
    return image.copy()
