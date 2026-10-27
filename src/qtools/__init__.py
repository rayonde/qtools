"""qtools - Laboratory and Instrumentation Tools.

Subpackages are loaded on demand so importing one instrument family does not
initialize optional dependencies belonging to another family.
"""

from __future__ import annotations

from importlib import import_module

__version__ = "0.1.0"


_SUBPACKAGES = {"camera", "dm", "motor", "powermeter", "slm", "tdc", "tec", "tomo"}


def __getattr__(name: str):
    if name not in _SUBPACKAGES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module

__all__ = ["__version__", "camera", "dm", "motor", "powermeter", "slm", "tdc", "tec", "tomo"]
