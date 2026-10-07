import sys
import typing
from pathlib import Path

import imageio.v3 as iio
import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
from slmsuite.hardware.cameras.flir import FLIR

from slmutils.generate.display import SUPPORTED_EXTENSIONS
from slmutils.typing import Float, PathLike
from slmutils.utils import show_image


class SuppressPrint:
    def __enter__(self):
        self.restore, sys.stdout = sys.stdout, None

    def __exit__(self, *args):
        sys.stdout = self.restore


class Camera:
    def __init__(self, serial: str = "25354617", pitch_um: float = 3.45):
        self.cam = FLIR(serial=serial, pitch_um=pitch_um)

    @staticmethod
    def info():
        return FLIR.info()

    def exposure_auto(self, fraction: Float = 0.8):
        with SuppressPrint():
            exposure = self.cam.autoexposure(float(fraction))
        return exposure

    def save(self, filename: PathLike, preview: bool = False):
        image = self.capture()
        datafilename, imfilename = Camera._resolve_filename(filename)
        np.save(datafilename, image)
        if preview:
            _image = np.array(image >> 4, dtype=np.uint8)
            iio.imwrite(imfilename, _image)
        return image

    def show(self):
        image = self.capture() >> 4
        image = np.asarray(image, dtype=np.uint8)
        show_image(image)

    def save_image(self, filename: PathLike):
        image = self.capture()
        _image = np.array(image >> 4, dtype=np.uint8)
        iio.imwrite(filename, _image)

    @staticmethod
    def _resolve_filename(filename: PathLike):
        suffix = Path(filename).suffix
        if suffix == ".npy":
            datafilename = filename
            imfilename = f"{filename}.png"
        else:
            datafilename = f"{filename}.npy"
            imfilename = filename
            if suffix not in SUPPORTED_EXTENSIONS:
                imfilename = f"{filename}.png"
        return datafilename, imfilename

    def capture(self):
        image = self.cam.get_image()
        image = typing.cast(npt.NDArray[np.uint16], image)
        return image

    def monitor(self):
        try:
            plt.ion()
            fig, ax = plt.subplots()
            im = self.capture()
            graph = ax.imshow(im)
            while True:
                plt.pause(0.5)
                im = self.capture()
                graph.set_data(im)
                fig.canvas.draw()
        finally:
            plt.ioff()


if __name__ == "__main__":
    camera = Camera()
    camera.exposure_auto()
    camera.show()
