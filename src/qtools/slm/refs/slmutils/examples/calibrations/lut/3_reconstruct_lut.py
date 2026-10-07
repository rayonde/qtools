# Read and write HoloEye LETO-II LUT

from typing import Mapping, Callable, Any
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from slmutils.generate.lut import write_lut, read_lut


# Identify jumps and clip
xs = np.arange(256)
ys = read_lut("targets/8-5_linear.lut")
new_greys = np.loadtxt("2_process_scans.lut.txt", dtype=np.float64)
new_ys = np.interp(new_greys, xs, ys)

# Linear LUT
linear = read_lut("targets/8-5_linear.lut").T
plt.plot(linear, label="linear")
# ys = read_lut("targets/8-5_lin2,2pi_532nm_0,2-1,4V.lut").T
# plt.plot(ys, label="default 2.2$\\pi$")
ys = read_lut("targets/8-5_lin2pi_532nm_0,2-1,4V.lut").T
plt.plot(ys, label="default 2$\\pi$")
plt.plot(new_ys, label="reconstructed")
plt.legend()
plt.xlabel("Gray level")
plt.ylabel("LUT value")
plt.xticks(np.arange(0, 256 + 64, 64))
plt.ylim(bottom=0, top=linear[-1])
plt.xlim(left=0, right=256)
plt.savefig("3_reconstruct_lut.png", dpi=250)
plt.show()

# Write LUT
write_lut("targets/20260713_reconstructed_lin2pi_532nm_0,2-1,4V.lut", new_ys)


raise
for path in [
    "targets/8-5_linear.lut",
    "targets/8-5_lin2pi_532nm_0,2-1,4V.lut",
    "targets/8-5_lin2,1pi_532nm_0,2-1,4V.lut",
    "targets/8-5_lin2,2pi_532nm_0,2-1,4V.lut",
]:
    label = Path(path).name
    data = read_lut(path)
    plt.plot(*data.T, label=label)

plt.legend()
plt.ylabel("Gamma")
plt.xlabel("Gray level")
plt.show()
