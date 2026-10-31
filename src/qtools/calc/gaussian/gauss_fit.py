"""
2D Gaussian beam fitting for camera RAW and common image formats.

Example
-------
profile = Profile("beam.bmp")
result = profile.fit(n_beam=1, pixel_size=3.25, zoom=True, fix_xy=True)
pprint(result)
result.plot(save=True)
"""

import argparse
import os
import pprint

import cv2
import matplotlib.pyplot as plt
import numpy as np
from lmfit import Model, Parameters
from matplotlib.patches import Ellipse
from matplotlib.transforms import Bbox
from scipy import ndimage
from scipy.ndimage import maximum_filter


DEFAULT_PIXEL_SIZE_UM = 5.0
DEFAULT_LOCAL_SIZE = 50
DEFAULT_MIN_DISTANCE = 200
MAX_FIT_POINTS = 50000
IMAGE_EXTENSIONS = {
    '.bmp', '.png', '.tif', '.tiff', '.jpg', '.jpeg',
    '.pgm', '.ppm', '.pnm', '.webp',
}


def gauss_flat(x, amplitude, xo, yo, sigma_x, sigma_y, theta, offset):
    """2D rotated Gaussian model."""
    x1 = x[:, 0]
    x2 = x[:, 1]
    theta = -theta
    xo = float(xo)
    yo = float(yo)
    a = (np.cos(theta) ** 2) / (2 * sigma_x ** 2) + \
        (np.sin(theta) ** 2) / (2 * sigma_y ** 2)
    b = -(np.sin(2 * theta)) / (4 * sigma_x ** 2) + \
        (np.sin(2 * theta)) / (4 * sigma_y ** 2)
    c = (np.sin(theta) ** 2) / (2 * sigma_x ** 2) + \
        (np.cos(theta) ** 2) / (2 * sigma_y ** 2)
    g = np.exp(-(a * (x1 - xo) ** 2 + 2 * b * (x1 - xo) * (x2 - yo) +
                 c * (x2 - yo) ** 2))
    return amplitude * g + offset


fit_mod = Model(gauss_flat)


def _image_signature(path):
    with open(path, 'rb') as image_file:
        signature = image_file.read(12)
    return (
        signature.startswith(b'BM') or
        signature.startswith(b'\x89PNG\r\n\x1a\n') or
        signature.startswith(b'\xff\xd8\xff') or
        signature.startswith(b'II*\x00') or
        signature.startswith(b'MM\x00*')
    )


def is_image_file(path):
    """Return True for supported encoded image formats."""
    suffix = os.path.splitext(str(path))[1].lower()
    return suffix in IMAGE_EXTENSIONS or _image_signature(path)


def read_image(path):
    """Read an encoded image, preserving its stored dimensions and dtype."""
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f'Unable to decode image: {path}')

    if image.ndim == 3:
        if image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        else:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    elif image.ndim != 2:
        raise ValueError(f'Unsupported image shape: {image.shape}')

    print(f'Detected image ({image.shape[1]}x{image.shape[0]}, {image.dtype}).')
    return image


def read_mono_raw(raw_path, dtype=np.uint8, color=False):
    """Read a RAW file and optionally unpack packed 4-byte color data."""
    data = np.fromfile(raw_path, dtype=dtype)
    if data.size % 4 == 0 and color:
        quad = data.reshape(-1, 4)
        if (np.all(quad[:, 0] == quad[:, 1]) and
                np.all(quad[:, 1] == quad[:, 2]) and
                np.all(quad[:, 3] == 255)):
            print('Detected packed 4-byte mono raw. Extracting first channel.')
            data = quad[:, 0]
        else:
            print('Detected packed 4-byte raw. Converting RGB to mono.')
            data = np.round(
                quad[:, :3].astype(np.float32).mean(axis=1)
            ).astype(np.uint8)
    else:
        print('Detected plain mono raw.')
    return data


