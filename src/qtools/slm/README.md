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

## Backends and optional dependencies

Available backends are `holoeye` and `simulated`. The Holoeye backend uses a
bound Qt monitor and supports Holoeye LUT files. The simulated backend imports
`slmsuite` only when `SLM("simulated")` is selected. Iterative algorithm
adapters have the same lazy-import behavior.

The historical implementation and calibration examples remain unchanged under
[`refs/`](refs/).
