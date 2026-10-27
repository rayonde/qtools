"""Errors raised by deformable mirror controllers."""


class DMError(RuntimeError):
    """Base class for mirror driver failures."""


class DMDependencyError(DMError):
    """The vendor SDK or its operating-system prerequisites are unavailable."""


class DMConnectionError(DMError):
    """A device could not be selected or is not connected."""


class DMCapabilityError(DMError):
    """The device does not support the requested control."""


class DMDriverError(DMError):
    """An SDK call returned an error status."""

    def __init__(self, function: str, status: int, message: str = "") -> None:
        self.function = function
        self.status = status
        self.detail = message
        super().__init__(f"{function} failed (0x{status & 0xFFFFFFFF:08X}): {message}")


class DMDriverWarning(RuntimeWarning):
    """A successful SDK call reported a vendor warning."""
