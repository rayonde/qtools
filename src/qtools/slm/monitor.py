"""Monitor discovery and stable SLM-to-screen bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MonitorInfo:
    """Description of an attached display."""

    index: int
    name: str
    resolution: tuple[int, int]
    geometry: tuple[int, int, int, int]


@dataclass(frozen=True)
class MonitorBinding:
    """Resolved monitor selection retained by one SLM instance."""

    monitor: MonitorInfo

    @property
    def index(self) -> int:
        return self.monitor.index

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
    for index, screen in enumerate(app.screens()):
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
    """Resolve an explicit monitor or select the secondary screen by default."""

    monitors = list_monitors()
    if not monitors:
        raise RuntimeError(
            "No display monitors were detected. Use a headless backend or install/configure Qt."
        )

    selected = 1 if len(monitors) > 1 else 0
    if index is not None:
        selected = index
    if selected < 0 or selected >= len(monitors):
        raise IndexError(f"Monitor index {selected} is out of range for {len(monitors)} monitors.")
    return MonitorBinding(monitors[selected])


__all__ = ["MonitorBinding", "MonitorInfo", "list_monitors", "resolve_monitor"]
