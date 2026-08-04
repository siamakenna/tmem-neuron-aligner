from __future__ import annotations

from pathlib import Path

import click
import pandas as pd

import numpy as np

from .config import ensure_dirs, load_config, load_plate_map, load_roi_annotations, validate_config as validate
from .export_zarr import export_ome_zarr
from .preprocess import calculate_ic_fields_by_timepoint
from .register import register_file_to_reference
from .roi import build_roi_timeseries, roi_from_table
from .stitch import stitch_folder_to_ometiff
from .nd2_tools import build_manifest, extract_nd2_selection, print_nd2_report


@click.group()
def main() -> None:
    """TMEM106B month-long neuron alignment pipeline."""




@main.command("inspect-nd2")
@click.argument("nd2_path")
def inspect_nd2_command(nd2_path: str) -> None:
    """Print axes, channels, positions, and basic metadata for one ND2 file."""
    try:
        print_nd2_report(nd2_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("build-manifest")
@click.argument("raw_root")
@click.option("--output", default="configs/image_manifest.csv", show_default=True)
def build_manifest_command(raw_root: str, output: str) -> None:
    """Inventory all ND2 files below RAW_ROOT without loading full images."""
    try:
        df = build_manifest(raw_root, output_csv=output)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Wrote {output} with {len(df)} rows")


@main.command("extract-nd2")
@click.argument("nd2_path")
@click.argument("output_path")
@click.option("--position", type=int, default=None, help="Zero-based P/position index.")
@click.option("--time", "time_index", type=int, default=None, help="Zero-based T index.")
@click.option("--channel", type=int, default=None, help="Zero-based C index.")
@click.option("--z", "z_index", type=int, default=None, help="Zero-based Z index.")
@click.option("--max-project-z", is_flag=True, help="Maximum-project retained Z planes.")
def extract_nd2_command(
    nd2_path: str,
    output_path: str,
    position: int | None,
    time_index: int | None,
    channel: int | None,
    z_index: int | None,
    max_project_z: bool,
) -> None:
    """Lazily extract a pilot subset from ND2 and save OME-TIFF."""
    try:
        out = extract_nd2_selection(
            nd2_path,
            output_path,
            position=position,
            time=time_index,
            channel=channel,
            z=z_index,
            max_project_z=max_project_z,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Wrote {out}")


@main.command("compute-ic-fields")
@click.argument("plate_dir")
@click.option("--output", default=None, help="Output .npz path (default: <plate_dir>/ic_fields.npz).")
@click.option("--sample-fraction", type=float, default=0.25, show_default=True)
@click.option("--workers", type=int, default=None, help="Parallel processes (default: one per timepoint).")
def compute_ic_fields_command(plate_dir: str, output: str | None, sample_fraction: float, workers: int | None) -> None:
    """Compute per-timepoint illumination correction fields for a plate and save as .npz."""
    plate_path = Path(plate_dir)
    out = Path(output) if output else plate_path / "ic_fields.npz"
    try:
        ic_fields = calculate_ic_fields_by_timepoint(plate_path, sample_fraction=sample_fraction, n_workers=workers)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    np.savez_compressed(out, **ic_fields)
    click.echo(f"Wrote {out} ({len(ic_fields)} timepoints)")
    for name, ic in sorted(ic_fields.items()):
        click.echo(f"  {name}: shape={ic.shape}, range=[{ic.min():.2f}, {ic.max():.2f}]")


@main.command("validate-config")
@click.argument("config_path")
def validate_config_command(config_path: str) -> None:
    cfg = load_config(config_path)
    ensure_dirs(cfg)
    for msg in validate(cfg):
        click.echo(msg)
    plate_map = load_plate_map(cfg)
    click.echo(f"Loaded plate map rows: {len(plate_map)}")


@main.command("stitch")
@click.argument("config_path")
@click.option("--plate", required=True)
@click.option("--well", required=True)
def stitch_command(config_path: str, plate: str, well: str) -> None:
    cfg = load_config(config_path)
    plate_map = load_plate_map(cfg)
    rows = plate_map[(plate_map["plate"] == plate) & (plate_map["well"] == well)]
    if rows.empty:
        raise click.ClickException(f"No rows found for plate={plate}, well={well}")

    stitch_cfg = cfg.raw["stitching"]
    rows_n = stitch_cfg.get("grid_rows")
    cols_n = stitch_cfg.get("grid_cols")
    if not rows_n or not cols_n:
        raise click.ClickException("Set stitching.grid_rows and stitching.grid_cols for the quick grid stitcher, or stitch in Fiji first.")

    for _, row in rows.iterrows():
        raw_path = cfg.root / row["raw_path"] if not Path(row["raw_path"]).is_absolute() else Path(row["raw_path"])
        out = cfg.resolve("paths.interim_root") / "stitched" / plate / row["day"] / f"Well_{well}_stitched.ome.tif"
        stitch_folder_to_ometiff(
            raw_path,
            out,
            int(rows_n),
            int(cols_n),
            float(stitch_cfg.get("tile_overlap_fraction", 0.10)),
            bool(stitch_cfg.get("snake_order", False)),
        )
        click.echo(f"Wrote {out}")


@main.command("register-well")
@click.argument("config_path")
@click.option("--plate", required=True)
@click.option("--well", required=True)
@click.option("--reference-day", default=None)
def register_well_command(config_path: str, plate: str, well: str, reference_day: str | None) -> None:
    raise click.ClickException(
        "register-well is not safe: it registers on a max-projection that includes the mCherry "
        "channel, locking onto illumination instead of cells (500–1400 px garbage shifts, "
        "post-corr ~0.005). Use run_260213_all_wells_batch.py with --ref-mode anchored instead."
    )
    cfg = load_config(config_path)
    plate_map = load_plate_map(cfg)
    rows = plate_map[(plate_map["plate"] == plate) & (plate_map["well"] == well)].copy()
    if rows.empty:
        raise click.ClickException(f"No rows found for plate={plate}, well={well}")

    reference_day = reference_day or cfg.raw["registration"]["reference_day"]
    stitched_root = cfg.resolve("paths.interim_root") / "stitched" / plate
    registered_root = cfg.resolve("paths.interim_root") / "registered_wells" / plate / f"Well_{well}"
    registered_root.mkdir(parents=True, exist_ok=True)

    ref_path = stitched_root / reference_day / f"Well_{well}_stitched.ome.tif"
    if not ref_path.exists():
        raise click.ClickException(f"Reference stitched image not found: {ref_path}")

    shifts = []
    reg_cfg = cfg.raw["registration"]["well_registration"]
    for _, row in rows.sort_values("day").iterrows():
        moving = stitched_root / row["day"] / f"Well_{well}_stitched.ome.tif"
        out = registered_root / f"{row['day']}_registered.ome.tif"
        if row["day"] == reference_day:
            # Registering reference to itself keeps naming consistent.
            ref_out, shift, _ = register_file_to_reference(ref_path, ref_path, out, 1, 0)
        else:
            ref_out, shift, _ = register_file_to_reference(
                ref_path,
                moving,
                out,
                int(reg_cfg.get("upsample_factor", 10)),
                float(reg_cfg.get("max_shift_pixels", 500)),
            )
        shifts.append({"day": row["day"], "path": str(ref_out), "dy": shift[0], "dx": shift[1]})
        click.echo(f"Wrote {ref_out} shift={shift}")

    pd.DataFrame(shifts).to_csv(registered_root / "well_registration_shifts.csv", index=False)


@main.command("make-roi-stack")
@click.argument("config_path")
@click.option("--plate", required=True)
@click.option("--well", required=True)
@click.option("--roi-id", required=True)
def make_roi_stack_command(config_path: str, plate: str, well: str, roi_id: str) -> None:
    cfg = load_config(config_path)
    plate_map = load_plate_map(cfg)
    roi_table = load_roi_annotations(cfg)
    roi = roi_from_table(roi_table, plate, well, roi_id)

    days = list(plate_map[(plate_map["plate"] == plate) & (plate_map["well"] == well)].sort_values("day")["day"])
    registered_root = cfg.resolve("paths.interim_root") / "registered_wells" / plate / f"Well_{well}"
    paths = [registered_root / f"{day}_registered.ome.tif" for day in days]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise click.ClickException(f"Missing registered well files: {missing}")

    out_dir = cfg.resolve("paths.interim_root") / "neuron_rois" / plate / f"Well_{well}" / roi_id
    out = out_dir / f"{roi_id}_registered_timeseries.ome.tif"
    roi_cfg = cfg.raw["registration"]["roi_registration"]
    build_roi_timeseries(
        paths,
        roi,
        out,
        local_register=True,
        upsample_factor=int(roi_cfg.get("upsample_factor", 20)),
        max_shift_pixels=float(roi_cfg.get("max_shift_pixels", 100)),
    )
    click.echo(f"Wrote {out}")


@main.command("quantify")
@click.argument("config_path")
@click.option("--plate", required=True)
@click.option("--well", required=True)
@click.option("--roi-id", required=True)
@click.option("--phenotype-channel-index", type=int, default=None)
def quantify_command(config_path: str, plate: str, well: str, roi_id: str, phenotype_channel_index: int | None) -> None:
    import numpy as np

    from .analysis.mcherry_metrics import MCherryMetricConfig, quantify_mcherry_timeseries
    from .io import read_image

    cfg = load_config(config_path)
    roi_path = cfg.resolve("paths.interim_root") / "neuron_rois" / plate / f"Well_{well}" / roi_id / f"{roi_id}_registered_timeseries.ome.tif"
    if not roi_path.exists():
        raise click.ClickException(f"ROI stack not found: {roi_path}")

    plate_map = load_plate_map(cfg)
    well_rows = plate_map[(plate_map["plate"] == plate) & (plate_map["well"] == well)]
    if well_rows.empty:
        raise click.ClickException(f"No plate-map entry for plate={plate}, well={well}")
    if "mcherry_analysis_valid" in well_rows.columns:
        valid = well_rows["mcherry_analysis_valid"].astype(str).str.lower().isin(["true", "1", "yes"]).any()
        if not valid:
            raise click.ClickException(
                "mCherry puncta/diffusion analysis is not valid for this well. "
                "Use E/F wells or correct the plate map."
            )

    arr = np.asarray(read_image(roi_path))
    arr = np.squeeze(arr)
    if arr.ndim == 2:
        arr = arr[np.newaxis, np.newaxis, :, :]
    elif arr.ndim == 3:
        arr = arr[:, np.newaxis, :, :]

    ch = phenotype_channel_index if phenotype_channel_index is not None else 0
    mcherry_stack = arr[:, ch, :, :]

    qcfg = cfg.raw["quantification"]
    config = MCherryMetricConfig(
        background_percentile=float(qcfg.get("diffuse_percentile_background", 20)),
        min_puncta_area=int(qcfg.get("puncta_min_size_pixels", 6)),
        puncta_sigma_small=float(qcfg.get("puncta_sigma", 1.0)),
    )
    df = quantify_mcherry_timeseries(mcherry_stack, config=config)
    out = cfg.resolve("paths.processed_root") / "measurements" / f"{plate}_Well_{well}_{roi_id}_measurements.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    click.echo(f"Wrote {out}")


@main.command("export-zarr")
@click.argument("config_path")
@click.argument("image_path")
@click.argument("output_zarr")
def export_zarr_command(config_path: str, image_path: str, output_zarr: str) -> None:
    cfg = load_config(config_path)
    chunks = tuple(cfg.raw.get("export", {}).get("zarr_chunks", [])) or None
    out = export_ome_zarr(image_path, output_zarr, chunks=chunks)
    click.echo(f"Wrote {out}")


if __name__ == "__main__":
    main()
