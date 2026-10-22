"""Display-only LUT functions. Output must never enter measurements or tracking."""
from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

COLORS = {"gray": (1, 1, 1), "488": (0, 1, 0), "561": (1, 0, 1)}


@dataclass(frozen=True)
class LUT:
    low: float
    high: float
    color: str = "gray"
    scope: str = "fixed-longitudinal-per-neuron"
    source: str = "explicit"

    def __post_init__(self):
        if not (np.isfinite(self.low) and np.isfinite(self.high) and self.high > self.low):
            raise ValueError("LUT requires finite high > low")
        if self.color not in COLORS:
            raise ValueError(f"Unknown color: {self.color}")

    def metadata(self):
        return asdict(self)


def longitudinal_lut(stack, *, color="gray", source="all supplied visits, p1/p99.6"):
    a = np.asarray(stack, dtype=float)
    v = a[np.isfinite(a)]
    if not v.size:
        raise ValueError("Cannot choose LUT from empty/nonfinite data")
    low, high = np.percentile(v, [1, 99.6])
    if high <= low:
        high = low + max(1.0, abs(low) * 1e-6)
    return LUT(float(low), float(high), color, source=source)


def normalize_for_display(image, lut):
    a = np.array(image, dtype=np.float64, copy=True)
    a[~np.isfinite(a)] = lut.low
    # Clip the local display copy before subtraction, so finite out-of-range
    # values cannot overflow against a very large negative lower limit.
    np.clip(a, lut.low, lut.high, out=a)
    low, high = float(lut.low), float(lut.high)
    span = high - low
    if np.isfinite(span):
        # Preserve the existing arithmetic for ordinary microscopy limits.
        return np.clip((a - low) / span, 0, 1)
    # Both limits are finite, but their difference can overflow when they
    # straddle zero. Half scaling keeps the same ratio representable.
    return np.clip((a * 0.5 - low * 0.5) / (high * 0.5 - low * 0.5), 0, 1)


def apply_lut_for_display(image, lut):
    a = np.asarray(image)
    if a.ndim != 2:
        raise ValueError("Display expects a single YX channel, not a channel projection")
    gray = normalize_for_display(a, lut)
    rgb = np.rint(gray[..., None] * np.asarray(COLORS[lut.color]) * 255).astype(np.uint8)
    rgb[~np.isfinite(a)] = (255, 96, 0)
    return rgb


def make_overlay(reference, moving, lut):
    if np.shape(reference) != np.shape(moving):
        raise ValueError("Overlay shapes differ")
    r = normalize_for_display(reference, lut)
    m = normalize_for_display(moving, lut)
    return np.rint(np.stack([m, r, m], axis=-1) * 255).astype(np.uint8)


def bbox_display(image, bounds, lut):
    """Spatial geometry supplied by 488 anchors; LUT only clips display intensities."""
    return apply_lut_for_display(bounds.crop(image), lut)


def make_qc_panel(images, labels, *, cell=256):
    """RGB arrays -> compact labeled horizontal panel. At most four panels."""
    if not 1 <= len(images) <= 4 or len(images) != len(labels):
        raise ValueError("Provide 1-4 images and matching labels")
    canvas = Image.new("RGB", (cell * len(images), cell + 48), "#111111")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for i, (array, label) in enumerate(zip(images, labels)):
        im = Image.fromarray(np.asarray(array, dtype=np.uint8))
        scale = min(cell / im.width, cell / im.height)
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                       Image.Resampling.NEAREST)
        canvas.paste(im, (cell * i, 48))
        draw.text((cell * i + 6, 6), str(label), fill="white", font=font)
    return canvas
