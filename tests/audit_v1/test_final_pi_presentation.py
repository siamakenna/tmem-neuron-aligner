"""SOFTWARE_FIXTURE_ONLY controls. No real microscopy or biological labels."""

import base64
import csv
import importlib.util
import io
import json
import stat
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from PIL import Image

pytest.importorskip("pptx", reason="Optional presentation tooling requires python-pptx")
from pptx import Presentation

SPEC = importlib.util.spec_from_file_location(
    "pi_presentation",
    Path(__file__).resolve().parents[2] / "scripts/create_final_pi_presentation.py",
)
pi = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pi)


def png(size=(8, 4)):
    stream = io.BytesIO()
    Image.new("RGB", size, "#246824").save(stream, format="PNG")
    return stream.getvalue()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def svg(images):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg">']
    for i, blob in images:
        parts.append(
            f'<image x="{24 + i % 5 * 330}" y="{158 + i // 5 * 430}" '
            f'href="data:image/png;base64,{base64.b64encode(blob).decode()}"/>'
        )
    return ("".join(parts) + "</svg>").encode()


@pytest.fixture
def private_project(tmp_path):
    project = tmp_path / "SOFTWARE_FIXTURE_ONLY"
    project.mkdir()
    fig = project / "actual-fov-evidence-20261103/figures"
    fig.mkdir(parents=True)
    ids = (
        "E05_N057",
        "E05_N066",
        "F05_N005",
        "F05_N061",
        "I05_N006",
        "I05_N052",
        "J05_N028",
        "J05_N029",
        "M05_N009",
        "M05_N022",
        "N05_N010",
        "N05_N022",
    )
    rendered = (ids[0], ids[6], ids[7], ids[10])
    config = {
        "bbox_size": 128,
        "segmentation": {
            "min_area": 180,
            "consensus_fraction": 0.6,
            "min_core_area": 80,
            "max_core_area": 2500,
            "phenotype_dilation": 2,
            "background_exclusion": 8,
        },
        "tracking": {"template_size": 41, "search_radius": 60, "min_score": 0.25},
    }
    sources, sheets, cases, segs, tracks, views = [], [], [], [], [], []
    for ni, nid in enumerate(ids):
        trace = project / "benchmark-local/tracks" / nid
        write_json(
            trace / "manifest.json",
            {"metadata": {"parameters": config}, "evidence_type": "SOFTWARE_FIXTURE_ONLY"},
        )
        bindings = [
            {
                "day": day,
                "live_crop_exactly_equal": True,
                "anchor_yx_crop_px": [4, 4],
                "anchor_yx_registered_px": [4, 4],
                "bounds": {"y0": 0, "y1": 128, "x0": 0, "x1": 128},
            }
            for day in pi.DAYS
        ]
        sources.append(
            {
                "neuron_id": nid,
                "trace": str(trace),
                "trace_manifest_sha256": pi.digest((trace / "manifest.json").read_bytes()),
                "source_code_matches_current": {"SOFTWARE_FIXTURE_ONLY": True},
                "FOV_bindings": bindings,
            }
        )
        cases.append(
            {
                "neuron_id": nid,
                "original_diagnostic_status": "diagnostic_rejected"
                if ni < 6
                else "diagnostic_complete_pending_review",
                "accepted": False,
                "original_failures_preserved": True,
            }
        )
        for di, day in enumerate(pi.DAYS):
            primary = not (ni in (0, 1) and di == 0)
            for area in (140, 180, 220):
                valid = (
                    (not primary if ni in (0, 1) and di in (0, 1) else primary)
                    if area == 140
                    else True
                    if area == 220
                    else primary
                )
                change = (
                    "neutral_flag"
                    if valid == primary
                    else "gained_diagnostic_flag_not_acceptance"
                    if valid
                    else "lost_diagnostic_flag"
                )
                segs.append(
                    {
                        "neuron_id": nid,
                        "day": day,
                        "minimum_area_px": area,
                        "valid_488_mask": str(valid),
                        "primary_valid_488_mask": str(primary),
                        "flag_change": change,
                        "mask_area_px": area,
                        "mask_IoU_vs_primary": 1 if area == 180 else 0.5,
                        "adopted": "False",
                    }
                )
            for radius in (40, 60, 80):
                tracks.append(
                    {
                        "neuron_id": nid,
                        "day": day,
                        "radius_px": radius,
                        "score": 0.7,
                        "score_pass": "True",
                        "displacement_from_stored_anchor_px": radius / 10,
                        "candidate_change_from_radius60_px": abs(radius - 60),
                        "adopted": "False",
                    }
                )
            for policy in ("visible", "within_range"):
                views.append(
                    {
                        "neuron_id": nid,
                        "day": day,
                        "policy": policy,
                        "interpretation": "smaller_view_support_retained_not_accuracy",
                        "adopted": "False",
                        "measurement_geometry_changed": "False",
                        "frozen_QC_unchanged": "True",
                    }
                )
        if nid not in rendered:
            continue
        for day, kind, count in [
            *(
                (d, k, 25 if k == "flow" else 10)
                for d in (8, 32, 39)
                for k in ("flow", "comparison")
            ),
            (None, "nine_visits", 9),
        ]:
            stem = f"{nid}_day{day:02d}_{kind}" if day is not None else nid + "_nine_visits"
            cards = []
            for index in range(count):
                record = {
                    "stage": "SOFTWARE_FIXTURE_ONLY",
                    "details": {},
                    "parameters": {},
                    "statistics": {"shape": [8, 8]},
                    "why": "Constructed software control only",
                }
                if index == 16:
                    record["details"] = {"bounds_y0_y1_x0_x1": [0, 8, 0, 8]}
                if index == 19:
                    record["details"] = {"correlation_peak_yx": [3, 4]}
                cards.append(
                    {
                        "title": "SOFTWARE_FIXTURE_ONLY",
                        "stage": "SOFTWARE_FIXTURE_ONLY",
                        "status": "executed",
                        "provenance": {"record": record},
                    }
                )
            sheets.append(
                {
                    "stem": stem,
                    "cards": cards,
                    "SVG": stem + ".svg",
                    "trace_manifest_sha256": sources[-1]["trace_manifest_sha256"],
                }
            )
            (fig / (stem + ".svg")).write_bytes(svg([(i, png()) for i in range(count)]))
    write_csv(fig / "segmentation_sensitivity.csv", segs)
    write_csv(fig / "tracking_sensitivity.csv", tracks)
    write_csv(fig / "viewing_comparisons.csv", views)
    write_json(fig / "case_summary.json", {"cases": cases})
    master = [
        {
            "well": well,
            "role": "control" if j == 0 else "TMEM106B",
            "condition": "SOFTWARE_FIXTURE_ONLY",
        }
        for pair in pi.PAIRS
        for j, well in enumerate(pair)
    ]
    write_csv(project / "dataset/master.csv", master)
    write_json(
        project / "dataset/dataset_manifest.json",
        {"master": {"sha256": pi.digest((project / "dataset/master.csv").read_bytes())}},
    )
    handoff = project / "private-acquisition-20261102/pi-handoff-20261102"
    inventory, reg = [], []
    for pair in pi.PAIRS:
        for well in pair:
            parent = project / "private-acquisition-20261102/fields" / well
            write_json(parent / "source_bindings.json", {"evidence_type": "SOFTWARE_FIXTURE_ONLY"})
            write_json(
                parent / "summary.json",
                [
                    {
                        "mode": mode,
                        "strict_common_support_fraction": 0.5,
                        "qc_pass_visits": 9,
                        "total_visits": 9,
                    }
                    for mode in ("to_first", "anchored")
                ],
            )
            for mode in ("to_first", "anchored"):
                image = parent / (mode + ".png")
                image.write_bytes(png((1800, 1800)))
                inventory.append(
                    {
                        "figure_id": well + "_" + mode,
                        "path": str(image),
                        "sha256": pi.digest(image.read_bytes()),
                        "source_binding": str(parent / "source_bindings.json"),
                    }
                )
                reg.extend(
                    {"well": well, "method": mode, "timepoint_day": day, "qc_pass": "True"}
                    for day in pi.DAYS
                )
    write_csv(handoff / "FIGURE_INDEX.csv", inventory)
    write_csv(handoff / "ORIGINAL_FIELD_REGISTRATION_QC.csv", reg)
    for name in ("ACQUISITION_AND_STITCHING_REPORT.md", "NEURON_QC_AND_REVIEW_STATUS.md"):
        (handoff / name).write_text("SOFTWARE_FIXTURE_ONLY")
    report = "\n".join(
        f"|{well}|to_first: 9/9 numeric visit gates; support 0.500; anchored: 9/9 numeric visit gates; support 0.500 |"
        for pair in pi.PAIRS
        for well in pair
    )
    (handoff / "REGISTRATION_VALIDATION.md").write_text(report)
    write_json(
        project / "private-acquisition-20261102/header_summary.json",
        {"target_fluorescence_containers": 54, "evidence_type": "SOFTWARE_FIXTURE_ONLY"},
    )
    (project / "actual-fov-evidence-20261103/CHECKPOINT.md").write_text("SOFTWARE_FIXTURE_ONLY")
    manifest = {
        "schema_version": "tmem.actual_fov_figures.v1",
        "all_proposals_unadopted": True,
        "measurement_geometry_changed": False,
        "accepted_export_written": False,
        "real_accepted_ids": [],
        "scientific_inference_ready": False,
        "sources": sources,
        "sheets": sheets,
        "render_cases": rendered,
        "outputs_sha256": {p.name: pi.digest(p.read_bytes()) for p in fig.iterdir()},
    }
    write_json(fig / "figure_manifest.json", manifest)
    return project


