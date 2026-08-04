from __future__ import annotations

from tmem_align.registration_qc import classify_registration_qc

H = W = 2000


def test_qc_fails_on_low_post_correlation():
    # good overlap + small shift, but near-zero correlation = spurious alignment -> fail
    r = classify_registration_qc(0.95, 5, 5, H, W, post_correlation=0.004)
    assert r["qc_pass"] is False


def test_qc_passes_with_good_correlation():
    r = classify_registration_qc(0.95, 5, 5, H, W, post_correlation=0.09)
    assert r["qc_pass"] is True


def test_qc_backward_compatible_without_correlation():
    # callers that don't pass post_correlation keep the old overlap/shift-only behavior
    r = classify_registration_qc(0.95, 5, 5, H, W)
    assert r["qc_pass"] is True


def test_qc_large_shift_flagged_and_fails_on_overlap():
    r = classify_registration_qc(0.4, 700, 0, H, W, post_correlation=0.09)
    assert r["large_shift"] is True
    assert r["qc_pass"] is False  # overlap 0.4 < 0.5


def test_qc_low_correlation_overrides_good_geometry():
    # this is the exact failure that let ~all rows pass before: fine geometry, no real peak
    r = classify_registration_qc(0.8, 10, 10, H, W, post_correlation=0.004)
    assert r["qc_pass"] is False
