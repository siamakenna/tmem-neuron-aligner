"""Quantitative observation, artifact integrity and explicit missing-stage tests."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

import numpy as np
from PIL import Image

from tmem_align.audit_v1.display import LUT
from tmem_align.audit_v1.stage_trace import StageTrace, array_sha256, capture, verify_trace


class StageTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tmem_stage_trace_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "trace"

    def recorder(self, **kwargs):
        return StageTrace(self.root, metadata={"coordinate_system": "registered_common_overlap",
            "channels": ["405", "561", "488"]}, **kwargs)

    def test_round_trip_numeric_arrays_graph_and_explanation(self):
        image = np.arange(30, dtype=np.uint16).reshape(5, 6)
        trace = self.recorder(luts={"488": LUT(0, 30, "488")})
        first = trace.capture("raw", image, why="Preserve the exact input pixels.")
        mask = image > 10
        second = trace.capture("mask", mask, parents=["raw"], why="Expose the threshold support.",
                               parameters={"threshold_adu": 10})
        manifest = trace.finish({"comparison": "software diagnostic only"})
        np.testing.assert_array_equal(np.load(self.root / first["artifacts"]["numeric"]["path"]), image)
        self.assertEqual(verify_trace(self.root), manifest)
        self.assertEqual(second["preview"]["mode"], "boolean-mask")
        self.assertIn("s0 --> s1", (self.root / "processing_flow.mmd").read_text())
        page = (self.root / "index.html").read_text()
        self.assertIn("Preserve the exact input pixels.", page)
        self.assertIn("array.npy", page)
        self.assertFalse(manifest["scientific_inference_ready"])
        self.assertEqual(manifest["real_accepted_ids"], [])

    def test_saved_stage_is_snapshot_and_does_not_mutate_input(self):
        image = np.arange(12, dtype=np.float32).reshape(3, 4)
        before = image.copy()
        trace = self.recorder()
        record = trace.capture("raw", image, why="Observe an input without modifying it.")
        np.testing.assert_array_equal(image, before)
        image[:] = -1
        stored = np.load(self.root / record["artifacts"]["numeric"]["path"])
        np.testing.assert_array_equal(stored, before)
        trace.finish()

    def test_lut_changes_only_preview_and_not_numeric_hash(self):
        image = np.arange(20, dtype=np.uint16).reshape(4, 5)
        a = self.recorder(luts={"488": LUT(0, 20, "488")})
        b = StageTrace(Path(self.temp.name) / "other", luts={"488": LUT(10, 1000, "488")})
        x = a.capture("raw", image, why="Render a fixed quantitative input.")
        y = b.capture("raw", image, why="Render the same quantitative input with another LUT.")
        self.assertEqual(x["array_sha256"], y["array_sha256"])
        self.assertEqual(x["artifacts"]["numeric"]["sha256"], y["artifacts"]["numeric"]["sha256"])
        self.assertNotEqual(x["artifacts"]["preview"]["sha256"], y["artifacts"]["preview"]["sha256"])

    def test_nonexecuted_stages_are_explicit_and_have_no_fake_arrays(self):
        trace = self.recorder()
        for name, status in [("raw_ic", "unavailable"), ("optional_bg", "skipped"), ("tracking", "failed")]:
            record = trace.capture(name, why="The required historical input was not provided.", status=status)
            self.assertEqual(record["artifacts"], {})
        manifest = trace.finish()
        self.assertFalse(manifest["successful_execution"])
        self.assertFalse(list(self.root.rglob("*.npy")))
        verify_trace(self.root)

    def test_unavailable_stage_cannot_contain_an_invented_before_after(self):
        trace = self.recorder()
        for status in ["unavailable", "skipped"]:
            with self.assertRaises(ValueError):
                trace.capture(status, np.ones((3, 4)), why="Missing stage.", status=status)

    def test_executed_requires_numeric_output_and_actual_purpose(self):
        trace = self.recorder()
        with self.assertRaises(ValueError):
            trace.capture("empty", why="No input was supplied.")
        with self.assertRaises(ValueError):
            trace.capture("purposeless", np.ones((3, 4)))

    def test_names_parents_and_status_reject_ambiguous_graphs(self):
        trace = self.recorder()
        image = np.ones((3, 4))
        for name in ["../escape", "/absolute", "with/slash", "", ".."]:
            with self.assertRaises(ValueError):
                trace.capture(name, image, why="Unsafe name.")
        with self.assertRaises(ValueError):
            trace.capture("first", image, parents=["later"], why="Invalid parent order.")
        trace.capture("first", image, why="An actual first stage.")
        with self.assertRaises(ValueError):
            trace.capture("first", image, why="Duplicate stage.")
        with self.assertRaises(ValueError):
            trace.capture("second", image, parents=["first", "first"], why="Duplicate ancestry.")
        with self.assertRaises(ValueError):
            trace.capture("badstatus", image, why="Unknown status.", status="approved")

    def test_numeric_type_axes_and_nonfinite_rejected_without_partial_stage(self):
        trace = self.recorder()
        cases = [(np.array([[object()]], dtype=object), "YX"),
                 (np.ones((2, 3), complex), "YX"), (np.array([[np.nan]]), "YX"),
                 (np.array([[np.inf]]), "YX"), (np.ones((2, 3)), "CYX"),
                 (np.ones((2, 3)), "XY"), (np.empty((0, 4)), "YX")]
        for array, axes in cases:
            with self.assertRaises(ValueError):
                trace.capture("bad", array, axes=axes, why="Invalid numeric input.")
        self.assertEqual(list((self.root / "stages").iterdir()), [])

    def test_multichannel_preview_uses_explicit_channel_and_first_time(self):
        image = np.zeros((2, 3, 4, 5), np.uint16)
        image[0, 2] = 500
        image[1, 2] = 900
        image[:, 1] = 1000
        trace = self.recorder(luts={"488": LUT(0, 1000, "488")})
        record = trace.capture("stack", image, axes="TCYX", channel="488", why="Expose one declared plane.")
        preview = np.asarray(Image.open(self.root / record["artifacts"]["preview"]["path"]))
        np.testing.assert_array_equal(preview[..., 1], np.full((4, 5), 128, np.uint8))
        self.assertEqual(record["preview"]["selection"], {"time_index": 0, "channel_index": 2, "channel_label": "488"})
        self.assertFalse(record["preview"]["projection_performed"])
        stored = np.load(self.root / record["artifacts"]["numeric"]["path"])
        np.testing.assert_array_equal(stored, image)

    def test_unknown_or_ambiguous_preview_channel_is_rejected(self):
        trace = self.recorder()
        with self.assertRaises(ValueError):
            trace.capture("unknown", np.ones((3, 4, 5)), axes="CYX", channel="other", why="Unknown channel.")
        self.assertEqual(list((self.root / "stages").iterdir()), [])

    def test_component_labels_are_categorical_not_intensity(self):
        labels = np.array([[0, 1, 2], [0, 3, 4]], dtype=np.int32)
        trace = self.recorder()
        record = trace.capture("components", labels, why="Expose separate segmentation components.",
                               details={"array_role": "component_labels"})
        self.assertEqual(record["preview"]["mode"], "categorical-label-colors-display-only")
        self.assertIsNone(record["preview"]["lut"])
        pixels = np.asarray(Image.open(self.root / record["artifacts"]["preview"]["path"]))
        np.testing.assert_array_equal(pixels[0, 0], [0, 0, 0])
        self.assertFalse(np.array_equal(pixels[0, 1], pixels[0, 2]))

    def test_declared_normalized_correlation_and_IC_fields_have_semantic_LUTs(self):
        trace = self.recorder(luts={"488": LUT(0, 5000, "488"),
                                   "IC_field": LUT(.5, 1.5, "gray")})
        cases = [("normalized_intensity", np.array([[0., .5, 1.]]), (0, 1)),
                 ("correlation", np.array([[-1., 0., 1.]]), (-1, 1)),
                 ("illumination_field", np.array([[.5, 1., 1.5]]), (.5, 1.5))]
        for role, image, expected in cases:
            record = trace.capture(role, image, why="Expose a dimensionless diagnostic.",
                                   details={"array_role": role})
            self.assertEqual((record["preview"]["lut"]["low"],
                              record["preview"]["lut"]["high"]), expected)
        raw = trace.capture("raw", np.array([[0, 2500, 5000]], np.uint16), why="Preserve fixed raw488 LUT.")
        self.assertEqual(raw["preview"]["lut"]["high"], 5000)

    def test_signed_responses_show_negative_values_without_changing_quantitative_data(self):
        trace = self.recorder(luts={"488": LUT(0, 4095, "488"),
                                   "DoG": LUT(-100, 100, "gray")})
        for name, role, values, expected in [
                ("zscore", "signed_response", [-2., 0., 2.], (-4, 4)),
                ("explicit", "signed_response", [-2., 0., 2.], (-2, 2)),
                ("dog", "dog_response", [-100., 0., 100.], (-100, 100))]:
            array = np.array([values], np.float64)
            details = {"array_role": role}
            if name == "explicit":
                details["display_range"] = [-2, 2]
            record = trace.capture(name, array, why="Expose the signed algorithm response.", details=details)
            self.assertEqual((record["preview"]["lut"]["low"], record["preview"]["lut"]["high"]), expected)
            preview = np.asarray(Image.open(self.root / record["artifacts"]["preview"]["path"]))
            channel = 1 if role == "signed_response" else 0
            self.assertLess(preview[0, 0, channel], preview[0, 1, channel])
            self.assertLess(preview[0, 1, channel], preview[0, 2, channel])
            np.testing.assert_array_equal(np.load(self.root / record["artifacts"]["numeric"]["path"]), array)
        with self.assertRaises(ValueError):
            trace.capture("bad_signed", np.ones((2, 3)), why="Reject an invalid range.",
                          details={"array_role": "signed_response", "display_range": [4, -4]})

    def test_consensus_counts_use_explicit_valid_mask_range(self):
        trace = self.recorder(luts={"488": LUT(0, 4095, "488")})
        counts = np.array([[0, 3, 6]], np.uint16)
        record = trace.capture("consensus_support", counts, why="Show mask votes per pixel.",
            details={"array_role": "support_count", "display_range": [0, 6]})
        self.assertEqual(record["preview"]["lut"]["high"], 6)
        preview = np.asarray(Image.open(self.root / record["artifacts"]["preview"]["path"]))
        np.testing.assert_array_equal(preview[..., 1], [[0, 128, 255]])
        with self.assertRaises(ValueError):
            trace.capture("missing_total", counts, why="Reject an unspecified count range.",
                          details={"array_role": "support_count"})

    def test_numeric_hash_binds_shape_dtype_values_but_not_strides(self):
        array = np.arange(12, dtype=np.uint16).reshape(3, 4)
        self.assertEqual(array_sha256(array), array_sha256(np.asfortranarray(array)))
        self.assertNotEqual(array_sha256(array), array_sha256(array.reshape(4, 3)))
        self.assertNotEqual(array_sha256(array), array_sha256(array.astype(np.uint32)))

    def test_artifact_corruption_inventory_and_links_fail_verification(self):
        trace = self.recorder()
        record = trace.capture("raw", np.ones((3, 4)), why="Bind raw evidence.")
        trace.finish()
        path = self.root / record["artifacts"]["numeric"]["path"]
        original = path.read_bytes()
        path.write_bytes(original + b"changed")
        with self.assertRaises(ValueError):
            verify_trace(self.root)
        path.write_bytes(original)
        extra = self.root / "extra.txt"
        extra.write_text("unbound")
        with self.assertRaises(ValueError):
            verify_trace(self.root)
        extra.unlink()
        backup = Path(self.temp.name) / "outside.npy"
        backup.write_bytes(original)
        path.unlink()
        path.symlink_to(backup)
        with self.assertRaises(ValueError):
            verify_trace(self.root)

    def test_stage_document_and_manifest_record_must_agree(self):
        trace = self.recorder()
        trace.capture("raw", np.ones((3, 4)), why="Bind the actual stage rationale.")
        trace.finish()
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["stages"][0]["why"] = "Invented rationale"
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            verify_trace(self.root)

    def test_diagnostic_manifest_cannot_grant_track_acceptance(self):
        trace = self.recorder()
        trace.finish()
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["real_accepted_ids"] = ["E05_N006"]
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            verify_trace(self.root)

    def test_root_cannot_overwrite_and_finished_trace_is_immutable(self):
        trace = self.recorder()
        with self.assertRaises(FileExistsError):
            self.recorder()
        trace.finish()
        with self.assertRaises(ValueError):
            trace.capture("later", np.ones((2, 3)), why="Late mutation.")
        with self.assertRaises(ValueError):
            trace.finish()

    def test_optional_hook_without_trace_is_a_noop(self):
        class ForbiddenArray:
            def __array__(self):
                raise AssertionError("Disabled diagnostics must not touch data")
        self.assertIsNone(capture(None, "stage", ForbiddenArray()))

    def test_replaceable_observer_cannot_normalize_scientific_pixels_in_place(self):
        class DisplayStub:
            def capture(self, name, array, **kwargs):
                array[:] = 0
                return name
        image = np.arange(12, dtype=np.float32).reshape(3, 4)
        before = image.copy()
        self.assertEqual(capture(DisplayStub(), "observed", image), "observed")
        np.testing.assert_array_equal(image, before)

    def test_html_escapes_user_text(self):
        trace = self.recorder()
        trace.capture("raw", np.ones((2, 3)), why="<script>alert('bad')</script>")
        trace.finish()
        html = (self.root / "index.html").read_text()
        # The gallery has its own fixed filter script. Supplied text must
        # remain escaped and cannot become a second executable script.
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("alert('bad')", html)
        self.assertEqual(html.count("<script>"), 1)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
