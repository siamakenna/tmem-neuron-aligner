# Napari Viewing Guide

Napari is optional. Command-line processing should work without it, but napari is useful for manual ROI identity review.

## Environment

Use the repo environment that has napari installed:

```bash
source .venv/bin/activate
```

If needed:

```bash
pip install -e ".[viewer]"
```

## Open A Stack

```python
from tmem_align.viewer_napari import open_in_napari

open_in_napari("reports/260213_pilot_20260623_125859/single_neuron_examples/registered_roi_stacks/E05_single_neuron_registered_tcyx.ome.tif")
```

## Recommended Files To Inspect

Raw selected preview:

```text
LOCAL_INTERIM_OUTPUT/pilot/.../*raw_tcyx.ome.tif
```

Registered full-frame stack:

```text
LOCAL_INTERIM_OUTPUT/pilot/.../*registered_tcyx.ome.tif
```

Common-overlap stack:

```text
LOCAL_INTERIM_OUTPUT/pilot/.../*registered_common_overlap_tcyx.ome.tif
```

Neuron-centered ROI stack:

```text
reports/260213_pilot_20260623_125859/single_neuron_examples/registered_roi_stacks/
```

OME-Zarr:

```text
reports/260213_pilot_20260623_125859/single_neuron_examples/ome_zarr/
```

QC montages and metric plots:

```text
LOCAL_PROCESSED_OUTPUT/pilot/registration_qc*
LOCAL_PROCESSED_OUTPUT/pilot/*_longitudinal/
```

## Layering Recommendation

For manual review, load:

- alignment channel as a structural reference layer
- mCherry channel as a phenotype layer
- ROI box or mask as a labels/shapes layer

Use the dashboard well page to find the source well, day list, channel names, and available OME-TIFF/OME-Zarr links.
