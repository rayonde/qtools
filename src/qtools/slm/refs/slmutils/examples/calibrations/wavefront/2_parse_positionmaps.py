import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
import imageio.v3 as iio
import itertools
from scipy.optimize import curve_fit

from kochen.fitutil import fit, gaussian_bg, estimate_gaussian_params

#### GET INTERFERENCE PATTERN ####

def get_image(dirpath):
    im = None
    paths = list(Path(dirpath).glob("*.npy"))
    for path in paths:
        if im is None:
            im = np.load(path).astype(np.uint32)
        else:
            im += np.load(path).astype(np.uint32)
    assert im is not None
    return im.astype(np.float64) / len(paths)

# im_all = np.mean([get_image(path) for path in dirpath.glob("00*")], axis=0)
im1 = get_image("interference/000")
# np.save("interference/background000.npy", im1)


#### ANALYZE POSITION ####

def camera_to_image(array):
    array = array.astype(np.uint16) >> 4
    return array.astype(np.uint8)

im2 = get_image("positionmap/mask1")
np.save("positionmap/mask1.npy", im2)
iio.imwrite("positionmap/mask1.png", camera_to_image(im2))
im3 = get_image("positionmap/mask2")
np.save("positionmap/mask2.npy", im3)
iio.imwrite("positionmap/mask2.png", camera_to_image(im3))
im4 = (im2 + im3) / 2
np.save("positionmap/mask.npy", im4)
iio.imwrite("positionmap/mask.png", camera_to_image(im4))
# plt.imshow(im4)
# plt.show()


# Crop out grid
im5 = im4[210:890, 75:1360]  # initial offsets!
height, width = im5.shape
unit_height = height // 8
unit_width = width // 15
im6 = im5[:unit_height, :unit_width]

f = open("positionmap/results.txt", "w")
Path("positionmap/results").mkdir(exist_ok=True)
# fig, axs = plt.subplots(8, 15)
for i, j in itertools.product(range(15), range(8)):
    fig, axs = plt.subplots(2, 2)#, sharex=True, sharey=True)
    im = im5[j*unit_height:(j+1)*unit_height, i*unit_width:(i+1)*unit_width]
    # axs[0][0].imshow(im)
    axs[1][1].pcolormesh(im)

    # fit along x
    imx = np.max(im, axis=0)
    xs = np.arange(len(imx))
    fxs = np.arange(len(imx) * 250) / 250
    p0 = estimate_gaussian_params(xs, imx)
    popt, labels = fit(gaussian_bg, xs, imx, errors=True, labels=True, p0=p0)
    xpos = popt[1] + i*unit_width + 75  # plus initial offsets
    popt = [x.n for x in popt]
    axs[0][1].plot(fxs, gaussian_bg(fxs, *popt))

    # fit along x
    imy = np.max(im, axis=1)
    ys = np.arange(len(imy))
    fys = np.arange(len(imy) * 250) / 250
    p0 = estimate_gaussian_params(ys, imy)
    popt, labels = fit(gaussian_bg, ys, imy, errors=True, labels=True, p0=p0)
    ypos = popt[1] + j*unit_height + 210  # plus initial offsets
    popt = [x.n for x in popt]
    axs[1][0].plot(-gaussian_bg(fys, *popt), fys)

    print(i, j, xpos, ypos)
    f.write(f"{i}\t{j}\t{xpos.n:.2f}\t{xpos.s:.2f}\t{ypos.n:.2f}\t{ypos.s:.2f}\n")

    plt.savefig(f"positionmap/results/{i:02d}_{j:02d}_{xpos.n:.0f}_{ypos.n:.0f}.png")
    plt.close()

f.close()
# plt.show()
# plt.imshow(im5)
# plt.show()