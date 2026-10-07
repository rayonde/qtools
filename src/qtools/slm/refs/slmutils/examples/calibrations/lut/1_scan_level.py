import sys
import time
from pathlib import Path

import numpy as np
import tqdm
import imageio.v3 as iio

from slmutils.generate.phase import DEFAULT_PHASEMASK as pm, DEFAULT_SLM as slm
from slmutils.display.client import display
from slmutils.camera.flir import Camera

class SuppressPrint:
    def __enter__(self):
        self.restore, sys.stdout = sys.stdout, None
    def __exit__(self, *args):
        sys.stdout = self.restore

NUM_REPEATS = 4

camera = Camera()
levels = list(reversed(list(np.arange(256))))
for repeat in range(NUM_REPEATS):
    basedir = Path(f"./scan_level_{repeat}")
    maskdir = basedir / "masks"
    maskdir.mkdir(parents=True, exist_ok=True)

    for level in tqdm.tqdm(levels):
        with SuppressPrint():
            camera.cam.autoexposure(0.8)
        one_third = int(1080 // 3)
        two_third = 1080 - one_third
        phase = pm.replace(slm.random()) \
            .replace(slm.binary(16), left=960, top=one_third) \
            .flip()
        data = slm._phase2gray(phase)
        data[one_third:, 960:] = level
        display.load(data)
        raise
        iio.imwrite(maskdir / f"{level:03d}_mask.png", data)

        time.sleep(0.1)
        target = camera.capture()

        filepath = basedir / f"{level:03d}_result.txt"
        np.savetxt(filepath.with_suffix(".txt"), target, fmt="%4d")
        _target = np.array(target >> 4, dtype=np.uint8)
        iio.imwrite(filepath.with_suffix(".png"), _target)
