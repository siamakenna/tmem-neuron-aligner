#!/usr/bin/env python3
"""Audit current v2 anchors and curated phenotype calculations without retracking."""
import argparse
from pathlib import Path

import numpy as np

from tmem_align.audit_v1.commands import context, dependency_check, emit_stages, input_record
from tmem_align.audit_v1.contracts import Bounds, require_cyx
from tmem_align.audit_v1.display import LUT, apply_lut_for_display, make_qc_panel
from tmem_align.audit_v1.evidence import Evidence, write_json
from tmem_align.audit_v1.reference import phenotype_steps, renderer

DAYS = [8, 12, 16, 20, 25, 29, 32, 36, 39]


def audit_track(stack, track, neuron_id, out, source, master_path, export_fixtures):
    import pandas as pd
    from scipy.ndimage import binary_fill_holes
    from skimage import morphology

    r = renderer(); track = track.sort_values("time_index").copy()
    if track["time_index"].duplicated().any() or track["day"].tolist() != DAYS:
        raise ValueError(f"{neuron_id}: need exactly the nine expected visits, no duplicate indices")
    if len(track) != 9 or min(stack.shape[-2:]) < 128:
        raise ValueError("Need nine visits and source images at least 128x128")
    boxes, geometry = [], []
    for idx, row in track.iterrows():
        ti = int(row["time_index"])
        if not 0 <= ti < stack.shape[0]: raise ValueError("Time index outside source stack")
        coords = r.square_bounds(float(row.anchor_y), float(row.anchor_x), 128, *stack.shape[-2:])
        bounds = Bounds(*coords); box = bounds.crop(stack[ti]); require_cyx(box)
        boxes.append(box)
        for name, value in zip(["bbox_y0", "bbox_y1", "bbox_x0", "bbox_x1"], coords):
            track.loc[idx, name] = value
        geometry.append(dict(day=int(row.day), time_index=ti, **vars(bounds)))
    boxes = np.stack(boxes)
    masks, valid, seg_meta = r.reconstruct_masks(boxes, track, 2, 128, 180)
    core, required, nvalid, method = r.build_tight_identity_core(masks, valid, .60, 80, 2500)
    roi = binary_fill_holes(morphology.dilation(core, morphology.disk(2))).astype(bool)
    screen = r.screen_secondary_soma(r.build_reference_488(boxes, 2, valid),
                                    search_radius=52., min_distance=14,
                                    peak_ratio_threshold=.55, area_ratio_threshold=.30,
                                    score_threshold=.40)
    params = dict(bbox_size=128, identity_consensus_fraction=.60, phenotype_dilation=2,
                  segmentation_min_area=180, min_core_area=80, max_core_area=2500,
                  background_exclusion=8, puncta_min_size=6)
    provenance = context(neuron_id, "REAL CANDIDATE TRACK: manual identity review required",
                         well=str(track.iloc[0].well), neuron_id=neuron_id, fov=None,
                         inputs=[input_record(source), input_record(master_path)], parameters=params)
    folder = out / neuron_id; folder.mkdir(exist_ok=False)
    write_json(folder / "crop_geometry.json", geometry)
    write_json(folder / "soma_screen.json", vars(screen))
    write_json(folder / "parameters.json", params)
    seg_meta.assign(day=DAYS).to_csv(folder / "segmentation_qc.csv", index=False)
    # Match the reference display limits, fixed over all nine visits for this neuron.
    lut488 = LUT(*r.robust_limits(boxes[:, 2]), color="488", source="reference robust_limits p1/p99.6")
    lut561 = LUT(*r.robust_limits(boxes[:, 1]), color="561", source="reference robust_limits p1/p99.6")
    results = [phenotype_steps(boxes[i, 1], roi) for i in range(len(boxes))]
    corrected_stack = np.stack([result[0][3] for result in results])
    lut_corrected = LUT(0, max(1., float(np.percentile(corrected_stack[:, roi], 99.6))),
                        color="561", source="pooled corrected 561 in phenotype ROI, p99.6")
    write_json(folder / "luts.json", {"488": lut488.metadata(), "561": lut561.metadata(),
                                      "corrected_561": lut_corrected.metadata()})
    e = Evidence(folder / "00_roi", provenance)
    e.stage("01_consensus_vote_count", masks[valid].sum(0), LUT(0, nvalid), channel="488 masks")
    e.stage("02_identity_core", core, LUT(0, 1), channel="488")
    e.stage("03_phenotype_roi", roi, LUT(0, 1), channel="488-derived geometry")
    e.finish(dict(consensus_required=required, valid_visits=nvalid, method=method,
                  single_soma_pass=screen.single_soma_pass, review="MANUAL_REVIEW_REQUIRED"))
    rows = []
    for i, (_, row) in enumerate(track.iterrows()):
        (metrics, puncta, diffuse, corrected), stages = results[i]
        stages = {"identity_488": boxes[i, 2], "adaptive_mask_488": masks[i], **stages}
        ev = Evidence(folder / f"day_{int(row.day):02d}", {**provenance, "day": int(row.day)})
        for name, image in stages.items():
            channel = "488" if "488" in name else "561"
            lut = lut488 if channel == "488" else lut561
            if name in ["03_background_corrected", "09_diffuse_intensity"]: lut = lut_corrected
            if image.dtype == bool: lut = LUT(0, 1, source="boolean support")
            if name.endswith("dog"):
                v = max(float(np.max(np.abs(image))), 1e-6)
                lut = LUT(-v, v, scope="per-stage diagnostic", source="symmetric absolute maximum")
            if name.endswith("labels"):
                lut = LUT(0, max(1, int(image.max())), source="label identifiers, not intensity")
            ev.stage(name, image, lut, channel=channel, parameters=params)
        qc = dict(**metrics, adaptive_valid=bool(valid[i]), single_soma_pass=screen.single_soma_pass,
                  review="MANUAL_REVIEW_REQUIRED")
        ev.finish(qc)
        panel = [apply_lut_for_display(boxes[i, 2], lut488),
                 apply_lut_for_display(boxes[i, 1], lut561)]
        overlay = panel[1].copy(); overlay[puncta] = [255, 255, 0]
        panel += [overlay, apply_lut_for_display(corrected * diffuse, lut_corrected)]
        make_qc_panel(panel, ["488 identity", "Raw 561", "Puncta overlay", "Diffuse intensity"]).save(
            ev.root / "four_panel.png")
        rows.append(dict(neuron_id=neuron_id, well=str(row.well), day=int(row.day), **qc))
    pd.DataFrame(rows).to_csv(folder / "metrics.csv", index=False)
    if export_fixtures:
        np.savez_compressed(folder / "small_fixture.npz", boxes_tcyx=boxes, identity_core=core,
                            phenotype_roi=roi, adaptive_masks=masks, adaptive_valid=valid)
        track.to_csv(folder / "fixture_tracks.csv", index=False)
    return dict(neuron_id=neuron_id, automated_single_soma_pass=screen.single_soma_pass,
                expected_review="exclude_multi_neuron" if neuron_id == "F05_N025" else "review_identity_and_roi",
                manual_decision="", reviewer="", failure_category="", notes="")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--atlas-root", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--neuron-ids", nargs="+", default=["J05_N015", "N05_N011", "F05_N025"])
    p.add_argument("--export-fixtures", action="store_true")
    args = p.parse_args(); dependency_check()
    import pandas as pd
    import tifffile
    master_path = args.atlas_root / "all_neurons_longitudinal_master.csv"
    master = pd.read_csv(master_path)
    args.out.mkdir(parents=True, exist_ok=False)
    reviews, failures = [], []
    for well in dict.fromkeys(nid.split("_")[0] for nid in args.neuron_ids):
        ids = [nid for nid in args.neuron_ids if nid.startswith(well + "_")]
        subset = master[master.neuron_id.isin(ids)]
        if set(subset.neuron_id) != set(ids): raise ValueError(f"Missing IDs for {well}: {ids}")
        sources = subset.source_registered_stack.dropna().unique()
        if len(sources) != 1: raise ValueError(f"Expected one source stack for {well}")
        source = Path(sources[0])
        with tifffile.TiffFile(source) as tif:
            if tif.series[0].axes != "TCYX": raise ValueError("Require explicit TCYX source stack")
            stack = tif.asarray()
        for nid in ids:
            try:
                reviews.append(audit_track(stack, subset[subset.neuron_id == nid], nid, args.out,
                                           source, master_path, args.export_fixtures))
            except Exception as exc:
                failures.append({"neuron_id": nid, "error": str(exc)})
        del stack
    pd.DataFrame(reviews).to_csv(args.out / "manual_review.csv", index=False)
    write_json(args.out / "failures.json", failures)
    if failures: raise SystemExit("Some tracks failed; inspect failures.json. Run is NOT a pass.")
    print(f"Saved to {args.out}. Manual review remains required, especially F05_N025.")


if __name__ == "__main__":
    main()
