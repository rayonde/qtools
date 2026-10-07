"""Explicit, lazy backend registry."""

from __future__ import annotations

from importlib import import_module
from typing import Type

from qtools.slm.backends.base import SLMBackend

_BACKEND_MODULES = {
    "holoeye": ("qtools.slm.backends.holoeye.backend", "HoloeyeBackend"),
    "simulated": ("qtools.slm.backends.simulated.backend", "SimulatedBackend"),
}


def get_backend(name: str) -> Type[SLMBackend]:
    key = name.lower()
    try:
        module_name, class_name = _BACKEND_MODULES[key]
    except KeyError as exc:
        raise KeyError(f"Unknown backend {name!r}; available: {sorted(_BACKEND_MODULES)}") from exc
    module = import_module(module_name)
    return getattr(module, class_name)


def list_backends() -> list[str]:
    return sorted(_BACKEND_MODULES)


__all__ = ["SLMBackend", "get_backend", "list_backends"]
