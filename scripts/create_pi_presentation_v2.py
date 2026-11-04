"""Corrected full-plate discussion deck from existing bound images and QC receipts."""

import argparse
import json
import shutil
from pathlib import Path

from create_final_pi_presentation import MUTED, RED, TEAL, generate
from pptx.util import Pt

from tmem_align.audit_v1.full_plate import contract_digest, load_contract, plain, sha


def revise(deck, examples, audit, contract, revision="V2"):
    def text_replace(slide, old, new):
        for shape in slide.shapes:
            if shape.has_text_frame and old in shape.text:
                for p in shape.text_frame.paragraphs:
                    for run in p.runs:
                        if old in run.text:
                            run.text = run.text.replace(old, new)

    for slide in deck.prs.slides:
        text_replace(slide, "single neuron", "structural candidate")
    text_replace(
        deck.prs.slides[1],
        "Why follow the same neuron?",
        "Following a structural candidate across visits",
    )
    for i in (0, 1, 9):
        deck.slide = deck.prs.slides[i]
        deck.text(
            "ILLUSTRATIVE / AMBIGUOUS: independent identity and ROI ownership remain unconfirmed.",
            0.55,
            6.3,
            12.1,
            0.25,
            12,
            RED,
        )
    # Show full-field context on the cover in addition to the explicitly curated crop.
    deck.slide = deck.prs.slides[0]
    stem = examples["longitudinal"]["neuron_id"] + "_day08_flow"
    deck.card(stem, 0, 9.0, 1.1, 3.3, 2.0, "488 FOV (unreviewed)")
    deck.provenance[-1]["slide"] = 1
    deck.records[-1]["actual_graphics"] -= 1
    deck.records[0]["actual_graphics"] += 1
    replacements = {
        4: (
            "Full acquisition scope: 192 imaged positions",
            "Saved headers: 1,920 ND2 files. 1,728 fluorescence + 192 separate Day 8 brightfield files.",
            [
                ["Imaged / physical capacity", "192 / 384"],
                ["Fluorescence observations", "192 per day x 9 days"],
                ["Day 8 brightfield", "192, separate modality"],
                ["Physical coverage", "Unresolved; no mosaic certification"],
            ],
        ),
        12: (
            "Full-plate technical QC: " + audit["status"],
            "Grey = QC unavailable. Numbered cells show recorded numeric pass fractions only.",
            None,
        ),
        13: (
            "Nine-day acquisition and QC coverage",
            "Selection completeness, recorded registration QC and biological acceptance are distinct.",
            [
                [
                    str(r["day"]),
                    str(r["expected_wells"]),
                    str(r["qc_observations"]),
                    str(r["missing"]),
                ]
                for r in audit["by_day"]
            ],
        ),
        14: (
            "Current findings and next scientific checks",
            "The active legacy run has no atomic per-well receipts. Do not duplicate it.",
            [
                ["Plate selection", str(audit["selection_rows"]) + " fluorescence visits"],
                ["Durable QC rows", str(audit["qc_rows"]) + "; absence is pending, not failure"],
                ["Independent neuron acceptance", "0 verified in existing cohort"],
                [
                    "Next evidence",
                    "Acquisition geometry / calibration, independent 488 then 561 review",
                ],
            ],
        ),
    }
    for index, (title, subtitle, rows) in replacements.items():
        deck.slide = deck.prs.slides[index]
        for shape in list(deck.slide.shapes):
            el = shape._element
            el.getparent().remove(el)
        deck.text(title, 0.45, 0.25, 12.3, 0.65, 29, bold=True)
        deck.text(subtitle, 0.5, 0.95, 12.2, 0.65, 16, MUTED)
        if index == 12:
            bywell = {r["well"]: r for r in audit["by_well"]}
            for rowno, letter in enumerate("CDEFGHIJKLMN"):
                deck.text(letter, 0.5, 1.7 + rowno * 0.35, 0.3, 0.25, 10)
                for col in range(5, 21):
                    well = f"{letter}{col:02}"
                    record = bywell[well]
                    x = 0.9 + (col - 5) * 0.72
                    y = 1.7 + rowno * 0.35
                    fill = (
                        RED
                        if record["status"] == "FAILED"
                        else "D8E1E9"
                        if record["pass_fraction"] is None
                        else TEAL
                        if record["pass_fraction"] == 1
                        else RED
                    )
                    deck.shape(x, y, 0.66, 0.29, fill)
                    deck.text(
                        "FAILED"
                        if record["status"] == "FAILED"
                        else well
                        if record["pass_fraction"] is None
                        else f"{record['pass_fraction']:.2f}",
                        x + 0.02,
                        y + 0.01,
                        0.62,
                        0.24,
                        8,
                        "182D45"
                        if record["pass_fraction"] is None and record["status"] != "FAILED"
                        else "FFFFFF",
                    )
            deck.text(
                "192 acquired positions C:N / 05:20. Grey does not mean zero performance.",
                0.7,
                6.15,
                11.8,
                0.4,
                17,
            )
        else:
            headers = (
                ["Day", "Expected wells", "Recorded QC", "Missing QC"]
                if index == 13
                else ["Observation", "Evidence / limit"]
            )
            deck.table(headers, rows, 0.65, 1.85, 12, 3.7, 17)
        deck.text(
            "Technical diagnostics only. No whole-well, identity, phenotype or biological acceptance.",
            0.6,
            6.8,
            12,
            0.35,
            14,
            RED,
        )
        deck.records[index]["title"] = title
        deck.records[index]["actual_graphics"] = 0
        deck.provenance = [r for r in deck.provenance if r["slide"] != index + 1]
        addition = (
            "\nWHAT: Full-plate acquisition and recorded technical QC, separate from candidate-level review."
            "\nWHY: Missing QC must not become an artificial zero or an accepted biological result."
            "\nHOW: Read the declared study contract and source-hashed saved tables; no new pixel processing."
            "\nRESULT: "
            + json.dumps(
                {k: audit[k] for k in ("status", "selection_rows", "qc_rows", "missing_tables")}
            )
            + "\nLIMIT: Numeric registration pass counts do not establish physical coverage, identity or phenotype acceptance. Missing outputs remain pending."
            + "\nNEXT CHECK: Authenticate acquisition geometry/channel/correction records and complete independent structural review."
        )
        narration = "This slide separates the acquired plate from the targeted neuron-review panel. The selection has 192 positions and nine visits, while the physical plate has 384 possible wells. Read the recorded technical observations and the missing entries together. A grey cell means the required QC result is not yet available, rather than a failed well or a zero phenotype. Reporter eligibility follows the study row map pending authentication. These receipts do not establish physical coverage or independent identity. The next check is the completed source-bound output and authentic acquisition records."
        deck.slide.notes_slide.notes_text_frame.text = narration + addition
        deck.script[index] = (
            "## " + str(index + 1) + ". " + title + "\n\n" + narration + addition + "\n"
        )
    for chartshape in deck.prs.slides[10].shapes:
        if chartshape.has_chart:
            # Leave room for renderer-independent native category labels.
            chartshape.height = int(3.3 * 914400)
            axis = chartshape.chart.category_axis
            axis.has_title = True
            axis.axis_title.text_frame.text = "Minimum-area preference (px)"
            for p in axis.axis_title.text_frame.paragraphs:
                p.font.name = "Arial"
                p.font.size = Pt(12)
    deck.slide = deck.prs.slides[10]
    for x, width, heading in (
        (0.7, 5.5, "Valid diagnostic visits (count)"),
        (6.9, 5.6, "Gained / lost visits vs 180 (count)"),
    ):
        deck.text(heading, x, 1.44, width, 0.24, 13, MUTED)
        deck.text("Minimum-area preference (px)", x, 5.13, width, 0.24, 13, MUTED)
    for shape in deck.prs.slides[18].shapes:
        if shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    for paragraph in cell.text_frame.paragraphs:
                        for run in paragraph.runs:
                            run.text = run.text.replace(
                                "Fresh branch controls", "Nov 3 branch controls"
                            )
    for shape in deck.prs.slides[19].shapes:
        if shape.has_text_frame and shape.text.startswith("Historical exclusions:"):
            shape.top = int(5.75 * 914400)
            shape.height = int(0.65 * 914400)
    for i, slide in enumerate(deck.prs.slides):
        if i not in (4, 12, 13, 14):
            # Replace the existing footer, avoiding the separate limitation at y=6.99.
            for shape in slide.shapes:
                if shape.has_text_frame and abs(shape.top / 914400 - 7.17) < 0.01:
                    for paragraph in shape.text_frame.paragraphs:
                        for run in paragraph.runs:
                            run.text = "V2: unreviewed structural illustrations; original and registered coordinate streams remain separate."
    if revision == "V3":
        revise_v3(deck, examples, audit, contract)


