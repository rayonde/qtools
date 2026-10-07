#!/usr/bin/env python3
"""Displays arbitrary images on a full-screen window.

Uses Qt under the hood for displaying a full-screen image, useful for
instances like sending an RGB-encoded phase map to a spatial light
modulator that usually presents themselves as a separate display.

An older version of this code uses wxPython, which is a bigger hassle
to setup for in Linux.

Changelog:
    2015-12-06 Sebastien M. Popoff: Init, adapted from [1]
    2017-05-09 Yeo Xijie: Reduced command set
    2024-12-13 Justin: Overhaul with documentation and refactoring
    2026-07-30 Justin: Migrated from wxPython to PySide6

References:
    [1]: Original 2013-03-03 source, <https://wiki.wxpython.org/MainLoopAsThread>
"""

import argparse
import atexit
import os
import signal
import sys
from pathlib import Path
from typing import Callable, Union

import numpy as np
import numpy.typing as npt
from PySide6.QtCore import QLibraryInfo, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel

from slmutils.display import DisplayInterface
from slmutils.generate.display import DisplayMask
from slmutils.typing import PathLike
from slmutils.utils import save_image, show_image

__all__ = [
    "Display",
]


def graceful_exit(signal=None, frame=None):
    sys.exit(0)


signal.signal(signal.SIGINT, graceful_exit)
signal.signal(signal.SIGTERM, graceful_exit)


def apply_wayland_workarounds():
    """
    Wayland has strict windowing protocols that do not allow arbitrary windows
    to force focus away, which includes running always-on-top toplevel windows.
    To bypass this, we rely on XWayland instead since X11 does support this
    functionality. This requires the presence of `libxcb`.

    We also disable a Wayland log event when focus is lost, e.g. window is closed.
    """
    if not sys.platform.startswith("linux"):
        return

    if os.environ.get("XDG_SESSION_TYPE") != "wayland" and "WAYLAND_DISPLAY" not in os.environ:
        return

    plugins_path = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    xcb_path = plugins_path / "platforms/libqxcb.so"
    if xcb_path.exists():
        os.environ["QT_QPA_PLATFORM"] = "xcb"  # use XWayland
    else:
        # Hide Wayland logging when window closed
        os.environ["QT_LOGGING_RULES"] = "qt.qpa.wayland.textinput.warning=false"


