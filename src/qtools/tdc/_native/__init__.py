"""Platform-specific ctypes loader for compiled C shared libraries."""

from __future__ import annotations

import ctypes
import logging
import platform
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_native_lib(lib_stem: str) -> ctypes.CDLL:
    """Load a precompiled shared library from the package _native directory.

    Searches, in order:
      1. ``<package>/_native/<lib_stem>.{dylib|so|dll}``
      2. ``<sys.path>/tdc/_native/<lib_stem>.{dylib|so|dll}`` (editable installs)
      3. Standard system search paths (``ctypes.CDLL(lib_stem)``)

    Args:
        lib_stem: Library base name without suffix, e.g. ``"libcoincidences"``.

    Returns:
        Loaded ``ctypes.CDLL`` handle.
    """
    system = platform.system()
    suffix_map = {"Linux": ".so", "Windows": ".dll", "Darwin": ".dylib"}
    suffix = suffix_map.get(system)

    if suffix is None:
        raise OSError(f"Unsupported operating system: {system}")

    lib_name = f"{lib_stem}{suffix}"

    # 1. Try local package native directory
    native_dir = Path(__file__).parent
    lib_path = native_dir / lib_name
    if lib_path.exists():
        logger.debug("Loading native library from package path: %s", lib_path)
        return ctypes.CDLL(str(lib_path))

    # 2. Fallback for editable installs: search sys.path
    for path in sys.path:
        for candidate in [
            Path(path) / "qtools" / "tdc" / "_native" / lib_name,
            Path(path) / "tdc" / "_native" / lib_name,
        ]:
            if candidate.exists():
                logger.debug("Loading native library from editable site-packages path: %s", candidate)
                return ctypes.CDLL(str(candidate))

    # 3. Try standard system search paths
    try:
        logger.debug("Attempting to load native library from system path: %s", lib_name)
        return ctypes.CDLL(lib_name)
    except OSError as e:
        raise OSError(
            f"Could not load native library '{lib_name}'. "
            "Please compile the C shared library or install the precompiled wheels."
        ) from e


def load_libreadevents() -> ctypes.CDLL:
    """Load the precompiled libreadevents shared library."""
    return _load_native_lib("libreadevents")


def load_libcoincidences() -> ctypes.CDLL:
    """Load the precompiled libcoincidences shared library."""
    return _load_native_lib("libcoincidences")
