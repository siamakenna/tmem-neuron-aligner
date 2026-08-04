from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import tifffile as tif


def find_images(folder: str | Path, suffixes: Iterable[str] = (".tif", ".tiff", ".ome.tif", ".ome.tiff", ".nd2")) -> list[Path]:
    folder = Path(folder)
    if folder.is_file():
        return [folder]
    suffixes = tuple(s.lower() for s in suffixes)
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in suffixes or any(str(p).lower().endswith(s) for s in suffixes))


def read_image(path: str | Path) -> np.ndarray:
    path = Path(path)
    if path.suffix.lower() == ".nd2":
        import nd2
        return np.asarray(nd2.imread(str(path)))
    arr = tif.imread(path)
    return np.asarray(arr)


def write_ome_tiff(path: str | Path, image: np.ndarray, axes: str = "CYX", pixel_size_um: float | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"axes": axes}
    if pixel_size_um:
        metadata["PhysicalSizeX"] = pixel_size_um
        metadata["PhysicalSizeXUnit"] = "µm"
        metadata["PhysicalSizeY"] = pixel_size_um
        metadata["PhysicalSizeYUnit"] = "µm"
    tif.imwrite(path, image, photometric="minisblack", metadata=metadata, ome=True)


def normalize_to_2d(image: np.ndarray) -> np.ndarray:
    """Collapse simple singleton axes to a 2D image for registration/stitching."""
    arr = np.squeeze(image)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        # Conservative fallback: maximum projection over first axis.
        return arr.max(axis=0)
    raise ValueError(f"Cannot normalize image with shape {image.shape} to 2D")
