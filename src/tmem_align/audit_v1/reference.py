"""Small audit integrations with the UNMODIFIED reference pipeline.

Private preprocessing helpers are intentionally pinned to the source snapshot;
each execution compares its staged result with the public reference function.
These functions need the repository's microscopy dependencies.
"""
import importlib
import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

from .contracts import require_cyx, strict_overlap


def renderer():
    # Existing scripts use sibling imports. Support source checkout execution only.
    root = Path(__file__).resolve().parents[3]
    script_dir = root / "scripts"
    if not (script_dir / "render_curated_neuron_phenotypes.py").exists():
        raise RuntimeError("Run this audit from the supplied source checkout")
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    return importlib.import_module("render_curated_neuron_phenotypes")


def preprocess_steps(image, *, flatfield=None, darkfield=None, background_radius=None):
    from tmem_align import preprocess as p

    a = np.asarray(image)
    if a.ndim not in (2, 3) or not a.size or not np.isfinite(a).all():
        raise ValueError("Use a finite YX/CYX frame for preprocessing audit")
    if flatfield is not None:
        field = np.asarray(flatfield)
        if not np.isfinite(field).all() or np.any(field <= 0):
            raise ValueError("Audit rejects nonpositive/nonfinite IC fields")
    if darkfield is not None and not np.isfinite(darkfield).all():
        raise ValueError("Darkfield must be finite")
    if background_radius is not None and (not isinstance(background_radius, int)
                                          or background_radius < 1):
        raise ValueError("Background radius must be a positive integer")
    stages = {"00_raw": a.copy(), "01_before_ic": a.copy()}
    dark_corrected = p._apply_ic_field_float(a, None, darkfield)
    stages["02_dark_subtracted_float"] = dark_corrected
    ic = p._apply_ic_field_float(a, flatfield, darkfield)
    stages["03_after_ic_float"] = ic
    final_float = p._background_float(ic, background_radius) if background_radius else ic
    stages["04_background_estimate"] = ic - final_float
    stages["05_after_background_float"] = final_float
    noop = flatfield is None and darkfield is None and background_radius is None
    output = a.copy() if noop else p._quantize(final_float)
    expected = p.preprocess_image(a, ic_field=flatfield, darkfield=darkfield,
                                  background_radius=background_radius)
    np.testing.assert_array_equal(output, expected, err_msg="Preprocessing reference mismatch")
    stages["06_downstream_input"] = output
    return output, stages, {"reference_exact_match": True, "ic_applied": flatfield is not None,
                            "darkfield_applied": darkfield is not None,
                            "background_radius": background_radius,
                            "quantization": "none" if noop else "rint then clip [0,65535], once"}


def alignment_steps(reference_cyx, moving_cyx, *, max_shift=500, min_correlation=0.07):
    from tmem_align.register import apply_shift, register_translation
    from tmem_align.registration_qc import classify_registration_qc, correlation, overlap_fraction

    ref, mov = require_cyx(reference_cyx), require_cyx(moving_cyx)
    if ref.shape != mov.shape:
        raise ValueError("Alignment frame shapes differ")
    r, m = ref[2], mov[2]
    if np.std(r) == 0 or np.std(m) == 0:
        raise ValueError("Uninformative 488 frame: cannot establish registration")
    _, (dy, dx), error = register_translation(r, m, robust_preprocess=False,
                                             mask_percentile=20.0, max_shift_pixels=max_shift)
    shifted = apply_shift(mov, dy, dx)
    bounds = strict_overlap(ref.shape[-2:], [(0, 0), (dy, dx)])
    post = correlation(r, shifted[2])
    overlap = overlap_fraction(r.shape, (dy, dx))
    qc = classify_registration_qc(overlap, dy, dx, *r.shape, post_correlation=post,
                                  min_post_correlation=min_correlation)
    stages = {"00_reference_488": r, "01_moving_488": m,
              "02_reference_alignment_mask": r > np.percentile(r, 20),
              "03_moving_alignment_mask": m > np.percentile(m, 20),
              "04_aligned_488": shifted[2]}
    diagnostics = dict(dy=dy, dx=dx, phase_error=error, masked_phase_error_is_undefined=True,
                       pre_correlation=correlation(r, m), post_correlation=post,
                       overlap_fraction=overlap, common_bounds=vars(bounds),
                       registration_channel="488", mask_percentile=20, robust_preprocess=False,
                       min_correlation=min_correlation, **qc)
    return shifted, stages, diagnostics


def phenotype_steps(raw561, roi, *, background_exclusion=8, puncta_min_size=6):
    """Keep the curated renderer's result; expose its otherwise hidden intermediates."""
    from skimage import measure, morphology

    a, mask = np.asarray(raw561), np.asarray(roi)
    if a.ndim != 2 or mask.shape != a.shape or mask.dtype != bool or not mask.any():
        raise ValueError("Require a nonempty boolean phenotype ROI matching raw 561")
    if not np.isfinite(a).all():
        raise ValueError("Nonfinite phenotype pixels")
    result = renderer().quantify_phenotype(a, mask, background_exclusion, puncta_min_size)
    metrics, puncta, diffuse, corrected = result
    background_mask = ~morphology.dilation(mask, morphology.disk(background_exclusion))
    if background_mask.sum() < 50:
        background_mask = ~mask
    dog = gaussian_filter(corrected, 1.0) - gaussian_filter(corrected, 3.0)
    candidates = (dog > metrics["dog_threshold"]) & mask
    filtered = morphology.remove_small_objects(candidates, max_size=max(0, puncta_min_size - 1))
    np.testing.assert_array_equal(filtered, puncta, err_msg="Puncta reference mismatch")
    np.testing.assert_array_equal(mask, puncta | diffuse)
    if np.any(puncta & diffuse):
        raise AssertionError("Punctate and diffuse supports overlap")
    np.testing.assert_allclose(metrics["total_mcherry_intensity"],
                               metrics["punctate_mcherry_integrated_intensity"] +
                               metrics["diffuse_mcherry_integrated_intensity"], rtol=1e-12)
    stages = {"00_raw_561": a, "01_phenotype_roi": mask,
              "02_background_mask": background_mask, "03_background_corrected": corrected,
              "04_dog": dog, "05_puncta_candidates": candidates,
              "06_size_filtered_puncta": puncta, "07_puncta_labels": measure.label(puncta),
              "08_diffuse_support": diffuse, "09_diffuse_intensity": corrected * diffuse}
    return result, stages
