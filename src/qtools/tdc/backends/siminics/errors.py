"""Siminics backend exceptions."""

from __future__ import annotations


class SiminicsError(RuntimeError):
    """Base class for Siminics SDK and acquisition errors."""


class SiminicsSDKUnavailable(ImportError, SiminicsError):
    """Raised when the Windows vendor SDK cannot be loaded."""


class SiminicsSDKError(SiminicsError):
    """Raised when a vendor DLL operation returns a non-zero status."""

    def __init__(self, operation: str, code: int):
        self.operation = operation
        self.code = int(code)
        super().__init__(f"Siminics {operation} failed with error code {self.code}")

