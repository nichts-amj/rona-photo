"""CPU-only, gated two-band luminance transfer from cached A/B results.

This is an experimental heuristic, not a learned artifact detector. It retains
the existing manual protection mask and encoded-sRGB chroma channel differences.
"""
import numpy as np
from PIL import Image

DEFAULTS = {"sigma_fine": 1.0, "sigma_coarse": 4.0,
            "fine_gain": 0.65, "mid_gain": 1.0,
            "edge_floor": 0.012, "max_delta_levels": 24}


def gaussian(plane, sigma):
    """Float32 separable Gaussian, symmetric edges, radius ceil(3 sigma)."""
    if sigma <= 0 or plane.ndim != 2:
        raise ValueError("Expected a plane and positive sigma")
    radius = int(np.ceil(3*sigma))
    coords = np.arange(-radius, radius+1, dtype=np.float32)
    kernel = np.exp(-0.5*(coords/sigma)**2)
    kernel /= kernel.sum()
    result = np.asarray(plane, dtype=np.float32)
    h, w = result.shape
    for axis in (0, 1):
        pads = [(0,0), (0,0)]
        pads[axis] = (radius, radius)
        padded = np.pad(result, pads, mode="symmetric")
        result = np.zeros((h,w), dtype=np.float32)
        for index, weight in enumerate(kernel):
            view = padded[index:index+h, :] if axis == 0 else padded[:, index:index+w]
            result += weight*view
    return result


def gradient(plane):
    padded = np.pad(plane, 1, mode="edge")
    return (padded[1:-1,2:]-padded[1:-1,:-2])*0.5, (padded[2:,1:-1]-padded[:-2,1:-1])*0.5


def luminance(rgb):
    return (rgb[:,:,0].astype(np.float32)*0.299 + rgb[:,:,1].astype(np.float32)*0.587 + rgb[:,:,2].astype(np.float32)*0.114)/255


def detail_fuse(a, b, alpha, settings=None):
    p = {**DEFAULTS, **(settings or {})}
    if a.mode != "RGB" or b.mode != "RGB" or a.size != b.size:
        raise ValueError("A and B must be matching RGB images")
    if alpha.shape != (a.height,a.width) or not np.isfinite(alpha).all() or alpha.min()<0 or alpha.max()>1:
        raise ValueError("Invalid alpha")
    if p["sigma_fine"] <= 0 or p["sigma_coarse"] <= p["sigma_fine"] or p["edge_floor"] <= 0 or not 0 < p["max_delta_levels"] <= 255:
        raise ValueError("Invalid detail parameters")
    if not 0 <= p["fine_gain"] <= 1 or not 0 <= p["mid_gain"] <= 1:
        raise ValueError("Detail gains must be in [0,1]")
    ar, br = np.asarray(a), np.asarray(b)
    ya, yb = luminance(ar), luminance(br)
    smooth_a = gaussian(ya,p["sigma_fine"])
    smooth_b = gaussian(yb,p["sigma_fine"])
    delta = yb-ya
    fine_smooth = smooth_b-smooth_a
    coarse_smooth = gaussian(delta,p["sigma_coarse"])
    # Transfer two bands of B-A, omitting the coarse residual. A remains the
    # base, with no separate unsharp mask or arbitrary image-wide contrast.
    proposed = p["fine_gain"]*(delta-fine_smooth)+p["mid_gain"]*(fine_smooth-coarse_smooth)
    ax, ay = gradient(smooth_a)
    bx, by = gradient(smooth_b)
    ma = np.hypot(ax,ay)
    mb = np.hypot(bx,by)
    alignment = np.clip((ax*bx+ay*by)/(ma*mb+1e-10),0,1)
    gate = (ma/(ma+p["edge_floor"]))*alignment
    proposed *= alpha*gate
    # Integer equal-channel offsets preserve R-G and B-G exactly. Limit to
    # gamut before addition rather than clipping channels independently.
    shift = np.rint(np.clip(proposed*255,-p["max_delta_levels"],p["max_delta_levels"])).astype(np.int16)
    shift = np.maximum(shift,-ar.min(axis=2).astype(np.int16))
    shift = np.minimum(shift,255-ar.max(axis=2).astype(np.int16))
    shift[alpha == 0] = 0
    result = (ar.astype(np.int16)+shift[:,:,None]).astype(np.uint8)
    return Image.fromarray(result), {"parameters":p, "mean_gate":float(gate.mean()),
        "fraction_changed_pixels":float(np.mean(shift != 0)), "max_abs_offset_levels":int(np.abs(shift).max()),
        "mean_abs_offset_levels":float(np.abs(shift).mean()),
        "method":"two-band encoded-sRGB luminance residual; source-edge strength and A/B gradient agreement gate",
        "mask":"reuse prior manual float32 alpha without changes",
        "limitations":"Gate is heuristic and does not establish text or texture correctness; chroma preservation refers to channel differences in encoded sRGB."}
