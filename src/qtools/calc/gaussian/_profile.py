"""Compatibility facade for the original camera Profile workflow."""

import numpy as np

from ._fit import fit
from ._io import read_image, read_raw


class Profile:
    """Load an image, inspect its moments, and call fitted()/fitted_multi_beam()."""

    def __init__(self, data=None, *, pixel_size=1.0, unit="px"):
        self.data = np.array([])
        self.height = self.width = 0
        self.bit_depth = np.dtype("uint8")
        self.mm = {}
        self.fit_data = np.array([])
        self.result = None
        self.pixel_size, self.unit = pixel_size, unit
        if data is not None:
            self.frame2array(data)

    def raw2array(self, raw_filename, bit_depth=8, *, shape=None):
        return self.frame2array(
            read_raw(raw_filename, shape=shape, bit_depth=bit_depth)
        )

    def frame2array(self, frame):
        data = np.array(read_image(frame), copy=True)
        moments = self._moments(data)
        self.data = data
        self.height, self.width = self.data.shape
        self.bit_depth = self.data.dtype
        self.mm = moments
        self.result = None
        self.fit_data = np.array([])
        return self

    def _require_data(self):
        if not self.data.size:
            raise ValueError("Load an image using frame2array() or raw2array() first.")

    def moment(self):
        self._require_data()
        return self._moments(self.data)

    @staticmethod
    def _moments(data):
        weights = np.maximum(data.astype(float) - np.percentile(data, 10), 0)
        weights[weights < weights.max() * 0.1] = 0
        if weights.sum() <= 0:
            raise ValueError("Cannot compute beam moments for a constant image.")
        y, x = np.ogrid[: data.shape[0], : data.shape[1]]
        return {
            f"m{p}{q}": float(np.sum(weights * x**p * y**q))
            for p, q in ((0, 0), (1, 0), (0, 1), (2, 0), (0, 2), (1, 1))
        }

    @property
    def x_bar(self):
        self._require_data()
        return self.mm["m10"] / self.mm["m00"]

    @property
    def y_bar(self):
        self._require_data()
        return self.mm["m01"] / self.mm["m00"]

    @property
    def _covariance(self):
        x, y = self.x_bar, self.y_bar
        cross = self.mm["m11"] / self.mm["m00"] - x * y
        return np.array(
            [
                [self.mm["m20"] / self.mm["m00"] - x * x, cross],
                [cross, self.mm["m02"] / self.mm["m00"] - y * y],
            ]
        )

    @property
    def angle(self):
        covariance = self._covariance
        return float(
            0.5 * np.arctan2(2 * covariance[0, 1], covariance[0, 0] - covariance[1, 1])
        )

    @property
    def eig(self):
        """Moment-based major/minor 4-sigma diameters, in pixels."""
        return tuple(
            4 * np.sqrt(np.maximum(np.linalg.eigvalsh(self._covariance)[::-1], 0))
        )

    @property
    def rowmaxs(self):
        self._require_data()
        return np.arange(self.height), self.data.max(axis=1)

    @property
    def colmaxs(self):
        self._require_data()
        return np.arange(self.width), self.data.max(axis=0)

    def maxrow_col(self):
        self._require_data()
        return tuple(
            int(value)
            for value in np.unravel_index(np.argmax(self.data), self.data.shape)
        )

    def fitted(self, fix_theta=False, **kwargs):
        return self.fitted_multi_beam(fix_theta=fix_theta, **kwargs)

    def fitted_multi_beam(
        self, n_beams=1, threshold_factor=0.1, fix_theta=False, **kwargs
    ):
        self._require_data()
        self.result = fit(
            self.data,
            n_beams=n_beams,
            threshold_factor=threshold_factor,
            fix_theta=fix_theta,
            pixel_size=self.pixel_size,
            unit=self.unit,
            **kwargs,
        )
        self.fit_data = self.result.fitted_image
        return self.result
