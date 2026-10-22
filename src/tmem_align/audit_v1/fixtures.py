"""Small deterministic examples; never presented as experimental neurons."""
import numpy as np
from scipy.ndimage import shift


def neuron_fixture():
    y, x = np.mgrid[:96, :96]
    soma = np.exp(-((y - 48)**2 + (x - 48)**2) / (2 * 11**2))
    identity = 1500 * soma
    for cy, cx in ((24, 28), (69, 72), (30, 70)):
        identity += 600 * np.exp(-((y - cy)**2 + (x - cx)**2) / 25)
    mcherry = 40 + 65 * soma
    for cy, cx in ((44, 41), (51, 56), (39, 55)):
        mcherry += 900 * np.exp(-((y - cy)**2 + (x - cx)**2) / 8)
    cyx = np.stack([np.full_like(soma, 20), mcherry, identity]).astype(np.float32)
    roi = (y - 48)**2 + (x - 48)**2 <= 19**2
    moving = shift(cyx, (0, 4, -6), order=1, mode="constant")
    return cyx, moving, roi


def illumination_fixture():
    field = np.broadcast_to(np.linspace(0.5, 1.5, 32), (32, 32)).copy()
    raw = np.rint(1000 * field + 100).astype(np.uint16)
    return raw, field, 100.0
