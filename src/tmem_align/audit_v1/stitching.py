"""Explicit integer-coordinate, channel-preserving well assembly.

No tile matching, inferred tile order, stage-axis guessing or exposure correction.
Overlap pixels are arithmetic means. Missing support remains NaN, never fake zero signal.
"""
from dataclasses import dataclass

import numpy as np

from .contracts import require_cyx


@dataclass(frozen=True)
class Tile:
    tile_id: str
    image: np.ndarray
    y: int
    x: int


def stage_to_pixel(stage_xy_um, origin_xy_um, pixel_size_um, orientation):
    """Convert stage XY (tile TOP LEFT) to image YX, returning rounding residual.

    orientation maps stage (x,y) displacement to image (y,x) displacement;
    it must be a signed permutation matrix, verified with asymmetric landmarks.
    If metadata describes tile centers, convert to top-left first using the
    verified camera convention. Never estimate orientation from mCherry.
    """
    mat = np.asarray(orientation, dtype=float)
    stage = np.asarray(stage_xy_um, dtype=float)
    origin = np.asarray(origin_xy_um, dtype=float)
    if stage.shape != (2,) or origin.shape != (2,) or not np.isfinite([stage, origin]).all():
        raise ValueError("Require two finite stage/origin coordinates")
    if mat.shape != (2, 2) or not np.isin(mat, [-1, 0, 1]).all():
        raise ValueError("Orientation must be a signed permutation matrix")
    if not np.array_equal(mat @ mat.T, np.eye(2)):
        raise ValueError("Orientation must preserve orthogonal image axes")
    if not np.isfinite(pixel_size_um) or pixel_size_um <= 0:
        raise ValueError("pixel_size_um must be positive")
    exact = mat @ (stage - origin) / pixel_size_um
    rounded = np.rint(exact).astype(int)
    return tuple(map(int, rounded)), tuple(map(float, exact - rounded))


def grid_offsets(rows, cols, tile_shape, overlap_fraction=0.1, snake=False):
    """Nominal SYNTHETIC/regular-grid positions in acquisition order."""
    if not all(isinstance(n, int) and n > 0 for n in (rows, cols, *tile_shape)):
        raise ValueError("Positive integer grid and tile dimensions required")
    if not np.isfinite(overlap_fraction) or not 0 <= overlap_fraction < 1:
        raise ValueError("overlap_fraction must be in [0,1)")
    sy, sx = (int(round(n * (1 - overlap_fraction))) for n in tile_shape)
    if min(sy, sx) < 1:
        raise ValueError("Overlap collapses tile stride")
    return [(r * sy, c * sx) for r in range(rows)
            for c in (reversed(range(cols)) if snake and r % 2 else range(cols))]


def assemble_well(tiles, canvas_yx, *, max_pixels=40_000_000):
    """Return float32 CYX mosaic, uint32 coverage, incremental overlap diagnostics.

    The caller supplies the same canvas/origin for every visit. Peak working RAM
    is approximately 52 bytes per canvas pixel plus loaded tiles; max_pixels is
    a guard, not a streaming implementation.
    """
    tiles = list(tiles)
    if not tiles:
        raise ValueError("No tiles supplied")
    if len(canvas_yx) != 2 or any(not isinstance(n, int) or n <= 0 for n in canvas_yx):
        raise ValueError("canvas_yx requires two positive integers")
    h, w = canvas_yx
    if h * w > max_pixels:
        raise ValueError("Canvas exceeds max_pixels memory guard")
    ids, positions = set(), set()
    for tile in tiles:
        a = require_cyx(tile.image)
        if tile.tile_id in ids or (tile.y, tile.x) in positions:
            raise ValueError("Duplicate tile ID or position")
        if not all(isinstance(n, (int, np.integer)) for n in (tile.y, tile.x)):
            raise ValueError("Tile offsets must be integer pixels")
        if tile.y < 0 or tile.x < 0 or tile.y + a.shape[1] > h or tile.x + a.shape[2] > w:
            raise ValueError("Tile extends outside the shared canvas")
        ids.add(tile.tile_id)
        positions.add((tile.y, tile.x))
    total = np.zeros((3, h, w), dtype=np.float64)
    coverage = np.zeros((h, w), dtype=np.uint32)
    seams = []
    for tile in tiles:
        a = np.asarray(tile.image, dtype=float)
        sl = (slice(tile.y, tile.y + a.shape[1]), slice(tile.x, tile.x + a.shape[2]))
        acc, weight = total[:, sl[0], sl[1]], coverage[sl]
        overlap = weight > 0
        mae = []
        if overlap.any():
            difference = a[:, overlap] - acc[:, overlap] / weight[overlap]
            mae = np.mean(np.abs(difference), axis=1).tolist()
        seams.append(dict(tile_id=tile.tile_id, y=tile.y, x=tile.x,
                          overlap_pixels=int(overlap.sum()), mean_abs_difference_by_channel=mae))
        acc += a
        weight += 1
    output = np.full(total.shape, np.nan, dtype=np.float32)
    np.divide(total, coverage[None], out=output, where=coverage[None] > 0)
    return output, coverage, seams
