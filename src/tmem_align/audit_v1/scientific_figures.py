"""Readable scientific panels with explicit evidence type, denominators and gaps."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .matched_analysis import DAYS, PAIRS, STATUSES, SYNTHETIC, require, sha256, verify_analysis

WATERMARK = "SYNTHETIC EXAMPLE — NOT EXPERIMENTAL RESULTS"
COLORS = {"reporter_control": "#28799b", "TMEM106B": "#b44c53"}
plt.rcParams.update(
    {
        "font.size": 11,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    }
)


def finish(figure, title, method, synthetic):
    figure.suptitle(title, fontsize=17, fontweight="bold", y=0.985)
    figure.text(0.03, 0.025, method, fontsize=9, va="bottom", wrap=True)
    if synthetic:
        figure.text(0.5, 0.92, WATERMARK, ha="center", color="#a12b35", fontsize=11, weight="bold")
    figure.tight_layout(rect=(0.02, 0.10, 0.98, 0.88))
    return figure


def scalar_image(array, shape=None):
    array = np.asarray(array)
    require(array.ndim == 2 and np.isfinite(array).all(), "Image must be finite YX")
    require(shape is None or array.shape == shape, "Image/mask dimensions differ")
    return array


def registration_figure(reference, moving, aligned, qc, *, synthetic, source):
    require(bool(source), "Image evidence source is required")
    reference = scalar_image(reference)
    moving, aligned = (scalar_image(value, reference.shape) for value in (moving, aligned))
    require(qc.get("registration_channel") == "488", "Registration must be 488-based")
    require(
        all(np.isfinite(qc[field]) for field in ("dy", "dx", "overlap_fraction")),
        "Registration diagnostics are missing",
    )
    figure, axes = plt.subplots(1, 3, figsize=(14, 5))
    low, high = np.percentile(reference, [1, 99.7])
    high = max(high, low + 1)
    for ax, array, label in zip(
        axes,
        (reference, moving, aligned),
        ("Reference 488", "Before alignment", "After alignment"),
        strict=True,
    ):
        ax.imshow(array, cmap="gray", vmin=low, vmax=high)
        ax.set(title=label, xlabel="x (pixels)", ylabel="y (pixels)")
    return finish(
        figure,
        "1 · Follow the same image region over time",
        f"488 transform (dy, dx)=({qc['dy']:.2f}, {qc['dx']:.2f}) px; "
        f"overlap={qc['overlap_fraction']:.1%}; QC={qc.get('qc_pass')}. "
        f"One reference LUT. Source: {source}",
        synthetic,
    )


def segmentation_figure(image, detected, truth, *, synthetic, source, manual_mask=None):
    require(bool(source), "Segmentation evidence source is required")
    image = scalar_image(image)
    for mask in (detected, truth):
        require(
            np.asarray(mask).dtype == bool and np.asarray(mask).shape == image.shape,
            "Masks must be bool and match source image",
        )
    if manual_mask is not None:
        require(
            not synthetic and isinstance(manual_mask, dict) and bool(manual_mask.get("evidence")),
            "Manual mask needs independent reviewed evidence",
        )
        third = np.asarray(manual_mask["mask"])
        require(third.dtype == bool and third.shape == image.shape, "Invalid manual mask")
        third_label = "Human-reviewed mask"
    else:
        require(synthetic, "Real segmentation requires a reviewed comparison mask")
        third, third_label = truth, "Construction truth (not manual review)"
    figure, axes = plt.subplots(1, 3, figsize=(14, 5))
    for ax, array, label in zip(
        axes, (image, detected, third), ("488 image", "Detected mask", third_label), strict=True
    ):
        ax.imshow(array, cmap="gray")
        ax.set(title=label, xlabel="x (pixels)", ylabel="y (pixels)")
    union = np.count_nonzero(detected | third)
    iou = np.count_nonzero(detected & third) / union if union else np.nan
    comparison = "Synthetic target-mask" if synthetic else "Reviewed comparison-mask"
    return finish(
        figure,
        "2 · Check the segmentation against its evidence",
        f"Source: {source}. {comparison} IoU={iou:.3f}; "
        "inspect neighboring cells and boundary support. Pixel units only.",
        synthetic,
    )


def phenotype_figure(raw, stages, *, synthetic, source):
    require(bool(source), "Phenotype evidence source is required")
    raw = scalar_image(raw)
    names = (
        "01_phenotype_roi",
        "02_background_mask",
        "06_size_filtered_puncta",
        "08_diffuse_support",
    )
    for name in names:
        value = np.asarray(stages[name])
        require(value.shape == raw.shape and value.dtype == bool, "Invalid phenotype support")
    roi, _, puncta, diffuse = (np.asarray(stages[name]) for name in names)
    require(
        np.array_equal(roi, puncta | diffuse) and not np.any(puncta & diffuse),
        "Puncta/diffuse partition is invalid",
    )
    figure, axes = plt.subplots(1, 5, figsize=(16, 5))
    arrays = (raw, roi, stages["02_background_mask"], puncta, diffuse)
    labels = (
        "Registered 561",
        "Fixed 488-derived ROI",
        "Background support",
        "Puncta",
        "Diffuse support",
    )
    for ax, value, label in zip(axes, arrays, labels, strict=True):
        ax.imshow(value, cmap="magma" if value is raw else "gray")
        ax.set(title=label, xlabel="x (pixels)")
    return finish(
        figure,
        "4 · Separate punctate and diffuse mCherry",
        f"Source: {source}. Signed DoG → threshold → size filter. "
        "Computational phenotype; mechanism requires separate evidence.",
        synthetic,
    )


def tracking_figure(table, *, synthetic):
    figure, axes = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[3, 1.5])
    statuses = {status: i for i, status in enumerate(STATUSES)}
    for nid, group in table.groupby("neuron_id", sort=True):
        group = group.set_index("day").reindex(DAYS)
        color = COLORS[group.condition.dropna().iloc[0]]
        axes[0].plot(
            DAYS,
            group.mean_mcherry_intensity,
            marker="o",
            color=color,
            alpha=0.7,
            linewidth=1.4,
            label=nid,
        )
        missing = group[group.observation_status != "accepted"]
        axes[1].scatter(
            missing.index,
            [statuses[value] for value in missing.observation_status],
            marker="x",
            color=color,
        )
    axes[0].set(ylabel="Mean mCherry in ROI (ADU / pixel)")
    axes[0].legend(fontsize=8, ncol=4)
    axes[1].set(yticks=list(statuses.values()), yticklabels=list(statuses), xlabel="Imaging day")
    axes[1].tick_params(axis="y", labelsize=8)
    for ax in axes:
        ax.set_xticks(DAYS)
    count = int((table.observation_status == "accepted").sum())
    return finish(
        figure,
        "3 · Nine-day neuron measurements, with missing visits retained",
        f"Accepted observations {count}/{len(table)} expected neuron-visits. "
        "Gaps break lines; lower panel shows status without inventing intensities. No survival inference.",
        synthetic,
    )


def matched_figure(wells, *, synthetic):
    figure, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, (control, experimental) in zip(axes, PAIRS, strict=True):
        for well in (control, experimental):
            group = wells[wells.well == well].set_index("day").reindex(DAYS)
            condition = "reporter_control" if well == control else "TMEM106B"
            ax.plot(
                DAYS,
                group.mean_mcherry_intensity_mean,
                marker="o",
                label=well,
                color=COLORS[condition],
            )
            for day, row in group.iterrows():
                if np.isfinite(row.mean_mcherry_intensity_mean):
                    ax.annotate(
                        f"n={int(row.n_accepted_neurons)}",
                        (day, row.mean_mcherry_intensity_mean),
                        xytext=(0, 6 if well == experimental else -13),
                        textcoords="offset points",
                        ha="center",
                        fontsize=7,
                    )
        ax.set(title=f"{control} / {experimental}", xlabel="Imaging day", xticks=DAYS)
        ax.tick_params(axis="x", labelsize=8)
        ax.margins(y=0.2)
        ax.legend()
    axes[0].set_ylabel("Within-well mean mCherry (ADU / pixel)")
    return finish(
        figure,
        "5 · Compare the three matched well pairs",
        "Each point is a well mean; n labels count contributing neurons. "
        "Biological N ≤ 3 wells/condition or 3 matched pairs. No neuron-pooled error bars.",
        synthetic,
    )


def qc_figure(table, *, synthetic):
    counts = table.observation_status.value_counts().reindex(STATUSES, fill_value=0)
    figure, axes = plt.subplots(1, 2, figsize=(14, 6))
    bars = axes[0].barh(STATUSES, counts.to_numpy(), color="#3c7886")
    axes[0].bar_label(bars, padding=3)
    axes[0].set(xlabel="Neuron-visits", title=f"Observation status · denominator {len(table)}")
    reasons = table[table.observation_status != "accepted"].reason.value_counts()
    axes[1].barh(reasons.index, reasons.to_numpy(), color="#b47863")
    axes[1].set(xlabel="Neuron-visits", title="Reasons for nonaccepted observations")
    axes[1].tick_params(axis="y", labelsize=8)
    return finish(
        figure,
        "7 · Show what entered the analysis and what is still missing",
        "Mutually exclusive observation bins. Fate remains a separate ledger field; "
        "missing fluorescence never supplies a confirmed-death event.",
        synthetic,
    )


def save_figure(figure, root, stem):
    files = []
    for suffix in ("png", "pdf"):
        path = root / f"{stem}.{suffix}"
        figure.savefig(path, dpi=180)
        files.append({"path": path.name, "sha256": sha256(path)})
    plt.close(figure)
    return files


def generate(analysis_path, out, *, image_examples=False):
    tables, provenance, _ = verify_analysis(analysis_path)
    synthetic = provenance["evidence_type"] == SYNTHETIC
    require(not image_examples or synthetic, "Image examples are synthetic-only")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    index = {
        str(number): {"status": "BLOCKED — missing input", "files": []} for number in range(1, 8)
    }
    synthetic_diagnostics = None
    for number, figure in (
        (3, tracking_figure(tables["neuron_longitudinal"], synthetic=synthetic)),
        (5, matched_figure(tables["well_day_summary"], synthetic=synthetic)),
        (7, qc_figure(tables["neuron_longitudinal"], synthetic=synthetic)),
    ):
        index[str(number)] = {
            "status": "SYNTHETIC EXAMPLE" if synthetic else "VERIFIED ACCEPTED INPUTS",
            "files": save_figure(figure, out, f"figure_{number}"),
        }
    if image_examples:
        from .analysis_example import source_script
        from .fixtures import neuron_fixture
        from .reference import alignment_steps, phenotype_steps, renderer
        from .stress_fixtures import stress_fixture

        challenge = stress_fixture("neighboring_somata")
        frame, truth = challenge["reference_cyx"], challenge["target_mask"]
        moving = source_script("exercise_stress_pipeline.py").translated(frame, 4, -6)
        aligned, _, qc = alignment_steps(frame, moving)
        detected, _ = renderer().segment_neuron_in_box(frame[2], 48.0, 44.0, 96, 180)
        punctate, _, punctate_roi = neuron_fixture()
        (phenotype_metrics, _, _, _), stages = phenotype_steps(punctate[1], punctate_roi)
        union = np.count_nonzero(detected | truth)
        synthetic_diagnostics = {
            "registration_known_displacement_yx_px": [4, -6],
            "registration_estimated_shift_yx_px": [qc["dy"], qc["dx"]],
            "registration_error_px": float(np.hypot(qc["dy"] + 4, qc["dx"] - 6)),
            "segmentation_target_mask_iou": float(np.count_nonzero(detected & truth) / union),
            "puncta_detected": int(phenotype_metrics["puncta_count"]),
            "manual_review": "NOT_PERFORMED; construction truth only",
        }
        examples = (
            (
                1,
                registration_figure(
                    frame[2],
                    moving[2],
                    aligned[2],
                    qc,
                    synthetic=True,
                    source="deterministic synthetic488; known shift(4,-6)",
                ),
            ),
            (
                2,
                segmentation_figure(
                    frame[2],
                    detected,
                    truth,
                    synthetic=True,
                    source="neighboring_somata synthetic construction",
                ),
            ),
            (
                4,
                phenotype_figure(
                    punctate[1],
                    stages,
                    synthetic=True,
                    source="three-puncta synthetic benchmark and prescribed 488-truth ROI",
                ),
            ),
        )
        for number, figure in examples:
            index[str(number)] = {
                "status": "SYNTHETIC EXAMPLE",
                "files": save_figure(figure, out, f"figure_{number}"),
            }
    index["6"]["reason"] = (
        "Confirmed longitudinal fate, loss reasons and censoring evidence unavailable; no survival curve generated"
    )
    record = {
        "evidence_type": provenance["evidence_type"],
        "figures": index,
        "analysis_provenance_sha256": sha256(Path(analysis_path) / "analysis_provenance.json"),
        "image_coordinate_units": "pixels; no physical scale bar",
        "watermark": WATERMARK if synthetic else None,
        "figure_code_sha256": sha256(Path(__file__)),
        "synthetic_diagnostics": synthetic_diagnostics,
    }
    (out / "figure_index.json").write_text(json.dumps(record, indent=2) + "\n")
    return record
