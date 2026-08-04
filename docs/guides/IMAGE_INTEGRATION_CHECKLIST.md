# Image integration checklist

Use this when Irune/John provides the files.

## Before copying data

- [ ] Confirm whether raw files are `.nd2`, exported TIFF, or OME-TIFF.
- [ ] Confirm whether each file is a plate, well, day, tile, multipoint acquisition, or channel.
- [ ] Get the plate map: well → genotype/condition/replicate.
- [ ] Get channel order and names.
- [ ] Get pixel size and z-step.
- [ ] Get tile grid dimensions or stage coordinates.
- [ ] Confirm whether days/timepoints are named consistently.
- [ ] Confirm fluorescence channel mapping; do not assume BrightFocus/brightfield images are needed.
- [ ] Confirm the repeated condition cycle: C/G/K = PLD3 only, D/H/L = PLD3 + TMEM106B, E/I/M = PLD3 + mCherry, F/J/N = PLD3 + TMEM106B + mCherry.

## First test dataset

Choose one small subset:

- [ ] One plate.
- [ ] One mCherry reporter-control well from the E/I/M phase.
- [ ] One primary experimental well from the F/J/N phase.
- [ ] Two or three days across the month.
- [ ] All channels needed for alignment and mCherry phenotype.

## File placement

Use this pattern:

```text
data/raw/Plate001/Day01/Well_A01/
data/raw/Plate001/Day07/Well_A01/
data/raw/Plate001/Day14/Well_A01/
```

## First-pass success criteria

- [ ] Can open raw/exported images.
- [ ] Can stitch one well/day.
- [ ] Can register Day07 and Day14 to Day01.
- [ ] Can crop one neuron ROI.
- [ ] Can make a neuron-centered time stack.
- [ ] Can quantify mCherry puncta and diffuse signal only for wells marked `mcherry_analysis_valid=true`.
- [ ] Can export OME-Zarr or OME-TIFF for sharing/viewing.

## Things to verify manually

- [ ] The same neuron is visible in all selected timepoints.
- [ ] The selected files are fluorescence images, not BrightFocus/brightfield defaults.
- [ ] The alignment channel is not the changing mCherry phenotype if avoidable.
- [ ] The mCherry channel is not saturated.
- [ ] Wells without mCherry are not included as zero-puncta samples.
- [ ] The neuron crop is large enough to include drift and neurites.
- [ ] The output stack scrolls through days in the correct order.
