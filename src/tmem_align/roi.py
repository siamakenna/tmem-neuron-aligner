from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .io import read_image, write_ome_tiff
from .register import register_translation


@dataclass(frozen=True)
class Roi:
    plate: str
    well: str
    roi_id: str
    x: int
    y: int
    width: int
    height: int


def crop_xy(image: np.ndarray, x: int, y: int, width: int, height: int) -> np.ndarray:
    arr = np.asarray(image)
    return arr[..., y:y + height, x:x + width]


def roi_from_table(roi_table: pd.DataFrame, plate: str, well: str, roi_id: str) -> Roi:
    subset = roi_table[(roi_table["plate"] == plate) & (roi_table["well"] == well) & (roi_table["roi_id"] == roi_id)]
    if subset.empty:
        raise ValueError(f"ROI not found: plate={plate}, well={well}, roi_id={roi_id}")
    row = subset.iloc[0]
    return Roi(plate, well, roi_id, int(row.x), int(row.y), int(row.width), int(row.height))


def build_roi_timeseries(
    registered_well_paths: list[Path],
    roi: Roi,
    output_path: str | Path,
    local_register: bool = True,
    upsample_factor: int = 20,
    max_shift_pixels: float = 100,
) -> Path:
    crops = []
    shifts = []
    reference_crop = None

    for p in registered_well_paths:
        img = read_image(p)
        crop = crop_xy(img, roi.x, roi.y, roi.width, roi.height)
        if reference_crop is None:
            reference_crop = crop
            registered_crop = crop
            shifts.append((0.0, 0.0))
        elif local_register:
            registered_crop, shift, _ = register_translation(
                reference_crop, crop, upsample_factor, max_shift_pixels, robust_preprocess=False
            )
            shifts.append(shift)
        else:
            registered_crop = crop
            shifts.append((0.0, 0.0))
        crops.append(registered_crop)

    stack = np.stack(crops, axis=0)
    write_ome_tiff(output_path, stack, axes="TYX" if stack.ndim == 3 else "TCYX")

    shift_csv = Path(output_path).with_suffix(".local_shifts.csv")
    pd.DataFrame({"path": [str(p) for p in registered_well_paths], "dy": [s[0] for s in shifts], "dx": [s[1] for s in shifts]}).to_csv(shift_csv, index=False)
    return Path(output_path)
