"""Optional RPC display client helpers."""

from __future__ import annotations


def connect(*, port: int = 4444, secret: str = ""):
    try:
        from ipyutils import Client
    except ImportError as exc:
        raise ImportError("The display client requires the optional 'ipyutils' package.") from exc
    from qtools.slm.display.interface import DisplayInterface

    return Client(DisplayInterface, port=port, secret=secret)


__all__ = ["connect"]
