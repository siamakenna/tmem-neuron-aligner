"""Small, explicit channel and coordinate contracts. No display dependencies."""
from dataclasses import dataclass

import numpy as np

CHANNELS = ("405", "561", "488")


def require_cyx(image, channels=CHANNELS):
    """Require the project channel order; never infer channels from intensity."""
    a = np.asarray(image)
    if tuple(channels) != CHANNELS:
        raise ValueError("Explicitly reorder to C0=405, C1=561, C2=488 first")
    if a.ndim != 3 or a.shape[0] != 3 or min(a.shape[1:]) < 1:
        raise ValueError(f"Expected nonempty CYX with three channels, got {a.shape}")
    if a.dtype.kind not in "buif" or not np.isfinite(a).all():
        raise ValueError("Quantitative image must contain finite real values")
    return a


def identity_channel(image, channels=CHANNELS):
    return require_cyx(image, channels)[2]


@dataclass(frozen=True)
class Bounds:
    """Half-open array coordinates, ordered y0,y1,x0,x1."""
    y0: int
    y1: int
    x0: int
    x1: int

    def validate(self, shape):
        values = (self.y0, self.y1, self.x0, self.x1)
        if any(not isinstance(v, (int, np.integer)) for v in values):
            raise ValueError("Bounds must be integer pixels")
        h, w = shape[-2:]
        if not (0 <= self.y0 < self.y1 <= h and 0 <= self.x0 < self.x1 <= w):
            raise ValueError(f"Bounds {self} outside {h}x{w}")
        return self

    def crop(self, image):
        a = np.asarray(image)
        self.validate(a.shape)
        return a[..., self.y0:self.y1, self.x0:self.x1].copy()


def strict_overlap(shape, shifts):
    """Intersection of translated rectangular supports; fail if empty.

    This is geometric support, not a guarantee about spline interpolation edges.
    Stitching gaps must be rejected or propagated separately.
    """
    s = np.asarray(shifts, dtype=float)
    if s.ndim != 2 or s.shape[1] != 2 or len(s) == 0 or not np.isfinite(s).all():
        raise ValueError("Expected finite (dy,dx) shifts")
    h, w = shape[-2:]
    top, left = np.ceil(np.maximum(s.max(axis=0), 0)).astype(int)
    bottom, right = np.floor(np.minimum(s.min(axis=0), 0) + [h, w]).astype(int)
    return Bounds(int(top), int(bottom), int(left), int(right)).validate((h, w))
