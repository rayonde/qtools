"""Backward-compatible import for the FLIR backend.

Concrete backends live in :mod:`qtools.camera.backends`; this module remains
so existing scripts using ``qtools.camera.flir.FLIR`` keep working.
"""

from qtools.camera.backends.flir import FLIR

__all__ = ["FLIR"]
