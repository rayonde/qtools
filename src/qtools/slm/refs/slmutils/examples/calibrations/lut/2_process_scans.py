from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tqdm
from scipy.fft import rfft, fftfreq
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter

def fitfunc(x, f, offset, background, amplitude):
    sinusoid = np.cos((x - offset) * 2 * np.pi * f)
    return amplitude * 0.5 * (sinusoid + 1) + background

def get_level(path):
    return int(str(path.name).split("_")[-2])

cache_filename = "2_process_scans.txt"

if not Path(cache_filename).exists():
    GREYS = []
    OFFSETS = []
    OFFSETS2 = []
    dirpaths = ["scan_level_0", "scan_level_1", "scan_level_2", "scan_level_3"]
    for dirpath in dirpaths:
        greys = []
        GREYS.append(greys)
        offsets = []
        OFFSETS.append(offsets)
        offsets2 = []
        OFFSETS2.append(offsets2)
        paths = sorted(Path(dirpath).glob("*.txt"), key=get_level)
        estimated_freq = None
        for path in tqdm.tqdm(paths):
            grey = get_level(path)
            data = np.loadtxt(path)
            data = data[360:820, 470:982]
            # plt.imshow(data); plt.show()

            # Vertically average
            data = np.mean(data, axis=0)
            # plt.plot(data, "x-"); plt.show()

            # Estimate frequency
            ys = data
            xs = np.arange(len(data))
            if estimated_freq is None:
                fys = np.abs(rfft(ys))  # pyright: ignore[reportArgumentType]
                fxs = fftfreq(len(ys))
                fxs = fxs[:len(fys)-1]
                fys = fys[:-1]
                estimated_freq = fxs[1:][np.argmax(fys[1:])]  # exclude DC part
            estimated_background = np.min(ys)
            estimated_amplitude = np.max(ys) - estimated_background
            estimated_period = round(1/estimated_freq)
            estimated_offset = xs[np.argmax(ys[:estimated_period])]
            # print(estimated_freq)
            # plt.plot(fxs, fys, "x-"); plt.show()

            # Fitting
            p0 = (estimated_freq, estimated_offset, estimated_background, estimated_amplitude)
            popt, pcov = curve_fit(fitfunc, xs, ys, p0=p0)
            ixs = np.linspace(xs[0], xs[-1], 400)
            # p, = plt.plot(xs, ys, "x")
            # plt.plot(ixs, fitfunc(ixs, *p0), "--", c="grey")
            # plt.plot(ixs, fitfunc(ixs, *popt), "--", c=p.get_color())#; plt.show()

            # Extract offset
            amplitude = popt[3]
            assert amplitude > 0  # avoid inverted sinusoids
            period = 1 / popt[0]
            offset = popt[1]
            offset -= period * (offset // period)  # principal angles
            offset2 = offset + period

            print(grey, offset)
            greys.append(grey)
            offsets.append(offset)
            offsets2.append(offset2)

    _GREYS = np.mean(np.array(GREYS), axis=0)
    _GREYS_ERR = np.std(np.array(GREYS), axis=0, ddof=1)
    _OFFSETS = np.mean(np.array(OFFSETS), axis=0)
    _OFFSETS_ERR = np.std(np.array(OFFSETS), axis=0, ddof=1)
    _OFFSETS2 = np.mean(np.array(OFFSETS2), axis=0)
    _OFFSETS2_ERR = np.std(np.array(OFFSETS2), axis=0, ddof=1)
    np.savetxt(cache_filename, np.array(
        [_GREYS, _OFFSETS, _OFFSETS2, _GREYS_ERR, _OFFSETS_ERR, _OFFSETS2_ERR]
    ).T)

data = np.loadtxt(cache_filename)
_GREYS, _OFFSETS, _OFFSETS2, _GREYS_ERR, _OFFSETS_ERR, _OFFSETS2_ERR = data.T

plt.plot(_GREYS, _OFFSETS, "x", label="raw")

filtered = savgol_filter(_OFFSETS, window_length=30, polyorder=2)
filtered = np.asarray(filtered, dtype=np.float64)
plt.plot(_GREYS, filtered, "-", label="smoothed")

_GREYS_ORIG = _GREYS.copy()
_GREYS[85:92] = None
_OFFSETS[85:92] = None
_OFFSETS[92:] = _OFFSETS2[92:]  # loop-over
_OFFSETS_ERR[92:] = _OFFSETS2_ERR[92:]
plt.errorbar(_GREYS, _OFFSETS, _OFFSETS_ERR, fmt="x", label="cleaned")
plt.xlabel("Grey level")
plt.ylabel("Interference curve offset")
plt.title("LUT linearity (using linear LUT)")
plt.legend()
plt.savefig("2_process_scans.png")
plt.clf()

# Find point where phase is 2pi
import bisect
from scipy.signal import medfilt
start = filtered[0]  # phase 0 rad
idx = bisect.bisect_right(filtered, start, lo=150)
grey_2pi = np.interp(start, filtered[idx-1:idx+1], _GREYS[idx-1:idx+1])

# Identify point on smoothed actual curve
filtered = savgol_filter(_OFFSETS, window_length=30, polyorder=2)
filtered = np.asarray(filtered, dtype=np.float64)
offset_2pi = np.interp(grey_2pi, _GREYS, filtered)  # map to actual curve
# plt.plot(_GREYS_ORIG, filtered)

# We know the offset is linear in phase, so we have:
offset_0pi = filtered[0]
grey_0pi = 0
def map_offset(offsets):
    return (offsets - offset_0pi) / (offset_2pi - offset_0pi)

# Filter along discontinuities
leftpiece = savgol_filter(_OFFSETS[:85], window_length=30, polyorder=2)
rightpiece = savgol_filter(_OFFSETS[92:], window_length=30, polyorder=2)
midpiece = np.interp(np.arange(85, 92), [84, 92], [leftpiece[-1], rightpiece[0]])
filtered = list(leftpiece) + list(midpiece) + list(rightpiece)
filtered = np.asarray(filtered, dtype=np.float64)
# plt.plot(_GREYS[:85], leftpiece)
# plt.plot(_GREYS[92:], rightpiece)
# offset_0pi
# plt.plot(_GREYS_ORIG, filtered)
# plt.plot(_GREYS, medfilt(_OFFSETS, 9))
# plt.plot(_GREYS, filtered)
# plt.show()

# Finally map offsets
filtered2 = map_offset(filtered)  # [offset_0pi, offset_2pi] -> [0, 1]
plt.plot(_GREYS_ORIG, filtered2)
new_greys = np.interp(np.linspace(0, 1, 256), filtered2[:235], _GREYS_ORIG[:235])
plt.plot(new_greys, np.interp(new_greys, _GREYS_ORIG, filtered2))
plt.show()

np.savetxt("2_process_scans.lut.txt", new_greys)


# end =