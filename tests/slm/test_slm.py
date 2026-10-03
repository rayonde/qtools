"""Unit tests for the SLM subpackage."""

import pytest
from qtools.slm import SLMDriver


def test_slm_driver_mock_connection():
    driver = SLMDriver(device_id=0, is_mock=True)
    assert not driver.is_connected
    assert driver.connect() is True
    assert driver.is_connected is True

    # Test phase loading
    assert driver.load_phase([[0, 1], [1, 0]]) is True

    driver.disconnect()
    assert not driver.is_connected


def test_slm_unconnected_error():
    driver = SLMDriver(device_id=0, is_mock=True)
    with pytest.raises(RuntimeError):
        driver.load_phase([[0, 0]])
