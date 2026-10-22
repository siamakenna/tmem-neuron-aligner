#!/usr/bin/env python3
"""Exercise unchanged scientific functions on nine bounded synthetic challenges.

Outputs are measured algorithm responses, not human approval or validation of
real identity. Detector misses and numerical QC failures are recorded findings.
Unexpected software exceptions and 561-to-identity leakage fail this execution.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from types import SimpleNamespace
import traceback

import numpy as np

from tmem_align.audit_v1.display import LUT, apply_lut_for_display, make_qc_panel
from tmem_align.audit_v1.evidence import write_json
from tmem_align.audit_v1.parameters import build_resolved_parameters
from tmem_align.audit_v1.stress_fixtures import CASE_IDS, DEFAULT_SEED, stress_fixture

DISPLACEMENT_YX = (4, -6)
ALIGNMENT_PARAMETERS = {"max_shift": 20, "min_correlation": 0.07}
SOMA_PARAMETERS = {"search_radius": 52.0, "min_distance": 14,
                   "peak_ratio_threshold": 0.55, "area_ratio_threshold": 0.30,
                   "score_threshold": 0.40}
SEGMENTATION_MIN_AREA = 180
PHENOTYPE_PARAMETERS = {"background_exclusion": 8, "puncta_min_size": 6}
HANDLED_SEGMENTATION_PREFIXES = (
    "Empty 488 search region", "Insufficient local 488 signal",
    "Insufficient 488 foreground", "No plausible 488 component",
)


def production_backend():
    from tmem_align.audit_v1.reference import alignment_steps, phenotype_steps, renderer
    reference = renderer()
    return SimpleNamespace(alignment_steps=alignment_steps, phenotype_steps=phenotype_steps,
                           segment_neuron_in_box=reference.segment_neuron_in_box,
                           screen_secondary_soma=reference.screen_secondary_soma,
                           robust01=reference.robust01)


def translated(array, dy, dx):
    """Exact zero-padded integer fixture displacement, with no wraparound."""
    result = np.zeros_like(array)
    height, width = array.shape[-2:]
    src_y, src_x = slice(max(0, -dy), min(height, height-dy)), slice(max(0, -dx), min(width, width-dx))
    dst_y, dst_x = slice(max(0, dy), min(height, height+dy)), slice(max(0, dx), min(width, width+dx))
    result[..., dst_y, dst_x] = array[..., src_y, src_x]
    return result


def edge(mask):
    padded = np.pad(mask, 1)
    interior = padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    return mask & ~interior


def overlap_record(mask, labels, target):
    contributors = {str(int(value)): int(np.count_nonzero(mask & (labels == value)))
                    for value in np.unique(labels) if value and np.any(mask & (labels == value))}
    union = int(np.count_nonzero(mask | target))
    return {"mask_area_px": int(mask.sum()), "truth_contributor_overlap_px": contributors,
            "target_truth_iou": float(np.count_nonzero(mask & target)/union) if union else None}


def _alignment(backend, reference, moving):
    try:
        aligned, stages, qc = backend.alignment_steps(reference, moving, **ALIGNMENT_PARAMETERS)
        return {"execution": "computed", "qc": qc}, aligned, stages
    except ValueError as error:
        message = str(error)
        if "exceeds max_shift_pixels" not in message and "Uninformative 488" not in message:
            raise
        return {"execution": "handled_qc_rejection", "reason": message}, None, {}


def _segment(backend, image, anchor, *, ref_area=None, prior=None):
    try:
        mask, metadata = backend.segment_neuron_in_box(
            image, float(anchor[0]), float(anchor[1]), image.shape[0], SEGMENTATION_MIN_AREA,
            ref_area=ref_area, prior_mask=prior,
            prior_source="synthetic_reference_488" if prior is not None else "none")
        return {"execution": "computed", "metadata": metadata}, np.asarray(mask, dtype=bool)
    except RuntimeError as error:
        if not str(error).startswith(HANDLED_SEGMENTATION_PREFIXES):
            raise
        return {"execution": "handled_qc_rejection", "reason": str(error)}, np.zeros(image.shape, bool)


def exercise_case(case_id, out, *, seed=DEFAULT_SEED, backend=None):
    """Run the real alignment, adaptive mask, soma screen and phenotype functions."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    backend = backend or production_backend()
    fixture = stress_fixture(case_id, seed=seed)
    arrays = {name: value for name, value in fixture.items() if isinstance(value, np.ndarray)}
    original = {name: hashlib.sha256(value.tobytes()).hexdigest() for name, value in arrays.items()}
    image, reference = fixture["cyx"], fixture["reference_cyx"]
    roi, labels, truth_target = fixture["phenotype_roi"], fixture["labels"], fixture["target_mask"]
    moving = translated(image, *DISPLACEMENT_YX)
    np.savez_compressed(out / "input_and_truth.npz", **arrays, translated_moving_cyx=moving)
    write_json(out / "parameters.json", {
        "fixture": fixture["parameters"], "source_parameters": "../source_parameters.json",
        "benchmark_invocation": {"alignment": ALIGNMENT_PARAMETERS,
            "moving_displacement_yx_px": DISPLACEMENT_YX,
            "expected_registration_shift_yx_px": [-DISPLACEMENT_YX[0], -DISPLACEMENT_YX[1]],
            "adaptive_bbox_size_px": int(image.shape[-1]),
            "adaptive_min_area_px": SEGMENTATION_MIN_AREA, "secondary_soma": SOMA_PARAMETERS,
            "phenotype": PHENOTYPE_PARAMETERS,
            "phenotype_roi_source": "Prescribed 488 synthetic truth ROI. NOT the production adaptive mask.",
            "soma_reference": "robust01 of one synthetic frame; no longitudinal median is asserted",
            "scope": "96px synthetic benchmark calls. Normal curated review crops remain128px unchanged."}})
    observed = {"case_id": case_id, "execution_status": "running", "evidence_type": "SYNTHETIC_PRODUCTION_RESPONSE",
                "production_detector_result": "COMPUTED_BELOW",
                "manual_review": "NOT_PERFORMED", "accepted_for_biological_analysis": False,
                "construction_truth": {key: value for key, value in fixture["expected_result"].items()
                                       if key != "production_detector_result"}, "findings": []}
    try:
        alignment, aligned, stages = _alignment(backend, reference, moving)
        alt_ref, alt_mov = reference.copy(), moving.copy()
        rng = np.random.default_rng(seed+1)
        alt_ref[1] = rng.uniform(0, 65535, alt_ref[1].shape)
        alt_mov[1] = rng.uniform(0, 65535, alt_mov[1].shape)
        counterfactual, alt_aligned, _ = _alignment(backend, alt_ref, alt_mov)
        if alignment["execution"] != counterfactual["execution"]:
            raise AssertionError("Changing561 altered488 registration rejection/computation")
        if aligned is None and alignment.get("reason") != counterfactual.get("reason"):
            raise AssertionError("Changing561 altered488 registration rejection details")
        if aligned is not None:
            for name in ["dy", "dx", "common_bounds"]:
                if alignment["qc"][name] != counterfactual["qc"][name]:
                    raise AssertionError("Changing561 altered488 transform or overlap")
            np.testing.assert_array_equal(aligned[2], alt_aligned[2], err_msg="561 altered aligned488 pixels")
            shift_error = float(np.hypot(alignment["qc"]["dy"]+DISPLACEMENT_YX[0],
                                        alignment["qc"]["dx"]+DISPLACEMENT_YX[1]))
            alignment["known_truth_shift_error_px"] = shift_error
            if not alignment["qc"].get("qc_pass") or shift_error > 1.0:
                observed["findings"].append({"observation": "registration_qc_failed_or_wrong_synthetic_shift",
                                             "suggested_review_category": "new_QC_condition"})
        else:
            observed["findings"].append({"observation": "registration_rejected_by_existing_guard",
                                         "suggested_review_category": "expected_handled"})
        alignment["changing561_preserves488_transform_and_pixels"] = True
        observed["alignment"] = alignment
        write_json(out / "observations.json", observed)
        if stages:
            np.savez_compressed(out / "alignment_stages.npz", **stages)
        identity_lut = LUT(0, 1000, "488", scope="shared-synthetic-alignment-comparison", source="explicit0..1000")
        make_qc_panel([apply_lut_for_display(reference[2], identity_lut),
                       apply_lut_for_display(moving[2], identity_lut),
                       apply_lut_for_display(aligned[2] if aligned is not None else np.zeros_like(image[2]), identity_lut)],
                      ["Reference488", "Moved challenged488", "Aligned488 or rejected"], cell=192).save(out / "alignment.png")

        baseline, prior = _segment(backend, reference[2], fixture["parameters"]["target_center_yx"])
        ref_area = baseline.get("metadata", {}).get("segmentation_area") if baseline["execution"] == "computed" else None
        segmentation, mask = _segment(backend, image[2], fixture["parameters"]["target_center_yx"],
                                      ref_area=ref_area, prior=prior if prior.any() else None)
        segmentation["reference_segmentation"] = baseline
        segmentation["overlap_with_construction_truth"] = overlap_record(mask, labels, truth_target)
        screen = backend.screen_secondary_soma(backend.robust01(image[2]), **SOMA_PARAMETERS)
        screen_record = dict(vars(screen))
        known_multiple = len(fixture["expected_result"]["roi_contributor_labels"]) > 1
        screen_record["known_prescribed_roi_multiple_contributors"] = known_multiple
        screen_record["screen_passed_despite_known_roi_contamination"] = bool(known_multiple and screen.single_soma_pass)
        if screen_record["screen_passed_despite_known_roi_contamination"]:
            observed["findings"].append({"observation": "soma_screen_missed_known_roi_contamination",
                                         "suggested_review_category": "new_QC_condition"})
        if segmentation["execution"] == "handled_qc_rejection":
            observed["findings"].append({"observation": "adaptive_segmentation_rejected_synthetic_input",
                                         "suggested_review_category": "expected_handled"})
        if fixture["expected_result"]["target_visible_support_fraction"] < 1.0:
            observed["findings"].append({"observation": "known_partial_soma_support",
                                         "suggested_review_category": "scientific_limitation"})
        observed["adaptive_segmentation"] = segmentation
        observed["secondary_soma_screen"] = screen_record
        np.savez_compressed(out / "segmentation_stages.npz", production_adaptive_mask=mask,
                            reference_adaptive_mask=prior, truth_soma_labels=labels, truth_target=truth_target,
                            prescribed_truth_phenotype_roi=roi)
        display488 = LUT(0, 60 if case_id == "low_488_nonblank" else 1000, "488",
                         scope="synthetic-case-diagnostic", source="explicit range, see numeric parameters")
        raw488 = apply_lut_for_display(image[2], display488)
        truth_view, detected_view = raw488.copy(), raw488.copy()
        truth_view[edge(roi)] = [255, 255, 255]
        truth_view[edge(truth_target)] = [0, 180, 255]
        detected_view[edge(mask)] = [255, 180, 0]
        make_qc_panel([raw488, truth_view, detected_view],
                      ["488 challenged", "TRUTH target + ROI", "Production adaptive mask"], cell=192).save(out / "segmentation.png")
        write_json(out / "observations.json", observed)

        reference_result, _ = backend.phenotype_steps(reference[1], roi, **PHENOTYPE_PARAMETERS)
        result, phenotype_stages = backend.phenotype_steps(image[1], roi, **PHENOTYPE_PARAMETERS)
        metrics, puncta, diffuse, corrected = result
        reference_metrics = reference_result[0]
        if not np.isclose(metrics["total_mcherry_intensity"],
                          metrics["punctate_mcherry_integrated_intensity"]+metrics["diffuse_mcherry_integrated_intensity"],
                          rtol=1e-10, atol=1e-5):
            raise AssertionError("Production phenotype partition failed quantitative conservation")
        truth_count = int(fixture["expected_result"]["puncta_truth_count"])
        observed["phenotype"] = {"production_detector_result": "COMPUTED",
            "roi_source": "Prescribed 488-truth benchmark mask, independent of561 and adaptive output",
            "metrics": metrics, "reference_metrics": reference_metrics,
            "declared_puncta_truth_count": truth_count,
            "detected_puncta_count": int(metrics["puncta_count"]),
            "detected_count_matches_constructed_truth": int(metrics["puncta_count"]) == truth_count,
            "intensity_partition_conserved": True,
            "reference_to_challenged_total_ratio": float(metrics["total_mcherry_intensity"]/reference_metrics["total_mcherry_intensity"])
                if reference_metrics["total_mcherry_intensity"] > 0 else None}
        if int(metrics["puncta_count"]) != truth_count:
            observed["findings"].append({"observation": "puncta_detector_count_differs_from_constructed_truth",
                                         "suggested_review_category": "new_QC_condition"})
        np.savez_compressed(out / "phenotype_stages.npz", **phenotype_stages)
        lut561 = LUT(0, 2600 if case_id in {"puncta_rich", "exposure_change"} else 200, "561",
                     scope="fixed-within-synthetic-case", source="explicit diagnostic range")
        raw561 = apply_lut_for_display(image[1], lut561)
        overlay = raw561.copy()
        overlay[puncta] = [255, 255, 0]
        overlay[edge(roi)] = [255, 255, 255]
        make_qc_panel([raw561, overlay, apply_lut_for_display(corrected*diffuse, lut561)],
                      ["561 challenged", "Production puncta + TRUTH ROI", "Production diffuse residual"], cell=192).save(out / "phenotype.png")
        if any(hashlib.sha256(value.tobytes()).hexdigest() != original[name] for name, value in arrays.items()):
            raise AssertionError("Production challenge execution mutated quantitative fixture inputs")
        observed["input_array_sha256"] = original
        observed["quantitative_inputs_unchanged"] = True
        observed["production_detector_result"] = "COMPUTED"
        observed["execution_status"] = "executed_with_recorded_observations"
        write_json(out / "observations.json", observed)
        return observed
    except Exception as error:
        observed["execution_status"] = "unexpected_software_error"
        observed["error"] = f"{type(error).__name__}: {error}"
        write_json(out / "observations.json", observed)
        (out / "traceback.txt").write_text(traceback.format_exc())
        raise


