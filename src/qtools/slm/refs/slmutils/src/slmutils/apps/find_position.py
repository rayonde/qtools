import bisect
import time
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
from scipy.special import erf
from tqdm import tqdm

from slmutils.generate import DisplayMask
from slmutils.typing import Float, Integer


def scan(
    refmask: DisplayMask,
    measure: Callable[[DisplayMask], Float],
    left: Integer | Float,
    right: Integer | Float,
    top: Integer | Float,
    bottom: Integer | Float,
    step: Integer = 5,
    plot: bool | str = False,
):
    """Perform a knife-edge equivalent scan to identify beam center.

    If 'left', 'right', 'top' and 'bottom' are given fractional values between
    0 and 1, these will be interpreted as fractions of the corresponding mask
    width and height.

    Args:
        refmask: Mask with dimensions compatible with target slm.
        measure: Function of signature 'mask -> transmission_measurement'.
        left: Left side of scan window, in pixel units.
        right: Right side of scan window, in pixel units.
        top: Top of scan window, in pixel units.
        bottom: Bottom of scan window, in pixel units.
        step: Number of steps between measurements, in pixel units.
        plot: Whether to plot fit functions, or provide filename for plot.

    Returns:
        x: Center coordinate along x-axis.
        y: Center coordinate along y-axis.
        wx: 1-sigma width along x-axis.
        wy: 1-sigma width along y-axis.
    """
    assert right > left
    assert bottom > top
    h, w = refmask.array.shape

    # Convert from fractional units
    if 0 <= left <= 1 and 0 <= right <= 1:
        left = left * w
        right = right * w
    if 0 <= top <= 1 and 0 <= bottom <= 1:
        top = top * h
        bottom = bottom * h
    left = int(round(left))
    right = int(round(right))
    top = int(round(top))
    bottom = int(round(bottom))

    # Sanity check by flashing the screen
    measure(refmask.random())  # random
    measure(refmask.flat())  # flat
    _mask = refmask.flat().replace(refmask.random(), left=left, right=right, top=top, bottom=bottom)
    measure(_mask)  # covered
    time.sleep(1)

    # Scan x-axis
    xs = np.arange(left, right + step, step)
    xx = []
    pbar = tqdm(xs)
    for x in pbar:
        _mask = refmask.flat().replace(refmask.random(), left=left, right=x, top=top, bottom=bottom)
        power = measure(_mask)
        xx.append(power)
        pbar.set_description(f"x={x}, z={power:.2e}")
    xx = np.array(xx)
    xpopt = fit(xs, xx)

    # Scan y-axis
    ys = np.arange(top, bottom + step, step)
    yy = []
    pbar = tqdm(ys)
    for y in pbar:
        mask = refmask.flat().replace(refmask.random(), left=left, right=right, top=top, bottom=y)
        power = measure(mask)
        yy.append(power)
        pbar.set_description(f"y={y}, z={power:.2e}")
    yy = np.array(yy)
    ypopt = fit(ys, yy)

    measure(refmask.flat())  # restore flat profile

    # Terminate here if no plotting required
    x, wx = xpopt[:2]
    y, wy = ypopt[:2]
    if plot is False:
        return x, y, wx, wy

    # Optional plotting for quick debug
    filename = "scan_beamposition.png"
    fig, axs = plt.subplots(2, 1, figsize=(5, 4))
    if type(plot) is str:
        filename = plot

    plt.sca(axs[0])
    label = f"$\\mu_x = {xpopt[0]:.1f}$, $\\sigma_x={xpopt[1]:.1f}$"
    plt.plot(xs, xx, "x", c="tab:blue", label=label)
    plt.plot(xs, error_function(xs, *xpopt), "k--", linewidth=1)
    plt.legend()

    plt.sca(axs[1])
    label = f"$\\mu_y = {ypopt[0]:.1f}$, $\\sigma_y={ypopt[1]:.1f}$"
    plt.plot(ys, yy, "x", c="tab:orange", label=label)
    plt.plot(ys, error_function(ys, *ypopt), "k--", linewidth=1)
    plt.legend()

    plt.tight_layout()
    plt.savefig(filename, dpi=250)

    return x, y, wx, wy


def error_function(x, offset, sigma, amplitude, background):
    def phi(z):
        return 0.5 * (erf(z / np.sqrt(2)) + 1)

    return amplitude * phi((x - offset) / sigma) + background


def fit(xs, ys):
    est_amplitude = ys[-1] - ys[0]
    est_background = ys[0]
    q25 = est_amplitude / (np.e**2) + est_background
    q50 = est_amplitude / 2 + est_background
    if est_amplitude < 0:
        i25 = bisect.bisect_right(-ys, -q25)
        i50 = bisect.bisect_right(-ys, -q50)
    else:
        i25 = bisect.bisect_right(ys, q25)
        i50 = bisect.bisect_right(ys, q50)
    est_sigma = abs(xs[i25] - xs[i50])
    est_offset = xs[i50]
    p0 = (est_offset, est_sigma, est_amplitude, est_background)
    popt, _ = curve_fit(error_function, xs, ys, p0=p0)
    return popt
