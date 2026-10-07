"""Qt full-screen display implementation with optional dependency loading."""

from __future__ import annotations

import atexit
from pathlib import Path

import numpy as np
import numpy.typing as npt

from qtools.slm.display.displaymask import DisplayMask
from qtools.slm.display.interface import DisplayInterface
from qtools.slm.monitor import MonitorBinding
from qtools.slm.utils import save_image, show_image


class QtDisplay(DisplayInterface):
    def __init__(self, binding: MonitorBinding, *, rescaling: str | None = None):
        if rescaling not in (None, "fill", "stretch"):
            raise ValueError("rescaling must be None, 'fill', or 'stretch'.")
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QColor, QImage, QPixmap
            from PySide6.QtWidgets import QApplication, QLabel
        except ImportError as exc:
            raise ImportError("QtDisplay requires PySide6; use headless=True without Qt.") from exc

        self._Qt = Qt
        self._QImage = QImage
        self._QPixmap = QPixmap
        self._QColor = QColor
        self._QApplication = QApplication
        self._binding = binding
        self._resolution = binding.resolution
        self._app = QApplication.instance() or QApplication(["qtools-slm"])
        screens = self._app.screens()
        screen = screens[binding.index]
        geometry = screen.geometry()
        self._rescaling = rescaling
        self._current: QPixmap | None = None
        self._previous: QPixmap | None = None
        self._closed = False
        self.label = QLabel()
        self.label.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        self.label.setStyleSheet("background-color: black;")
        self.label.setCursor(Qt.CursorShape.BlankCursor)
        self.label.setGeometry(geometry)
        self.label.setFixedSize(geometry.width(), geometry.height())
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.showFullScreen()
        self.clear()
        atexit.register(self.close)

    @property
    def resolution(self) -> tuple[int, int]:
        return self._resolution

    def _array(self, mask: DisplayMask | npt.ArrayLike) -> npt.NDArray[np.uint8]:
        if isinstance(mask, DisplayMask) and mask.bits > 8 and not mask.rgb:
            raise ValueError("Display masks above 8 bits must be RGB-packed before display output.")
        values = mask.array if isinstance(mask, DisplayMask) else np.asarray(mask)
        if values.ndim == 2:
            values = np.repeat(values[:, :, None], 3, axis=2)
        if values.ndim != 3 or values.shape[-1] not in (3, 4):
            raise ValueError("Display data must be grayscale or RGB.")
        return np.ascontiguousarray(values[:, :, :3], dtype=np.uint8)

    def load(self, mask: DisplayMask | npt.ArrayLike) -> None:
        values = self._array(mask)
        height, width = values.shape[:2]
        image = self._QImage(values.data, width, height, 3 * width, self._QImage.Format.Format_RGB888)
        self._set_pixmap(self._QPixmap.fromImage(image.copy()))

    def _set_pixmap(self, pixmap) -> None:
        if self._rescaling:
            mode = {
                "fill": self._Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                "stretch": self._Qt.AspectRatioMode.IgnoreAspectRatio,
            }[self._rescaling]
            pixmap = pixmap.scaled(self.label.size(), mode, self._Qt.TransformationMode.SmoothTransformation)
        self._previous = self._current
        self._current = pixmap
        self.label.setPixmap(pixmap)
        self.label.repaint()
        self._QApplication.processEvents()

    def load_image(self, path: str) -> None:
        image = self._QImage(str(Path(path).expanduser()))
        if image.isNull():
            raise FileNotFoundError(path)
        self._set_pixmap(self._QPixmap.fromImage(image))

    def clear(self) -> None:
        self.load(np.zeros((1, 1), dtype=np.uint8))

    def undo(self) -> None:
        if self._previous is None:
            return
        self._current, self._previous = self._previous, self._current
        self.label.setPixmap(self._current)
        self._QApplication.processEvents()

    def get_data(self) -> npt.NDArray[np.uint8]:
        if self._current is None:
            return np.zeros((self._resolution[1], self._resolution[0], 3), dtype=np.uint8)
        image = self._current.toImage().convertToFormat(self._QImage.Format.Format_RGB888)
        width, height = image.width(), image.height()
        data = np.frombuffer(bytes(image.constBits()), dtype=np.uint8)
        return data.reshape(height, -1)[:, : 3 * width].reshape(height, width, 3).copy()

    def save(self, filename: str) -> None:
        save_image(self.get_data(), filename)

    def show(self) -> None:
        show_image(self.get_data())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.label.close()


__all__ = ["QtDisplay"]
