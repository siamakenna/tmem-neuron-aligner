"""Replaceable, display-only previews and explicitly unadopted LUT boxes.

``render_preview`` is the small visualization extension point. Its result is an
RGB preview, never a quantitative image. ``propose_lut_bbox`` offers a separate
488-only viewing suggestion; it does not update an anchor, mask, measurement ROI,
tracking result, or review decision.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict

import numpy as np
from scipy.ndimage import label

from .contracts import Bounds
from .display import LUT, apply_lut_for_display


def _image_yx(image, *, finite):
    a = np.asarray(image)
    if a.ndim != 2 or not a.size or a.dtype.kind not in "buif":
        raise ValueError("Visualization requires one nonempty real numeric YX channel")
    if finite and not np.isfinite(a).all():
        raise ValueError("LUT box proposals require finite 488 pixels")
    return a


def _bounds(bounds, shape):
    if bounds is None:
        return Bounds(0, int(shape[0]), 0, int(shape[1]))
    if not isinstance(bounds, Bounds):
        raise ValueError("Supply Bounds(y0,y1,x0,x1) in half-open image coordinates")
    if any(isinstance(v, (bool, np.bool_)) for v in vars(bounds).values()):
        raise ValueError("Bounds must be integer pixel coordinates, not booleans")
    bounds.validate(shape)
    # NumPy integer coordinates are valid inputs, but JSON provenance should
    # contain ordinary integers rather than NumPy scalar objects.
    return Bounds(*(int(value) for value in (bounds.y0, bounds.y1, bounds.x0, bounds.x1)))


def _edge(mask):
    padded = np.pad(mask, 1, constant_values=False)
    interior = (padded[:-2, 1:-1] & padded[2:, 1:-1]
                & padded[1:-1, :-2] & padded[1:-1, 2:])
    return mask & ~interior


def render_preview(image, lut, *, bounds=None, overlays=None):
    """Render an independent, read-only RGB preview using the existing LUT code.

    ``image`` is a single YX plane. ``bounds`` is an optional spatial crop in
    that plane. Nonfinite display pixels retain the existing orange marker.

    Each overlay is a mapping with a full-image boolean ``mask`` and optional
    ``color`` (three integer values 0..255), ``alpha`` (0..1), and ``outline``
    (default True). An overlay is cropped together with its image; a cropped
    region is not used to infer a new object boundary. No supplied array is
    modified. Callers needing a writable UI buffer can use ``result.copy()``.
    """
    a = _image_yx(image, finite=False)
    if not isinstance(lut, LUT):
        raise ValueError("Supply an explicit LUT instance")
    box = _bounds(bounds, a.shape)
    rgb = apply_lut_for_display(box.crop(a), lut)
    if overlays is None:
        overlays = ()
    if isinstance(overlays, Mapping):
        raise ValueError("overlays must be a sequence of overlay mappings")
    for overlay in overlays:
        if not isinstance(overlay, Mapping) or "mask" not in overlay:
            raise ValueError("Each overlay requires a full-image boolean mask")
        if set(overlay) - {"mask", "color", "alpha", "outline"}:
            raise ValueError("Unknown overlay option")
        mask = np.asarray(overlay["mask"])
        if mask.dtype != bool or mask.shape != a.shape:
            raise ValueError("Overlay masks must be boolean and match the full image")
        color = np.asarray(overlay.get("color", (255, 255, 0)))
        if (color.shape != (3,) or color.dtype.kind not in "iu"
                or np.any(color < 0) or np.any(color > 255)):
            raise ValueError("Overlay color must be three integer values in 0..255")
        alpha = overlay.get("alpha", 1.0)
        if (isinstance(alpha, (bool, np.bool_)) or not np.isscalar(alpha)
                or not isinstance(alpha, (int, float, np.integer, np.floating))
                or not np.isfinite(alpha) or not 0 <= alpha <= 1):
            raise ValueError("Overlay alpha must be a finite number in 0..1")
        outline = overlay.get("outline", True)
        if not isinstance(outline, (bool, np.bool_)):
            raise ValueError("Overlay outline must be boolean")
        support = box.crop(_edge(mask) if outline else mask)
        rgb[support] = np.rint((1 - float(alpha)) * rgb[support]
                               + float(alpha) * color).astype(np.uint8)
    rgb.setflags(write=False)
    return rgb


def propose_lut_bbox(image488, lut, *, anchor_yx=None, search_bounds=None,
                     padding=0, min_area=1, channel="488", range_policy="visible"):
    """Suggest a viewing box from a connected 488 component, without adoption.

    Default ``visible`` support is ``pixel > lut.low``. Pixels above ``lut.high``
    stay visible at the clipped display maximum and remain in the proposal.
    Therefore changing only the upper display limit cannot drop bright soma
    pixels. Optional ``within_range`` means ``lut.low < pixel <= lut.high``;
    this deliberate exclusion of clipped-high pixels is recorded explicitly.

    Components use eight-neighbor connectivity, inside ``search_bounds`` only.
    If an anchor is supplied, select the component containing its floored pixel
    index; never jump to another component. Otherwise select the largest eligible
    component, resolving area ties by row-major component label. ``padding`` is
    clipped to the search box. All coordinates use the original YX image frame.
    """
    a = _image_yx(image488, finite=True)
    if not isinstance(lut, LUT):
        raise ValueError("Supply an explicit LUT instance")
    if channel != "488":
        raise ValueError("LUT box proposals use the explicitly declared 488 channel only")
    if range_policy not in {"visible", "within_range"}:
        raise ValueError("range_policy must be 'visible' or 'within_range'")
    for name, value, lower in [("padding", padding, 0), ("min_area", min_area, 1)]:
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer))
                or value < lower):
            raise ValueError(f"{name} must be an integer >= {lower}")
    padding, min_area = int(padding), int(min_area)
    search = _bounds(search_bounds, a.shape)
    crop = search.crop(a)
    support = crop > lut.low
    above_high = int(np.count_nonzero(crop > lut.high))
    if range_policy == "within_range":
        support &= crop <= lut.high
    components, count = label(support, structure=np.ones((3, 3), dtype=np.uint8))
    areas = np.bincount(components.ravel(), minlength=count + 1)
    eligible = [i for i in range(1, count + 1) if areas[i] >= min_area]
    record = dict(
        schema_version="tmem.visualization_lut_bbox.v1",
        status="pending", bounds=None, mask_count=0,
        channel="488", display_only=True, adopted=False,
        measurement_geometry_changed=False, review_approval_granted=False,
        method="8-connected 488 LUT support inside an explicit search box",
        range_policy=range_policy,
        support_rule="low < pixel" if range_policy == "visible" else "low < pixel <= high",
        upper_limit_role="display clipping only; clipped-high pixels included"
            if range_policy == "visible" else "explicit candidate-support upper cutoff",
        lut=lut.metadata(), search_bounds=asdict(search), padding_px=padding,
        minimum_component_area_px=min_area, component_count=int(count),
        eligible_component_count=len(eligible), support_pixels=int(support.sum()),
        above_high_pixels_in_search=above_high,
        above_high_pixels_excluded_from_support=above_high if range_policy == "within_range" else 0,
        source_shape=list(a.shape), source_dtype=str(a.dtype),
        source_array_sha256=hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest(),
        coordinate_system="original image YX; half-open integer pixel bounds",
        anchor_yx=None, anchor_index_yx=None,
        anchor_index_rule="floor in zero-based pixel coordinates",
        selection_rule="component containing anchor; no nearest-component rescue"
            if anchor_yx is not None else "largest eligible component; lowest label breaks ties",
    )
    chosen = None
    if anchor_yx is not None:
        anchor = np.asarray(anchor_yx)
        if (anchor.shape != (2,) or anchor.dtype.kind not in "iuf"
                or not np.isfinite(anchor).all()):
            raise ValueError("anchor_yx must contain two finite real pixel coordinates")
        if not (0 <= anchor[0] < a.shape[0] and 0 <= anchor[1] < a.shape[1]):
            raise ValueError("Anchor lies outside the image")
        y, x = np.floor(anchor).astype(int)
        record.update(anchor_yx=[float(anchor[0]), float(anchor[1])],
                      anchor_index_yx=[int(y), int(x)])
        if not (search.y0 <= y < search.y1 and search.x0 <= x < search.x1):
            record["status"] = "anchor_outside_search"
            return record
        chosen = int(components[y - search.y0, x - search.x0])
        if chosen == 0:
            record["status"] = "anchor_not_in_lut_support"
            return record
        if areas[chosen] < min_area:
            record["status"] = "anchor_component_below_min_area"
            return record
    elif eligible:
        chosen = max(eligible, key=lambda i: (int(areas[i]), -i))
    if chosen is None:
        record["status"] = "no_signal" if count == 0 else "no_eligible_component"
        return record
    yy, xx = np.where(components == chosen)
    proposed = Bounds(
        max(search.y0, int(yy.min()) + search.y0 - padding),
        min(search.y1, int(yy.max()) + search.y0 + 1 + padding),
        max(search.x0, int(xx.min()) + search.x0 - padding),
        min(search.x1, int(xx.max()) + search.x0 + 1 + padding),
    ).validate(a.shape)
    record.update(status="proposal", bounds=asdict(proposed),
                  mask_count=int(areas[chosen]), selected_component_label=chosen,
                  selected_centroid_yx=[float(yy.mean() + search.y0),
                                        float(xx.mean() + search.x0)])
    return record
