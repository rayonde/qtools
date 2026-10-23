# qtools.slm pseudo-knife-edge beam-center scan

## Goal

Add the phase-generation and measurement workflow used by the qlab SLM
alignment notes for a pseudo-knife-edge scan. The feature must generate a
deterministic random-phase region on an SLM, scan that region across the beam,
measure the selected optical signal, and fit the resulting cumulative-Gaussian
curves to obtain the beam center and one-sigma widths in x and y.

## Scope and non-goals

- Add a pure NumPy phase generator under `qtools.slm.phase`.
- Add a reusable, hardware-agnostic scan and fit workflow under
  `qtools.slm.scripts.find_position`.
- Add an optional camera ROI measurement adapter and a runnable FLIR-oriented
  command-line entry point.
- Keep camera SDK imports out of the phase layer and out of module import time.
- Do not implement image-centroid detection; the method measures a scalar
  selected-channel intensity and fits the edge response.
- Do not change the existing SLM backend or camera backend contracts.

## Design

### Phase generation

`qtools.slm.phase.knife_edge.pseudo_knife_edge()` returns an SLM-sized phase
array in radians. It keeps the selected scan rectangle at flat phase and
replaces the part before the supplied edge with reproducible uniform random
phase. The axis is either `x` or `y`; the edge is constrained to the scan
rectangle. A seed makes every edge position use the same underlying random
texture, so only the boundary moves between measurements.

`PhaseRegion.pseudo_knife_edge()` and `PhaseMask.pseudo_knife_edge()` expose
the generator through the fluent phase API. A `PhaseMask` method adds the
randomized region to an existing phase, allowing blaze/lens compensation to
remain present outside the pseudo-knife-edge region.

### Scan and measurement

The scanner receives three hardware-neutral inputs:

```text
display_phase(phase_mask) -> None
measure() -> float
geometry / canvas
```

It creates a phase mask for every x edge and then every y edge, displays it,
waits for the optional settle time, and records one scalar measurement. The
default camera adapter captures one or more frames and sums an optional ROI;
the same scanner can instead use a power-meter or photon-count callback.

The fit model is:

```text
background + amplitude * Phi((edge - center) / sigma)
```

where `Phi` is the standard normal CDF. The sign of `amplitude` is allowed to
be positive or negative because the display and detector coordinate direction
may reverse. The returned center is the CDF midpoint and `sigma` is the fitted
one-sigma beam width.

### Results and plotting

The scan returns a structured result containing x/y centers, widths, raw scan
arrays, and fitted parameters. Plotting is optional. When enabled, the script
renders the x and y measurements together with their cumulative-Gaussian fits
and annotates the fitted centers and widths.

### CLI workflow

`python -m qtools.slm.scripts.find_position` opens the selected SLM and FLIR
camera lazily, runs the scan, prints the result, and optionally saves the
diagnostic plot. Hardware access is only performed when the CLI is executed or
the corresponding adapter is called.

## Validation

Tests cover:

- deterministic seeded phase generation;
- x/y edge orientation and bounds validation;
- fluent phase-mask composition with a base phase;
- cumulative-Gaussian fitting for both curve directions;
- synthetic full x/y scans using fake display and measurement callbacks;
- camera ROI reduction without requiring the FLIR SDK.