def test_safe_paths_missing_traversal_escape_and_symlinks(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    p = root / "source.txt"
    p.write_text("SOFTWARE_FIXTURE_ONLY")
    assert pi.safe(root, "source.txt") == p
    for bad in ("missing.txt", "../escape", tmp_path / "outside.txt"):
        with pytest.raises(ValueError):
            pi.safe(root, bad)
    (root / "alias").symlink_to(p)
    with pytest.raises(ValueError, match="Symlink"):
        pi.safe(root, "alias")


@pytest.mark.parametrize("value", ["true", "yes", "", None, True, 1])
def test_strict_boolean_rejects_noncontract_values(value):
    with pytest.raises(ValueError):
        pi.boolean(value)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "garbage", True])
def test_measurements_reject_nonfinite_malformed_and_boolean(value):
    with pytest.raises((ValueError, TypeError)):
        pi.number(value)


def test_svg_card_slots_bind_position_not_document_order():
    first, second = png(), png((4, 8))
    assert pi.svg_slots(svg([(6, second), (0, first)]), 7) == {0: first, 6: second}
    with pytest.raises(ValueError, match="Duplicate"):
        pi.svg_slots(svg([(0, first), (0, first)]), 2)
    with pytest.raises(ValueError, match="invalid"):
        pi.svg_slots(svg([(6, first)]), 1)


