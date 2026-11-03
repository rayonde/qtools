# Waveplate Jones Calculus Design

## Scope

Add `qtools.calc.waveplate` as a NumPy-first polarization optics module. The
module models ideal HWP, QWP, arbitrary linear retarders, and ideal PBS
projectors. It supports pure polarization states as Jones vectors and keeps
the low-level matrix form visible to callers.

## API

- `retarder(theta_deg, retardance_deg)` returns a Jones matrix.
- `qwp(theta_deg, retardance_deg=90)` and `hwp(theta_deg)` are named helpers.
- `pbs(axis="H")` returns the ideal H/V or D/A PBS projection matrix.
- `apply(state, elements, return_history=False)` applies matrices in optical
  propagation order; the last element acts last. It accepts a state shaped
  `(2,)` or a batch shaped `(..., 2)`, and returns the propagated Jones state.
- `probability(state, projector)` returns the projected intensity for each
  state, normalized to the input intensity.
- `solve_analyzer_angles(target, architecture=("qwp", "hwp"), axis="H")`
  finds waveplate angles whose PBS analyzer projects onto a target pure state.
  It reports an error when the requested architecture cannot realize that
  state.
- `stokes(state, normalize=True)` returns Stokes vectors with shape `(..., 4)`.
- `bloch(state)` returns normalized polarization Bloch/Poincare coordinates
  `(S1, S2, S3)` with shape `(..., 3)`.

Angle arrays and state batches use NumPy broadcasting. Jones matrix arrays use
shape `(..., 2, 2)`. A history returned by `apply(..., return_history=True)`
contains the input state followed by the state after each element, with shape
`(n_elements + 1, ..., 2)`.

## Conventions

The Jones basis is `(H, V)`. A retarder has fast axis at `theta_deg` and
retardance `retardance_deg`; its matrix is equivalent up to a global phase to
`R(theta) @ diag(1, exp(i*delta)) @ R(theta).T`. `pbs("H")` and `pbs("V")`
project onto horizontal and vertical polarization. `pbs("D")` and `pbs("A")`
use the corresponding 45-degree linear basis. Stokes coordinates are
`S1=|H|^2-|V|^2`, `S2=2 Re(H V*)`, and `S3=2 Im(H V*)`.

## Examples and validation

Add a notebook showing HWP/PBS, QWP/HWP/PBS analyzer architectures, arbitrary
retardance, batch angle scans, and Bloch-sphere trajectories. Add focused tests
for matrix limits, propagation order, PBS probabilities, batch broadcasting,
Stokes/Bloch outputs, and reachable/unreachable analyzer states.
