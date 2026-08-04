# Methods Draft

## Dataset Organization

Raw ND2 files were read in place from the 260213 recopy dataset folder and were not modified.
The pilot selected wells E05 and F05 and the
earliest available fluorescence timepoints: 8, 12, 16.

## Image Loading

ND2 files were opened lazily with the Python `nd2` package. For this pilot, the first site/position
was selected when a position axis was present, and arrays were standardized to `CYX`. Supported
axis patterns include `YX`, `CYX`, `ZCYX`, and common time/position variants after selecting a
single time/position and max-projecting Z when present.

## Channel Selection

The 488 channel was used for registration as a stable non-phenotype channel. The 561 channel was
used for mCherry phenotype measurement. Emergency mCherry-based registration was not used in this
pilot.

## Well/Day Registration

The earliest selected day was used as the reference. Later days were robustly normalized by
background percentile clipping and light Gaussian smoothing, then registered to the reference with
`skimage.registration.phase_cross_correlation` using subpixel upsampling. The resulting X/Y shift
was applied to all channels with linear interpolation, and stacks were cropped to their common
overlap.

## Neuron/ROI Measurement

This pilot uses a whole-field foreground mask rather than validated single-neuron tracking. The
foreground mask is derived from the aligned 488 channel and used to restrict 561/mCherry
measurement.

## Puncta/Diffuse mCherry Quantification

mCherry images were background-subtracted with a low percentile estimate. Puncta candidates were
detected with a Difference-of-Gaussian image and robust median/MAD plus high-percentile threshold.
Connected components were size-filtered. Diffuse intensity was measured as foreground signal
outside puncta. The reported rupture-like score is diffuse integrated intensity divided by
punctate integrated intensity plus epsilon.

## QC And Exclusion Criteria

Registration QC includes estimated shifts, pre/post registration correlation, overlap fraction,
registration error, and a pilot pass/fail flag. Alignments should be manually reviewed before
biological interpretation.

## Statistical Analysis

For this tiny pilot, per-timepoint values and per-well slopes are reported. There are not enough
independent wells/sites/cells for inferential statistics or mixed-effects modeling.

## Software Versions

Core packages: numpy, pandas, scipy, scikit-image, tifffile, matplotlib, and optional nd2. Exact
versions should be captured from the analysis environment for a manuscript supplement.