@pytest.mark.parametrize(
    "blob",
    [
        b'<svg><image x="24" y="158" href="https://example.invalid/a.png"/></svg>',
        b"<!DOCTYPE svg><svg/>",
        b"<svg><script/></svg>",
        b"<svg><foreignObject/></svg>",
    ],
)
def test_svg_external_executable_and_entity_content_rejected(blob):
    with pytest.raises(ValueError):
        pi.svg_slots(blob, 1)


def test_grid_missing_duplicate_setting_and_adoption():
    rows = [
        {"neuron_id": "FIXTURE", "day": day, "radius_px": r, "adopted": "False"}
        for day in pi.DAYS
        for r in (40, 60, 80)
    ]
    pi.grid(rows, {"FIXTURE"}, (40, 60, 80), "radius_px")
    for bad in (rows[:-1], rows + [rows[0]], [{**r, "adopted": "True"} for r in rows]):
        with pytest.raises(ValueError):
            pi.grid(bad, {"FIXTURE"}, (40, 60, 80), "radius_px")


def test_bound_evidence_metrics_preserve_equal_total_gains_and_losses(private_project):
    e = pi.Evidence(private_project)
    metrics = e.metrics()
    assert metrics["areas"][140] == [106, 2, 2]
    assert metrics["areas"][180] == [106, 0, 0]
    assert metrics["areas"][220] == [108, 2, 0]
    assert metrics["views"]["visible"] == [108, 0, 0]
    assert metrics["visits"] == 108
    assert len(e.bound) > 20
    e.finish()
    bound = Path(next(iter(e.bound)))
    bound.write_bytes(bound.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="changed"):
        e.finish()


