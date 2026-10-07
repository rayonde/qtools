
from slmutils.camera.flir import Camera
from slmutils.display.client import display
from slmutils.generate import DEFAULT_DISPLAYMASK
from examples.generate_eyearray import get_mask1, get_mask2, get_vertical_grating

import numpy as np
from tqdm import tqdm, trange
from pathlib import Path

camera = Camera()

# capture background interference pattern
mask = DEFAULT_DISPLAYMASK
for level in trange(0, 256, 8):
    directory = f"wavefront/interference/{level:03d}"
    Path(directory).mkdir(parents=True, exist_ok=True)
    for i in range(10):
        mask = DEFAULT_DISPLAYMASK.flat(level)
        display.load(mask)

        camera.exposure_auto()
        if i == 0:
            camera.save(f"{directory}/{i}.npy", preview=True)
        else:
            camera.save(f"{directory}/{i}.npy")

# mask1
directory = "wavefront/positionmap/mask1"
Path(directory).mkdir(parents=True, exist_ok=True)
for i in trange(20):
    mask = get_mask1()
    display.load(mask)
    if i == 0:
        camera.exposure_auto()
        mask.save(f"{directory}/mask.png")
        camera.save(f"{directory}/{i:03d}.npy", preview=True)
    else:
        camera.save(f"{directory}/{i:03d}.npy")

# mask2
directory = "wavefront/positionmap/mask2"
Path(directory).mkdir(parents=True, exist_ok=True)
for i in trange(20):
    mask = get_mask2()
    display.load(mask)
    if i == 0:
        camera.exposure_auto()
        mask.save(f"{directory}/mask.png")
        camera.save(f"{directory}/{i:03d}.npy", preview=True)
    else:
        camera.save(f"{directory}/{i:03d}.npy")

# grating
for i in range(3):
    for x in trange(15):
        directory = f"wavefront/scan_{i}/{x:02d}"
        Path(directory).mkdir(parents=True, exist_ok=True)
        for level in np.arange(0, 256, 8):
            mask = get_vertical_grating(x, level)
            display.load(mask)

            camera.exposure_auto()
            if level == 0:
                mask.save(f"{directory}/mask.png")
                camera.save(f"{directory}/{level:03d}.npy", preview=True)
            else:
                camera.save(f"{directory}/{level:03d}.npy")
