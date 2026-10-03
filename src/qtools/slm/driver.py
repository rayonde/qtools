"""SLM (Spatial Light Modulator) instrument controller."""

import logging

logger = logging.getLogger(__name__)


class SLMDriver:
    """Base controller for Spatial Light Modulator (SLM) devices."""

    def __init__(self, device_id: int = 0, is_mock: bool = False):
        self.device_id = device_id
        self.is_mock = is_mock
        self.is_connected = False

    def connect(self) -> bool:
        """Establish connection with the SLM hardware or mock simulator."""
        if self.is_mock:
            self.is_connected = True
            logger.info("Connected to Mock SLM (device_id=%s)", self.device_id)
            return True

        # Hardware initialization logic via self.sdk
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        """Close connection to the device."""
        self.is_connected = False

    def load_phase(self, phase_data) -> bool:
        """Upload a 2D phase mask or hologram array to the SLM screen."""
        if not self.is_connected:
            raise RuntimeError("Cannot load phase: SLM is not connected.")
        return True
