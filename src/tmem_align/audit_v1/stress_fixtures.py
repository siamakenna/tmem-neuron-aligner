"""Deterministic challenge images with declared synthetic truth.

These fixtures expose known geometry and nuisance changes. They cannot establish
same-neuron identity or validate a real microscope's exposure/illumination model.
No production tracking, segmentation, or measurement parameter is changed here.
"""
from __future__ import annotations

import numpy as np


CASE_IDS = (
    "low_488_nonblank", "neighboring_somata", "two_somata_one_crop",
    "crowded_field", "edge_of_FOV", "puncta_rich", "diffuse_cell",
    "exposure_change", "illumination_gradient",
)
SHAPE = (96, 96)
DEFAULT_SEED = 20261020


def _gaussian(y, x, cy, cx, sigma):
    return np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2 * sigma ** 2))


def stress_fixture(case_id: str, *, seed: int = DEFAULT_SEED) -> dict:
    """Return synthetic CYX planes, truth masks and fully resolved parameters.

    ``reference_cyx`` records the image before the declared challenge operation.
    ``cyx`` is the challenged image. Labels describe geometric truth, not an
    automated detector's result. ``phenotype_roi`` is a prescribed 488-truth ROI.
    The scientific software has not passed a case merely because this function
    successfully constructs it.
    """
    if case_id not in CASE_IDS:
        raise ValueError(f"Unknown synthetic stress case: {case_id}")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    y, x = np.mgrid[:SHAPE[0], :SHAPE[1]]
    centers = [(48, 48)]
    radius, roi_radius = 9, 15
    if case_id == "neighboring_somata":
        centers, roi_radius = [(48, 44), (48, 63)], 16
    elif case_id == "two_somata_one_crop":
        centers, roi_radius = [(48, 39), (48, 57)], 24
    elif case_id == "crowded_field":
        centers, roi_radius = [(48, 48), (35, 35), (44, 65), (64, 42), (68, 70)], 20
    elif case_id == "edge_of_FOV":
        centers, radius, roi_radius = [(3, 48)], 12, 15
    target_center = centers[0]
    labels = np.zeros(SHAPE, dtype=np.uint8)
    identity = np.full(SHAPE, 20.0)
    for label, (cy, cx) in enumerate(centers, 1):
        support = (y - cy) ** 2 + (x - cx) ** 2 <= radius ** 2
        labels[support] = label
        identity += 900 * _gaussian(y, x, cy, cx, 5.0)
    cy, cx = target_center
    roi = (y - cy) ** 2 + (x - cx) ** 2 <= roi_radius ** 2
    target = (y - cy) ** 2 + (x - cx) ** 2 <= radius ** 2
    puncta_centers = [(44, 44), (44, 53), (53, 43), (53, 53)]
    puncta = np.zeros(SHAPE, dtype=bool)
    diffuse = 40 + 90 * _gaussian(y, x, cy, cx, 10.0)
    phenotype = diffuse.copy()
    if case_id in {"puncta_rich", "exposure_change"}:
        for py, px in puncta_centers:
            phenotype += 1200 * _gaussian(y, x, py, px, 1.1)
            puncta |= (y - py) ** 2 + (x - px) ** 2 <= 2 ** 2
    else:
        puncta_centers = []
    reference = np.stack([np.full(SHAPE, 20.0), phenotype, identity]).astype(np.float32)
    challenged = reference.copy()
    flat = np.ones_like(reference)
    parameters = {
        "case_id": case_id, "evidence_type": "SYNTHETIC_CHALLENGE",
        "seed": seed, "shape_cyx": [3, *SHAPE], "dtype": "float32",
        "channel_order": ["405", "561", "488"], "intensity_units": "synthetic_ADU",
        "coordinate_units": "pixels", "centers_yx": [list(p) for p in centers],
        "target_center_yx": list(target_center), "soma_truth_radius_px": radius,
        "roi_radius_px": roi_radius, "identity_gaussian_sigma_px": 5.0,
        "identity_peak_above_background_ADU": 900.0,
        "identity_background_ADU": 20.0, "phenotype_background_ADU": 40.0,
        "diffuse_gaussian_sigma_px": 10.0,
        "puncta_centers_yx": [list(p) for p in puncta_centers],
        "puncta_gaussian_sigma_px": 1.1, "puncta_truth_radius_px": 2,
        "noise_sigma_ADU": 0.0, "exposure_factor_561": 1.0,
        "independent_physical_calibration": False,
        "human_review_status": "NOT_PERFORMED",
    }
    if case_id == "low_488_nonblank":
        rng = np.random.default_rng(seed)
        noise_sigma = 6.0
        challenged[2] = (20 + 18 * _gaussian(y, x, cy, cx, 5.0)
                          + rng.normal(0, noise_sigma, SHAPE)).astype(np.float32)
        parameters.update(noise_sigma_ADU=noise_sigma,
                          challenged_identity_peak_above_background_ADU=18.0,
                          nominal_peak_signal_to_noise=3.0,
                          snr_definition="noise-free peak above background / Gaussian noise SD")
    elif case_id == "exposure_change":
        challenged[1] *= 2.0
        parameters["exposure_factor_561"] = 2.0
    elif case_id == "illumination_gradient":
        field = np.broadcast_to(np.linspace(0.65, 1.35, SHAPE[1]), SHAPE)
        flat = np.broadcast_to(field, reference.shape).astype(np.float32).copy()
        challenged = reference * flat
        parameters.update(flatfield_min=0.65, flatfield_max=1.35,
                          flatfield_model="known synthetic detector-x multiplicative field")
    full_y, full_x = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    full_support_area = int(np.count_nonzero(full_y ** 2 + full_x ** 2 <= radius ** 2))
    visible_target_area = int(target.sum())
    contributors = sorted(int(v) for v in np.unique(labels[roi]) if v)
    expected = {
        "case_id": case_id, "evidence_type": "SYNTHETIC_TRUTH_ONLY",
        "roi_contributor_labels": contributors,
        "roi_has_multiple_contributors": len(contributors) > 1,
        "target_full_support_area_px": full_support_area,
        "target_visible_support_area_px": visible_target_area,
        "target_visible_support_fraction": visible_target_area / full_support_area,
        "puncta_truth_count": len(puncta_centers),
        "expected_human_approval": "NOT_ASSIGNED",
        "production_detector_result": "NOT_COMPUTED_BY_FIXTURE_GENERATOR",
        "limitation": "Synthetic construction does not prove real longitudinal identity or calibration accuracy.",
    }
    if case_id == "low_488_nonblank":
        expected["review_instruction"] = "Inspect low SNR. A numerical match alone cannot establish identity."
    elif len(contributors) > 1:
        expected["review_instruction"] = "The prescribed ROI contains multiple synthetic contributors; it is not a clean single-soma ROI."
    elif case_id == "edge_of_FOV":
        expected["review_instruction"] = "Partial support is known. Do not interpret clipped support as a phenotype change."
    elif case_id == "exposure_change":
        expected["review_instruction"] = "561 intensity doubles at unchanged geometry. Illumination correction is not exposure correction."
    elif case_id == "illumination_gradient":
        expected["review_instruction"] = "The supplied exact synthetic field reverses this constructed field only."
    else:
        expected["review_instruction"] = "Inspect the supplied known phenotype support without inferring a biological mechanism."
    return {
        "cyx": challenged.astype(np.float32), "reference_cyx": reference,
        "labels": labels, "target_mask": target, "phenotype_roi": roi,
        "puncta_truth_mask": puncta, "flatfield_cyx": flat,
        "parameters": parameters, "expected_result": expected,
    }
