#!/usr/bin/env python3
"""Check stored raw/field/corrected numeric patches from the completed IC run.

This checks arithmetic parity on supplied128px patches. It does not validate the
full-field estimator, independent physical calibration, or neuron identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def verify_fixture(path):
    path = Path(path)
    with np.load(path, allow_pickle=False) as fixture:
        raw = fixture['raw']
        field = fixture['field_float64']
        corrected = fixture['corrected']
        bounds = fixture['bounds_yxyx']
        if (raw.shape != (128, 128) or field.shape != raw.shape
                or corrected.shape != raw.shape or raw.dtype != np.uint16
                or corrected.dtype != np.uint16 or field.dtype != np.float64
                or bounds.shape != (4,)):
            raise ValueError('Historical IC fixture has unexpected shapes or dtypes')
        if not np.isfinite(field).all() or np.any(field <= 0):
            raise ValueError('Historical IC field must be finite and positive')
        # Match the recorded public correction: float64 division, one rint and
        # one clip at the output boundary. Do not estimate a field from a crop.
        actual = np.clip(np.rint(raw.astype(np.float64)/field), 0, 65535).astype(np.uint16)
        np.testing.assert_array_equal(actual, corrected,
                                      err_msg='Stored IC arithmetic changed from its historical reference')
        return {'fixture_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'shape': list(raw.shape), 'bounds_yxyx': bounds.tolist(),
                'exact_match': True, 'raw_sum': int(raw.sum(dtype=np.uint64)),
                'corrected_sum': int(corrected.sum(dtype=np.uint64))}


def verify_evidence(root):
    root = Path(root)
    paths = sorted((root/'ic_examples').glob('*/day_*/*/small_numeric_fixture.npz'))
    if len(paths) != 5:
        raise ValueError(f'Expected five selected historical IC fixtures, found {len(paths)}')
    records = [{'path': str(path.relative_to(root)), **verify_fixture(path)} for path in paths]
    return {'schema_version': 'tmem.historical_ic_fixture_check.v1',
            'supplied_patch_arithmetic': 'PASS', 'patches_checked': len(records),
            'scope': 'Stored128x128 raw/field/corrected patches only. Full-field estimation and physical calibration are separate evidence.',
            'physical_calibration_validated': False, 'empirical_ic_adopted': False,
            'fixtures': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True,
                        help='New JSON file, preferably under the current verification output directory')
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f'Output already exists: {args.out}')
    result = verify_evidence(args.evidence_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as handle:
        handle.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(f'PASS: five supplied historical IC patches match exactly. Output: {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
