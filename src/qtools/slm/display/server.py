"""Optional RPC display server entry point."""

from __future__ import annotations

from qtools.slm.display.qt import QtDisplay
from qtools.slm.monitor import resolve_monitor


def serve(*, monitor: int | None = None, port: int = 4444, secret: str | None = None) -> None:
    """Serve a Qt display through ipyutils when that optional dependency is installed."""

    try:
        from ipyutils import Server
    except ImportError as exc:
        raise ImportError("The display server requires the optional 'ipyutils' package.") from exc
    display = QtDisplay(resolve_monitor(monitor))
    Server(display, port=port, secret=secret or "").run()


if __name__ == "__main__":
    serve()
