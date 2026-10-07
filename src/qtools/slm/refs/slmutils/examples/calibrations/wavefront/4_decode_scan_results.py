import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
import imageio.v3 as iio
import itertools
from scipy.optimize import curve_fit
from tqdm import tqdm
from scipy.interpolate import CubicSpline

from slmutils.generate import PhaseMask, DisplayMask, HoloeyeLETO

slm = HoloeyeLETO(532e-9)
pm = PhaseMask(slm)

def fitfunc(x, offset, background, amplitude):
    sinusoid = np.cos((x - offset) * 2 * np.pi / 256)
    return amplitude * 0.5 * (sinusoid + 1) + background


distilled = []
data = np.load("scan_results.npy")
for i, j, *offsets1_offsets2 in data:
    # if (i, j) != (6, 3):
    #     continue
    ys1 = offsets1_offsets2[:32]
    ys2 = offsets1_offsets2[32:]

    y0 = ys1[0]  # start
    y1 = ys2[0]  # end
    dy = (y1 - y0)
    m = (y1 - y0) / 256
    def linear(x, c):
        return m * x + c

    # Clean up data
    idx = np.flatnonzero(np.diff(ys1) < -4)
    if len(idx) >= 1:
        assert len(idx) == 1
        idx = idx[0] + 1
        ys = np.hstack([ys1[:idx], ys2[idx:]])
    else:
        ys = ys1

    # For i < 2, the overlap with gratings is on the left side, i.e.
    # there is a pi-phase shift. We estimate it by taking half the
    # offset interval 'dy', i.e. 'dy/2' should roughly correspond to pi.
    if i < 2:
        ys = ys - dy/2

    xs = np.arange(0, 256, 8)
    popt, pcov = curve_fit(linear, xs, ys, p0=ys[0])
    offset = popt[0]
    # because offset was not designed to be negative, negative offsets
    # end up underflowing. Since we are fitting a linear curve, doing a
    # manual vertical offset is sufficient to fix it
    if offset > dy * 2/3:
        offset -= dy

    # Convert offset to a phase value
    offset = offset / dy

    # print(int(i), int(j), round(offset, 2))
    # plt.plot(xs, ys1)
    # plt.plot(xs, ys2)
    # plt.plot(xs, ys, "kx")
    # plt.plot(xs, linear(xs, *popt), "r--")
    # plt.show()
    distilled.append([i, j, round(offset, 2)])

distilled = np.array(distilled)
ii, jj, offsets = distilled.T
offsets = offsets.reshape(-1, 8).T
# plt.imshow(offsets)
# plt.colorbar()
# plt.show()


##### INTERPOLATION #####
# Use actual SLM coordinates instead indices now
# Grid coordinates from the initial mask creation
radius = 64
array_width = radius * 2 * 15
array_height = radius * 2 * 8  # should be 1080 as well
xs = np.arange(1, 30, 2) * radius + (1920 - array_width) / 2  # offset
ys = np.arange(1, 16, 2) * radius + (1080 - array_height) / 2

# Target interpolation grid
fxs, fys = np.arange(1920), np.arange(1080)

# Nearest neighbour interpolation
# See: <https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RegularGridInterpolator.html#scipy.interpolate.RegularGridInterpolator>
from scipy.interpolate import RegularGridInterpolator
interp = RegularGridInterpolator((xs, ys), offsets.T, method="nearest", bounds_error=False, fill_value=None)
fxx, fyy = np.meshgrid(fxs, fys)
points = interp((fxx, fyy))
plt.imshow(points)
plt.xlabel("Horizontal pixels")
plt.ylabel("Vertical pixels")
cbar = plt.colorbar()
cbar.set_label("Phase (rad)")
plt.tight_layout()
plt.savefig("20260715_wavefront_full_nearest.phaseplot.NODISPLAY.png")
# plt.show()
plt.clf()

