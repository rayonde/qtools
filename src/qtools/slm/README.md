# qtools.slm

SLM phase generation and display control for Holoeye devices and optional
`slmsuite` simulation.

The package uses a small object model:

```text
PhaseRegion (empty, bounded PhaseMask)
        ↓ analytic phase function
PhaseMask (full SLM phase array, radians)
        ↓ to_display()
DisplayMask (device gray levels or RGB transport data)
```

## Quick start

For an actual Holoeye SLM, `monitor=None` selects the secondary display when
available. Set `headless=True` for an in-memory framebuffer.
Monitor numbers are one-based, so `monitor=2` selects the second display
after checking `list_monitors()`.

```python
from qtools.slm import SLM

with SLM("holoeye", monitor=None) as slm:
    phase = slm.create_canvas().lens(f=2.0)
    slm.load_phase(phase)
```

The explicit conversion path is:

```python
display = phase.to_display(bits=8, rgb=False)
slm.load(display)
```

When calling `slm.load()` with a raw NumPy array, it must already be an
integer-valued 8-bit grayscale/RGB image at the SLM resolution. Use an
RGB-packed `DisplayMask` for data above 8 bits.

The device and phase objects expose an `info` property for inspection:

```python
print(slm.info)
canvas = slm.create_canvas()
print(canvas.info)
```

Use `blazed_grating()` for a pixel-periodic phase ramp:

```python
import numpy as np

phase = canvas.blazed_grating(
    period=16,          # 16 pixels per cycle
    angle=90,            # +90 ramps bottom to top; -90 ramps top to bottom
    direction=1,         # 0 -> max_phase; -1 reverses the ramp
    max_phase=2 * np.pi,
    order=None,          # one phase level per pixel by default
)
phase.show()             # inline in Jupyter, system viewer in a terminal
print(phase.info)
```

Here `order=8` or `order=16` means 8 or 16 discrete phase levels per cycle.
`phase.info` includes the pixel period, phase levels and predicted diffraction
angle calculated from the wavelength and pixel pitch.

## Regional phase generation

`create_canvas()` returns the root `PhaseRegion`; there is no separate Canvas
class. Every generated phase mask remains full SLM size, with zero phase
outside its region.

```python
with SLM("holoeye", headless=True) as slm:
    canvas = slm.create_canvas()
    left, right = canvas.partition(axis="x", ratios=(1, 2))

    left_phase = left.spiral(order=1)
    right_phase = right.spiral(order=2)
    combined = canvas.compose(left_phase, right_phase)

    slm.load_phase(combined)
```

## Perfect-vortex phase

Use `perfect_spiral()` for the common axicon-plus-spiral phase used to generate
a perfect vortex beam. `radial_frequency` is in cycles per pixel.

```python
with SLM("holoeye", headless=True) as slm:
    phase = slm.create_canvas().perfect_spiral(
        order=1,
        radial_frequency=0.02,
    )
    slm.load_phase(phase)
```

## Pseudo-knife-edge beam-center scan

`pseudo_knife_edge()` creates a seeded random-phase region and moves its edge
across the selected SLM rectangle. Measure one scalar optical signal at each
edge position (for example, the sum of a camera ROI), then fit the x and y
responses with cumulative Gaussians to obtain the beam center and one-sigma
widths. This measures the selected-channel intensity; it does not find the
bright-pixel centroid directly from the camera image.

```python
from qtools.slm import pseudo_knife_edge

phase = pseudo_knife_edge(
    shape=(1080, 1920),
    bounds=(200, 1720, 100, 980),
    axis="x",
    edge=960,
    seed=0,
)
```

The complete SLM + camera workflow is available as:

```bash
python -m qtools.slm.scripts.find_position \
    --scan-bounds 200 1720 100 980 \
    --roi 0 640 0 480 \
    --step 10 \
    --plot beam_center_scan.png
```

The script displays the x/y masks, captures the camera ROI through
`qtools.camera.Camera`, restores the base phase, and reports the fitted center.
For a power meter or a simulated setup, call `scan_beam_center()` directly
with custom `display_phase` and `measure` callbacks.

## Backends and optional dependencies

Available backends are `holoeye` and `simulated`. The Holoeye backend uses a
bound Qt monitor and supports Holoeye LUT files. The simulated backend imports
`slmsuite` only when `SLM("simulated")` is selected. Iterative algorithm
adapters have the same lazy-import behavior.

The historical implementation and calibration examples remain unchanged under
[`refs/`](refs/).
