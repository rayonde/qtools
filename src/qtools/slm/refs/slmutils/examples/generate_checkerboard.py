"""Creates a checkerboard pattern for Holoeye LETO-II."""

from slmutils.generate.phase import PhaseMask
from slmutils.generate.slm import HoloeyeLETO

slm = HoloeyeLETO(wl=532e-9)
# fmt: off
pm = (
    PhaseMask(slm)
    .add(slm.binary((2, 0)))  # binary grating of period 2 along x-axis
    .add(slm.binary((0, 2)))  # binary grating of period 2 along y-axis
).save("checkerboard.png")
# fmt: on
