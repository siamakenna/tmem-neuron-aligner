from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.diagnose_registration_drift import (
    common_mode_by_day,
    load_shifts,
    well_summary,
)


def _df(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "well",
            "timepoint_day",
            "estimated_y_shift",
            "estimated_x_shift",
            "overlap_fraction",
        ],
    )


def test_well_summary_classifies():
    df = _df(
        [
            ("A", 8, 0, 0, 1.0),
            ("A", 12, 5, 0, 0.99),
            ("A", 16, -3, 4, 0.99),  # clean
            ("B", 8, 0, 0, 1.0),
            ("B", 12, 900, 0, 0.4),
            ("B", 16, 2, 0, 0.99),  # one bad day
            ("C", 8, 0, 0, 1.0),
            ("C", 12, 900, 0, 0.4),
            ("C", 16, 0, 700, 0.5),  # erratic
        ]
    )
    df["shift_mag"] = np.hypot(df["estimated_y_shift"], df["estimated_x_shift"])
    s = well_summary(df, large_thresh=100.0).set_index("well")
    assert s.loc["A", "classification"] == "clean"
    assert s.loc["B", "classification"] == "one_bad_day"
    assert s.loc["C", "classification"] == "high_drift_or_erratic"
    assert s.loc["C", "n_large_shifts"] == 2


def test_common_mode_coherence():
    # day 12: all wells shift the same way -> coherent (shareable, ~1)
    # day 16: wells shift in random directions, same magnitude -> cancels (~0)
    rows = [
        ("A", 12, 100, 0, 0.9),
        ("B", 12, 100, 0, 0.9),
        ("C", 12, 100, 0, 0.9),
        ("A", 16, 100, 0, 0.9),
        ("B", 16, -100, 0, 0.9),
        ("C", 16, 0, 100, 0.9),
        ("D", 16, 0, -100, 0.9),
    ]
    df = _df(rows)
    df["shift_mag"] = np.hypot(df["estimated_y_shift"], df["estimated_x_shift"])
    cm = common_mode_by_day(df).set_index("timepoint_day")
    assert cm.loc[12, "coherence"] > 0.95  # aligned
    assert cm.loc[16, "coherence"] < 0.1  # cancels out


def test_load_shifts_missing_column(tmp_path):
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"well": ["A"], "timepoint_day": [8]}).to_csv(bad, index=False)
    try:
        load_shifts(bad)
    except ValueError as e:
        assert "missing columns" in str(e)
    else:
        raise AssertionError("expected ValueError for missing shift columns")
