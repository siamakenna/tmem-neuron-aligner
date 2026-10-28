"""Production observers preserve quantitative results and expose real branches."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import make_soma_anchored_bbox_movies_v2 as soma
import render_curated_neuron_phenotypes as curated
from tmem_align.audit_v1.fixtures import neuron_fixture
from tmem_align.audit_v1.stage_trace import StageTrace, verify_trace


class RecordingTrace:
    """Inspect observer calls without substituting a scientific implementation."""
    def __init__(self):
        self.records = {}

    def capture(self, name, array=None, **metadata):
        if name in self.records:
            raise AssertionError("Duplicate processing stage: " + name)
        if any(parent not in self.records for parent in metadata.get("parents", ())):
            raise AssertionError("Child precedes processing parent: " + name)
        value = dict(metadata)
        value["array"] = None if array is None else np.array(array, copy=True)
        self.records[name] = value
        return value


def soma_image(size=128):
    yy, xx = np.mgrid[:size, :size]
    cy = cx = size // 2
    image = 100 + 3000 * np.exp(-((yy-cy)**2 + (xx-cx)**2) / (2*8**2))
    image += 180 * np.exp(-((yy-cy+4)**2 + (xx-cx-4)**2) / 7)
    return np.rint(image).astype(np.uint16)


def same_metadata(test, left, right):
    test.assertEqual(set(left), set(right))
    for name in left:
        a, b = left[name], right[name]
        if isinstance(a, float) and np.isnan(a):
            test.assertTrue(np.isnan(b), name)
        else:
            test.assertEqual(a, b, name)


class AdaptiveSegmentationTracing(unittest.TestCase):
    def test_actual_threshold_morphology_and_selection_are_observed_without_pixel_change(self):
        image = soma_image()
        before = image.copy()
        plain, plain_metadata = soma.segment_neuron_in_box(image, 64, 64, 128, 180)
        trace = RecordingTrace()
        observed, observed_metadata = soma.segment_neuron_in_box(
            image, 64, 64, 128, 180, trace=trace, trace_prefix="visit08")
        np.testing.assert_array_equal(observed, plain)
        np.testing.assert_array_equal(image, before)
        same_metadata(self, observed_metadata, plain_metadata)
        for suffix in ["raw_488", "crop", "normalized", "smoothed", "segmentation_seed",
                       "allowed_region", "selected_component", "mask"]:
            self.assertIn("visit08_" + suffix, trace.records)
        candidate_names = [n for n in trace.records if n.endswith("_threshold")]
        self.assertGreater(len(candidate_names), 1)
        self.assertIn("visit08_candidate_00_components", trace.records)
        self.assertEqual(trace.records["visit08_normalized"]["details"]["array_role"], "normalized_intensity")
        np.testing.assert_array_equal(trace.records["visit08_mask"]["array"], observed)
        self.assertFalse(trace.records["visit08_mask"]["details"]["scientific_acceptance_granted"])

    def test_blank_signal_retains_its_actual_failure_and_prior_stages(self):
        image = np.zeros((128, 128), np.uint16)
        trace = RecordingTrace()
        with self.assertRaisesRegex(RuntimeError, "Insufficient local 488 signal"):
            soma.segment_neuron_in_box(image, 64, 64, 128, 180, trace=trace)
        failure = trace.records["segmentation_failure"]
        self.assertEqual(failure["status"], "failed")
        self.assertIsNone(failure["array"])
        self.assertIn("segmentation_smoothed", trace.records)
        self.assertEqual(int(image.sum()), 0)

    def test_component_scoring_explains_distance_rejection_of_a_neighbor(self):
        yy, xx = np.mgrid[:128, :128]
        centered = (yy-64)**2 + (xx-64)**2 <= 9**2
        neighbor = (yy-64)**2 + (xx-106)**2 <= 9**2
        binary = centered | neighbor
        trace = RecordingTrace()
        trace.capture("trial_threshold", binary, parents=(), why="Prescribed two-component unit input")
        candidate = soma._candidate_from_binary(binary, binary.astype(np.float32), 64, 64,
            None, None, trace=trace, trace_prefix="trial")
        self.assertIsNotNone(candidate)
        self.assertTrue(candidate[1][64, 64])
        self.assertFalse(candidate[1][64, 106])
        scores = trace.records["trial_selection"]["details"]["components"]
        self.assertEqual(len(scores), 2)
        self.assertTrue(any(row.get("rejected") and "nearest>18px" in row.get("reason", "") for row in scores))

    def test_supplied_spatial_prior_is_recorded_without_modifying_it(self):
        image = soma_image()
        prior, first_metadata = soma.segment_neuron_in_box(image, 64, 64, 128, 180)
        frozen = prior.copy()
        kwargs = dict(ref_area=first_metadata["segmentation_area"], prior_mask=prior, prior_source="unit_previous_valid")
        plain, _ = soma.segment_neuron_in_box(image, 64, 64, 128, 180, **kwargs)
        trace = RecordingTrace()
        observed, _ = soma.segment_neuron_in_box(image, 64, 64, 128, 180, trace=trace, **kwargs)
        np.testing.assert_array_equal(observed, plain)
        np.testing.assert_array_equal(prior, frozen)
        np.testing.assert_array_equal(trace.records["segmentation_prior_core"]["array"], frozen)
        self.assertEqual(trace.records["segmentation_prior_core"]["details"]["prior_source"], "unit_previous_valid")


class CuratedTracing(unittest.TestCase):
    def track(self):
        return pd.DataFrame([dict(day=day, time_index=i, anchor_y=64.0, anchor_x=64.0,
                                  bbox_y0=0, bbox_x0=0, tracking_valid=True)
                             for i, day in enumerate([8, 12, 16])])

    def boxes(self):
        image = soma_image()
        cyx = np.stack([np.zeros_like(image), np.full_like(image, 700), image])
        return np.stack([cyx] * 3)

    def test_reconstruction_keeps_the_same_masks_and_qc_decisions(self):
        boxes, rows = self.boxes(), self.track()
        plain = curated.reconstruct_masks(boxes, rows, 2, 128, 180)
        trace = RecordingTrace()
        observed = curated.reconstruct_masks(boxes, rows, 2, 128, 180, trace=trace)
        np.testing.assert_array_equal(observed[0], plain[0])
        np.testing.assert_array_equal(observed[1], plain[1])
        pd.testing.assert_frame_equal(observed[2], plain[2])
        self.assertEqual(len([n for n in trace.records if n.endswith("_qc")]), 3)
        self.assertTrue(np.any(observed[1]))

    def test_evidence_io_failure_does_not_turn_into_an_invalid_scientific_mask(self):
        class FailedTrace:
            def capture(self, *args, **kwargs):
                raise OSError("deliberate evidence write failure")
        with self.assertRaisesRegex(soma.SegmentationTraceError, "deliberate evidence write failure"):
            curated.reconstruct_masks(self.boxes(), self.track(), 2, 128, 180, trace=FailedTrace())

    def test_consensus_records_votes_and_preserves_the_three_valid_mask_gate(self):
        yy, xx = np.mgrid[:128, :128]
        mask = (yy-64)**2 + (xx-64)**2 <= 11**2
        masks = np.stack([mask] * 4)
        plain = curated.build_tight_identity_core(masks, [True] * 4, .6, 80, 2500)
        trace = RecordingTrace()
        observed = curated.build_tight_identity_core(masks, [True] * 4, .6, 80, 2500, trace=trace)
        np.testing.assert_array_equal(observed[0], plain[0])
        self.assertEqual(observed[1:], plain[1:])
        self.assertEqual(int(trace.records["identity_core_vote_count"]["array"].max()), 4)
        self.assertEqual(len(trace.records["identity_core_vote_count"]["parents"]), 4)
        blocked = RecordingTrace()
        with self.assertRaisesRegex(RuntimeError, ">=3 valid 488 masks"):
            curated.build_tight_identity_core(masks, [True, True, False, False], .6, 80, 2500, trace=blocked)
        self.assertEqual(blocked.records["identity_core_failure"]["details"]["minimum_valid_masks"], 3)

    def test_phenotype_observes_exact_background_dog_partition_without_changing_it(self):
        cyx, _, roi = neuron_fixture()
        raw = cyx[1].copy()
        plain = curated.quantify_phenotype(raw, roi, 8, 6)
        trace = RecordingTrace()
        observed = curated.quantify_phenotype(raw, roi, 8, 6, trace=trace)
        same_metadata(self, plain[0], observed[0])
        for left, right in zip(plain[1:], observed[1:]):
            np.testing.assert_array_equal(left, right)
        np.testing.assert_array_equal(trace.records["phenotype_diffuse_support"]["array"] |
                                      trace.records["phenotype_puncta_filtered"]["array"], roi)
        np.testing.assert_array_equal(raw, cyx[1])
        self.assertEqual(trace.records["phenotype_dog"]["details"]["array_role"], "dog_response")

    def test_empty_phenotype_roi_is_preserved_as_failure(self):
        trace = RecordingTrace()
        with self.assertRaisesRegex(RuntimeError, "Phenotype ROI is empty"):
            curated.quantify_phenotype(np.ones((32, 32)), np.zeros((32, 32), bool), 8, 6, trace=trace)
        self.assertEqual(trace.records["phenotype_failure"]["status"], "failed")


class TrackingTracing(unittest.TestCase):
    def test_template_and_bounded_match_parity_with_known_translation(self):
        image = soma_image(256)
        before = image.copy()
        trace = RecordingTrace()
        plain_template = soma.make_template(image, 128, 128, 33)
        template = soma.make_template(image, 128, 128, 33, trace=trace, trace_prefix="day08")
        np.testing.assert_array_equal(template, plain_template)
        moving = np.zeros_like(image)
        moving[3:, :-4] = image[:-3, 4:]
        plain = soma.track_anchor(moving, template, 128, 128, 12)
        observed = soma.track_anchor(moving, template, 128, 128, 12, trace=trace, trace_prefix="day12")
        np.testing.assert_allclose(observed, plain, rtol=0, atol=0)
        np.testing.assert_allclose(observed[:2], [131, 124], atol=1)
        np.testing.assert_array_equal(image, before)
        self.assertLess(trace.records["day12_raw_search"]["array"].size, image.size)
        self.assertEqual(trace.records["day12_correlation"]["details"]["array_role"], "correlation")
        self.assertFalse(trace.records["day12_chosen_peak"]["details"]["stored_anchor_overwritten"])

    def test_undersized_search_retains_undefined_score_and_a_failed_stage(self):
        image = np.arange(64, dtype=np.float32).reshape(8, 8)
        template = np.ones((9, 9), np.float32)
        trace = RecordingTrace()
        actual = soma.track_anchor(image, template, 4, 4, 2, trace=trace)
        self.assertEqual(actual[:2], (4.0, 4.0))
        self.assertTrue(np.isnan(actual[2]))
        self.assertEqual(trace.records["tracking_failure"]["status"], "failed")

    def test_real_recorder_writes_source_bound_segmentation_arrays(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "observed"
            trace = StageTrace(root, metadata={"evidence_type": "SYNTHETIC_UNIT_TEST"})
            actual, _ = soma.segment_neuron_in_box(soma_image(), 64, 64, 128, 180, trace=trace)
            trace.finish({"scientific_acceptance_granted": False})
            checked = verify_trace(root)
            self.assertTrue(checked)
            saved = np.load(root / "stages/segmentation_mask/array.npy", allow_pickle=False)
            np.testing.assert_array_equal(saved, actual)
            self.assertTrue((root / "index.html").is_file())


class SecondarySomaTracing(unittest.TestCase):
    parameters = dict(search_radius=52.0, min_distance=14, peak_ratio_threshold=.55,
                      area_ratio_threshold=.30, score_threshold=.40)

    def test_actual_primary_secondary_support_and_scores_preserve_the_screen_result(self):
        yy, xx = np.mgrid[:128, :128]
        reference = np.exp(-((yy-64)**2 + (xx-64)**2) / (2*6**2))
        reference += .8 * np.exp(-((yy-64)**2 + (xx-96)**2) / (2*6**2))
        reference = reference.astype(np.float32)
        frozen = reference.copy()
        plain = curated.screen_secondary_soma(reference, **self.parameters)
        trace = RecordingTrace()
        observed = curated.screen_secondary_soma(reference, trace=trace, **self.parameters)
        same_metadata(self, vars(plain), vars(observed))
        np.testing.assert_array_equal(reference, frozen)
        for suffix in ["reference_488", "smoothed", "search_region", "peak_candidates",
                       "primary_peak", "primary_support", "selected_secondary"]:
            self.assertIn("secondary_soma_" + suffix, trace.records)
        result = trace.records["secondary_soma_selected_secondary"]["details"]
        same_metadata(self, result["screen_result"], vars(observed))
        self.assertFalse(result["scientific_acceptance_granted"])
        self.assertFalse(result["roi_ownership_validated"])
        eligible = [row for row in result["candidate_scores"] if row["eligible"]]
        self.assertGreater(len(eligible), 0)
        self.assertAlmostEqual(eligible[0]["score"],
                               eligible[0]["peak_ratio"] * np.sqrt(eligible[0]["area_ratio"]))

    def test_empty_peak_fallback_is_explicit_and_never_claims_exclusive_ownership(self):
        reference = np.zeros((128, 128), np.float32)
        trace = RecordingTrace()
        plain = curated.screen_secondary_soma(reference, **self.parameters)
        observed = curated.screen_secondary_soma(reference, trace=trace, **self.parameters)
        same_metadata(self, vars(plain), vars(observed))
        peak = trace.records["secondary_soma_peak_candidates"]["details"]
        self.assertEqual(peak["detected_peak_count"], 0)
        self.assertTrue(peak["crop_center_fallback_used"])
        selected = trace.records["secondary_soma_selected_secondary"]
        self.assertEqual(selected["status"], "skipped")
        self.assertIsNone(selected["array"])
        self.assertFalse(selected["details"]["roi_ownership_validated"])

    def test_small_search_preserves_failure_and_exposes_the_failed_guard(self):
        trace = RecordingTrace()
        with self.assertRaisesRegex(RuntimeError, "search region too small"):
            curated.screen_secondary_soma(np.ones((8, 8), np.float32), trace=trace,
                                          **self.parameters)
        self.assertEqual(trace.records["secondary_soma_failure"]["status"], "failed")
        self.assertEqual(trace.records["secondary_soma_failure"]["details"]["minimum_search_pixels"], 100)


if __name__ == "__main__":
    unittest.main()
