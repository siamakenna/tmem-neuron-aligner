"""Integrity and truthfulness checks for generated SVG workflow graphics."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from tmem_align.audit_v1.stage_trace import StageTrace

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("graphic_renderer", ROOT / "scripts/render_pipeline_flowcharts.py")
graphics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graphics)


class PipelineFlowcharts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def trace(self):
        path = self.root / "trace"
        record = StageTrace(path, metadata=dict(invoked_mode="registered-track", coordinate_system="registered_common_overlap",
                                               title='<script>alert("x")</script>'))
        record.capture("visit_00_registered_488", np.arange(16, dtype=np.uint16).reshape(4, 4),
                       channel="488", why="CONTROL FIXTURE: not original ND2 data.")
        record.capture("segmentation_normalized", np.ones((4, 4)), channel="488",
                       why="CONTROL numerical-stage observation.")
        record.capture("historical_ic", why="Original raw sources unavailable.", status="unavailable")
        record.finish()
        return path

    def test_design_graphics_are_real_svg_and_never_claim_execution(self):
        out = self.root / "graphics"
        result = graphics.render(out)
        for name in ["original_ND2_to_well.svg", "segmentation_tracking.svg"]:
            ET.parse(out / name)
            text = (out / name).read_text()
            self.assertIn("WORKFLOW DESIGN", text)
            self.assertIn("Unavailable in supplied evidence", text)
            self.assertNotIn("data:image", text)
        self.assertFalse(result["original_nd2_pipeline_validated"])
        self.assertTrue((out / "index.html").is_file())

    def test_registered_trace_previews_remain_registered_not_original_nd2(self):
        trace = self.trace()
        original = (trace / "stages/visit_00_registered_488/array.npy").read_bytes()
        out = self.root / "graphics"
        result = graphics.render(out, trace=trace)
        self.assertTrue(result["trace_integrity_verified"])
        self.assertEqual(result["trace_input_kind"], "registered_inputs_declared")
        self.assertFalse(result["original_nd2_source_recorded"])
        self.assertFalse(result["original_nd2_pipeline_validated"])
        self.assertIn("Original ND2 read", result["unavailable_categories"])
        self.assertIn("data:image/png;base64,", (out / "segmentation_tracking.svg").read_text())
        self.assertEqual((trace / "stages/visit_00_registered_488/array.npy").read_bytes(), original)

    def test_tampered_preview_blocks_graphic_output(self):
        trace = self.trace()
        (trace / "stages/visit_00_registered_488/preview.png").write_bytes(b"corrupted")
        out = self.root / "graphics"
        with self.assertRaisesRegex(ValueError, "changed"):
            graphics.render(out, trace=trace)
        self.assertFalse(out.exists())

    def test_missing_trace_does_not_create_invented_panels(self):
        out = self.root / "graphics"
        with self.assertRaises(ValueError):
            graphics.render(out, trace=self.root / "missing")
        self.assertFalse(out.exists())

    def test_svg_escapes_supplied_text(self):
        evidence = graphics.trace_evidence()
        svg = graphics.build_svg('<script>& "label"', [("n", 440, 190, "<name>", "x & y")], [], evidence)
        ET.fromstring(svg)
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;&amp;", svg)
        self.assertIn("x &amp; y", svg)

    def test_output_is_new_and_evidence_json_has_no_embedded_fake_pixels(self):
        out = self.root / "graphics"
        graphics.render(out)
        with self.assertRaises(FileExistsError):
            graphics.render(out)
        result = json.loads((out / "flowchart_provenance.json").read_text())
        self.assertEqual(result["previews"], [])
        self.assertEqual(result["real_accepted_ids"], [])
        self.assertFalse(result["scientific_inference_ready"])

    def test_preview_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            graphics._safe_artifact(self.root, "../outside.png")

    def test_png_export_has_graphic_dimensions_and_no_fake_original_pixels(self):
        from PIL import Image
        out = self.root / "graphics"
        result = graphics.render(out, raster=True)
        self.assertIn("original_ND2_to_well.png", result["graphic_files"])
        with Image.open(out / "original_ND2_to_well.png") as image:
            self.assertEqual(image.width, 2400)
            self.assertGreater(image.height, 3000)
            self.assertNotEqual(image.getpixel((1000,450)), image.getpixel((0,0)))
        self.assertFalse(result["original_nd2_pipeline_validated"])

    def test_recorded_nd2_metadata_does_not_assert_a_validated_experiment(self):
        path = self.root / "nd2_trace"
        recorder = StageTrace(path, metadata=dict(invoked_mode="nd2-well",
            inputs=[dict(path="original.nd2", sha256="a"*64)]))
        recorder.capture("nd2_read_tile", np.ones((4,4)), why="CONTROL FIXTURE; no real ND2 was read.")
        recorder.finish()
        result = graphics.trace_evidence(path)
        self.assertTrue(result["original_nd2_source_recorded"])
        self.assertFalse(result["original_nd2_pipeline_validated"])

    def test_current_raw_pair_nested_nd2_provenance_and_reference_panels(self):
        path = self.root / "current_pair"
        recorder = StageTrace(path, metadata=dict(mode="raw-pair", channels=["405", "561", "488"],
            supplied_input_provenance=dict(inputs=[dict(path="original.nd2", sha256="b"*64)])))
        a = np.ones((3,4,4), dtype=np.uint16)
        recorder.capture("reference_preprocess_00_before_ic", a, axes="CYX", channel="488", why="CONTROL FIXTURE")
        recorder.capture("moving_preprocess_00_before_ic", a*2, axes="CYX", channel="488", why="CONTROL FIXTURE")
        recorder.capture("reference_preprocess_03_after_ic_float", a.astype(float), axes="CYX", channel="488", why="CONTROL FIXTURE")
        recorder.capture("registered_moving_cyx", a, axes="CYX", channel="488", why="CONTROL FIXTURE")
        recorder.finish()
        result = graphics.trace_evidence(path)
        self.assertEqual(result["trace_mode"], "raw-pair")
        self.assertTrue(result["original_nd2_source_recorded"])
        stages = {p["category"]:p["stage"] for p in result["previews"]}
        self.assertEqual(stages["Original ND2 read"], "reference_preprocess_00_before_ic")
        self.assertEqual(stages["Before IC"], "reference_preprocess_00_before_ic")
        self.assertEqual(stages["After IC"], "reference_preprocess_03_after_ic_float")
        self.assertEqual(stages["Alignment / registered input"], "registered_moving_cyx")
        self.assertFalse(result["original_nd2_pipeline_validated"])


if __name__ == "__main__":
    unittest.main()