def validate_segmentation_source(evidence, neuron_id, day):
    """visit_08 is an index, not a day; bind the displayed winning ancestry."""
    source = evidence.sources[neuron_id]
    trace = evidence.load(Path(source["trace"]) / "manifest.json")
    days = trace["metadata"]["expected_days"]
    index = days.index(day)
    stages = {s["stage"]: s for s in trace["stages"]}
    raw = stages[f"visit_{index:02d}_registered_488"]
    prefix = f"primary_segmentation_visit_{index:02d}"
    sheet = evidence.sheets[f"{neuron_id}_day{day:02d}_flow"]
    threshold = sheet["cards"][6]["provenance"]["record"]
    selected = sheet["cards"][12]["provenance"]["record"]
    crop = sheet["cards"][1]["provenance"]["record"]
    winner = threshold["stage"].removesuffix("_threshold")
    if (
        raw["details"].get("day") != day
        or raw["details"].get("time_index") != index
        or raw["channel"] != "488"
        or not winner.startswith(prefix + "_candidate_")
        or threshold["stage"] != winner + "_threshold"
        or prefix + "_smoothed" not in threshold["parents"]
        or selected["stage"] != prefix + "_selected_component"
        or selected["parents"] != [winner + "_selection"]
        or crop["stage"] != prefix + "_crop"
        or crop["array_sha256"] != raw["array_sha256"]
        or stages[threshold["stage"]]["array_sha256"] != threshold["array_sha256"]
        or stages[selected["stage"]]["array_sha256"] != selected["array_sha256"]
    ):
        raise ValueError("Segmentation figure visit/source ancestry mismatch")
    return {
        "day": day,
        "time_index": index,
        "visit_label": f"visit_{index:02d}",
        "threshold_stage": threshold["stage"],
        "selected_stage": selected["stage"],
    }