def test_hash_mismatch_and_input_mutation_fail_closed(tmp_path):
    e = pi.Evidence.__new__(pi.Evidence)
    e.project, e.bound = tmp_path, {}
    p = tmp_path / "source.txt"
    p.write_text("SOFTWARE_FIXTURE_ONLY")
    with pytest.raises(ValueError, match="hash mismatch"):
        e.read(p, "0" * 64)
    e.read(p)
    p.write_text("changed")
    with pytest.raises(ValueError, match="mutated"):
        e.read(p)


@pytest.mark.parametrize(
    "kind", ["accepted", "geometry", "master_role", "bad_flag", "missing_grid"]
)
def test_corrupt_scientific_state_or_metadata_rejected(private_project, kind):
    fig = private_project / "actual-fov-evidence-20261103/figures"
    path = fig / "figure_manifest.json"
    m = json.loads(path.read_text())
    if kind == "accepted":
        m["real_accepted_ids"] = ["SOFTWARE_FIXTURE_ONLY"]
    elif kind == "geometry":
        m["measurement_geometry_changed"] = True
    elif kind == "master_role":
        p = private_project / "dataset/master.csv"
        p.write_text(p.read_text().replace("TMEM106B", "control"))
        declaration = private_project / "dataset/dataset_manifest.json"
        write_json(declaration, {"master": {"sha256": pi.digest(p.read_bytes())}})
    else:
        p = fig / "segmentation_sensitivity.csv"
        if kind == "bad_flag":
            p.write_text(p.read_text().replace("neutral_flag", "invented", 1))
        else:
            p.write_text("\n".join(p.read_text().splitlines()[:-1]) + "\n")
        m["outputs_sha256"][p.name] = pi.digest(p.read_bytes())
    write_json(path, m)
    with pytest.raises(ValueError):
        pi.Evidence(private_project)


def test_executed_slot_missing_vs_recorded_no_view(private_project):
    e = pi.Evidence(private_project)
    stem = next(iter(e.sheets))
    e.slots[stem] = {}
    with pytest.raises(ValueError, match="lacks"):
        e.card(stem, 0)
    e.sheets[stem]["cards"][0]["provenance"] = {
        "parameters": {"proposal": {"interpretation": "failure_no_view"}}
    }
    image, reference = e.card(stem, 0)
    assert image is None and reference["image_sha256"] is None


