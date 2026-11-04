"""Small guards preventing legacy selectors from silently dropping ND2 data."""
from __future__ import annotations


def require_legacy_single_observation(sizes, max_sites):
    """The legacy CYX loader is not an all-position/time/Z well assembler."""
    if type(max_sites) is not int or max_sites != 1:
        raise ValueError("Legacy CYX loading supports max_sites=1 only; use trace_original_nd2_well.py for whole-well ND2 processing")
    for axis in ("P", "T", "Z"):
        count = sizes.get(axis, 1)
        if type(count) is not int or count < 1:
            raise ValueError("ND2 axis sizes must be positive integers: " + axis)
        if count != 1:
            raise ValueError(f"Refusing implicit {axis}=0 or projection for {count} observations. "
                             "Use trace_original_nd2_well.py with an explicit complete tile/time/Z manifest")


def add_unique_well_visit(by_well, well, day, path):
    """Reject ambiguous FOV files rather than replacing an earlier file."""
    visits = by_well.setdefault(well, {})
    day = int(day)
    if day in visits:
        raise ValueError(f"Multiple ND2 files for {well} day {day}: {visits[day]} and {path}. "
                         "Declare all FOVs in the reviewed whole-well ND2 manifest; no file was selected away")
    visits[day] = path