def revise_v3(deck, examples, audit, contract):
    """Targeted scientific corrections; prior exported V1/V2 remain immutable."""
    nid = examples["segmentation"]["neuron_id"]
    ancestry = validate_segmentation_source(deck.e, nid, 39)

    def reset(index, title, subtitle):
        deck.slide = deck.prs.slides[index]
        for shape in list(deck.slide.shapes):
            shape._element.getparent().remove(shape._element)
        deck.provenance = [r for r in deck.provenance if r["slide"] != index + 1]
        deck.records[index].update(title=title, actual_graphics=0, scientific_visual=True)
        deck.text(title, 0.45, 0.25, 12.3, 0.65, 29, bold=True)
        deck.text(subtitle, 0.5, 0.95, 12.2, 0.55, 16, MUTED)
        deck.text(
            "Registered atlas context, unreviewed. Original ND2 mapping remains unresolved.",
            0.5,
            7.17,
            11.8,
            0.23,
            9.5,
            MUTED,
        )
        deck.text(str(index + 1), 12.55, 7.15, 0.3, 0.25, 10, MUTED)

    def card(index, day, x, y, w, h):
        before = deck.records[-1]["actual_graphics"]
        deck.card(
            f"{nid}_day{day:02d}_flow",
            0,
            x,
            y,
            w,
            h,
            f"{nid}, Day {day}, registered 488 FOV context (unreviewed)",
        )
        delta = deck.records[-1]["actual_graphics"] - before
        deck.records[-1]["actual_graphics"] -= delta
        deck.records[index]["actual_graphics"] += delta
        deck.provenance[-1]["slide"] = index + 1

    for index, title, subtitle in (
        (
            0,
            "TMEM106B longitudinal imaging",
            "Real fields, processing decisions and the evidence still needed",
        ),
        (
            1,
            "Structural context across visits",
            "488 supports identity review. Independent 561 review follows structural eligibility.",
        ),
    ):
        reset(index, title, subtitle)
        if index == 0:
            card(index, 8, 3.7, 1.65, 5.9, 4.65)
        else:
            card(index, 8, 0.65, 1.65, 5.5, 4.5)
            card(index, 39, 6.9, 1.65, 5.5, 4.5)
        deck.text(
            "Context only. No single-neuron identity or ROI ownership is confirmed.",
            0.65,
            6.9,
            12,
            0.26,
            12,
            RED,
        )
        narration = (
            "This broad registered field introduces the imaging context without presenting an ambiguous contour as a confirmed neuron. "
            "The source is the explicitly curated structural example, not a candidate selected from its phenotype. "
            "Its small box is a recorded processing location, not an independently approved identity. "
            "We will inspect enlarged crops and their masks later, including failures and neighboring structures. "
            "The original detector acquisition and the historical registered atlas remain separate coordinate systems. "
            "Independent structural review and authentic acquisition geometry are still required before biological comparison."
        )
        notes = (
            narration
            + "\nWHAT: Broad registered 488 field.\nWHY: Give context without a misleading single-neuron hero.\nHOW: Reuse source-bound saved full-field panel.\nRESULT: Real context only; zero identity acceptance.\nLIMIT: Physical coverage and atlas mapping unresolved.\nNEXT CHECK: Independent 488 identity/ROI review and acquisition records."
        )
        deck.slide.notes_slide.notes_text_frame.text = notes
        deck.records[index]["narration_words"] = len(narration.split())
        deck.script[index] = f"## {index + 1}. {title}\n\n{notes}\n"
    # Correct terminology everywhere, including inherited notes and speaker script.
    substitutions = {
        "V2:": "V3:",
        "192 imaged positions": "192 filename-identified well IDs",
        "192 acquired positions": "192 filename-identified well IDs",
        "Imaged / physical capacity": "Filename IDs / plate capacity",
        "192 positions": "192 filename-identified well IDs",
    }
    for i, slide in enumerate(deck.prs.slides):
        for shape in slide.shapes:
            frames = [shape.text_frame] if shape.has_text_frame else []
            if shape.has_table:
                frames += [cell.text_frame for row in shape.table.rows for cell in row.cells]
            for frame in frames:
                for paragraph in frame.paragraphs:
                    for run in paragraph.runs:
                        for old, new in substitutions.items():
                            run.text = run.text.replace(old, new)
        notes = slide.notes_slide.notes_text_frame.text
        for old, new in substitutions.items():
            notes = notes.replace(old, new)
            deck.script[i] = deck.script[i].replace(old, new)
        slide.notes_slide.notes_text_frame.text = notes
    deck.slide = deck.prs.slides[7]
    explanation = "visit_08 = index 8, ninth visit, Day 39. Threshold ancestry matches this visit."
    deck.text(explanation, 0.65, 1.35, 12, 0.25, 12, MUTED)
    deck.slide.notes_slide.notes_text_frame.text += "\nSOURCE INDEX CHECK: " + json.dumps(ancestry)
    deck.script[7] += "\nSOURCE INDEX CHECK: " + json.dumps(ancestry) + "\n"
    deck.slide = deck.prs.slides[4]
    deck.text(
        "Physical FOV/site coverage unresolved. Zero certified complete-well mosaics.",
        0.65,
        5.9,
        12,
        0.35,
        16,
        RED,
    )
    if audit.get("process_status_observation") != "RUNNING":
        slide = deck.prs.slides[14]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    for run in p.runs:
                        run.text = run.text.replace("The active legacy run", "The legacy run")
    deck.records[4]["title"] = "Full acquisition scope: 192 filename-identified well IDs"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("project", "curation", "plate-audit", "dataset-config", "out"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--revision", choices=["V2", "V3"], default="V2")
    a = p.parse_args()
    input_hashes = {
        str(plain(x)): sha(plain(x)) for x in (a.curation, a.plate_audit, a.dataset_config)
    }
    c = load_contract(a.dataset_config)
    audit = json.loads(plain(a.plate_audit).read_text())
    if (
        audit.get("schema_version") != "tmem.full_plate_audit.v1"
        or audit["expected_wells"] != len(c["wells"])
        or audit["days"] != c["visits"]
        or audit.get("wells") != c["wells"]
        or audit.get("contract_sha256") != contract_digest(c)
        or audit.get("dataset_config_sha256") != sha(a.dataset_config)
        or audit["issues"]
    ):
        raise ValueError("Invalid plate audit")
    for source, h in audit["source_sha256"].items():
        if sha(plain(source)) != h:
            raise ValueError("Plate source changed; create fresh audit")
    generate(
        a.project,
        a.out,
        a.curation,
        lambda d, e: revise(d, e, audit, c, a.revision),
        name="TMEM106B_PI_Meeting_" + a.revision + "_20261104",
    )
    manifest = a.out / "presentation_manifest.json"
    value = json.loads(manifest.read_text())
    value.update(
        schema_version="tmem.pi_presentation." + a.revision.lower(),
        plate_audit_sha256=sha(a.plate_audit),
        dataset_config_sha256=sha(a.dataset_config),
        curation_sha256=sha(a.curation),
        generator_v2_sha256=sha(__file__),
    )
    for path, expected in input_hashes.items():
        if sha(path) != expected:
            raise ValueError("Presentation input changed during export")
    shutil.copyfile(__file__, a.out / "create_pi_presentation_v2.py")
    manifest.write_text(json.dumps(value, indent=2) + "\n")


if __name__ == "__main__":
    main()