def test_complete_constructed_deck_embedded_editable_and_private(private_project, tmp_path):
    out = tmp_path / "private-output"
    declaration = explicit_curation(private_project)
    before = {p: pi.digest(p.read_bytes()) for p in private_project.rglob("*") if p.is_file()}
    manifest = pi.generate(private_project, out, declaration)
    prs = Presentation(out / (pi.NAME + ".pptx"))
    assert len(prs.slides) == 20
    assert abs(prs.slide_width / prs.slide_height - 16 / 9) < 0.000001
    assert all(60 <= r["narration_words"] <= 120 for r in manifest["slides"][:15])
    assert manifest["actual_experimental_graphic_slides"] == 10
    assert manifest["scientific_visual_slides"] == 20
    assert manifest["accepted_ids"] == [] and not manifest["geometry_changed"]
    assert manifest["rendering"] == manifest["visual_inspection"] == "PENDING"
    charts = [s.chart for slide in prs.slides for s in slide.shapes if s.has_chart]
    assert len(charts) == 2
    assert all(chart.font.name == pi.FONT for chart in charts)
    for chart in charts:
        all_ids = [int(n.get("val")) for n in chart._chartSpace.iter() if n.tag == pi.qn("c:axId")]
        axis_ids = {
            int(n.get("val"))
            for n in chart._chartSpace.iter()
            if n.tag == pi.qn("c:axId")
            and n.getparent().tag
            in {pi.qn("c:catAx"), pi.qn("c:valAx"), pi.qn("c:dateAx"), pi.qn("c:serAx")}
        }
        cross_ids = [
            int(n.get("val")) for n in chart._chartSpace.iter() if n.tag == pi.qn("c:crossAx")
        ]
        assert all(0 <= n <= 2**32 - 1 for n in [*all_ids, *cross_ids])
        assert axis_ids and cross_ids and set(cross_ids).issubset(axis_ids)
    assert tuple(charts[0].series[0].values) == (106.0, 106.0, 108.0)
    assert sum(s.has_table for slide in prs.slides for s in slide.shapes) >= 7
    assert all(slide.notes_slide.notes_text_frame.text for slide in prs.slides)
    assert all("LIMITATION:" in slide.notes_slide.notes_text_frame.text for slide in prs.slides)
    pictures = [s for slide in prs.slides for s in slide.shapes if s.shape_type == 13]
    assert pictures
    assert all(
        abs(
            s.width / s.height
            - Image.open(io.BytesIO(s.image.blob)).width
            / Image.open(io.BytesIO(s.image.blob)).height
        )
        < 0.0001
        for s in pictures
    )
    with zipfile.ZipFile(out / (pi.NAME + ".pptx")) as archive:
        assert any(n.startswith("ppt/embeddings/") for n in archive.namelist())
        for name in archive.namelist():
            if name.endswith(".rels"):
                assert not any(
                    r.get("TargetMode") == "External" and r.get("Type", "").endswith("/image")
                    for r in ET.fromstring(archive.read(name))
                )
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in out.iterdir())
    assert before == {
        p: pi.digest(p.read_bytes()) for p in private_project.rglob("*") if p.is_file()
    }
    with pytest.raises(ValueError, match="new private output"):
        pi.generate(private_project, out, declaration)


def test_output_overlap_and_cli_invalid_source_rejected(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ValueError, match="outside"):
        pi.generate(project, project / "dataset/forbidden")
    with pytest.raises(SystemExit) as error:
        pi.main(["--project", str(project), "--out", str(tmp_path / "private")])
    assert error.value.code == 2
    assert "--curation" in capsys.readouterr().err


def explicit_curation(project):
    manifest_path = project / "actual-fov-evidence-20261103/figures/figure_manifest.json"
    sources = {
        s["neuron_id"]: s["trace_manifest_sha256"]
        for s in json.loads(manifest_path.read_text())["sources"]
    }
    roles = {
        "longitudinal": "N05_N010",
        "segmentation": "E05_N057",
        "tracking": "J05_N028",
        "ownership_ambiguous": "J05_N029",
    }
    p = project / "curation.json"
    write_json(
        p,
        {
            "schema_version": "tmem.example_curation.v1",
            "figure_manifest_sha256": pi.digest(manifest_path.read_bytes()),
            "selections": {
                role: {
                    "neuron_id": n,
                    "trace_manifest_sha256": sources[n],
                    "status": "AMBIGUOUS",
                    "channel": "488",
                    "rationale": "SOFTWARE_FIXTURE_ONLY",
                    "source_refs": ["constructed"],
                }
                for role, n in roles.items()
            },
        },
    )
    return p


def test_symlink_output_and_unavailable_panel_remain_explicit(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="Symlink output"):
        pi.generate(project, alias / "new")
    deck = pi.Deck(None)
    deck.new("SOFTWARE_FIXTURE_ONLY")
    deck.picture(None, {}, 1, 1, 3, 3, "Recorded no-view failure")
    assert deck.records[0]["actual_graphics"] == 0
    assert not any(s.shape_type == 13 for s in deck.slide.shapes)
    assert any("Evidence unavailable" in s.text for s in deck.slide.shapes if s.has_text_frame)


def test_external_project_cannot_write_into_generator_checkout(tmp_path):
    project = tmp_path / "external-project"
    project.mkdir()
    repository = Path(__file__).resolve().parents[2]
    forbidden = repository / "SOFTWARE_FIXTURE_ONLY-never-created-output"
    assert not forbidden.exists()
    with pytest.raises(ValueError, match="outside source/data trees"):
        pi.generate(project, forbidden)
    assert not forbidden.exists()
