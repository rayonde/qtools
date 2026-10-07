import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit
from scipy.stats import chisquare

xs = np.arange(256)
fxs = np.linspace(0, 256, 300)

def func(x, offset, amplitude, background):
    sinusoidal = np.cos((x - offset) * 2 * np.pi / 256)
    return amplitude * 0.5 * (1 - sinusoidal) + background

fig, ax = plt.subplots(figsize=(5,3))

data = np.loadtxt("4_scan_default2pi.txt")
ys, yerrs = data.T * 1e6
yerrs[:6] = 0  # only for clarity of data presentation, probably from hiV -> loV transition
plt.errorbar(xs, ys, yerrs, linewidth=1, label="default 2$\\pi$")
p0 = (0, np.max(ys) - np.min(ys), np.min(ys))
popt, pcov = curve_fit(func, xs, ys, p0=p0)
# goodness = chisquare(ys, func(xs, *popt)).statistic
plt.plot(fxs, func(fxs, *popt), "--", alpha=0.5, color="tab:blue")#, label=f"reconstructed: {goodness}")

data = np.loadtxt("4_scan_reconstructed.txt")
ys, yerrs = data.T * 1e6
plt.errorbar(xs, ys, yerrs, linewidth=1, color="tab:orange", label="reconstructed")
p0 = (0, np.max(ys) - np.min(ys), np.min(ys))
popt, pcov = curve_fit(func, xs, ys, p0=p0)
# goodness = chisquare(ys, func(xs, *popt)).statistic
plt.plot(fxs, func(fxs, *popt), "--", alpha=0.5, color="tab:orange")#, label=f"reconstructed: {goodness}")

plt.xlabel("Gray level")
plt.ylabel("Power (uW)")
plt.ylim(bottom=0)
plt.legend()

plt.tight_layout()
plt.savefig("5_plot_PBS_phase.png", dpi=250)
plt.show()