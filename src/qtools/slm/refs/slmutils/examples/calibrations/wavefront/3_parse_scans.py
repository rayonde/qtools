import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
import imageio.v3 as iio
import itertools
from scipy.optimize import curve_fit
from tqdm import tqdm
from scipy.fft import rfft, fftfreq

background = np.load("interference/background000.npy")

with open("positionmap/results.txt") as f:
    data = np.loadtxt(f)

ii = data[:,0].astype(np.uint8)
jj = data[:,1].astype(np.uint8)
xs = np.round(data[:,2]).astype(np.uint32)
ys = np.round(data[:,4]).astype(np.uint32)

# Average distance between points
#np.diff(np.mean(xs.reshape(15, -1), axis=1))  # [82.1, 84.0, 86.1, 87.6, 88.8, 89.6, 89.8, 90.2, 90.1, 90.1, 89.0, 88.9, 87.8, 84.6]
#np.diff(np.mean(ys.reshape(-1, 8), axis=0))  # [84.5, 89.5, 90.5, 90.3, 90.2, 89.4, 86.1]

"""
naive strategy:
00 -> [1]
01 -> [0] + [2]
02 -> 1 + 3
...
13 -> 12 + [14]
14 -> 13
"""


def fitfunc(x, f, offset, background, amplitude):
    sinusoid = np.cos((x - offset) * 2 * np.pi * f)
    return amplitude * 0.5 * (sinusoid + 1) + background


def position_to_indexdir(i):
    if i < 2:
        return f"{i+2:02d}"
    else:
        return f"{i-2:02d}"

Path("scan_results_raw").mkdir(exist_ok=True)
scandirs = ["scan_0", "scan_1", "scan_2"]
grays = np.arange(0, 256, 8)
prev_i = None  # cache images :)
images = []
ALLDATA = []
params = zip(ii, jj, xs, ys)
params = tqdm(params, total=len(ii))
for i, j, x, y in params:
    # if i > 0:
    #     continue
    # if i < 14:  # preview...
    #     continue

    # Get all image data
    if prev_i != i:  # new set of images
        subdir = position_to_indexdir(i)
        images = []
        for gray in grays:

            # Average for each gray
            filename = f"{gray:03d}.npy"
            im = None
            for scandir in scandirs:
                path = Path(scandir) / subdir / filename
                data = np.load(path).astype(np.uint16)
                if im is None:
                    im = data
                else:
                    im += data

            # Average and minimize background
            im = im.astype(np.float64) / len(scandirs)# - background
            # if True:
            if i == 14:
                im = im - background
            images.append(im)

    # For each (i, j)
    # width = 80
    if i < 2:
        left = 20
        right = 40
    else:
        left = 40
        right = 20
    # if i < 1:
    #     left = 20
    #     right = 40
    # else:
    #     left = 40
    #     right = 20
    height = 80
    ij_offsets = []
    ij_offsets2 = []
    for gray, image in zip(grays, images):
        # Preview sample
        # fig, ax = plt.subplots()
        # plt.imshow(image)
        # plt.plot(xs, ys, "kx")
        # plt.plot([x], [y], "rx")
        # rect = plt.Rectangle((x - width//2, y - height//2), width, height, edgecolor="red", facecolor="none", lw=1)
        # ax.add_patch(rect)
        # plt.savefig("sample.png")
        # plt.show()

        # Extract square
        im = image[y - height//2:y + height//2, x - left:x + right]
        data = np.mean(im, axis=0)  # squish vertically
        if i < 2:
            # image is reversed
            data = np.flip(data)
        xs = np.arange(len(data))

        # Fit sine
        # fys = np.abs(rfft(data))
        # fxs = fftfreq(len(data))
        # fxs = fxs[:len(fys)-1]
        # fys = fys[:-1]
        # estimated_freq = fxs[1:][np.argmax(fys[1:])]  # exclude DC part
        # print(estimated_freq, 1/22)

        estimated_freq = 1/20  # trial-and-error, or do FFT
        bottom = np.min(data)
        top = np.max(data)
        estimated_amplitude = (top - bottom) / 2  # imbalanced sine
        estimated_background = (1*top + 3*bottom) / 4
        estimated_period = round(1/estimated_freq)
        estimated_offset = xs[np.argmax(data[:estimated_period])]
        p0 = (estimated_freq, estimated_offset, estimated_background, estimated_amplitude)

        fxs = np.arange(len(data) * 250) / 250
        # plt.plot(np.arange(len(data)), data, "kx")
        popt, pcov = curve_fit(fitfunc, xs, data, p0=p0)
        # plt.plot(fxs, fitfunc(fxs, *popt))
        # plt.imshow(im)
        # plt.show()


        amplitude = popt[3]
        # if amplitude <= 0:
        #     # Debug
        #     plt.plot(np.arange(len(data)), data, "kx")
        #     plt.plot(fxs, fitfunc(fxs, *p0), "k--", alpha=0.5)
        #     plt.plot(fxs, fitfunc(fxs, *popt), "r--")
        #     plt.show()
        # assert amplitude > 0  # avoid inverted sinusoids
        period = 1 / popt[0]
        offset = popt[1]
        if amplitude <= 0:
            offset += period / 2  # invert the sinusoid
        offset -= period * (offset // period)  # principal angles
        offset2 = offset + period

        # Visual validation
        # print(i, j, gray)
        plt.plot(np.arange(len(data)), data, "kx")
        plt.plot(fxs, fitfunc(fxs, *p0), "k--", alpha=0.1)
        plt.plot(fxs, fitfunc(fxs, *popt), "r--")
        plt.savefig(f"scan_results_raw/{i}_{j}_{gray}_{offset:.0f}_{offset2:.0f}.png")
        plt.clf()

        # offset = popt[1]
        ij_offsets.append(offset)
        ij_offsets2.append(offset2)


    # print(ij_offsets)
    # plt.plot(ij_offsets)
    # plt.show()
    ALLDATA.append([i, j, *ij_offsets, *ij_offsets2])

data = np.array(ALLDATA, dtype=np.float64)
np.save("scan_results.npy", data)