def infer_image_shape(pixel_count):
    """Infer a conventional aspect ratio for a headerless RAW image."""
    for width_ratio, height_ratio in [(4, 3), (3, 2), (16, 9), (5, 4), (1, 1)]:
        height = int(np.sqrt(pixel_count * height_ratio / width_ratio))
        if height > 0 and pixel_count % height == 0:
            width = pixel_count // height
            if abs(width / height - width_ratio / height_ratio) < 1e-6:
                return height, width
    for height in range(int(np.sqrt(pixel_count)), 0, -1):
        if pixel_count % height == 0:
            return height, pixel_count // height
    raise ValueError(f'Unable to infer image shape for {pixel_count} pixels')


def choose_bin_factor(height, width, requested_factor=0):
    """Choose spatial binning for fitting while preserving pixel coordinates."""
    requested_factor = int(requested_factor)
    if requested_factor > 0:
        return max(1, min(requested_factor, height, width))
    if height * width <= MAX_FIT_POINTS:
        return 1
    return max(1, int(np.ceil(np.sqrt(height * width / MAX_FIT_POINTS))))


def block_reduce(data, factor, row_offset=0, col_offset=0):
    """Average factor x factor blocks and return original-pixel coordinates."""
    data = np.asarray(data, dtype=np.float32)
    height, width = data.shape
    factor = max(1, min(int(factor), height, width))

    if factor == 1:
        rows = np.arange(height, dtype=float) + row_offset
        cols = np.arange(width, dtype=float) + col_offset
        return data, cols, rows

    height_trimmed = (height // factor) * factor
    width_trimmed = (width // factor) * factor
    reduced = data[:height_trimmed, :width_trimmed].reshape(
        height_trimmed // factor,
        factor,
        width_trimmed // factor,
        factor,
    ).mean(axis=(1, 3))
    rows = row_offset + np.arange(height_trimmed // factor) * factor + (factor - 1) / 2
    cols = col_offset + np.arange(width_trimmed // factor) * factor + (factor - 1) / 2
    return reduced, cols, rows


class Profile:
    """Beam image container and fitting entry point."""

    def __init__(self, path=None, bit_depth=8, color=False):
        self.data = np.array([])
        self.height = 0
        self.width = 0
        self.bit_depth = np.uint8
        self.mm = {}
        self.path = None
        self.pixel_size_um = DEFAULT_PIXEL_SIZE_UM
        self.last_result = None
        if path is not None:
            self.read(path, bit_depth=bit_depth, color=color)

    def read(self, path, bit_depth=8, color=False):
        """Read RAW, BMP, PNG, TIFF, JPEG, or another OpenCV image."""
        path = str(path)
        self.bit_depth = np.uint16 if bit_depth == 16 else np.uint8
        if is_image_file(path):
            frame = read_image(path)
        else:
            data = read_mono_raw(path, dtype=self.bit_depth, color=color)
            height, width = infer_image_shape(data.size)
            print(f'Reshaping to {height}x{width}')
            frame = data.reshape((height, width))

        self.frame2array(frame)
        self.path = path
        return self

    def frame2array(self, frame):
        """Initialize the profile from a 2D NumPy array."""
        frame = np.asarray(frame)
        if frame.ndim != 2:
            raise ValueError(f'Expected a 2D grayscale image, got {frame.shape}')
        self.height, self.width = frame.shape
        self.data = frame
        self.bit_depth = frame.dtype
        self.mm = self.moment()
        return self

    def moment(self):
        image = self.data.astype(np.float32)
        if image.size == 0:
            return {}
        image_u8 = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        _, binary = cv2.threshold(
            image_u8, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        return cv2.moments((image * binary).astype(np.float32))

    @property
    def x_bar(self):
        if self.mm.get('m00', 0) == 0:
            return np.nan
        return self.mm['m10'] / self.mm['m00']

    @property
    def y_bar(self):
        if self.mm.get('m00', 0) == 0:
            return np.nan
        return self.mm['m01'] / self.mm['m00']

    @property
    def angle(self):
        if self.mm.get('m00', 0) == 0:
            return 0.0
        u11 = (self.mm['m11'] - self.x_bar * self.mm['m01']) / self.mm['m00']
        u20 = (self.mm['m20'] - self.x_bar * self.mm['m10']) / self.mm['m00']
        u02 = (self.mm['m02'] - self.y_bar * self.mm['m01']) / self.mm['m00']
        if u20 == u02:
            return 0.0
        return 0.5 * np.arctan2(2 * u11, u20 - u02)

    @property
    def eig(self):
        if self.mm.get('m00', 0) == 0:
            return np.nan, np.nan
        u11 = (self.mm['m11'] - self.x_bar * self.mm['m01']) / self.mm['m00']
        u20 = (self.mm['m20'] - self.x_bar * self.mm['m10']) / self.mm['m00']
        u02 = (self.mm['m02'] - self.y_bar * self.mm['m01']) / self.mm['m00']
        common = np.sqrt((u20 - u02) ** 2 + 4 * u11 ** 2)
        return (
            2 * np.sqrt(2) * np.sqrt(u20 + u02 + common),
            2 * np.sqrt(2) * np.sqrt(max(0, u20 + u02 - common)),
        )


    def _detect_peaks(self, n_beam, local_size, min_distance):
        """Detect up to n_beam distinct intensity peaks."""
        data = self.data.astype(np.float32)
        background = float(np.median(data))
        dynamic_range = float(np.max(data) - background)
        if dynamic_range <= 0:
            raise ValueError('Image has no positive intensity range')

        smoothing = max(2.0, local_size / 6.0)
        smoothed = ndimage.gaussian_filter(data, sigma=smoothing)
        local_max = maximum_filter(smoothed, size=local_size) == smoothed
        border = max(2, local_size // 2)
        interior = np.zeros(smoothed.shape, dtype=bool)
        interior[border:-border, border:-border] = True
        candidates = np.argwhere(
            local_max & interior &
            (smoothed > background + 0.02 * dynamic_range)
        )
        if candidates.size == 0:
            y_peak, x_peak = np.unravel_index(np.argmax(smoothed), smoothed.shape)
            return [(int(y_peak), int(x_peak))]

        intensities = smoothed[candidates[:, 0], candidates[:, 1]]
        order = np.argsort(intensities)[::-1]
        selected = []
        for index in order:
            y_peak, x_peak = candidates[index]
            if all(
                (x_peak - x_other) ** 2 + (y_peak - y_other) ** 2
                >= min_distance ** 2
                for y_other, x_other in selected
            ):
                selected.append((int(y_peak), int(x_peak)))
            if len(selected) == n_beam:
                break

        if len(selected) < n_beam:
            raise ValueError(
                f'Requested {n_beam} beams, but only {len(selected)} distinct '
                f'peaks were found with min_distance={min_distance}'
            )
        return selected

    def _beam_roi(self, peak, peaks, threshold_ratio=0.10, margin=0.15):
        """Select a rectangular ROI around one peak and return its pixel bounds."""
        data = self.data.astype(np.float32)
        y_peak, x_peak = peak
        background = float(np.median(data))
        peak_level = float(data[y_peak, x_peak])
        threshold = background + threshold_ratio * max(0.0, peak_level - background)
        signal = data > threshold

        if len(peaks) > 1:
            yy, xx = np.indices(data.shape)
            best_distance = np.full(data.shape, np.inf, dtype=np.float64)
            owner = np.full(data.shape, -1, dtype=np.int16)
            for index, (y_other, x_other) in enumerate(peaks):
                distance = (yy - y_other) ** 2 + (xx - x_other) ** 2
                closer = distance < best_distance
                best_distance[closer] = distance[closer]
                owner[closer] = index
            signal &= owner == peaks.index(peak)

        labels, _ = ndimage.label(signal)
        peak_label = labels[y_peak, x_peak]
        if peak_label > 0:
            component = labels == peak_label
            rows, cols = np.where(component)
            x_min, x_max = int(cols.min()), int(cols.max())
            y_min, y_max = int(rows.min()), int(rows.max())
        else:
            half_size = max(20, int(2.5 * local_size))
            x_min = max(0, x_peak - half_size)
            x_max = min(self.width - 1, x_peak + half_size)
            y_min = max(0, y_peak - half_size)
            y_max = min(self.height - 1, y_peak + half_size)

        pad = max(10, int(margin * max(x_max - x_min, y_max - y_min)))
        return (
            max(0, x_min - pad),
            max(0, y_min - pad),
            min(self.width - 1, x_max + pad),
            min(self.height - 1, y_max + pad),
        )

    def _fit_roi(self, roi, initial_center, fix_xy=False, binning=False):
        """Fit one Gaussian using a dedicated rectangular ROI."""
        x_min, y_min, x_max, y_max = roi
        sub = self.data[y_min:y_max + 1, x_min:x_max + 1].astype(np.float32)
        factor = choose_bin_factor(sub.shape[0], sub.shape[1]) if binning else 1
        fit_data, x_grid, y_grid = block_reduce(sub, factor, y_min, x_min)
        if factor > 1:
            print(f'Block-averaging ROI {factor}x: '
                  f'{sub.shape[1]}x{sub.shape[0]} -> '
                  f'{fit_data.shape[1]}x{fit_data.shape[0]}')

        x_mesh, y_mesh = np.meshgrid(x_grid, y_grid)
        grid = np.column_stack([x_mesh.flatten(), y_mesh.flatten()])

        initial_y, initial_x = initial_center
        initial_x = float(np.clip(initial_x, x_min, x_max))
        initial_y = float(np.clip(initial_y, y_min, y_max))
        offset = float(np.percentile(fit_data, 5))
        amplitude = max(1.0, float(np.max(fit_data)) - offset)

        weights = np.maximum(fit_data - offset, 0.0)
        weight_sum = float(weights.sum())
        if weight_sum > 0:
            x_weighted, y_weighted = np.meshgrid(x_grid, y_grid)
            moment_x = float((weights * x_weighted).sum() / weight_sum)
            moment_y = float((weights * y_weighted).sum() / weight_sum)
            dx = x_weighted - moment_x
            dy = y_weighted - moment_y
            cov_xx = float((weights * dx ** 2).sum() / weight_sum)
            cov_yy = float((weights * dy ** 2).sum() / weight_sum)
            cov_xy = float((weights * dx * dy).sum() / weight_sum)
            common = np.sqrt((cov_xx - cov_yy) ** 2 + 4 * cov_xy ** 2)
            sigma_major = np.sqrt(max(0.5, (cov_xx + cov_yy + common) / 2))
            sigma_minor = np.sqrt(max(0.5, (cov_xx + cov_yy - common) / 2))
            image_angle = 0.5 * np.arctan2(2 * cov_xy, cov_xx - cov_yy)
            initial_x = float(np.clip(moment_x, x_min, x_max))
            initial_y = float(np.clip(moment_y, y_min, y_max))
        else:
            sigma_major = max(5.0, 0.12 * min(fit_data.shape))
            sigma_minor = sigma_major
            image_angle = 0.0

        if fix_xy:
            sigma_x_initial = np.sqrt(max(0.5, cov_xx)) if weight_sum > 0 else sigma_major
            sigma_y_initial = np.sqrt(max(0.5, cov_yy)) if weight_sum > 0 else sigma_minor
            theta_model_initial = 0.0
        else:
            sigma_x_initial = sigma_major
            sigma_y_initial = sigma_minor
            theta_model_initial = -image_angle

        params = Parameters()
        params.add('amplitude', value=amplitude, min=0)
        params.add('xo', value=initial_x, min=x_min, max=x_max)
        params.add('yo', value=initial_y, min=y_min, max=y_max)
        params.add('sigma_x', value=sigma_x_initial, min=0.5, max=max(fit_data.shape))
        params.add('sigma_y', value=sigma_y_initial, min=0.5, max=max(fit_data.shape))
        params.add('theta', value=theta_model_initial, min=-np.pi / 2,
                   max=np.pi / 2, vary=not fix_xy)
        params.add('offset', value=offset, min=0)

        result = fit_mod.fit(fit_data.flatten(), x=grid, params=params)
        values = result.values
        xo_pix = float(values['xo'])
        yo_pix = float(values['yo'])
        sigma_x_pix = float(values['sigma_x'])
        sigma_y_pix = float(values['sigma_y'])
        theta_model = float(values['theta'])
        theta_image = -theta_model
        pixel_size_um = float(self.pixel_size_um)

        detail = {
            'amplitude': float(values['amplitude']),
            'xo': xo_pix * pixel_size_um / 1000.0,
            'yo': yo_pix * pixel_size_um / 1000.0,
            'sigma_x': sigma_x_pix * pixel_size_um,
            'sigma_y': sigma_y_pix * pixel_size_um,
            'radius_x': 2.0 * sigma_x_pix * pixel_size_um,
            'radius_y': 2.0 * sigma_y_pix * pixel_size_um,
            'theta': np.degrees(theta_image) % 180.0,
            'xo_pix': xo_pix,
            'yo_pix': yo_pix,
            'sigma_x_pix': sigma_x_pix,
            'sigma_y_pix': sigma_y_pix,
            'theta_rad': theta_image,
            'offset': float(values['offset']),
            'roi': tuple(int(value) for value in roi),
            'bin_factor': factor,
        }
        return result, detail

    def fit(self, n_beam=1, pixel_size=None, zoom=True, fix_xy=False,
            binning=False, local_size=DEFAULT_LOCAL_SIZE,
            min_distance=DEFAULT_MIN_DISTANCE, roi_threshold=0.10,
            roi_margin=0.15):
        """
        Fit one or more Gaussian beams.

        Parameters
        ----------
        n_beam : int
            Number of beams to detect and fit.
        pixel_size : float
            Pixel pitch in micrometers. Defaults to the current profile value.
        zoom : bool
            Select a local rectangular ROI for each beam. Multi-beam fits always
            use independent ROIs.
        fix_xy : bool
            Fix the Gaussian rotation angle to zero.
        binning : bool
            Enable automatic block-average binning for large ROIs.
        """
        if self.data.size == 0:
            raise ValueError('No image loaded. Use Profile(path) or profile.read(path).')

        n_beam = int(n_beam)
        if n_beam < 1:
            raise ValueError('n_beam must be at least 1')
        if pixel_size is not None:
            self.pixel_size_um = float(pixel_size)

        peaks = self._detect_peaks(n_beam, local_size, min_distance)
        used_rois = []
        raw_results = []
        details = []

        for index, peak in enumerate(peaks):
            if zoom or n_beam > 1:
                y_peak, x_peak = peak
                peak_object = peak
                roi = self._beam_roi(
                    peak_object,
                    peaks,
                    threshold_ratio=roi_threshold,
                    margin=roi_margin,
                )
            else:
                y_peak, x_peak = peak
                roi = (0, 0, self.width - 1, self.height - 1)

            raw_result, detail = self._fit_roi(
                roi,
                (y_peak, x_peak),
                fix_xy=fix_xy,
                binning=binning,
            )
            used_rois.append(roi)
            raw_results.append(raw_result)
            details.append(detail)

        summary = []
        for index, detail in enumerate(details):
            summary.append({
                'beam': index + 1,
                'amplitude': detail['amplitude'],
                'center_mm': [detail['xo'], detail['yo']],
                'sigma_um': [detail['sigma_x'], detail['sigma_y']],
                'radius_um': [detail['radius_x'], detail['radius_y']],
                'angle_deg': float(detail['theta']),
                'roi_pixels': list(detail['roi']),
            })

        result = BeamFitResult(
            profile=self,
            info=summary,
            details=details,
            raw_results=raw_results,
            pixel_size_um=self.pixel_size_um,
            zoom=zoom,
        )
        self.last_result = result
        return result


    def plot_beams(self, beams_info=None, zoom=False, show_slices=True,
                   save=False, filename=None, show=True):
        """Plot the image and fitted beams, with a parameter table on the right."""
        if isinstance(beams_info, BeamFitResult):
            zoom = beams_info.zoom if zoom is False else zoom
            beams_info = beams_info.details

        pixel_size_um = float(self.pixel_size_um)
        x_max_um = self.width * pixel_size_um
        y_max_um = self.height * pixel_size_um

        if not beams_info:
            figure, ax = plt.subplots(constrained_layout=True)
            image = ax.imshow(
                self.data, cmap=plt.cm.jet, origin='lower',
                interpolation='nearest',
                extent=[0, x_max_um, 0, y_max_um],
            )
            ax.set_aspect('equal')
            ax.set_xlabel('x (um)')
            ax.set_ylabel('y (um)')
            figure.colorbar(image, ax=ax, orientation='horizontal',
                            shrink=0.65, pad=0.08, label='intensity')
        else:
            # Let Matplotlib size the figure and axes.  A dedicated spacer
            # column keeps the outward-facing y slice clear of the table.
            figure = plt.figure(constrained_layout=True)
            grid = figure.add_gridspec(
                1, 2, width_ratios=[5, 2.8], wspace=0.03,
            )
            ax = figure.add_subplot(grid[0, 0])
            ax_table = figure.add_subplot(grid[0, 1])
            ax_table.axis('off')
            ax.set_anchor('W')

            ax_slice_x = None
            ax_slice_y = None
            if show_slices:
                # Keep the two intensity axes equally thick while retaining the
                # image's pixel aspect ratio.
                slice_width = 0.22
                slice_height = slice_width * self.width / self.height
                ax_slice_x = ax.inset_axes(
                    [0, 1.05, 1, slice_height], transform=ax.transAxes,
                    sharex=ax,
                )
                ax_slice_y = ax.inset_axes(
                    [1.05, 0, slice_width, 1], transform=ax.transAxes,
                    sharey=ax,
                )

            image = ax.imshow(
                self.data, cmap=plt.cm.jet, origin='lower',
                interpolation='nearest',
                extent=[0, x_max_um, 0, y_max_um],
            )
            ax.set_aspect('equal')
            ax.set_xlabel('horizontal axis (um)')
            ax.set_ylabel('vertical axis (um)')
            figure.colorbar(
                image, ax=ax, orientation='horizontal',
                shrink=0.5, pad=0.02, label='intensity',
            )

            data_x = self.data.astype(float)
            x_positions = np.arange(self.width)
            y_positions = np.arange(self.height)
            x_um = x_positions * pixel_size_um
            y_um = y_positions * pixel_size_um
            fit_bounds = []
            intensity_min = float(np.nanmin(self.data))
            intensity_max = float(np.nanmax(self.data))

            for index, beam in enumerate(beams_info):
                color = 'black'
                center_x = beam['xo_pix'] * pixel_size_um
                center_y = beam['yo_pix'] * pixel_size_um
                sigma_x_um = beam['sigma_x_pix'] * pixel_size_um
                sigma_y_um = beam['sigma_y_pix'] * pixel_size_um

                ellipse = Ellipse(
                    (center_x, center_y), 2 * sigma_x_um, 2 * sigma_y_um,
                    angle=beam['theta'], fill=False, edgecolor=color,
                    linestyle='--', linewidth=2, alpha=0.9,
                )
                ax.add_patch(ellipse)
                ax.plot(center_x, center_y, 'o', color=color, markersize=5)

                roi_x0, roi_y0, roi_x1, roi_y1 = beam['roi']
                axis_um = 50 * pixel_size_um
                ax.arrow(
                    center_x, center_y,
                    axis_um * np.cos(beam['theta_rad']),
                    axis_um * np.sin(beam['theta_rad']),
                    head_width=8 * pixel_size_um,
                    head_length=6 * pixel_size_um,
                    fc=color, ec=color, length_includes_head=True,
                )

                fit_bounds.append((
                    roi_x0 * pixel_size_um,
                    roi_y0 * pixel_size_um,
                    (roi_x1 + 1) * pixel_size_um,
                    (roi_y1 + 1) * pixel_size_um,
                ))

                if show_slices:
                    y_index = int(np.clip(round(beam['yo_pix']), 0, self.height - 1))
                    x_index = int(np.clip(round(beam['xo_pix']), 0, self.width - 1))
                    row = data_x[y_index, :]
                    column = data_x[:, x_index]
                    fit_x = beam['amplitude'] * np.exp(
                        -((x_positions - beam['xo_pix']) ** 2) /
                        (2 * beam['sigma_x_pix'] ** 2)
                    ) + beam['offset']
                    fit_y = beam['amplitude'] * np.exp(
                        -((y_positions - beam['yo_pix']) ** 2) /
                        (2 * beam['sigma_y_pix'] ** 2)
                    ) + beam['offset']

                    ax_slice_x.plot(x_um, row, color='blue', linewidth=0.9, alpha=0.45)
                    ax_slice_x.plot(x_um, fit_x, 'k--', linewidth=2.0)
                    ax_slice_y.plot(column, y_um, color='green', linewidth=0.9, alpha=0.45)
                    ax_slice_y.plot(fit_y, y_um, 'k--', linewidth=2.0)
                    intensity_min = min(
                        intensity_min, float(np.nanmin(row)),
                        float(np.nanmin(fit_x)), float(np.nanmin(column)),
                        float(np.nanmin(fit_y)),
                    )
                    intensity_max = max(
                        intensity_max, float(np.nanmax(row)),
                        float(np.nanmax(fit_x)), float(np.nanmax(column)),
                        float(np.nanmax(fit_y)),
                    )

            if zoom and fit_bounds:
                bounds = np.asarray(fit_bounds)
                ax.set_xlim(max(0.0, float(bounds[:, 0].min())),
                            min(x_max_um, float(bounds[:, 2].max())))
                ax.set_ylim(max(0.0, float(bounds[:, 1].min())),
                            min(y_max_um, float(bounds[:, 3].max())))

            if show_slices:
                intensity_span = intensity_max - intensity_min
                intensity_pad = (
                    0.04 * intensity_span if intensity_span > 0 else 1.0
                )
                vmin = intensity_min - intensity_pad
                vmax = intensity_max + intensity_pad
                ax_slice_x.set_ylabel('intensity')
                ax_slice_x.set_title('x-axis slice', fontsize=9)
                ax_slice_x.grid(True, alpha=0.25)
                ax_slice_x.tick_params(labelbottom=False)
                ax_slice_x.set_ylim(vmin, vmax)
                ax_slice_y.set_xlabel('intensity')
                ax_slice_y.set_title('y-axis slice', fontsize=9)
                ax_slice_y.grid(True, alpha=0.25)
                ax_slice_y.tick_params(labelleft=False)
                ax_slice_y.set_xlim(vmin, vmax)

            cell_text = []
            beam_header_rows = set()
            for index, beam in enumerate(beams_info):
                if index:
                    cell_text.append(['', ''])
                beam_header_rows.add(len(cell_text))
                cell_text.extend([
                    [f"Beam {beam.get('id', index + 1)}", ''],
                    ['Amplitude', f"{beam['amplitude']:.0f}"],
                    ['Xc (mm)', f"{beam['xo']:.3f}"],
                    ['Yc (mm)', f"{beam['yo']:.3f}"],
                    ['sigma x (um)', f"{beam['sigma_x']:.1f}"],
                    ['sigma y (um)', f"{beam['sigma_y']:.1f}"],
                    ['Rx (um)', f"{beam['radius_x']:.1f}"],
                    ['Ry (um)', f"{beam['radius_y']:.1f}"],
                    ['theta (deg)', f"{beam['theta']:.1f}"],
                ])

            if len(beams_info) > 1:
                cell_text.append(['Separation', ''])
                for i, beam_i in enumerate(beams_info):
                    for beam_j in beams_info[i + 1:]:
                        distance = np.hypot(
                            beam_i['xo'] - beam_j['xo'],
                            beam_i['yo'] - beam_j['yo'],
                        )
                        cell_text.append([
                            f"Beam {beam_i.get('id', i + 1)}-"
                            f"{beam_j.get('id', i + 2)}",
                            f"{distance:.3f} mm",
                        ])

            table = ax_table.table(
                cellText=cell_text,
                cellLoc='left',
                colWidths=[0.65, 0.35],
                loc='upper center',
                bbox=[0.0, 0.0, 1.0, 1.0],
            )
            table.auto_set_font_size(False)
            table.set_fontsize(8.5 if len(cell_text) <= 16 else 7)
            for (row, column), cell in table.get_celld().items():
                cell.set_edgecolor('#cccccc')
                if row in beam_header_rows:
                    cell.set_facecolor('#e8e8e8')
                    cell.set_text_props(weight='bold')
                elif column == 0:
                    cell.set_facecolor('#f7f7f7')
                if column == 1:
                    cell.set_text_props(ha='center')
            ax_table.set_title('Beam parameters', fontsize=11, pad=2)

            # Align the table with the final image axes without imposing a
            # figure size or hard-coded positions. The locator is evaluated
            # after layout, so it also remains aligned when saving the figure.
            def align_table_with_image(table_axis, renderer):
                image_box = ax.get_position()
                table_cell = table_axis.get_subplotspec().get_position(figure)
                return Bbox.from_bounds(
                    table_cell.x0, image_box.y0,
                    table_cell.width, image_box.height,
                )

            ax_table.set_axes_locator(align_table_with_image)

        if save:
            if filename is None:
                if self.path:
                    filename = os.path.splitext(os.path.basename(self.path))[0] + '.png'
                else:
                    filename = 'beam_fit.png'
            figure.savefig(filename, dpi=300, bbox_inches='tight')

        self.last_figure = figure
        if show:
            plt.show()
            return None
        return figure




class BeamFitResult:
    """Fitted beam summary returned by Profile.fit()."""

    def __init__(self, profile, info, details, raw_results,
                 pixel_size_um, zoom):
        self.profile = profile
        self.info = info
        self.details = details
        self.raw_results = raw_results
        self.pixel_size_um = pixel_size_um
        self.zoom = zoom

    def __repr__(self):
        return pprint.pformat(self.info, sort_dicts=False, width=160)

    def plot(self, save=False, show=True, filename=None, zoom=None,
             show_slices=True):
        """Plot this result. Radius is defined as 2*sigma (1/e^2 radius)."""
        plot_zoom = self.zoom if zoom is None else zoom
        return self.profile.plot_beams(
            self.details, zoom=plot_zoom, show_slices=show_slices,
            save=save, filename=filename, show=show,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Fit Gaussian beams in RAW, BMP, PNG, TIFF, or JPEG images'
    )
    parser.add_argument('inputfile', metavar='input', help='Input image or RAW file')
    parser.add_argument('-n', metavar='beam number', type=int, default=1,
                        dest='n_beam', help='Number of Gaussian beams')
    parser.add_argument('-b', metavar='bit depth', type=int, default=8,
                        help='RAW bit depth: 8 or 16')
    parser.add_argument('-p', '--pixel-size', metavar='um', type=float,
                        default=DEFAULT_PIXEL_SIZE_UM,
                        help='Pixel pitch in micrometers')
    parser.add_argument('-fit', action='store_true', help='Run the Gaussian fit')
    parser.add_argument('-xy', action='store_true', dest='fix_xy',
                        help='Fix the Gaussian angle to the x/y axes')
    parser.add_argument('--binning', action='store_true', default=False,
                        help='Enable automatic ROI block-average binning')
    parser.add_argument('-save', action='store_true', help='Save the figure')
    parser.add_argument('-zoom', action='store_true', default=True,
                        help='Use a local ROI for each beam (default)')
    parser.add_argument('--no-zoom', action='store_false', dest='zoom',
                        help='Fit the full image for a single beam')
    parser.add_argument('-color', action='store_true', default=False,
                        help='Treat RAW data as packed 4-byte color')
    args = parser.parse_args()

    profile = Profile(
        args.inputfile,
        bit_depth=args.b,
        color=args.color,
    )
    if args.fit:
        result = profile.fit(
            n_beam=args.n_beam,
            pixel_size=args.pixel_size,
            zoom=args.zoom,
            fix_xy=args.fix_xy,
            binning=args.binning,
        )
        pprint.pprint(result)
        result.plot(save=args.save)
    else:
        profile.plot_beams(save=args.save)
