from __future__ import annotations

from pathlib import Path

import numpy as np
from tqdm import tqdm

from .io import find_images, normalize_to_2d, read_image, write_ome_tiff


def stitch_grid(
    tile_paths: list[str | Path],
    grid_rows: int,
    grid_cols: int,
    overlap_fraction: float = 0.10,
    snake_order: bool = False,
) -> np.ndarray:
    """Simple grid stitcher for quick prototyping.

    This assumes all tiles are the same shape and acquired in a regular grid. It uses nominal
    overlap and does not perform global optimization. For publication-grade stitching, use Fiji's
    Grid/Collection Stitching or microscope stage coordinates.
    """
    if len(tile_paths) != grid_rows * grid_cols:
        raise ValueError(f"Expected {grid_rows * grid_cols} tiles, found {len(tile_paths)}")

    tiles = [normalize_to_2d(read_image(p)) for p in tqdm(tile_paths, desc="Reading tiles")]
    th, tw = tiles[0].shape
    step_y = int(round(th * (1 - overlap_fraction)))
    step_x = int(round(tw * (1 - overlap_fraction)))
    canvas = np.zeros((step_y * (grid_rows - 1) + th, step_x * (grid_cols - 1) + tw), dtype=np.float32)
    weight = np.zeros_like(canvas, dtype=np.float32)

    for r in range(grid_rows):
        cols = range(grid_cols)
        if snake_order and r % 2 == 1:
            cols = reversed(range(grid_cols))
        for c_display, c in enumerate(cols):
            tile_index = r * grid_cols + c_display if snake_order else r * grid_cols + c
            tile = tiles[tile_index].astype(np.float32)
            y0 = r * step_y
            x0 = c * step_x
            canvas[y0:y0 + th, x0:x0 + tw] += tile
            weight[y0:y0 + th, x0:x0 + tw] += 1

    weight[weight == 0] = 1
    return (canvas / weight).astype(tiles[0].dtype)


def stitch_folder_to_ometiff(
    tile_folder: str | Path,
    output_path: str | Path,
    grid_rows: int,
    grid_cols: int,
    overlap_fraction: float = 0.10,
    snake_order: bool = False,
) -> Path:
    tile_paths = find_images(tile_folder)
    stitched = stitch_grid(tile_paths, grid_rows, grid_cols, overlap_fraction, snake_order)
    write_ome_tiff(output_path, stitched, axes="YX")
    return Path(output_path)
