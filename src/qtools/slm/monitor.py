"""Monitor discovery and stable SLM-to-screen bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MonitorInfo:
    """Description of an attached display.

    ``index`` is the user-facing monitor number and starts at 1.  Qt's
    internal zero-based index is available as :attr:`qt_index`.
    """

    index: int
    name: str
    resolution: tuple[int, int]
    geometry: tuple[int, int, int, int]

    @property
    def qt_index(self) -> int:
        return self.index - 1


@dataclass(frozen=True)
class MonitorBinding:
    """Resolved monitor selection retained by one SLM instance."""

    monitor: MonitorInfo

    @property
    def index(self) -> int:
        return self.monitor.index

    @property
    def qt_index(self) -> int:
        return self.monitor.qt_index

    @property
    def resolution(self) -> tuple[int, int]:
        return self.monitor.resolution


def list_monitors() -> list[MonitorInfo]:
    """Return attached Qt screens without importing Qt at package import time."""

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return []

    app = QApplication.instance()
    created = app is None
    if app is None:
        app = QApplication(["qtools-slm-monitor"])

    monitors: list[MonitorInfo] = []
    for index, screen in enumerate(app.screens(), start=1):
        geometry = screen.geometry()
        monitors.append(
            MonitorInfo(
                index=index,
                name=screen.name(),
                resolution=(geometry.width(), geometry.height()),
                geometry=(geometry.x(), geometry.y(), geometry.width(), geometry.height()),
            )
        )
    if created:
        app.quit()
    return monitors


def resolve_monitor(index: Optional[int] = None) -> MonitorBinding:
    """Resolve a 1-based monitor number or select the secondary by default."""

    monitors = list_monitors()
    if not monitors:
        raise RuntimeError(
            "No display monitors were detected. Use a headless backend or install/configure Qt."
        )

    selected = 2 if len(monitors) > 1 else 1
    if index is not None:
        selected = index
    if selected < 1 or selected > len(monitors):
        raise IndexError(
            f"Monitor number {selected} is out of range; available numbers are "
            f"1..{len(monitors)}."
        )
    return MonitorBinding(monitors[selected - 1])


__all__ = ["MonitorBinding", "MonitorInfo", "list_monitors", "resolve_monitor"]
