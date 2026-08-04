#!/usr/bin/env python
"""Compute per-timepoint IC fields for a plate and save as .npz."""

import argparse
import time
from pathlib import Path

import numpy as np

from tmem_align.preprocess import calculate_ic_fields_by_timepoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plate_dir", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output .npz path (default: <plate_dir>/ic_fields.npz)")
    parser.add_argument("--sample-fraction", type=float, default=0.25)
    parser.add_argument("--workers", type=int, default=None,
                        help="Parallel processes (default: one per timepoint)")
    args = parser.parse_args()

    out = args.output or args.plate_dir / "ic_fields.npz"

    print(f"Plate: {args.plate_dir}")
    print(f"Sample fraction: {args.sample_fraction}")
    print(f"Workers: {args.workers or 'auto'}")

    t0 = time.time()
    ic_fields = calculate_ic_fields_by_timepoint(
        args.plate_dir,
        sample_fraction=args.sample_fraction,
        n_workers=args.workers,
    )
    elapsed = time.time() - t0

    np.savez_compressed(out, **ic_fields)
    print(f"\n{len(ic_fields)} timepoints in {elapsed:.1f}s → {out}")
    for name, ic in sorted(ic_fields.items()):
        print(f"  {name}: shape={ic.shape}, range=[{ic.min():.2f}, {ic.max():.2f}]")


if __name__ == "__main__":
    main()
