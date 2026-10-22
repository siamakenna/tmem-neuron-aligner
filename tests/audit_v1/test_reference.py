"""Required microscopy integrations. Missing dependencies FAIL; never silently skip."""
import unittest

import numpy as np

from tmem_align.audit_v1.fixtures import illumination_fixture, neuron_fixture
from tmem_align.audit_v1.reference import (
    alignment_steps, phenotype_steps, preprocess_steps, renderer,
)


class PreprocessingIntegration(unittest.TestCase):
    def test_known_ic_before_after(self):
        raw, field, dark = illumination_fixture()
        out, stages, qc = preprocess_steps(raw, flatfield=field, darkfield=dark)
        np.testing.assert_allclose(out, 1000, atol=1)
        self.assertTrue(qc["reference_exact_match"])
        np.testing.assert_array_equal(stages["01_before_ic"], raw)

    def test_round_and_clip_only_at_end(self):
        raw = np.array([[1, 3, 65535]], dtype=np.uint16)
        out, stages, _ = preprocess_steps(raw, flatfield=np.array([[2., 2., .5]]))
        np.testing.assert_array_equal(out, [[0, 2, 65535]])
        np.testing.assert_array_equal(stages["03_after_ic_float"], [[.5, 1.5, 131070]])

    def test_ic_then_background_parity(self):
        raw, field, dark = illumination_fixture()
        _, _, qc = preprocess_steps(raw, flatfield=field, darkfield=dark, background_radius=5)
        self.assertTrue(qc["reference_exact_match"])

    def test_multichannel_independence(self):
        raw, field, _ = illumination_fixture()
        a = np.stack([raw, raw, raw]); b = a.copy(); b[1] *= 10
        x, _, _ = preprocess_steps(a, flatfield=np.stack([field] * 3))
        y, _, _ = preprocess_steps(b, flatfield=np.stack([field] * 3))
        np.testing.assert_array_equal(x[2], y[2])

    def test_noop_preserves_float_dtype(self):
        a = np.ones((8, 8), np.float32) * .75
        out, _, _ = preprocess_steps(a)
        self.assertEqual(out.dtype, a.dtype)
        np.testing.assert_array_equal(out, a)

    def test_invalid_ic_rejected(self):
        with self.assertRaises(ValueError):
            preprocess_steps(np.ones((8, 8)), flatfield=np.zeros((8, 8)))


class AlignmentIntegration(unittest.TestCase):
    def test_translation_sign_and_channel_separation(self):
        from tmem_align.register import apply_shift
        ref, mov, _ = neuron_fixture()
        aligned, _, qc = alignment_steps(ref, mov)
        np.testing.assert_allclose([qc["dy"], qc["dx"]], [-4, 6], atol=1)
        self.assertTrue(qc["qc_pass"])
        np.testing.assert_array_equal(aligned[1], apply_shift(mov[1], qc["dy"], qc["dx"]))
        ref2, mov2 = ref.copy(), mov.copy()
        ref2[1] = np.random.default_rng(8).uniform(0, 65535, ref2[1].shape)
        mov2[1] = np.fliplr(ref2[1])
        aligned2, _, qc2 = alignment_steps(ref2, mov2)
        self.assertEqual((qc["dy"], qc["dx"]), (qc2["dy"], qc2["dx"]))
        self.assertEqual(qc["common_bounds"], qc2["common_bounds"])
        np.testing.assert_array_equal(aligned[2], aligned2[2])

    def test_blank_488_rejected_even_with_bright_mcherry(self):
        ref, mov, _ = neuron_fixture(); mov[2] = 0; mov[1] = 60000
        with self.assertRaises(ValueError): alignment_steps(ref, mov)

    def test_large_translation_guard(self):
        ref, mov, _ = neuron_fixture()
        with self.assertRaises(ValueError): alignment_steps(ref, mov, max_shift=2)

    def test_anchored_stack_mcherry_invariance(self):
        from scripts.run_260213_longitudinal_pilot import register_stack
        ref, mov, _ = neuron_fixture()
        a = np.stack([ref, mov, ref]); b = a.copy()
        b[:, 1] = np.random.default_rng(41).uniform(0, 60000, b[:, 1].shape)
        kwargs = dict(well="J05", rows=[{"day": d} for d in [8, 12, 16]],
                      alignment_channel_index=2, alignment_channel_label="488",
                      robust_crop=False, ref_mode="anchored")
        x, qx, cx = register_stack(a, **kwargs); y, qy, cy = register_stack(b, **kwargs)
        # Each YX plane is shifted independently: 488 pixels must be identical.
        np.testing.assert_array_equal(x[:, 2], y[:, 2])
        self.assertEqual(cx, cy)
        for u, v in zip(qx, qy):
            for key in ["estimated_y_shift", "estimated_x_shift", "qc_pass", "anchor_ref_day"]:
                self.assertEqual(u[key], v[key])


class PhenotypeIntegration(unittest.TestCase):
    def test_puncta_diffuse_partition_and_expected_positions(self):
        raw, _, roi = neuron_fixture()
        (metrics, puncta, diffuse, _), stages = phenotype_steps(raw[1], roi)
        self.assertEqual(metrics["puncta_count"], 3)
        for y, x in [(44, 41), (51, 56), (39, 55)]:
            self.assertTrue(puncta[y, x])
        self.assertFalse(np.any(puncta & diffuse))
        np.testing.assert_array_equal(puncta | diffuse, roi)
        self.assertGreaterEqual(stages["05_puncta_candidates"].sum(), puncta.sum())

    def test_empty_roi_fails(self):
        raw, _, roi = neuron_fixture()
        with self.assertRaises(ValueError): phenotype_steps(raw[1], np.zeros_like(roi))

    def test_three_visit_consensus_and_missing_visit_gate(self):
        _, _, mask = neuron_fixture()
        r = renderer(); masks = np.stack([mask] * 4)
        core, required, nvalid, _ = r.build_tight_identity_core(masks, [True] * 4, .6, 80, 2500)
        np.testing.assert_array_equal(core, mask)
        self.assertEqual((required, nvalid), (3, 4))
        with self.assertRaises(RuntimeError):
            r.build_tight_identity_core(masks, [True, True, False, False], .6, 80, 2500)


if __name__ == "__main__":
    unittest.main()
