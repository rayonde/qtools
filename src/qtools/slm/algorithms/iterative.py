"""Lazy adapters for iterative algorithms from slmsuite."""

from __future__ import annotations

from typing import Any


def slmsuite_toolbox() -> Any:
    """Import and return slmsuite's holography toolbox on demand."""

    try:
        from slmsuite import holography
    except ImportError as exc:
        raise ImportError(
            "Iterative phase algorithms require optional dependency 'slmsuite'."
        ) from exc
    return holography


__all__ = ["slmsuite_toolbox"]