class Display(DisplayInterface):
    """Full-screen image display rendered by Qt.

    Each monitor is assigned an ID which is 0-indexed, i.e. 0 represents
    the primary monitor.  If *monitor* is ``None`` and more than one monitor
    is connected, the secondary monitor is used by default. Note the
    refresh rate on the physical monitor to avoid saturation.

    Images are centered and not rescaled to the monitor geometry by default.
    *rescaling* can be set to ``'fill'`` to scale the image and fill the entire
    display while preserving aspect ratio, or set to ``'stretch'`` to ignore
    aspect ratio.

    An optional window termination hook can be supplied for when the display
    window or process is no longer active. This hook accepts no arguments.

    Usage:
        >>> display = Display(rescaling="fill")
        >>> display.load_image("examples/phase_example.png")
    """

    _CURRENT_PIXMAP_KEY = "~~~curr~~~"
    _PREVIOUS_PIXMAP_KEY = "~~~prev~~~"

    def __init__(
        self,
        monitor: int | None = None,
        rescaling: str | None = None,
        terminate_hook: Callable | None = None,
    ):
        if rescaling not in (None, "fill", "stretch"):
            raise ValueError("'rescaling' must be one of {None, 'fill', 'stretch'}.")

        # Prepare Qt backend
        apply_wayland_workarounds()

        # Find monitor and get geometry
        app = QApplication()
        screens = app.screens()
        self._idx = idx = monitor if monitor is not None else len(screens) - 1
        geom = screens[idx].geometry()
        w, h = geom.width(), geom.height()

        self._resolution = (w, h)
        self._rescalemethod = {
            "fill": Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            "stretch": Qt.AspectRatioMode.IgnoreAspectRatio,
            None: None,
        }[rescaling]
        self._terminate_hook = terminate_hook
        self._pixmaps: dict[str, Union[QPixmap, None]] = {
            self._CURRENT_PIXMAP_KEY: None,
            self._PREVIOUS_PIXMAP_KEY: None,
        }

        # Open window
        self.label = label = QLabel()
        label.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        label.setStyleSheet("background-color: black;")
        label.setCursor(Qt.CursorShape.BlankCursor)
        label.setGeometry(geom)
        label.setFixedSize(w, h)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.showFullScreen()

        # Hook for window close
        self._closed = False
        label.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        label.destroyed.connect(lambda: self.close("label"))

        # Initialize window
        self.clear()

        # Close gracefully on termination
        atexit.register(self.close)

    def close(self, source="main") -> None:
        if self._closed:
            return  # make close() declarative
        self._closed = True
        if source == "main":
            self.label.close()
        if self._terminate_hook:
            self._terminate_hook()

    @property
    def monitor(self):
        """Return monitor index (0-based)."""
        return self._idx

    @property
    def resolution(self) -> tuple[int, int]:
        """Return resolution as '(width, height)' in pixels."""
        return self._resolution

    def load_cache(self, cache: str) -> None:
        """Displays an image that was previously cached."""
        if cache not in self._pixmaps:
            raise ValueError(f"Cache key '{cache}' does not exist.")

        pixmap = self._pixmaps[cache]
        if pixmap is None:
            raise ValueError(f"Cache key '{cache}' has no cached pixmap.")
        self._load_pixmap(pixmap)

    def load_image(self, path: PathLike, cache: Union[str, None] = None) -> None:
        """Displays an image directly from file.

        Convenience method for verifying display works as intended. Supports
        only images of 8-bit depth, see documentation for 'mpl.image.imread'.
        """
        path = Path(path).expanduser()
        if not path.exists():
            raise ValueError(f"'{path}' does not exist.")

        image = QImage(path)
        self._load_image(image, cache)

    def load(self, array: npt.NDArray | DisplayInterface, cache: Union[str, None] = None) -> None:
        """Loads RGB values to the display.

        The array is expected to be a 2D array of either single 8-bit integers
        (grayscale) or 3-tuple 8-bit integers (RGB color). Any additional alpha
        channels will be ignored.

        Note:
            This function follows the various PNG color profiles depending on
            the color (last) dimension: 0-tuple and 1-tuple is a grayscale,
            2-tuple is grayscale with alpha, 3-tuple is color, 4-tuple is color
            with alpha.
        """
        if isinstance(array, DisplayMask):
            array = array.array

        array = np.array(array)  # make a copy
        if array.ndim not in (2, 3):
            raise ValueError("Array must be 8-bit integers of 2 or 3 dimensions")

        # Extract single grayscale channel
        if array.ndim == 3 and array.shape[-1] in (1, 2):
            array = array[:, :, 0]

        # Combine to generate final array
        if array.ndim == 2:
            array = np.stack(3 * [array], axis=-1)  # greyscale
        else:
            array = array[:, :, :3]  # color

        h, w = array.shape[:2]
        qimage = QImage(array.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888)
        self._load_image(qimage, cache)

    def _load_image(self, qimage: QImage, cache: Union[str, None] = None) -> None:
        pixmap = QPixmap.fromImage(qimage)
        # Avoid 'label.setScaledContents(True)' stretching to make the rescaling explicit
        if self._rescalemethod:
            pixmap = pixmap.scaled(
                self.label.size(),
                self._rescalemethod,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._load_pixmap(pixmap, cache)

    def _load_pixmap(self, pixmap: QPixmap, cache: Union[str, None] = None) -> None:
        # Caching
        if cache is not None:
            self._pixmaps[cache] = pixmap
        self._pixmaps[self._PREVIOUS_PIXMAP_KEY] = self._pixmaps[self._CURRENT_PIXMAP_KEY]
        self._pixmaps[self._CURRENT_PIXMAP_KEY] = pixmap

        # Force render and block until completed
        self.label.setPixmap(pixmap)
        self.label.repaint()
        self.label.window().windowHandle().requestUpdate()
        QApplication.processEvents()

    def _get_data(self):
        """Return pixel map data.

        If *rescaling* was not set to ``stretch``, the pixel map may not necessarily
        align with the monitor geometry.
        """
        pixmap = self._pixmaps[self._CURRENT_PIXMAP_KEY]
        assert pixmap is not None
        w = pixmap.width()
        h = pixmap.height()
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
        data = np.frombuffer(bytes(image.constBits()), dtype=np.uint8)
        array = data.reshape(h, -1)[:, : 3 * w]  # remove row byte padding from 4-byte alignment
        return array.reshape(h, w, 3)

    def undo(self):
        """Set display to the previous image.

        This is a 2-cycle state, i.e. undo-ing twice goes back to the
        same image.

        Note:
            More elaborate state management can be done using a stack
            at the cost of increasing storage memory, but we avoid this
            since undo() is primarily for interactive purposes.
        """
        pixmap = self._pixmaps[self._PREVIOUS_PIXMAP_KEY]
        if pixmap is not None:
            self._load_pixmap(pixmap)

    def clear(self):
        """Initialize window with one black pixel."""
        image = QImage(1, 1, QImage.Format.Format_RGB888)
        image.fill(QColor(0, 0, 0))  # black
        self._load_image(image)

    def show(self):
        show_image(self._get_data())

    def save(self, filename: PathLike):
        save_image(self._get_data(), filename)


def _init_display():
    # fmt: off
    parser = argparse.ArgumentParser(
        description="Displays arbitrary images on a full-screen window."
    )
    parser.add_argument(
        "--monitor", type=int,
        help="Specify which monitor to use.")
    parser.add_argument(
        "--fill", action="store_true",
        help="Resize image to fit the display, preserving aspect ratio.")
    parser.add_argument(
        "--stretch", action="store_true",
        help="Resize image to fit the display, ignoring aspect ratio.")
    # fmt: on

    args = parser.parse_args()
    if args.fill and args.stretch:
        raise ValueError("Only one of '--fill' or '--stretch' can be provided.")

    if args.fill:
        rescaling = "fill"
    elif args.stretch:
        rescaling = "stretch"
    else:
        rescaling = None

    return Display(args.monitor, rescaling)


if __name__ == "__main__":
    display = _init_display()
