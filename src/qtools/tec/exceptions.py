"""Exceptions for the TEC subpackage."""

from __future__ import annotations


class TECError(Exception):
    """Base exception for all TEC-related errors."""


class TECConnectionError(TECError):
    """Raised when connecting to a TEC device fails or connection is lost."""


class TECDeviceNotFoundError(TECConnectionError, ValueError):
    """Raised when no matching TEC serial device is detected."""


class TECProtocolError(TECError, ValueError):
    """Raised when communication with TEC violates protocol or device returns an error."""
