"""Creates alternating circle checkerboard pattern for Holoeye LETO-II.

According to the strategy in [1].

References:
    [1]: Fuentes 2011, "Interferometric method for phase calibration in
         liquid crystal spatial light modulators using a self-generated
         diffraction-grating", doi: 10.1364/OE.24.014159
"""

from itertools import product

import numpy as np

from slmutils.generate import HoloeyeLETO, PhaseMask

slm = HoloeyeLETO(532e-9)
width, height = 1920, 1080
display_mask = PhaseMask(slm).to_display()

# Create a 15x8 checkerboard-like circle array
radius = 64
array_width = radius * 2 * 15
array_height = radius * 2 * 8  # should be 1080 as well

# Grid coordinates
xs = np.arange(1, 30, 2) * radius + (1920 - array_width) / 2  # offset
ys = np.arange(1, 16, 2) * radius + (1080 - array_height) / 2

# Construct from subdivided checkerboard
eyes1_coords = list(product(xs[0::2], ys[1::2])) + list(product(xs[1::2], ys[0::2]))
eyes2_coords = list(product(xs[0::2], ys[0::2])) + list(product(xs[1::2], ys[1::2]))


def get_mask1():
    mask = display_mask.random()
    for x, y in eyes1_coords:
        mask = mask.circle(255, radius, x, y)
    return mask


def get_mask2():
    mask = display_mask.random()
    for x, y in eyes2_coords:
        mask = mask.circle(255, radius, x, y)
    return mask


def get_mask12():
    mask = display_mask.random()
    for x, y in eyes1_coords + eyes2_coords:
        mask = mask.circle(255, radius, x, y)
    return mask


def get_vertical_grating(x, level=0):
    offset = (1920 - array_width) / 2  # offset
    left = offset + 2 * radius * x
    right = offset + 2 * radius * (x + 1)
    mask = display_mask.binary(32, level1=255, level2=127).crop(left, right, background=level)
    return mask


if __name__ == "__main__":
    get_mask1().show()
    get_mask2().show()
    get_mask12().show()
