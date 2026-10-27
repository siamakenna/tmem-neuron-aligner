"""Configuration contracts and actual production-path software integration.

Synthetic fixtures below test software, not biological validation. Production
IC, registration, segmentation, tracking, core and phenotype calls are unmocked.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from tmem_align.audit_v1.pipeline_diagnostics import (
    DAYS, DEFAULT_CONFIG, StageTrace, file_record, load_config,
    trace_raw_pair, trace_registered_track, verify_trace)

ROOT = Path(__file__).resolve().parents[2]


class PipelineDiagnosticConfig(unittest.TestCase):
    def test_checked_in_configuration_matches_code_defaults(self):
        self.assertEqual(load_config(ROOT / "configs/tmem_stage_diagnostics.json"), DEFAULT_CONFIG)

    def test_unknown_keys_rejected(self):
        for cfg in [{"min_are": 180}, {"segmentation": {"min_are": 180}},
                    {"luts": {"488": {"hgh": 4095}}}]:
            with self.assertRaises(ValueError):
                load_config(cfg)

    def test_merge_does_not_modify_caller_or_defaults(self):
        supplied = {"segmentation": {"min_area": 220}}
        before = copy.deepcopy(supplied)
        cfg = load_config(supplied)
        cfg["tracking"]["search_radius"] = 40
        self.assertEqual(supplied, before)
        self.assertEqual(load_config()["tracking"]["search_radius"], 60)

    def test_invalid_ranges_and_booleans_rejected(self):
        cases = [{"segmentation": {"min_area": True}}, {"tracking": {"template_size": 40}},
                 {"tracking": {"search_radius": 0}}, {"tracking": {"min_score": float("nan")}},
                 {"registration": {"robust_preprocess": 1}},
                 {"registration": {"mask_percentile": 100}},
                 {"registration": {"robust_preprocess": True, "mask_percentile": 20}},
                 {"segmentation": {"min_core_area": 90, "max_core_area": 80}},
                 {"segmentation": {"phenotype_dilation": 9}}]
        for cfg in cases:
            with self.assertRaises(ValueError):
                load_config(cfg)

    def test_grid_cost_is_bounded_and_declared(self):
        cases = [{"sensitivity": {"segmentation_min_area": [180, 180]}},
                 {"sensitivity": {"tracking_search_radius": [80, 40]}},
                 {"sensitivity": {"tracking_search_radius": []}},
                 {"sensitivity": {"segmentation_min_area": list(range(1, 8)),
                                  "tracking_search_radius": [40, 60, 80]}}]
        for cfg in cases:
            with self.assertRaises(ValueError):
                load_config(cfg)
        self.assertEqual(load_config()["sensitivity"]["segmentation_min_area"], [140, 180, 220])

    def test_raw_LUT_and_crop_contracts(self):
        cases = [{"bbox_size": 64}, {"schema_version": "unknown"},
                 {"luts": {"488": {"low": 4095, "high": 0}}},
                 {"luts": {"561": {"high": 70000}}},
                 {"lut_box": {"range_policy": "arbitrary"}}]
        for cfg in cases:
            with self.assertRaises(ValueError):
                load_config(cfg)

    def test_shared_observer_not_duplicate_implementation(self):
        from tmem_align.audit_v1 import stage_trace
        self.assertIs(StageTrace, stage_trace.StageTrace)
        self.assertIs(verify_trace, stage_trace.verify_trace)

    def test_secondary_soma_defaults_and_bounded_ratio_pixel_contracts(self):
        self.assertEqual(load_config()["secondary_soma"], dict(search_radius=52.0, min_distance=14,
            peak_ratio_threshold=.55, area_ratio_threshold=.30, score_threshold=.40))
        for values in [{"search_radius": 0}, {"min_distance": 60},
                       {"peak_ratio_threshold": -1}, {"area_ratio_threshold": True},
                       {"score_threshold": float("inf")}, {"min_distnce": 14}]:
            with self.assertRaises(ValueError):
                load_config({"secondary_soma": values})

    def test_source_file_hash_and_unlinked_file_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "input.npy"
            p.write_bytes(b"first")
            a = file_record(p)
            p.write_bytes(b"second")
            self.assertNotEqual(a["sha256"], file_record(p)["sha256"])
            link = Path(tmp) / "linked.npy"
            link.symlink_to(p)
            with self.assertRaises(ValueError):
                file_record(link)


class PipelineDiagnosticIntegration(unittest.TestCase):
    # These are required production integrations. Missing dependencies must
    # fail their execution; unit-only runs can select PipelineDiagnosticConfig.
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tmem_diagnostic_integration_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def numeric(self, root, manifest, stage):
        record = next(s for s in manifest["stages"] if s["stage"] == stage)
        return np.load(root / record["artifacts"]["numeric"]["path"], allow_pickle=False)

    def compact(self, **extra):
        return load_config(dict(sensitivity={"segmentation_min_area": [180],
                                             "tracking_search_radius": [60]}, **extra))

    def raw_fixture(self):
        yy, xx = np.mgrid[:96, :96]
        bead = (1800*np.exp(-((yy-37)**2+(xx-53)**2)/70)
                + 800*np.exp(-((yy-65)**2+(xx-31)**2)/45))
        truth = np.stack([50+bead*.2, 70+bead*.7, 100+bead]).astype(np.uint16)
        moved = np.roll(truth, shift=(3, -4), axis=(-2, -1))
        field = np.broadcast_to(np.linspace(.6, 1.4, 96), (96, 96)).copy()
        return truth, np.rint(truth*field+10).astype(np.uint16), np.rint(moved*field+10).astype(np.uint16), field

    def test_raw_pair_IC_then_registration_known_shift_and_channel_independence(self):
        truth, ref, mov, field = self.raw_fixture()
        before = [ref.copy(), mov.copy()]
        out = self.root / "pair"
        manifest = trace_raw_pair(ref, mov, out, flatfield=field,
            flatfield_coordinate_system="detector", darkfield=10,
            config={"registration": {"mask_percentile": None, "robust_preprocess": False}})
        verify_trace(out)
        np.testing.assert_allclose(manifest["summary"]["shift_dy_dx_px"], [-3, 4], atol=.2)
        np.testing.assert_allclose(self.numeric(out, manifest, "preprocessed_reference_cyx"), truth, atol=1)
        self.assertGreater(manifest["summary"]["correlation_488_after"], .99)
        self.assertGreater(manifest["summary"]["correlation_488_after"], manifest["summary"]["correlation_488_before"])
        self.assertFalse(manifest["summary"]["historical_pipeline_reproduced"])
        self.assertFalse(manifest["summary"]["production_eligible"])
        for a, b in zip([ref, mov], before):
            np.testing.assert_array_equal(a, b)
        self.assertFalse(list(out.glob("*.csv")))

    def test_raw_pair_rejects_unbound_invalid_field_and_blank488_before_output(self):
        _, ref, mov, field = self.raw_fixture()
        for supplied, coordinates in [(field, None), (field, "registered"), (np.zeros_like(field), "detector")]:
            out = self.root / "invalid"
            with self.assertRaises(ValueError):
                trace_raw_pair(ref, mov, out, flatfield=supplied, flatfield_coordinate_system=coordinates)
            self.assertFalse(out.exists())
        ref[2] = 0
        with self.assertRaises(ValueError):
            trace_raw_pair(ref, mov, self.root / "blank")

    def track_fixture(self, blank=False):
        import pandas as pd
        yy, xx = np.mgrid[:192, :192]
        soma = 2400*np.exp(-((yy-96)**2/170+(xx-96)**2/220))
        frame = np.stack([np.full_like(soma, 40), 100+.5*soma, 70+soma]).astype(np.uint16)
        if blank:
            frame[:] = 0
        stack, rows = np.stack([frame.copy() for _ in DAYS]), []
        for i, day in enumerate(DAYS):
            rows.append(dict(neuron_id="J05_N015", well="J05", day=day, time_index=i,
                anchor_y=96., anchor_x=96., bbox_y0=32, bbox_y1=160, bbox_x0=32, bbox_x1=160,
                tracking_valid=True, template_match_score=.9))
            rows.append(dict(neuron_id="J05_N099", well="J05", day=day, time_index=i,
                anchor_y=145., anchor_x=145., tracking_valid=True, template_match_score=.8))
        return stack, pd.DataFrame(rows)

    def test_registered_production_path_preserves_inputs_and_does_not_rewarp(self):
        stack, master = self.track_fixture()
        original, table = stack.copy(), master.copy(deep=True)
        out = self.root / "track"
        manifest = trace_registered_track(stack, master, "J05_N015", out)
        verify_trace(out)
        self.assertTrue(manifest["summary"]["core_constructed"])
        self.assertTrue(manifest["summary"]["secondary_soma_screen_performed"])
        self.assertTrue(manifest["summary"]["secondary_soma_screen_is_informational_only"])
        self.assertFalse(manifest["summary"]["registration_reapplied"])
        self.assertEqual(manifest["real_accepted_ids"], [])
        self.assertEqual(manifest["summary"]["software_execution_status"], "completed")
        statuses = {s["stage"]: s["status"] for s in manifest["stages"]}
        for name in ["historical_raw_input", "historical_ic_before_after", "historical_stitching", "historical_registration"]:
            self.assertEqual(statuses[name], "unavailable")
        self.assertTrue(self.numeric(out, manifest, "phenotype_roi_holes_filled").any())
        np.testing.assert_array_equal(stack, original)
        self.assertTrue(master.equals(table))
        proposals = json.loads((out / "display_only_lut_bbox_proposals.json").read_text())
        self.assertTrue(all(p["display_only"] and not p["adopted"] for p in proposals))
        tracking = json.loads((out / "tracking_comparison.json").read_text())
        self.assertTrue(tracking["all_proposals_unadopted"])
        self.assertEqual(set(tracking["results_by_radius"]), {"40", "60", "80"})
        self.assertEqual(len(tracking["results_by_radius"]["60"]), 9)
        sensitivity = json.loads((out / "parameter_sensitivity.json").read_text())
        self.assertEqual([s["segmentation_min_area_px"] for s in sensitivity["settings"]], [140, 180, 220])
        self.assertTrue(sensitivity["no_best_setting_selected"])
        self.assertTrue(all(not s["adopted"] for s in sensitivity["settings"]))
        from tmem_align.audit_v1.reference import renderer
        r = renderer()
        reference = r.build_reference_488(stack[:, :, 32:160, 32:160], 2,
            np.asarray([manifest["summary"]["valid_488_by_day"][str(day)] for day in DAYS]))
        expected = vars(r.screen_secondary_soma(reference, **load_config()["secondary_soma"]))
        actual = json.loads((out / "secondary_soma_screen.json").read_text())
        for key, value in expected.items():
            if isinstance(value, float) and not np.isfinite(value):
                self.assertIsNone(actual[key])
            else:
                self.assertEqual(actual[key], value)
        self.assertFalse(list(out.rglob("accepted*metrics*.csv")))

    def test_core_rejection_keeps_gallery_and_failed_stages_without_phenotype(self):
        stack, master = self.track_fixture(blank=True)
        out = self.root / "rejected"
        manifest = trace_registered_track(stack, master, "J05_N015", out, config=self.compact())
        self.assertEqual(manifest["summary"]["diagnostic_status"], "diagnostic_rejected")
        self.assertFalse(manifest["summary"]["core_constructed"])
        self.assertFalse(manifest["summary"]["secondary_soma_screen_performed"])
        self.assertEqual(json.loads((out / "secondary_soma_screen.json").read_text())["status"], "skipped")
        self.assertFalse(manifest["successful_execution"])
        self.assertEqual(json.loads((out / "diagnostic_phenotype_metrics.json").read_text()), [])
        self.assertTrue((out / "index.html").is_file())
        self.assertTrue(any(s["status"] == "failed" for s in manifest["stages"]))
        verify_trace(out)

    def test_LUT_changes_do_not_change_quantitative_geometry_or_phenotype(self):
        stack, master = self.track_fixture()
        first, second = self.root / "a", self.root / "b"
        a = trace_registered_track(stack, master, "J05_N015", first, config=self.compact())
        b = trace_registered_track(stack, master, "J05_N015", second,
            config=self.compact(luts={"488": {"low": 200, "high": 1500}, "561": {"low": 50, "high": 1800}}))
        for stage in ["primary_identity_core", "phenotype_roi_holes_filled"]:
            np.testing.assert_array_equal(self.numeric(first, a, stage), self.numeric(second, b, stage))
        self.assertEqual(json.loads((first / "diagnostic_phenotype_metrics.json").read_text()),
                         json.loads((second / "diagnostic_phenotype_metrics.json").read_text()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
