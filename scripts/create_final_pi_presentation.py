#!/usr/bin/env python3
"""Create an editable private PI deck from verified, already executed evidence.

Optional reporting tool: requires python-pptx and Pillow, not package runtime
dependencies. No image-processing algorithm or scientific decision is executed.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

DAYS = (8, 12, 16, 20, 25, 29, 32, 36, 39)
PAIRS = (("E05", "F05"), ("I05", "J05"), ("M05", "N05"))
NAVY, MUTED, TEAL, BLUE, LILAC, RED = "182D45", "526477", "267C80", "547CA3", "8B79AA", "B45D58"
BG, LINE, GREEN = "FAFBFD", "D8E1E9", "4C925E"
FONT = "Arial"
NAME = "TMEM106B_Final_PI_Meeting_Draft_20261103"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(root, reference):
    root, p = Path(root).absolute(), Path(reference)
    p = p if p.is_absolute() else root / p
    if ".." in p.parts:
        raise ValueError("Traversal in source reference")
    for item in (p, *p.parents):
        if item.is_symlink():
            raise ValueError("Symlink source/output is forbidden")
    if not p.resolve().is_relative_to(root.resolve()):
        raise ValueError("Source escapes declared project")
    if not p.is_file():
        raise ValueError("Missing source: " + str(p))
    return p


def boolean(v):
    if v not in ("True", "False"):
        raise ValueError("Expected explicit Boolean")
    return v == "True"


def number(v):
    if isinstance(v, bool):
        raise TypeError("Boolean is not a measurement")
    x = float(v)
    if not math.isfinite(x):
        raise ValueError("Nonfinite measurement")
    return x


def grid(rows, ids, settings, key):
    expected = {(n, d, s) for n in ids for d in DAYS for s in settings}
    actual = [
        (r["neuron_id"], int(r["day"]), int(r[key]) if key != "policy" else r[key]) for r in rows
    ]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Incomplete or duplicate comparison grid")
    for r in rows:
        if boolean(r["adopted"]):
            raise ValueError("Adopted alternatives cannot enter this diagnostic deck")


def svg_slots(data, count):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("SVG entities forbidden")
    result = {}
    for node in ET.fromstring(data).iter():
        if node.tag.rsplit("}", 1)[-1] in ("script", "foreignObject"):
            raise ValueError("Executable SVG content forbidden")
        if node.tag.rsplit("}", 1)[-1] != "image":
            continue
        href = node.get("href", "")
        if not href.startswith("data:image/png;base64,"):
            raise ValueError("External or unsupported SVG image")
        x, y = number(node.get("x")), number(node.get("y"))
        col, row = int((x - 24) // 330), int((y - 158) // 430)
        index = row * 5 + col
        if not (0 <= col < 5 and 0 <= index < count) or index in result:
            raise ValueError("Duplicate or invalid SVG card slot")
        blob = base64.b64decode(href.split(",", 1)[1], validate=True)
        with Image.open(io.BytesIO(blob)) as image:
            if image.format != "PNG":
                raise ValueError("Expected PNG card")
            image.verify()
        result[index] = blob
    return result


class Evidence:
    def __init__(self, project):
        for p in (Path(project).absolute(), *Path(project).absolute().parents):
            if p.is_symlink():
                raise ValueError("Symlink project forbidden")
        self.project = Path(project).resolve()
        self.bound = {}
        self.fig = self.project / "actual-fov-evidence-20261103/figures"
        self.handoff = self.project / "private-acquisition-20261102/pi-handoff-20261102"
        self.manifest = self.load(self.fig / "figure_manifest.json")
        m = self.manifest
        if m.get("schema_version") != "tmem.actual_fov_figures.v1" or not m.get(
            "all_proposals_unadopted"
        ):
            raise ValueError("Expected unadopted actual-FOV evidence")
        if (
            m["measurement_geometry_changed"]
            or m["accepted_export_written"]
            or m["real_accepted_ids"]
            or m["scientific_inference_ready"]
        ):
            raise ValueError("Unexpected scientific acceptance or geometry change")
        self.sources = {s["neuron_id"]: s for s in m["sources"]}
        if len(self.sources) != 12:
            raise ValueError("Expected the declared twelve-case panel")
        for source in self.sources.values():
            self.read(Path(source["trace"]) / "manifest.json", source["trace_manifest_sha256"])
            if [f["day"] for f in source["FOV_bindings"]] != list(DAYS) or not all(
                f["live_crop_exactly_equal"] for f in source["FOV_bindings"]
            ):
                raise ValueError("Incomplete FOV binding")
            if not all(source["source_code_matches_current"].values()):
                raise ValueError("Historical processing source mismatch")
        self.sheets = {s["stem"]: s for s in m["sheets"]}
        for name, expected in m["outputs_sha256"].items():
            self.read(self.fig / name, expected)
        self.views = self.table(self.fig / "viewing_comparisons.csv")
        self.segs = self.table(self.fig / "segmentation_sensitivity.csv")
        self.tracks = self.table(self.fig / "tracking_sensitivity.csv")
        ids = set(self.sources)
        grid(self.views, ids, ("visible", "within_range"), "policy")
        grid(self.segs, ids, (140, 180, 220), "minimum_area_px")
        grid(self.tracks, ids, (40, 60, 80), "radius_px")
        for r in self.views:
            if boolean(r["measurement_geometry_changed"]) or not boolean(r["frozen_QC_unchanged"]):
                raise ValueError("Changed frozen geometry/QC")
        for r in self.segs:
            valid, primary = boolean(r["valid_488_mask"]), boolean(r["primary_valid_488_mask"])
            expected = (
                "neutral_flag"
                if valid == primary
                else "gained_diagnostic_flag_not_acceptance"
                if valid
                else "lost_diagnostic_flag"
            )
            if r["flag_change"] != expected:
                raise ValueError("Flag change disagrees with saved validity")
            number(r["mask_area_px"])
        for r in self.tracks:
            boolean(r["score_pass"])
            number(r["score"])
            number(r["displacement_from_stored_anchor_px"])
        self.cases = self.load(self.fig / "case_summary.json")["cases"]
        if {c["neuron_id"] for c in self.cases} != ids or any(
            c["accepted"] or not c["original_failures_preserved"] for c in self.cases
        ):
            raise ValueError("Case decisions differ")
        declaration = self.load(self.project / "dataset/dataset_manifest.json")
        self.read(self.project / "dataset/master.csv", declaration["master"]["sha256"])
        master = self.table(self.project / "dataset/master.csv")
        self.roles = {}
        for well in (w for pair in PAIRS for w in pair):
            roles = {(r["role"], r["condition"]) for r in master if r["well"] == well}
            if len(roles) != 1:
                raise ValueError("Ambiguous well role")
            self.roles[well] = roles.pop()
        for control, experimental in PAIRS:
            if self.roles[control][0] != "control" or self.roles[experimental][0] != "TMEM106B":
                raise ValueError("Unexpected pair assignment")
        self.original = {r["figure_id"]: r for r in self.table(self.handoff / "FIGURE_INDEX.csv")}
        self.registration = self.table(self.handoff / "ORIGINAL_FIELD_REGISTRATION_QC.csv")
        self.header = self.load(self.project / "private-acquisition-20261102/header_summary.json")
        self.read(self.handoff / "ACQUISITION_AND_STITCHING_REPORT.md")
        self.read(self.handoff / "NEURON_QC_AND_REVIEW_STATUS.md")
        report = self.read(self.handoff / "REGISTRATION_VALIDATION.md").decode()
        self.registration_support = {}
        for well, first, anchored in re.findall(
            r"\|([A-Z]\d{2})\|to_first: \d+/\d+ numeric visit gates; support ([0-9.]+); anchored: \d+/\d+ numeric visit gates; support ([0-9.]+)",
            report,
        ):
            self.registration_support[(well, "to_first")] = number(first)
            self.registration_support[(well, "anchored")] = number(anchored)
        if len(self.registration_support) != 12:
            raise ValueError("Missing recorded registration support summaries")
        self.read(self.project / "actual-fov-evidence-20261103/CHECKPOINT.md")
        self.slots = {}

    def read(self, path, expected=None):
        p = safe(self.project, path)
        data = p.read_bytes()
        h = digest(data)
        if expected is not None and h != expected:
            raise ValueError("Source hash mismatch: " + p.name)
        if str(p) in self.bound and self.bound[str(p)] != h:
            raise ValueError("Source mutated")
        self.bound[str(p)] = h
        return data

    def load(self, path):
        return json.loads(self.read(path))

    def table(self, path):
        return list(csv.DictReader(io.StringIO(self.read(path).decode())))

    def card(self, stem, index):
        sheet = self.sheets[stem]
        if stem not in self.slots:
            name = sheet["SVG"]
            self.slots[stem] = svg_slots(
                self.read(self.fig / name, self.manifest["outputs_sha256"][name]),
                len(sheet["cards"]),
            )
        card = sheet["cards"][index]
        blob = self.slots[stem].get(index)
        no_view = (
            card.get("provenance", {})
            .get("parameters", {})
            .get("proposal", {})
            .get("interpretation")
            == "failure_no_view"
        )
        if blob is None and card["status"] in ("executed", "display_only") and not no_view:
            raise ValueError("Executed card lacks its bound image")
        return blob, {
            "sheet": stem,
            "card_index": index,
            "stage": card["stage"],
            "card": card,
            "trace_sha256": sheet["trace_manifest_sha256"],
            "image_sha256": digest(blob) if blob else None,
        }

    def original_panel(self, well, method, row, col):
        record = self.original[well + "_" + method]
        blob = self.read(record["path"], record["sha256"])
        self.read(record["source_binding"])
        with Image.open(io.BytesIO(blob)) as image:
            if image.size != (1800, 1800):
                raise ValueError("Unexpected original QC sheet dimensions")
            box = (34 + col * 600, 114 + row * 574, 566 + col * 600, 646 + row * 574)
            cropped = image.crop(box)
            stream = io.BytesIO()
            cropped.save(stream, format="PNG")
        return stream.getvalue(), {
            "original_figure_id": record["figure_id"],
            "source_sha256": record["sha256"],
            "crop_xyxy": box,
            "source_binding": record["source_binding"],
            "interpretation": "display crop only; original stored field, not whole well",
        }

    def metrics(self):
        areas = {}
        for area in (140, 180, 220):
            rows = [r for r in self.segs if int(r["minimum_area_px"]) == area]
            areas[area] = [
                sum(boolean(r["valid_488_mask"]) for r in rows),
                sum(r["flag_change"] == "gained_diagnostic_flag_not_acceptance" for r in rows),
                sum(r["flag_change"] == "lost_diagnostic_flag" for r in rows),
            ]
        views = {}
        for policy in ("visible", "within_range"):
            rows = [r for r in self.views if r["policy"] == policy]
            views[policy] = [
                sum(r["interpretation"] == k for r in rows)
                for k in (
                    "smaller_view_support_retained_not_accuracy",
                    "degradation_frozen_support_lost",
                    "failure_no_view",
                )
            ]
        tracks = {}
        for radius in (40, 60, 80):
            rows = [r for r in self.tracks if int(r["radius_px"]) == radius]
            tracks[radius] = [
                sum(boolean(r["score_pass"]) for r in rows),
                sum(number(r["candidate_change_from_radius60_px"]) > 0 for r in rows),
            ]
        return {
            "areas": areas,
            "views": views,
            "tracks": tracks,
            "primary_valid": areas[180][0],
            "visits": len(self.segs) // 3,
            "statuses": dict(Counter(c["original_diagnostic_status"] for c in self.cases)),
        }

    def finish(self):
        for p, h in self.bound.items():
            if digest(Path(p).read_bytes()) != h:
                raise ValueError("Source changed during generation")


def color(hex_value):
    return RGBColor.from_string(hex_value)


class Deck:
    def __init__(self, evidence):
        self.e = evidence
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(13.333333), Inches(7.5)
        self.provenance, self.records, self.script = [], [], []
        self.slide = None

    def text(self, text, x, y, w, h, size=19, fill=NAVY, bold=False):
        box = self.slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Inches(0.015)
        tf.margin_top = tf.margin_bottom = Inches(0.02)
        for i, line in enumerate(str(text).split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = line
            p.font.name, p.font.size, p.font.bold, p.font.color.rgb = (
                FONT,
                Pt(size),
                bold,
                color(fill),
            )
            p.space_after = Pt(0)
        return box

    def shape(self, x, y, w, h, fill, kind=MSO_SHAPE.RECTANGLE, line=None):
        s = self.slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
        s.fill.solid()
        s.fill.fore_color.rgb = color(fill)
        if line:
            s.line.color.rgb = color(line)
        else:
            s.line.fill.background()
        for effect in s._element.iter(qn("a:effectRef")):
            effect.set("idx", "0")
        return s

    def arrow(self, x, y, w=0.28, h=0.13):
        self.shape(x, y, w, h, MUTED, MSO_SHAPE.RIGHT_ARROW)

    def new(
        self,
        title,
        subtitle="",
        source="Registered 488 diagnostics. Fixed geometry. No biological approval.",
    ):
        self.slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        self.slide.background.fill.solid()
        self.slide.background.fill.fore_color.rgb = color(BG)
        self.text(title, 0.45, 0.24, 12.4, 0.64, 29, bold=True)
        if subtitle:
            self.text(subtitle, 0.46, 0.94, 12.2, 0.5, 15, MUTED)
        self.text(source, 0.46, 7.17, 11.9, 0.23, 9.5, MUTED)
        self.text(str(len(self.prs.slides)), 12.55, 7.15, 0.3, 0.25, 10, MUTED)
        self.records.append(
            {
                "slide": len(self.prs.slides),
                "title": title,
                "actual_graphics": 0,
                "scientific_visual": False,
            }
        )

    def takeaway(self, text, limit=""):
        self.shape(0.46, 6.57, 0.04, 0.43, TEAL)
        self.text(text, 0.62, 6.56, 12.1, 0.42, 18, bold=True)
        if limit:
            self.text(limit, 0.62, 6.99, 11.9, 0.2, 10.5, MUTED)

    def picture(self, blob, ref, x, y, w, h, label):
        if blob is None:
            self.shape(x, y, w, h, "FFF1DB", line="CBA15B")
            self.text("Evidence unavailable\n" + label, x + 0.1, y + 0.2, w - 0.2, h - 0.4, 17)
            return
        with Image.open(io.BytesIO(blob)) as image:
            ratio = min(w / image.width, h / image.height)
            iw, ih = image.width * ratio, image.height * ratio
        self.slide.shapes.add_picture(
            io.BytesIO(blob),
            Inches(x + (w - iw) / 2),
            Inches(y + (h - ih) / 2),
            width=Inches(iw),
            height=Inches(ih),
        )
        self.text(label, x, y + h + 0.07, w, 0.76, 14)
        self.records[-1]["actual_graphics"] += 1
        self.records[-1]["scientific_visual"] = True
        self.provenance.append(
            {
                "slide": len(self.prs.slides),
                "label": label,
                "embedded_sha256": digest(blob),
                "binding": ref,
            }
        )

    def card(self, stem, index, x, y, w, h, label=None):
        blob, ref = self.e.card(stem, index)
        if blob is None:
            label = (label or "") + "\n" + ref["card"]["title"]
            self.provenance.append(
                {
                    "slide": len(self.prs.slides),
                    "label": label,
                    "embedded_sha256": None,
                    "binding": ref,
                }
            )
        self.picture(blob, ref, x, y, w, h, label or ref["card"]["title"])

    def original(self, well, method, row, col, x, y, w, h, label):
        self.picture(*self.e.original_panel(well, method, row, col), x, y, w, h, label)

    def note(
        self,
        narration,
        purpose,
        result,
        limitation,
        sources="November 3 bound figure manifest and saved tables",
    ):
        notes = (
            narration
            + "\n\nWHAT / WHY / HOW: "
            + purpose
            + "\nRESULT: "
            + result
            + "\nLIMITATION: "
            + limitation
            + "\nSOURCES: "
            + sources
        )
        self.slide.notes_slide.notes_text_frame.text = notes
        self.script.append(
            "## "
            + str(len(self.prs.slides))
            + ". "
            + self.records[-1]["title"]
            + "\n\n"
            + narration
            + "\n\n"
            + notes[len(narration) :].strip()
            + "\n"
        )
        self.records[-1]["narration_words"] = len(narration.split())

    def table(self, headers, rows, x, y, w, h, font=17):
        t = self.slide.shapes.add_table(
            len(rows) + 1, len(headers), Inches(x), Inches(y), Inches(w), Inches(h)
        ).table
        for i, row in enumerate([headers, *rows]):
            for j, value in enumerate(row):
                c = t.cell(i, j)
                c.text = str(value)
                c.fill.solid()
                c.fill.fore_color.rgb = color("E8EEF5" if i == 0 else BG)
                c.margin_top = c.margin_bottom = Inches(0.06)
                for p in c.text_frame.paragraphs:
                    p.font.name, p.font.size, p.font.bold, p.font.color.rgb = (
                        FONT,
                        Pt(font),
                        i == 0,
                        color(NAVY),
                    )
        self.records[-1]["scientific_visual"] = True
        return t

    def chart(self, categories, series, x, y, w, h, max_value=None):
        data = CategoryChartData()
        data.categories = categories
        for name, values in series:
            data.add_series(name, values)
        chart = self.slide.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x), Inches(y), Inches(w), Inches(h), data
        ).chart
        chart.font.name = FONT
        chart.font.size = Pt(14)
        # python-pptx's default signed IDs open in Office, but c:axId/c:crossAx
        # are unsignedInt in OOXML. Preserve reference identity portably.
        for element in chart._chartSpace.iter():
            if element.tag in (qn("c:axId"), qn("c:crossAx")):
                value = int(element.get("val"))
                if value < 0:
                    element.set("val", str(value % (2**32)))
        chart.has_legend = len(series) > 1
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.font.name, chart.legend.font.size = FONT, Pt(13)
        chart.category_axis.tick_labels.font.name = chart.value_axis.tick_labels.font.name = FONT
        chart.category_axis.tick_labels.font.size = chart.value_axis.tick_labels.font.size = Pt(13)
        chart.value_axis.minimum_scale = 0
        if max_value:
            chart.value_axis.maximum_scale = max_value
        chart.plots[0].has_data_labels = True
        chart.plots[0].data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
        chart.plots[0].data_labels.font.name, chart.plots[0].data_labels.font.size = FONT, Pt(14)
        for s, c in zip(chart.series, (TEAL, LILAC, RED)):
            s.format.fill.solid()
            s.format.fill.fore_color.rgb = color(c)
            s.format.line.fill.background()
        self.records[-1]["scientific_visual"] = True
        return chart


def build(e):
    d, m = Deck(e), e.metrics()
    ids = list(e.manifest["render_cases"])
    regular = next(n for n in ids if n.startswith("N05"))
    problem = next(n for n in ids if n.startswith("J05_N028"))
    example = next(n for n in ids if n.startswith("E05"))
    f = lambda n, day: f"{n}_day{day:02d}_flow"
    c = lambda n, day: f"{n}_day{day:02d}_comparison"
    row = lambda rows, n, day, k, v: next(
        r for r in rows if r["neuron_id"] == n and int(r["day"]) == day and int(r[k]) == v
    )

    d.new(
        "TMEM106B Longitudinal Neuron Alignment",
        source="Private PI meeting draft, November 3, 2026. Real registered 488 observations.",
    )
    d.text(
        "From Real Microscopy Fields to\nEvidence-Bound Phenotype Analysis",
        0.48,
        1.15,
        7.4,
        1.2,
        29,
        bold=True,
    )
    d.text(
        "Pipeline development, registration, segmentation,\ntracking, QC, and scientific readiness",
        0.5,
        2.48,
        7.1,
        0.85,
        19,
        MUTED,
    )
    for j, day in enumerate((8, 25, 39)):
        stem = regular + "_nine_visits"
        d.card(
            stem,
            DAYS.index(day),
            0.5 + j * 4.18,
            3.4,
            3.9,
            2.5,
            f"{regular}, Day {day}, 488, fixed ROI",
        )
    d.note(
        "Today I want to show what we can now inspect directly, and where we still need experimental evidence. These are real registered 488 observations of one diagnostic candidate across the month. The yellow outline is the same fixed ROI, rather than a box chosen separately from the phenotype on each day. We now have inspectable records for the full processing sequence and its parameter sensitivity. The central question for this meeting is which remaining acquisition and identity checks we should prioritize before any biological comparison.",
        "Follow longitudinal candidates without using the phenotype to define identity.",
        "Real stages and fixed diagnostic ROIs are inspectable.",
        "No independently accepted biological cohort.",
    )

    d.new(
        "Why follow the same neuron?",
        "Identity comes from 488. Phenotype measurement comes later, using 561.",
    )
    for j, day in enumerate((8, 32, 39)):
        d.card(
            regular + "_nine_visits",
            DAYS.index(day),
            0.6 + j * 3.1,
            1.65,
            2.7,
            2.7,
            f"{regular}, Day {day}\n488, registered, fixed yellow ROI",
        )
    d.text("488\nIdentity + ROI review", 10.05, 1.75, 2.6, 1.1, 23, TEAL, True)
    d.text("561\nIndependent phenotype review", 10.05, 3.6, 2.6, 1.3, 22, LILAC, True)
    d.shape(10.9, 3.05, 0.25, 0.45, MUTED, MSO_SHAPE.DOWN_ARROW)
    d.takeaway(
        "Choosing identity using 561 would make selection depend on the outcome.",
        "Repeated fluorescence observations alone do not establish survival or mechanism.",
    )
    d.note(
        "Point to the fixed yellow outline across these visits. Our aim is to measure the same candidate consistently, even as the image changes. The structural 488 channel supplies the identity and ROI decisions. Only after that review should the 561 channel supply phenotype measurements. If we choose a cell or redraw its region because its mCherry looks interesting, the outcome starts influencing who enters the analysis. These images illustrate the workflow, but the identity and ownership still need independent review. Next, the plate design shows what would count as biological replication.",
        "488 identity independent of downstream 561.",
        "Frozen geometry supports consistent sampling.",
        "No survival or mechanistic inference from this montage.",
    )

    d.new(
        "Three matched well pairs, nine visits",
        "Metadata assigns E05 / I05 / M05 to control and F05 / J05 / N05 to experimental.",
        "Source: registered master metadata. Filename labels do not independently establish original plate identity.",
    )
    for i, pair in enumerate(PAIRS):
        for j, well in enumerate(pair):
            x, y = 0.8 + i * 4.15, 1.8 + j * 1.4
            d.shape(x, y, 1.0, 1.0, BLUE if j == 0 else LILAC, MSO_SHAPE.OVAL)
            d.text(well, x + 0.1, y + 0.25, 0.9, 0.5, 23, "FFFFFF", True)
            d.text(
                "Reporter control" if j == 0 else "TMEM106B experimental",
                x + 1.15,
                y + 0.25,
                2.7,
                0.7,
                17,
            )
    d.text("Day", 0.6, 5.18, 0.6, 0.4, 17, MUTED)
    for i, day in enumerate(DAYS):
        d.shape(1.3 + i * 1.27, 5.27, 0.85, 0.03, LINE)
        d.text(str(day), 1.3 + i * 1.27, 5.5, 0.8, 0.45, 20, TEAL, True)
    d.records[-1]["scientific_visual"] = True
    d.takeaway(
        "Cells and repeat visits are nested within wells. They do not add biological replicates."
    )
    d.note(
        "There are three potential matched well pairs in this experiment. The control wells carry the PLD3 mCherry reporter, and the paired experimental wells carry the TMEM106B construct, according to the registered master metadata. Each series spans these nine days. Our twelve diagnostic candidates are a software and image-review panel, with two candidates per well. They do not turn the experiment into twelve independent biological replicates. Any eventual comparison must respect the matched well structure and use a genuinely accepted cohort. We will keep that distinction visible as we walk through the processing steps.",
        "Verify pair roles from metadata and preserve nesting.",
        "Three potential matched pairs.",
        "Zero eligible accepted matched pairs currently.",
        "dataset/master.csv, role/condition columns only",
    )

    d.new(
        "Processing steps and their current evidence",
        "Color describes the evidence available for each stage, not a universal pass.",
        "Schematic. Blue: software controls. Teal: real registered execution. Amber: acquisition evidence missing. Lilac: human review.",
    )
    stages = [
        ("Original ND2\nMetadata + extraction", BLUE),
        ("Illumination correction\nFields missing", "D5AD6C"),
        ("Spatial assembly\nGeometry unresolved", "D5AD6C"),
        ("488 registration\nField diagnostics", BLUE),
        ("Candidate + soma\nRegistered stages", TEAL),
        ("Tracking + fixed ROI\nRegistered stages", TEAL),
        ("488 then 561 review\nHuman review pending", LILAC),
        ("Matched wells\nAccepted cohort missing", RED),
    ]
    for i, (label, fill) in enumerate(stages):
        j, k = i % 4, i // 4
        x, y = 0.55 + j * 3.18, 1.9 + k * 2.1
        d.shape(x, y, 2.85, 1.2, fill)
        d.text(str(i + 1) + ". " + label, x + 0.13, y + 0.1, 2.6, 1.05, 17.5, "FFFFFF", True)
        if j < 3:
            d.arrow(x + 2.9, y + 0.48, 0.22, 0.14)
    d.records[-1]["scientific_visual"] = True
    d.takeaway(
        "Implemented, executed, software-verified and biologically accepted are separate milestones."
    )
    d.note(
        "This is the full workflow, with the evidence level attached to each part. Original-container inspection and exact extraction establish that we can access the stored images without changing the pixels. They do not establish a complete well or the detector correction state. The central registered-image steps have real numerical intermediates that we can inspect today. Human identity and phenotype review remain separate gates after those diagnostic steps. The final matched-well software exists, but there is no accepted cohort to analyze. The next slides start at the original acquisitions and then switch explicitly to the registered atlas.",
        "Explain processing order and evidence levels.",
        "Real registered execution covers candidate through ROI.",
        "No original-to-atlas transform or scientific acceptance.",
    )

    h = e.header
    d.new(
        "Original acquisitions: access and extraction",
        "Stored original containers, rather than verified complete-well mosaics.",
        "Source: authenticated saved header inventory and extraction receipt. Named 488 channel. Original stored plane.",
    )
    d.original(
        "E05",
        "to_first",
        0,
        0,
        0.55,
        1.6,
        4.1,
        4.1,
        "E05, Day 8, named 488\nOriginal stored-field display, fixed Day 8 LUT",
    )
    d.table(
        ["Saved observation", "Evidence"],
        [
            ["Target containers", h["target_fluorescence_containers"]],
            ["Well / day design", "6 wells, 9 days"],
            ["Inspected dimensions", "CYX: 3 x 2868 x 2868"],
            ["Stored dtype", "uint16"],
            ["OME-TIFF pilot extraction", "Pixel-exact round trip"],
        ],
        5.05,
        1.72,
        7.65,
        3.25,
        18,
    )
    d.text(
        "Unresolved: acquisition extent, stage/camera geometry,\ncorrection state and conflicting optical channel metadata.",
        5.08,
        5.25,
        7.4,
        0.85,
        19,
        RED,
    )
    d.takeaway("Pixel preservation verifies extraction. It does not verify whole-well coverage.")
    d.note(
        "The original acquisitions are available locally, so file access is no longer the main blocker. The saved inventory covers fifty-four target fluorescence containers across six wells and nine visits. The inspected containers have three uint16 planes, each 2868 pixels square. A pilot extraction round-tripped through OME-TIFF with exact pixel equality. Point to the real original-field image on the left. We still need the acquisition plan to establish its coverage and correction state. Channel names also conflict with some optical metadata, so those labels need experimental reconciliation before claiming calibrated channel identity.",
        "Inspect stored container structure and non-destructive extraction.",
        "54 target containers and exact pilot extraction.",
        "Stored field is not certified raw detector data or a whole well.",
        "header_summary.json; selected54_headers.json; ACQUISITION_AND_STITCHING_REPORT.md; FIGURE_INDEX.csv",
    )

    d.new(
        "Registration support depends on the method",
        "F05, Day 39. Magenta = Day 8 reference. Green = current visit. Original stored-field coordinates.",
        "Source: F05 original-field QC inventory. Fixed Day 8 LUT. Unsupported black borders retained. Display crops only.",
    )
    for j, (method, col, label) in enumerate(
        (
            ("to_first", 1, "Before registration"),
            ("to_first", 2, "to_first after"),
            ("anchored", 2, "anchored after"),
        )
    ):
        d.original("F05", method, 2, col, 0.55 + j * 4.22, 1.55, 3.8, 3.8, label)
    summaries = e.load(Path(e.original["F05_anchored"]["source_binding"]).parent / "summary.json")
    first, anchored = (
        next(r for r in summaries if r["mode"] == mode) for mode in ("to_first", "anchored")
    )
    d.text(
        f"Nine-visit common support: to_first {first['strict_common_support_fraction']:.3f}    anchored {anchored['strict_common_support_fraction']:.3f}",
        0.65,
        5.85,
        12,
        0.45,
        21,
        TEAL,
        True,
    )
    d.takeaway(
        "Anchored retains nonempty support in all six field series. F05 to_first loses it.",
        "Different references and QC gates prevent treating correlation as a common accuracy metric. Whole-well validation: 0/54.",
    )
    d.note(
        "These panels compare the same F05 field before registration and after the two saved methods. The overlay colors show the Day 8 reference and the current image. Black borders remain visible because they show unsupported regions. For F05, the strict intersection across all nine visits is empty with to_first, while anchored retains nonempty support. That is a useful technical difference. It is still not independent geometric accuracy, and the methods can use different references and gates. We have not validated any of the fifty-four potential whole-well mosaics. Appendix slides separate that reconstruction requirement from field registration.",
        "Compare same original stored fields across saved methods.",
        "F05 strict common support restored diagnostically by anchored.",
        "No landmark validation, no whole well, no atlas anchor mapping.",
        "REGISTRATION_VALIDATION.md; ORIGINAL_FIELD_REGISTRATION_QC.csv; F05 summary.json and bound QC PNGs",
    )

    stem = f(example, 39)
    binding = next(s for s in e.manifest["sources"] if s["neuron_id"] == example)["FOV_bindings"][
        -1
    ]
    bounds = binding["bounds"]
    d.new(
        "A registered image location becomes a candidate",
        f"{example}, Day 39, 488. Yellow rectangle links the full field to the unchanged candidate box.",
    )
    d.card(stem, 0, 0.5, 1.6, 6.0, 4.4, "Full historical registered field, original box")
    d.arrow(6.6, 3.3, 0.45, 0.22)
    d.card(stem, 1, 7.25, 1.65, 3.95, 3.95, "Exact 128 x 128 crop, raw 0-4095 ADU")
    ay, ax = binding["anchor_yx_crop_px"]
    d.shape(7.25 + ax / 128 * 3.95 - 0.08, 1.65 + ay / 128 * 3.95 - 0.01, 0.16, 0.02, "00FFFF")
    d.shape(7.25 + ax / 128 * 3.95 - 0.01, 1.65 + ay / 128 * 3.95 - 0.08, 0.02, 0.16, "00FFFF")
    d.text(
        f"Stored anchor (y,x):\n{binding['anchor_yx_registered_px'][0]:.2f}, {binding['anchor_yx_registered_px'][1]:.2f}\nBox y: {bounds['y0']}:{bounds['y1']}\nx: {bounds['x0']}:{bounds['x1']}",
        11.4,
        2.15,
        1.5,
        2.8,
        15,
    )
    d.takeaway(
        "All 108 live registered crops exactly match their recorded production inputs.",
        "This coordinate link applies to the historical atlas. Original-ND2-to-atlas mapping remains unresolved.",
    )
    d.note(
        "We are now in the historical registered atlas, which is a separate coordinate system from the original fields. Start with the yellow rectangle in the full field, then follow it to the enlarged crop. The cyan mark is the stored anchor, and the exact coordinates come from the saved binding record. All one hundred and eight live crops matched the recorded processing inputs exactly. That gives us a traceable computational candidate, but it does not independently identify a biological neuron. Neighboring objects and the ownership of the region still need review at this stage.",
        "Connect full field, box and anchor without inventing a transform.",
        "108 exact crop bindings.",
        "Candidate identity is unreviewed; no physical scale bar.",
    )

    d.new(
        "How the soma mask takes shape",
        f"{example}, Day 39, registered 488. This visit fails its original primary QC.",
    )
    indices = (1, 2, 3, 6, 9, 10, 12, 22)
    labels = (
        "Raw crop",
        "Normalize",
        "Gaussian smooth",
        "Winning threshold",
        "Fill holes",
        "Components",
        "Selected soma",
        "Frozen identity core",
    )
    for j, (index, label) in enumerate(zip(indices, labels)):
        d.card(stem, index, 0.55 + (j % 4) * 3.18, 1.65 + (j // 4) * 2.25, 2.75, 1.75, label)
    threshold = e.sheets[stem]["cards"][6]["provenance"]["record"]
    d.takeaway(
        "Thresholding and morphology produce candidate support. QC stays failed.",
        "Raw: 0-4095 ADU. Normalized: 0-1. Masks: Boolean. Labels: categorical. Selected component does not prove identity.",
    )
    d.note(
        "Follow the upper row from the unchanged crop through normalization and smoothing to the winning threshold. Normalization makes structural contrast easier for the existing algorithm to use. Thresholding proposes bright support. Morphology then removes small objects, closes gaps and fills holes before component selection. The lower row shows that progression through labels and the selected soma to the longitudinal core. Nearby bright objects can still merge or compete, so a plausible outline is not enough. This example retains its original failed QC flag. The precise saved threshold and preprocessing parameters are recorded in the notes and provenance.",
        "Normalize, smooth, threshold, clean and select using saved winning ancestry.",
        "Actual stages shown, including a failed visit.",
        "Morphology can alter connectivity and ownership.",
        "Winning threshold record: "
        + json.dumps(
            {k: threshold.get(k) for k in ("stage", "parameters", "details", "why")},
            ensure_ascii=True,
        ),
    )

    tstem = f(problem, 32)
    d.new(
        "A higher match score can move the candidate",
        f"{problem}, Day 32, registered 488. Cyan: stored anchor in search, chosen peak on correlation. Unadopted.",
    )
    for j, (index, label) in enumerate(
        (
            (15, "Day 8 template"),
            (16, "Primary radius 60 search"),
            (18, "Correlation surface"),
            (19, "Recorded chosen peak"),
        )
    ):
        d.card(tstem, index, 0.55 + j * 3.18, 1.65, 2.8, 2.7, label)
    search = e.sheets[tstem]["cards"][16]["provenance"]["record"]
    y0, y1, x0, x1 = search["details"]["bounds_y0_y1_x0_x1"]
    anchor = next(b for b in e.sources[problem]["FOV_bindings"] if b["day"] == 32)[
        "anchor_yx_registered_px"
    ]
    marks = [(1, (anchor[0] - y0) / (y1 - y0), (anchor[1] - x0) / (x1 - x0))]
    peak = e.sheets[tstem]["cards"][19]["provenance"]["record"]["details"]["correlation_peak_yx"]
    height, width = e.sheets[tstem]["cards"][18]["provenance"]["record"]["statistics"]["shape"]
    marks.extend((j, (peak[0] + 0.5) / height, (peak[1] + 0.5) / width) for j in (2, 3))
    for panel, yy, xx in marks:
        mark = d.shape(
            0.55 + panel * 3.18 + 0.05 + xx * 2.7 - 0.065,
            1.65 + yy * 2.7 - 0.065,
            0.13,
            0.13,
            "00FFFF",
            MSO_SHAPE.OVAL,
            "00FFFF",
        )
        mark.fill.background()
        mark.line.width = Pt(1.5)
    comparisons = [row(e.tracks, problem, 32, "radius_px", r) for r in (40, 60, 80)]
    d.table(
        ["Radius (px)", "Match score", "Offset from stored anchor (px)"],
        [
            [
                r["radius_px"],
                f"{number(r['score']):.3f}",
                f"{number(r['displacement_from_stored_anchor_px']):.2f}",
            ]
            for r in comparisons
        ],
        0.8,
        5.0,
        11.8,
        1.15,
        17,
    )
    d.takeaway(
        "A better correlation score does not guarantee the same neuron.",
        "Stored anchors are reference positions, not independently reviewed identity truth. No candidate replaces the frozen anchor.",
    )
    d.note(
        "The template is the structural pattern that the tracker tries to find in the search window. The correlation surface assigns a matching score to each tested position, and the peak proposes a location. In this real example, increasing the radius opens up competing locations and gives a higher score, while the proposal moves substantially away from the stored anchor. Point to the score and displacement together in the table. Neither number alone establishes identity. We have deliberately left these proposals unadopted, so they cannot silently move the phenotype ROI or rescue a failed track.",
        "Explain template search and competing peaks.",
        "Score and displacement change together on identical source data.",
        "Candidate movement is not a verified identity switch.",
    )

    d.new(
        "Soma support, identity core and fixed ROI",
        "Yellow contour follows the stated stage. Cyan marks the stored anchor where shown. All panels are registered 488.",
    )
    for j, (n, day, index, label) in enumerate(
        (
            (regular, 39, 13, "Selected soma"),
            (regular, 39, 23, "Identity core"),
            (regular, 39, 24, "Fixed phenotype ROI"),
            (problem, 32, 24, "Ambiguous neighboring support"),
        )
    ):
        d.card(f(n, day), index, 0.55 + j * 3.18, 1.65, 2.8, 3.3, f"{n}, Day {day}\n{label}")
        local_anchor = next(b for b in e.sources[n]["FOV_bindings"] if b["day"] == day)[
            "anchor_yx_crop_px"
        ]
        xx = 0.55 + j * 3.18 + local_anchor[1] / 128 * 2.8
        yy = 1.9 + local_anchor[0] / 128 * 2.8
        d.shape(xx - 0.065, yy - 0.008, 0.13, 0.016, "00FFFF")
        d.shape(xx - 0.008, yy - 0.065, 0.016, 0.13, "00FFFF")
    d.text(
        "Soma: one visit     Core: across visits     ROI: same region for later measurement",
        0.7,
        5.9,
        12,
        0.65,
        18,
    )
    d.takeaway(
        "Fixed geometry supports consistent measurement, but ownership still needs review.",
        "Regular-looking and ambiguous examples both remain unapproved. No 561 result determines these regions.",
    )
    d.note(
        "These regions answer different questions. The soma mask describes support in a particular visit. The identity core combines longitudinal structural support, and the phenotype ROI provides the frozen region for later measurement. The first example looks relatively compact, but that appearance is not an approval. The final example has neighboring structural support that makes ownership harder to judge. Point out that we have kept the original geometry rather than shrinking it to obtain acceptance. Independent review needs to decide whether the region belongs to the same neuron across all visits before phenotype results enter an accepted analysis.",
        "Distinguish visit soma, longitudinal core and frozen ROI.",
        "Real overlays expose compact and ambiguous geometry.",
        "No independently reviewed ROI ownership.",
    )

    d.new(
        "Parameter changes produce gains and regressions",
        "All 12 cases and 108 visits. Baseline area 180, search radius 60. No alternative is adopted.",
    )
    d.chart(
        ["140", "180", "220"],
        [("Valid diagnostic visits", [m["areas"][a][0] for a in (140, 180, 220)])],
        0.5,
        1.7,
        5.8,
        3.6,
        108,
    )
    d.chart(
        ["140", "180", "220"],
        [
            ("Gained vs 180", [m["areas"][a][1] for a in (140, 180, 220)]),
            ("Lost vs 180", [m["areas"][a][2] for a in (140, 180, 220)]),
        ],
        6.7,
        1.7,
        6.0,
        3.6,
        8,
    )
    d.text("Search radius (px)", 0.7, 5.48, 3, 0.35, 17, MUTED)
    d.text(
        "   ".join(
            f"{r}: {m['tracks'][r][0]}/108 score passes, {m['tracks'][r][1]} changed peaks"
            for r in (40, 60, 80)
        ),
        0.7,
        5.88,
        12.1,
        0.5,
        15,
    )
    d.takeaway(
        "More valid diagnostic flags do not establish greater segmentation accuracy.",
        "Area 140 and 180 have equal totals but different passing visits. Changed peaks are agreement/sensitivity, not identity accuracy.",
    )
    d.note(
        "The left chart shows the aggregate counts for the three saved area settings. The first two totals match, but the right chart shows why that is misleading: the smaller setting gains some visits and loses others. The largest setting adds valid diagnostic flags, yet it can also select a substantially different mask. These are changes in algorithm behavior, not a measured accuracy improvement. The tracking summary similarly reports score passes and changed peaks rather than verified identities. We retain the primary settings and every original failed gate while we use this sensitivity analysis to focus review.",
        "Evaluate saved area and radius alternatives on the full declared panel.",
        "Counts, gains, losses and changed peaks derive from saved rows.",
        "No independent labels or parameter adoption.",
    )

    d.new(
        "A clearer view can still crop away the ROI",
        f"{example}, Day 39, registered 488. Display proposals: NOT ADOPTED.",
    )
    for j, (sheet, index, label) in enumerate(
        (
            (f(example, 39), 23, "Frozen identity core"),
            (f(example, 39), 24, "Frozen phenotype ROI"),
            (c(example, 39), 1, "Same crop, 200-2000 ADU"),
            (c(example, 39), 2, "Smaller visible view"),
            (c(example, 39), 3, "Two-sided range proposal"),
        )
    ):
        d.card(sheet, index, 0.5 + j * 2.57, 1.6, 2.3, 2.7, label)
    v = m["views"]
    d.table(
        ["Policy", "Full support", "Loses support", "No view"],
        [["Visible", *v["visible"]], ["Two-sided", *v["within_range"]]],
        0.7,
        5.0,
        11.9,
        1.15,
        17,
    )
    d.takeaway(
        "Display improvements must stay separate from measurement geometry.",
        "Visible: pixel > 200. Two-sided: 200 < pixel <= 2000. Frozen core/ROI determine retained support. No physical calibration claim.",
    )
    d.note(
        "These panels use exactly the same source pixels. The first retains the recorded raw display range, and the second uses the declared exploratory range. The smaller proposed view can make a cell easier to see, but it can also exclude part of the frozen structural support or phenotype ROI. The table includes every visit, including proposals that could not form a view. The upper cutoff in the two-sided policy deliberately tests bright-signal exclusion. We have not adopted any proposed box for measurement. The useful result here is an explicit tradeoff between visual focus and retained coverage.",
        "Test display-only LUT and viewport proposals on identical crops.",
        "Retained, lost and absent support counted separately.",
        "Contrast limits are declared display choices, not calibrated or optimized measurement parameters.",
    )

    d.new(
        "QC outcomes and review priorities",
        "Diagnostic failures remain excluded. All nine visits and historical exclusions still apply.",
    )
    d.table(
        ["Diagnostic observation", "Count"],
        [
            ["Cases / visits", f"{len(e.cases)} / {m['visits']}"],
            ["Primary 488-valid visits", m["primary_valid"]],
            ["Failed visit gates", m["visits"] - m["primary_valid"]],
            [
                "Rejected tracks / pending review",
                f"{m['statuses'].get('diagnostic_rejected', 0)} / {m['statuses'].get('diagnostic_complete_pending_review', 0)}",
            ],
            ["Newly accepted biological neurons", "0"],
        ],
        0.6,
        1.65,
        5.6,
        3.9,
        19,
    )
    d.text("Observed in saved diagnostics", 6.7, 1.75, 5.9, 0.45, 21, TEAL, True)
    d.text(
        "Failed mask gates\nLost frozen support\nMoved correlation peaks\nRegistration support failure",
        6.7,
        2.35,
        5.7,
        2.0,
        21,
    )
    d.text("Interpretations requiring review", 6.7, 4.6, 5.9, 0.45, 21, LILAC, True)
    d.text(
        "Weak signal, competing somata, partial ownership,\nfragmentation or oversized support, possible switches",
        6.7,
        5.15,
        5.8,
        0.95,
        18,
    )
    d.takeaway(
        "A failed gate, missing signal or unresolved identity does not establish neuron death."
    )
    d.note(
        "This table separates the diagnostic panel from an accepted biological sample. Seventeen visit gates fail under the primary settings. Six tracks are diagnostically rejected or blocked, while the other six still need independent review. There are no newly accepted neurons. The right side separates directly recorded behavior, such as lost support or a moved peak, from possible explanations that require image review. Weak signal, neighbors and ambiguous ROI ownership can produce similar automated failures. We should not translate any of those flags into cell death. The dashboard is a review queue, not a survival result.",
        "Separate immutable QC, pending review and provisional failure interpretations.",
        "Primary failures and zero acceptance preserved.",
        "No identity-switch, contamination or survival accuracy estimate.",
    )

    d.new(
        "What the pipeline now supports",
        "Engineering progress and experimental validation have different completion criteria.",
        "Schematic evidence milestones. Test success never grants biological acceptance.",
    )
    d.text("Verified engineering", 0.7, 1.7, 5.8, 0.5, 25, TEAL, True)
    d.text(
        "Source and environment checks\nFOV-to-cell provenance\nNumerical stage records and real-image diagnostics\nSensitivity analysis with failures retained\nReview and matched-well analysis infrastructure\nTested figure generation and source publication",
        0.7,
        2.4,
        5.8,
        3.7,
        19,
    )
    d.text("Experimental evidence still needed", 7.0, 1.7, 5.8, 0.5, 25, LILAC, True)
    d.text(
        "Complete acquisition geometry and calibration\nOriginal-to-atlas mapping\nIndependent identity and ROI review\nIndependent final 561 review\nA genuine accepted paired cohort",
        7.0,
        2.4,
        5.7,
        3.7,
        19,
    )
    d.shape(6.55, 1.75, 0.025, 3.55, LINE)
    for i, (label, fill) in enumerate(
        (
            ("Implemented", BLUE),
            ("Executed", TEAL),
            ("Software-verified", TEAL),
            ("Independent validation\npending", LILAC),
            ("Biological acceptance\nblocked", RED),
        )
    ):
        x = 0.65 + i * 2.53
        d.shape(x, 5.65, 2.28, 0.66, fill)
        d.text(label, x + 0.07, 5.68, 2.14, 0.58, 13.5 if i > 2 else 15, "FFFFFF", True)
        if i < 4:
            d.arrow(x + 2.31, 5.9, 0.18, 0.1)
    d.records[-1]["scientific_visual"] = True
    d.takeaway(
        "The software makes decisions inspectable. Scientific acceptance needs additional evidence."
    )
    d.note(
        "The main advance is that the analysis is now inspectable in a way that supports collaboration. We can connect a field to a crop, follow numerical intermediates, compare parameter choices on identical inputs and preserve the failures. There is also software for source-bound review and eventual matched-well analysis. The right column lists evidence that code cannot create: authentic acquisition geometry, a valid coordinate mapping and independent identity and phenotype review. These are different milestones from software verification. The immediate next step is therefore an evidence and review decision, rather than another round of parameter tuning to increase pass counts.",
        "Summarize engineering milestones against experimental requirements.",
        "Reproducible diagnostic infrastructure exists.",
        "Accepted cohort and biological outputs remain blocked.",
    )

    d.new(
        "Next decisions for the PI meeting",
        "The figures identify where additional evidence would change what we can claim.",
        "Discussion roadmap. No scientific gates change during presentation preparation.",
    )
    d.text(
        "1  Real processing stages are now traceable.\n2  Parameter sensitivity exposes both gains and failures.\n3  Identity and geometry remain the key scientific gates.",
        0.65,
        1.6,
        12.1,
        1.7,
        25,
        bold=True,
    )
    roadmap = [
        "Confirm acquisition geometry + calibration",
        "Validate one complete well/day pilot",
        "Extend verified reconstruction",
        "Independent 488 identity / ROI review",
        "Independent final 561 review",
        "Accepted matched-well analysis",
    ]
    for i, label in enumerate(roadmap):
        y = 3.55 + (i // 3) * 1.05
        x = 0.7 + (i % 3) * 4.2
        d.text(f"{i + 1}. {label}", x, y, 3.65, 0.8, 19, TEAL if i < 3 else LILAC, True)
        if i % 3 < 2:
            d.arrow(x + 3.72, y + 0.25, 0.22, 0.13)
    d.records[-1]["scientific_visual"] = True
    d.takeaway(
        "Which acquisition records can we obtain, and which candidates should reviewers inspect first?"
    )
    d.note(
        "My takeaway is that we can now discuss the actual processing decisions rather than only a workflow diagram. The comparisons also show why a higher score or an extra valid flag is not enough to choose a new setting. I would prioritize authentic acquisition records and a single evidence-complete reconstruction pilot, followed by independent identity and ROI review. Phenotype review comes after those structural decisions, and only genuine accepted exports should feed the matched-well analysis. For this meeting, which acquisition records are most accessible, and which ambiguous candidates should we put first in the reviewer queue?",
        "Prioritize evidence collection and independent review.",
        "Concrete graphical diagnostics support discussion.",
        "No accepted phenotype or treatment conclusion.",
    )

    d.new(
        "Appendix: exact parameters and reconstruction",
        "Parameter definitions describe diagnostic execution, not independently established accuracy.",
    )
    config = e.load(Path(e.sources[example]["trace"]) / "manifest.json")["metadata"]["parameters"]
    sg, tr = config["segmentation"], config["tracking"]
    d.table(
        ["Step", "Saved setting / definition"],
        [
            ["Candidate box", f"{config['bbox_size']} x {config['bbox_size']} pixels"],
            ["Minimum-area preference", f"{sg['min_area']} px; alternatives 140 / 220"],
            ["Consensus fraction", sg["consensus_fraction"]],
            ["Core area limits", f"{sg['min_core_area']} to {sg['max_core_area']} px"],
            [
                "ROI dilation / background exclusion",
                f"{sg['phenotype_dilation']} / {sg['background_exclusion']} px",
            ],
            [
                "Tracking template / primary radius",
                f"{tr['template_size']} / {tr['search_radius']} px",
            ],
            ["Minimum score", tr["min_score"]],
        ],
        0.55,
        1.6,
        7.4,
        3.9,
        17,
    )
    for i, label in enumerate(
        ("Declared tiles", "Integer placement", "Overlap averaging", "Coverage + seam QC")
    ):
        d.shape(8.45, 1.65 + i * 1.0, 4.1, 0.7, "E8EEF5")
        d.text(label, 8.6, 1.8 + i * 1.0, 3.8, 0.4, 18, bold=True)
    d.takeaway(
        "Whole-well reconstruction still needs complete tile membership and reviewed geometry.",
        "Reconstruction diagram is schematic. No real mosaic or physical scale bar is fabricated.",
    )
    d.note(
        "This appendix gives the exact primary settings from the saved source trace. Minimum area is a component-discovery preference and does not guarantee that every final soma meets a strict floor. The assembler schematic describes the implemented integer-placement model, with overlap averaging and coverage/seam checks. Off-axis camera geometry must not be rounded into that contract without evidence.",
        "Exact parameters and explicitly schematic reconstruction.",
        "Settings read from source trace.",
        "No whole-well pilot supported by current geometry.",
    )

    d.new(
        "Appendix: original-field registration QC",
        "Counts include the Day 8 self-reference. Common support uses the strict nine-visit intersection.",
        "Source: saved per-method original-field summaries and registration CSV. Accuracy and whole-well validation remain unavailable.",
    )
    regrows = []
    for well in (w for pair in PAIRS for w in pair):
        for method in ("to_first", "anchored"):
            visits = [r for r in e.registration if r["well"] == well and r["method"] == method]
            if len(visits) != 9 or {int(r["timepoint_day"]) for r in visits} != set(DAYS):
                raise ValueError("Incomplete original registration QC grid")
            passed = sum(boolean(r["qc_pass"]) for r in visits)
            regrows.append(
                [
                    well,
                    method,
                    f"{passed}/{len(visits)}",
                    f"{e.registration_support[(well, method)]:.3f}",
                ]
            )
    d.table(
        ["Well", "Method", "Numeric visit gates", "Common support fraction"],
        regrows,
        0.65,
        1.55,
        12.0,
        4.72,
        15,
    )
    d.takeaway(
        "Anchored retains support across all six series. That does not independently establish geometry.",
        "Anchored references may change and include additional well-level gates. Correlation values are not a shared accuracy scale.",
    )
    d.note(
        "This table keeps every well and both completed methods visible, including the F05 failure. Counts include the reference observation and therefore are not nine independent validation trials. Common support means the strict intersection across visits. The methods do not have identical gate definitions or necessarily identical references after reanchoring, so post-correlation should not be ranked as common accuracy.",
        "Show all saved original-field outcomes.",
        "Nonempty anchored support across six series.",
        "No independently reviewed landmarks or complete wells.",
    )

    d.new(
        "Appendix: the mask changes behind a new valid flag",
        f"{example}, Day 39. Same input pixels, saved area alternatives.",
    )
    segrows = [row(e.segs, example, 39, "minimum_area_px", a) for a in (140, 180, 220)]
    for i, (a, r) in enumerate(zip((140, 180, 220), segrows)):
        d.card(
            c(example, 39),
            4 + i,
            0.8 + i * 4.15,
            1.7,
            3.6,
            3.5,
            f"Area {a}: valid {r['valid_488_mask']}\nMask {r['mask_area_px']} px, IoU {number(r['mask_IoU_vs_primary']):.3f}",
        )
    d.text(
        "A diagnostic flag can improve while the selected support changes substantially.",
        0.8,
        5.85,
        11.9,
        0.5,
        21,
        TEAL,
        True,
    )
    d.takeaway(
        "The original failed gate stays failed. The alternative mask does not rescue the track."
    )
    d.note(
        "Compare the actual saved masks rather than only their validity labels. The larger-area setting changes the selected support and can create a new valid flag. Mask area and intersection-over-union quantify that change, but do not tell us which support belongs to the intended neuron. Both the baseline failure and the alternative remain in the report. No mask is substituted into the accepted workflow.",
        "Inspect real mask sensitivity on identical inputs.",
        "Area and IoU read directly from saved rows.",
        "No independently reviewed correct mask.",
    )

    d.new(
        "Appendix: provenance and software checks",
        "Evidence records remain private. Source code and sanitized documentation may be public.",
        "Counts describe separate or overlapping verification phases. Do not sum them as independent experiments.",
    )
    d.table(
        ["Evidence", "What it supports", "What it does not establish"],
        [
            ["FOV source bindings", "12 cases, 108 exact crops", "Independent identity"],
            ["Saved stage arrays + hashes", "Numerical traceability", "Correct ROI ownership"],
            [
                "Actual-FOV affected checks",
                "123 tests + 27 subtests passed",
                "Experimental accuracy",
            ],
            [
                "Fresh branch controls",
                "70 tests + 20 subtests passed",
                "New acquisition validation",
            ],
            ["Historical verification", "Separate saved source receipts", "A newly rerun baseline"],
            ["Presentation build", "Embedded editable objects", "Scientific acceptance"],
        ],
        0.6,
        1.7,
        12.1,
        3.7,
        17,
    )
    d.text(
        "Figure source commit: 90403cf\nFull source and image SHA256 bindings accompany this deck in the private provenance files.",
        0.7,
        5.65,
        12,
        0.75,
        19,
    )
    d.takeaway(
        "Implemented, executed and software-verified evidence stays separate from biological acceptance."
    )
    d.note(
        "The deck reuses verified saved evidence rather than rerunning image analysis. Individual embedded panels bind to the actual-FOV manifest or original-field figure inventory. The software counts here describe distinct or overlapping phases and should not be added together. The private provenance table records the source and display crop for every microscopy panel. The presentation itself still requires a full render and visual inspection, recorded separately after generation.",
        "Explain reproducibility and test scope.",
        "Source/image hashes and declared comparison grids verified.",
        "Software fixtures and engineering tests are not experiments.",
    )

    d.new(
        "Appendix: evidence needed for scientific release",
        "Two human workstreams remain: acquisition evidence and independent image review.",
        "Preserve all-nine-visit gates and historical exclusions. No automated scientific approval.",
    )
    d.table(
        ["Gate", "Smallest next action"],
        [
            [
                "Acquisition extent / mapping",
                "Obtain expected sites, stage/camera convention and landmarks",
            ],
            [
                "IC / calibration / channels",
                "Authenticate correction fields, instrument settings and scale",
            ],
            ["488 identity + ROI ownership", "Complete source-bound review of all required visits"],
            ["Independent final 561", "Review phenotype only after structural eligibility"],
            ["Cohort and matched wells", "Use genuine accepted exports plus exclusion ledger"],
            ["Fate / survival", "Supply independent fate and censoring evidence"],
        ],
        0.6,
        1.7,
        12.1,
        3.6,
        17,
    )
    d.text(
        "Historical exclusions: F05_N025, N05_N011. J05_N015 stays technical-only.\nN012 packet identity/source evidence and other flagged identities remain unresolved.",
        0.7,
        5.55,
        12,
        0.8,
        17,
        RED,
    )
    d.takeaway(
        "The current cohort has zero verified accepted neurons and zero eligible matched pairs."
    )
    d.note(
        "These are the evidence gates that remain after the engineering work. The acquisition expert can resolve geometry, calibration, channel settings and correction provenance. Independent reviewers can resolve identity and ROI ownership before final 561 review. The existing exclusions and technical-only labels remain in place. We should not fill any of these gaps with synthetic fields, guessed transforms, automated approvals or a reinterpretation of QC failure as death.",
        "Specify genuine release blockers and minimal human actions.",
        "No scientific gate cleared by presentation preparation.",
        "No treatment, death, rupture, fibril or survival claim.",
    )
    return d


def generate(project, out):
    project, out = Path(project).absolute(), Path(out).absolute()
    for p in (out, *out.parents):
        if p.is_symlink():
            raise ValueError("Symlink output forbidden")
    forbidden = (
        project / "repo",
        project / "dataset",
        project / "benchmark-local",
        project / "actual-fov-evidence-20261103",
        project / "private-acquisition-20261102",
        project / "review-local",
        project / "review-workspace-20261028",
    )
    code_repository = next(
        (
            p
            for p in Path(__file__).resolve().parents
            if (p / ".git").exists()
            or ((p / "pyproject.toml").is_file() and (p / "src/tmem_align").is_dir())
        ),
        None,
    )
    if code_repository is not None:
        forbidden += (code_repository,)
    if out.exists() or any(
        out.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(out.resolve())
        for p in forbidden
    ):
        raise ValueError("Use a new private output outside source/data trees")
    e = Evidence(project)
    deck = build(e)
    if len(deck.prs.slides) != 20 or any(
        not 60 <= r["narration_words"] <= 120 for r in deck.records[:15]
    ):
        raise ValueError("Slide/notes count contract failed")
    e.finish()
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    pptx = out / (NAME + ".pptx")
    deck.prs.save(pptx)
    (out / "TMEM106B_Presentation_Script.md").write_text(
        "# PI meeting script\n\n15 main slides, approximately 10-15 minutes. Five appendix slides for discussion.\n\n"
        + "\n".join(deck.script)
    )
    with (out / "TMEM106B_Figure_Provenance.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("slide", "label", "embedded_sha256", "binding"))
        writer.writeheader()
        writer.writerows(
            {**r, "binding": json.dumps(r["binding"], ensure_ascii=True)} for r in deck.provenance
        )
    shutil.copyfile(__file__, out / "create_final_pi_presentation.py")
    manifest = {
        "schema_version": "tmem.pi_presentation.v1",
        "slides": deck.records,
        "actual_experimental_graphic_slides": sum(r["actual_graphics"] > 0 for r in deck.records),
        "scientific_visual_slides": sum(r["scientific_visual"] for r in deck.records),
        "metrics": e.metrics(),
        "source_sha256": e.bound,
        "generator_sha256": digest(Path(__file__).read_bytes()),
        "accepted_ids": [],
        "geometry_changed": False,
        "scientific_inference_ready": False,
        "rendering": "PENDING",
        "visual_inspection": "PENDING",
    }
    manifest["outputs_sha256"] = {
        p.name: digest(p.read_bytes()) for p in out.iterdir() if p.is_file()
    }
    (out / "presentation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "TMEM106B_Presentation_Readiness.md").write_text(
        "# Presentation readiness\n\n20 editable slides:15main+5appendix. Actual microscopy on "
        + str(manifest["actual_experimental_graphic_slides"])
        + " slides; meaningful scientific visuals on "
        + str(manifest["scientific_visual_slides"])
        + " slides.\n\n"
        "Source images, display crops, table grids and source hashes verified. No image-processing algorithm rerun, anchor/mask/ROI/QC change or acceptance decision. Original stored-field coordinates remain separate from historical registered atlas coordinates. No physically calibrated scale bar.\n\n"
        "Rendering and full-slide visual inspection PENDING. See the parent's separate final render/review receipt before use. No PowerPoint-native application inspection claimed.\n\n"
        "Remaining science: acquisition extent/geometry, matching detector correction fields/calibration/channel reconciliation, original-to-atlas mapping, independent488identity/ROI review, separate final561 review and an accepted well-level cohort.0/54whole-well mosaics independently validated;0newly accepted biological neurons.\n"
    )
    for p in out.iterdir():
        p.chmod(0o600)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = generate(args.project, args.out)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, "PRESENTATION_BLOCKED: " + str(exc) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "actual_experimental_graphic_slides",
                    "scientific_visual_slides",
                    "rendering",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
