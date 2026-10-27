import sys
from pathlib import Path


import pytest
from qtools.pctrl.servo_manager import ServoManager


@pytest.fixture(autouse=True)
def reset_mgr():
    """Reset ServoManager state before each test."""
    yield


def test_servo_manager_mock_servos():
    """Mock mode: backend is a ServoBackend with MockPortHandler port."""
    mgr = ServoManager(mock_mode=True)

    backend = mgr.backend
    ph = backend.port_handler
    assert ph.__class__.__name__ == "MockPortHandler"
    assert backend.__class__.__name__ == "ServoBackend"

    assert ph.openPort() is True
    assert ph.setBaudRate(1000000) is True

    # Low-level SDK methods delegate to mock via __getattr__
    assert backend.WritePosEx(1, 512, 1200, 50) == (0, 0)
    pos, speed, res, err = backend.ReadPosSpeed(1)
    assert pos == 512
    assert res == 0

    backend.WritePosEx(1, 640, 1200, 50)
    pos, _, _, _ = backend.ReadPosSpeed(1)
    assert pos == 640

    # angle_to_pos / pos_to_angle work as instance methods
    assert backend.angle_to_pos(90.0) > 0
    assert isinstance(backend.pos_to_angle(512), float)

    # get_limits returns 4-tuples compatible with ServoManager.retrive_limits
    limits = mgr.retrive_limits([1])
    assert 1 in limits
    assert len(limits[1]) == 4

    # list_servos accepts stop_on_empty
    assert backend.list_servos(stop_on_empty=False)


def test_servo_manager_mock_powermeter():
    """Powermeter is no longer managed by ServoManager — test skipped."""
    pytest.skip("powermeter management moved out of ServoManager")


def test_servo_manager_mock_tdc():
    """TDC is no longer managed by ServoManager — test skipped."""
    pytest.skip("TDC management moved out of ServoManager")


def test_cli_mock_flag(tmp_path):
    from unittest.mock import patch
    from qtools.pctrl.cli import main

    config_file = tmp_path / "pctrl_config.yaml"
    config_file.write_text(
        "connection:\n  port: COM_MOCK_TEST\n  baudrate: 1000000\nchannels: []"
    )

    with patch("sys.argv", ["pctrl", "--mock", "-c", str(config_file), "status"]), \
         patch("qtools.pctrl.utils.run_status") as mock_status:
        main()
        mock_status.assert_called_once()
        kwargs = mock_status.call_args.kwargs
        assert kwargs.get("mock") is True
