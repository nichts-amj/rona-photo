"""Manual, auditable region fusion; protected cores are exactly baseline pixels."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def region_mask(size, region, scale=2):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if "polygon" in region:
        draw.polygon([(round(x*scale), round(y*scale)) for x, y in region["polygon"]], fill=255)
    elif "box" in region:
        draw.rectangle(tuple(round(v*scale) for v in region["box"]), fill=255)
    else:
        raise ValueError("Region must contain polygon or box")
    return mask


def make_alpha(size, config, scale=2):
    base = float(config["base_candidate_weight"])
    if not 0 <= base <= 1:
        raise ValueError("Weight out of range")
    alpha = np.full((size[1], size[0]), base, dtype=np.float32)
    protected = np.zeros(alpha.shape, dtype=bool)
    for region in config.get("candidate_regions", []):
        weight = float(region["weight"])
        if not 0 <= weight <= 1:
            raise ValueError("Weight out of range")
        mask = region_mask(size, region, scale).filter(ImageFilter.GaussianBlur(region.get("feather", 8)*scale))
        mix = np.asarray(mask, dtype=np.float32)/255
        alpha = alpha*(1-mix)+weight*mix
    for region in config.get("protected_regions", []):
        core = region_mask(size, region, scale)
        feather = region.get("feather", 8)*scale
        # Expand outward before blur, then clamp the entire selected core to 1.
        # Plain Gaussian blur would leak new pixels into protected faces/QR.
        expanded = core.filter(ImageFilter.MaxFilter(2*round(feather)+1)) if feather else core
        soft = np.asarray(expanded.filter(ImageFilter.GaussianBlur(feather)), dtype=np.float32)/255
        inside = np.asarray(core) == 255
        soft[inside] = 1
        alpha *= 1-soft
        protected |= inside
    if not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1:
        raise RuntimeError("Invalid fusion alpha")
    alpha[protected] = 0
    return alpha, protected


def fuse(a, b, alpha):
    if a.size != b.size or a.mode != "RGB" or b.mode != "RGB" or alpha.shape != (a.height, a.width):
        raise ValueError("Fusion requires matching RGB images and mask")
    if not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1:
        raise ValueError("Alpha must be finite and in [0,1]")
    # Row chunks bound memory use. Blend in encoded sRGB, explicitly recorded.
    result = np.empty((a.height, a.width, 3), dtype=np.uint8)
    ar, br = np.asarray(a), np.asarray(b)
    for y in range(0, a.height, 256):
        weight = alpha[y:y+256, :, None]
        result[y:y+256] = np.rint(ar[y:y+256].astype(np.float32)*(1-weight)+br[y:y+256].astype(np.float32)*weight).astype(np.uint8)
    return Image.fromarray(result)