def generate(out, *, seed=DEFAULT_SEED, case_ids=CASE_IDS, backend=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1]
    reference_parameters = build_resolved_parameters(source, dict(
        bbox_size=128, identity_consensus_fraction=.60, phenotype_dilation=2,
        segmentation_min_area=180, min_core_area=80, max_core_area=2500,
        background_exclusion=8, puncta_min_size=6))
    write_json(out / "source_parameters.json", {
        "scope": "Source-derived normal128px curated reference parameters. Exact96px benchmark invocation is recorded per case. No consensus/tracking identity is validated here.",
        "reference_algorithm": reference_parameters,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    records = []
    for case_id in case_ids:
        try:
            result = exercise_case(case_id, out / case_id, seed=seed, backend=backend)
            records.append({"case_id": case_id, "execution_status": result["execution_status"],
                            "findings_count": len(result["findings"]),
                            "observations": f"{case_id}/observations.json"})
        except Exception as error:
            folder = out / case_id
            folder.mkdir(exist_ok=True)
            if not (folder / "observations.json").exists():
                write_json(folder / "observations.json", {"case_id": case_id,
                    "execution_status": "unexpected_software_error",
                    "error": f"{type(error).__name__}: {error}",
                    "accepted_for_biological_analysis": False, "manual_review": "NOT_PERFORMED"})
            if not (folder / "traceback.txt").exists():
                (folder / "traceback.txt").write_text(traceback.format_exc())
            records.append({"case_id": case_id, "execution_status": "unexpected_software_error",
                            "error": f"{type(error).__name__}: {error}",
                            "observations": f"{case_id}/observations.json"})
    errors = sum(record["execution_status"] == "unexpected_software_error" for record in records)
    report = {"schema_version": "tmem.production_stress_execution.v1", "cases_executed": len(records),
              "unexpected_software_errors": errors, "execution_complete": errors == 0,
              "status": "execution_complete_with_observations" if not errors else "failed_software_execution",
              "detector_misses_are_reported_not_tuned_away": True,
              "human_review": "PENDING", "accepted_for_biological_analysis": False, "cases": records}
    write_json(out / "status.json", report)
    cards = []
    for record in records:
        name = html.escape(record["case_id"])
        section = f'<section><h2>{name}</h2><p>{html.escape(record["execution_status"])}</p>'
        section += f'<p><a href="{record["observations"]}">Measured outputs and truth comparison</a></p>'
        for filename in ["alignment.png", "segmentation.png", "phenotype.png"]:
            if (out / record["case_id"] / filename).is_file():
                section += f'<img src="{record["case_id"]}/{filename}" alt="{name} {filename}">'
        cards.append(section+'</section>')
    (out / "index.html").write_text('''<!doctype html><meta charset="utf-8"><title>TMEM production stress responses</title>
<style>body{background:#102127;color:white;font:18px system-ui;padding:30px;max-width:1200px;margin:auto}a{color:#70ead8}img{max-width:100%;image-rendering:pixelated}section{margin:35px 0}</style>
<h1>Measured production responses to synthetic challenges</h1>
<p>Unchanged alignment, adaptive segmentation, secondary-soma screening and phenotype functions run on declared synthetic inputs. Detector misses and QC failures are observations, not hidden successes. Software exceptions fail execution. No track or biological claim is accepted.</p>
<p>Phenotype uses a prescribed488-truth benchmark ROI, independent of561 and separate from the measured adaptive mask.</p>'''+"".join(cards))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--case", dest="case_ids", choices=CASE_IDS, nargs="+",
                        help="Run the named challenge(s); omitted means all nine")
    args = parser.parse_args()
    report = generate(args.out, seed=args.seed,
                      case_ids=tuple(args.case_ids) if args.case_ids else CASE_IDS)
    print(f"Production stress cases executed: {report['cases_executed']}; unexpected software errors: {report['unexpected_software_errors']}")
    print("Detector/QC observations require review. No scientific acceptance is assigned.")
    return 1 if report["unexpected_software_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