# Save as display
pm.replace(points).to_display().save("20260715_wavefront_full_nearest_normal.png")
pm.replace(-points).to_display().save("20260715_wavefront_full_nearest_inverted.png")

# Bicubic spline interpolation + smoothing
# See: <https://docs.scipy.org/doc/scipy/tutorial/interpolate/smoothing_splines.html#bivariate-spline-fitting-of-scattered-data>
from scipy.interpolate import bisplrep, bisplev
xx, yy = np.meshgrid(xs, ys)
tck = bisplrep(xx, yy, offsets, s=1)  # s chosen heuristically based on resulting feature size
foffsets = bisplev(fxs, fys, tck).T
plt.imshow(foffsets)
plt.xlabel("Horizontal pixels")
plt.ylabel("Vertical pixels")
cbar = plt.colorbar()
cbar.set_label("Phase (rad)")
plt.tight_layout()
plt.savefig("20260715_wavefront_full_interpolated.phaseplot.NODISPLAY.png")
plt.clf()

# Save as display
pm.replace(foffsets).to_display().save("20260715_wavefront_full_interpolated_regular.png")
pm.replace(-foffsets).to_display().save("20260715_wavefront_full_interpolated_inverted.png")
d = pm.replace(foffsets).to_display()
d.array -= np.min(d.array)
d.array = np.round(d.array / np.max(d.array) * 256).astype(np.uint8)
d.save("20260715_wavefront_full_interpolated_regular.highcontrast.NODISPLAY.png")



###### IGNORE LEFT EDGE POINTS  #######
offsets = offsets[:, 1:]
xs = xs[1:]

# Nearest neighbour interpolation
# See: <https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RegularGridInterpolator.html#scipy.interpolate.RegularGridInterpolator>
from scipy.interpolate import RegularGridInterpolator
interp = RegularGridInterpolator((xs, ys), offsets.T, method="nearest", bounds_error=False, fill_value=None)
fxx, fyy = np.meshgrid(fxs, fys)
points = interp((fxx, fyy))
plt.imshow(points)
plt.xlabel("Horizontal pixels")
plt.ylabel("Vertical pixels")
cbar = plt.colorbar()
cbar.set_label("Phase (rad)")
plt.tight_layout()
plt.savefig("20260715_wavefront_lefttrunc_nearest.phaseplot.NODISPLAY.png")
# plt.show()
plt.clf()

# Save as display
pm.replace(points).to_display().save("20260715_wavefront_lefttrunc_nearest_regular.png")
pm.replace(-points).to_display().save("20260715_wavefront_lefttrunc_nearest_inverted.png")

# Bicubic spline interpolation + smoothing + ignore left edge points
# See: <https://docs.scipy.org/doc/scipy/tutorial/interpolate/smoothing_splines.html#bivariate-spline-fitting-of-scattered-data>
from scipy.interpolate import bisplrep, bisplev
xx, yy = np.meshgrid(xs, ys)
tck = bisplrep(xx, yy, offsets, s=1)  # s chosen heuristically based on resulting feature size
foffsets = bisplev(fxs, fys, tck).T
plt.imshow(foffsets)
plt.xlabel("Horizontal pixels")
plt.ylabel("Vertical pixels")
cbar = plt.colorbar()
cbar.set_label("Phase (rad)")
plt.tight_layout()
plt.savefig("20260715_wavefront_lefttrunc_interpolated.phaseplot.NODISPLAY.png")
plt.clf()

# Save as display
pm.replace(foffsets).to_display().save("20260715_wavefront_lefttrunc_interpolated_regular.png")
pm.replace(-foffsets).to_display().save("20260715_wavefront_lefttrunc_interpolated_inverted.png")
d = pm.replace(foffsets).to_display()
d.array -= np.min(d.array)
d.array = np.round(d.array / np.max(d.array) * 256).astype(np.uint8)
d.save("20260715_wavefront_lefttrunc_interpolated_regular.highcontrast.NODISPLAY.png")