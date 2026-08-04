# External Alignment Method Review

Reviewed repository:

```text
https://github.com/petercla0119/align-channels-petrucelli
```

## Access and License

The repository was accessible on GitHub. Its license file states MIT License, copyright 2025 Claire Peterson.

## Conceptual Approach

The project is a multi-channel TIFF registration tool for aligning imaging rounds using a stable nuclei channel as spatial reference. Its README describes translation-only registration with sub-pixel precision, before/after dual-channel QC images, and consistent channel naming where Ch0 is nuclei/DAPI and Ch1 is the protein marker.

The code uses `skimage.registration.phase_cross_correlation` to compute a shift on the nuclei/reference channel, applies that shift to both channels, optionally crops to common overlap, writes aligned TIFF outputs, writes CSV shift logs, and generates visual QC overlays.

## Comparison To Current Pipeline

Current TMEM pipeline already uses phase cross-correlation for translation alignment. The strongest overlap is conceptual:

- use a stable non-phenotype channel for registration
- apply the same shift to phenotype channels
- record shift, error/QC, and parameters
- create before/after QC overlays
- crop to common overlap for quantification to avoid black-border artifacts

This aligns with the TMEM requirement to avoid using changing mCherry puncta as the main registration target.

## Useful Ideas To Adapt

- Add explicit reference-channel naming in every output and QC image.
- Generate paired before/after overlays for both alignment channel and mCherry channel.
- Record registration error/distance alongside dy/dx.
- Try center-region fallback when whole-frame correlation confidence is poor.
- Keep common-overlap crop metadata in machine-readable CSV/JSON.

## Cautions

- The external code is TIFF-oriented and uses eager `tifffile.imread`; it should not be used directly on raw ND2 or full-scale datasets.
- It is translation-only. It cannot correct rotation, scaling, local deformation, or Z-plane mismatch.
- It assumes channel ordering conventions that must be mapped carefully to Nikon ND2 channel names.
- It includes GUI dependencies that are unnecessary for this local-first pipeline.

## Recommendation

Do not vendor external code now. Keep the current pipeline method and adapt the ideas above in small, tested pieces. If later needed, add an optional MIT-attributed utility or dependency only after confirming license attribution requirements and after a pilot shows clear benefit.

Sources:

- GitHub repository page: https://github.com/petercla0119/align-channels-petrucelli
- README: https://raw.githubusercontent.com/petercla0119/align-channels-petrucelli/main/README.md
- License: https://raw.githubusercontent.com/petercla0119/align-channels-petrucelli/main/LICENSE
