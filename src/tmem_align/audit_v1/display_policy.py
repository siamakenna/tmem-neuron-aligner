"""Explicit, display-only limits for fixed longitudinal neuron views.

Spatial bounding boxes and phenotype ROIs are supplied by the 488 identity
workflow. A LUT can clip displayed intensities, never select measurement pixels.
"""

import numpy as np

from .display import LUT


def _require_stack(stack):
    a = np.asarray(stack)
    if a.ndim != 3 or min(a.shape, default=0) < 1 or a.dtype.kind not in 'buif':
        raise ValueError('Display policy requires a nonempty single-channel TYX stack')
    return a


def _require_roi(roi, shape):
    mask = np.asarray(roi)
    if mask.dtype != bool or mask.ndim != 2 or mask.shape != tuple(shape) or not mask.any():
        raise ValueError('ROI must be a nonempty matching boolean YX mask supplied by 488 geometry')
    return mask


def choose_lut(stack, roi=None, *, color, source='reference_bbox',
               low_percentile=1, high_percentile=99.6):
    """Return one LUT selected once across every supplied visit.

    ``reference_bbox`` matches the current renderer's float32 percentile limits
    on nonflat data. ``roi_fixed`` uses float64 values pooled across visits in
    the supplied, immutable 488-derived ROI. Nonfinite display values are omitted
    from range estimation and remain visibly marked by apply_lut_for_display.
    Flat images receive a finite nonzero display width; this is not normalization
    or a change to the quantitative data.
    """
    a = _require_stack(stack)
    if not np.isfinite([low_percentile, high_percentile]).all() or not (
            0 <= low_percentile < high_percentile <= 100):
        raise ValueError('Require finite 0 <= low_percentile < high_percentile <=100')
    if source not in {'reference_bbox', 'roi_fixed'}:
        raise ValueError('Unknown LUT source; use reference_bbox or roi_fixed')
    mask = None if roi is None else _require_roi(roi, a.shape[-2:])
    if source == 'roi_fixed' and mask is None:
        raise ValueError('roi_fixed requires an explicit 488-derived ROI')
    if source == 'reference_bbox':
        # The historical renderer uses float32 before np.percentile. Retain
        # that display convention for exact reference comparisons.
        with np.errstate(over='ignore', invalid='ignore'):
            values = np.asarray(a, dtype=np.float32).reshape(-1)
        if np.any(np.isfinite(a).reshape(-1) & ~np.isfinite(values)):
            raise ValueError(
                'Finite data exceed the float32 reference convention; use explicit limits')
        numeric = 'float32 reference'
    else:
        values = np.asarray(a[:, mask], dtype=np.float64).reshape(-1)
        numeric = 'float64 pooled ROI'
    values = values[np.isfinite(values)]
    if not values.size:
        raise ValueError('No finite values are available for the chosen display source')
    # Separate scalar calls preserve the renderer's float32 rounding convention;
    # a vector of percentiles may promote the result to float64 in NumPy.
    low = float(np.percentile(values, low_percentile))
    high = float(np.percentile(values, high_percentile))
    if high <= low:
        high = low + max(1.0, abs(low) * 1e-6)
        if not np.isfinite(high) or high <= low:
            raise ValueError('Flat data cannot form finite limits; supply an explicit LUT')
    origin = (f'{source}: all supplied visits, p{low_percentile:g}/p{high_percentile:g}; '
              f'{numeric}; display only')
    return LUT(low, high, color=color, scope='fixed-longitudinal-per-neuron', source=origin)


def clipping_stats(image, roi, lut):
    """Count strict display clipping in a supplied ROI without changing it.

    Values equal to a limit are not counted as clipped. The quantitative sum
    comes from the original ROI pixels and must not depend on the LUT.
    """
    a = np.asarray(image)
    if a.ndim != 2 or min(a.shape, default=0) < 1 or a.dtype.kind not in 'buif':
        raise ValueError('Clipping statistics require a nonempty numeric YX image')
    mask = _require_roi(roi, a.shape)
    values = a[mask]
    if not np.isfinite(values).all():
        raise ValueError('Quantitative ROI values must be finite')
    below = int(np.count_nonzero(values < lut.low))
    above = int(np.count_nonzero(values > lut.high))
    count = int(values.size)
    quantitative_sum = float(np.sum(values, dtype=np.float64))
    if not np.isfinite(quantitative_sum):
        raise ValueError('Quantitative ROI sum exceeds float64 range')
    return dict(roi_pixels=count, below_low=below, above_high=above,
                below_low_fraction=below / count, above_high_fraction=above / count,
                below_low_percent=100.0 * below / count, above_high_percent=100.0 * above / count,
                quantitative_sum=quantitative_sum)
