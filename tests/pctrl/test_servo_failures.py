from unittest.mock import MagicMock, patch

import pytest

from qtools.pctrl.backends.scservo import SCServo
from qtools.pctrl.backends.stservo import STServo
from qtools.pctrl.config import ConfigManager
from qtools.pctrl.servo_manager import ServoManager, auto_discover


@pytest.mark.parametrize("driver_class", [SCServo, STServo])
@pytest.mark.parametrize("speed", [None, 25, [15, 25]])
def test_set_speed_updates_every_requested_servo(driver_class, speed):
    driver = object.__new__(driver_class)
    driver.list_servos = MagicMock(return_value=[1, 2])
    driver.speed = 10
    driver._handler = MagicMock()
    driver._handler.write2ByteTxRx.return_value = (0, 0)

    assert driver.set_speed(speed=speed)
    assert [call.args[0] for call in driver._handler.write2ByteTxRx.call_args_list] == [1, 2]
    conversion = driver._handler.scs_toscs if driver_class is SCServo else driver._handler.sts_toscs
    expected = [10, 10] if speed is None else ([25, 25] if speed == 25 else speed)
    assert [call.args[0] for call in conversion.call_args_list] == expected


@pytest.mark.parametrize("driver_class", [SCServo, STServo])
def test_set_speed_rejects_mismatched_lists_before_writing(driver_class):
    driver = object.__new__(driver_class)
    driver._handler = MagicMock()
    with pytest.raises(ValueError, match="speed"):
        driver.set_speed([1, 2], [25])
    driver._handler.write2ByteTxRx.assert_not_called()


@pytest.fixture
def manager(tmp_path):
    cfg = ConfigManager(str(tmp_path / "pctrl.yaml"))
    cfg.add_servo("alice", 1550, "QWP", 1, 1)
    manager = object.__new__(ServoManager)
    manager.cfg = cfg
    manager._servo_backend = MagicMock()
    manager._pending_positions = {}
    return manager


@pytest.mark.parametrize("result,error", [(-1, 0), (0, 1)])
def test_position_errors_are_not_reported_as_zero_angle(manager, result, error):
    manager.backend.ReadPosSpeed.return_value = (512, 0, result, error)
    with pytest.raises(ConnectionError, match="alice1550_qwp_1"):
        manager.get_angle("alice1550_qwp_1")


@pytest.mark.parametrize("result,error", [(-1, 0), (0, 1)])
def test_move_errors_are_reported(manager, result, error):
    manager.backend.move.return_value = (result, error)
    with pytest.raises(ConnectionError, match="servo 1"):
        manager.move_to_angle("alice1550_qwp_1", 20)


def test_settle_timeout_is_reported(manager):
    manager.backend.is_moving.return_value = [True]
    with (
        patch("qtools.pctrl.motion.time.monotonic", side_effect=[0, 0, 2]),
        patch("qtools.pctrl.motion.time.sleep"),
        pytest.raises(TimeoutError, match="settle"),
    ):
        manager.wait_for_settle(["alice1550_qwp_1"], timeout=1)


def test_settle_waits_for_slow_move(manager):
    manager.backend.is_moving.side_effect = [[True], [False]]
    with patch("qtools.pctrl.motion.time.monotonic", side_effect=[0, 0, 7]), patch(
        "qtools.pctrl.motion.time.sleep"
    ):
        manager.wait_for_settle(["alice1550_qwp_1"])
    assert manager.backend.is_moving.call_count == 2


@pytest.mark.parametrize("status", [None, [], [None]])
def test_unknown_motion_status_is_not_treated_as_stopped(manager, status):
    manager.backend.is_moving.return_value = status
    with pytest.raises(ConnectionError, match="moving status"):
        manager.wait_for_settle(["alice1550_qwp_1"])


@pytest.mark.parametrize("driver_class", [SCServo, STServo])
@pytest.mark.parametrize("result,error", [(-1, 0), (0, 1)])
def test_backend_motion_read_failure_is_reported(driver_class, result, error):
    driver = object.__new__(driver_class)
    driver._handler = MagicMock()
    driver._handler.ReadMoving.return_value = (0, result, error)
    with pytest.raises(ConnectionError, match="moving status"):
        driver.is_moving(1)


def test_discovery_closes_backend_when_scan_fails():
    backend = MagicMock()
    backend.list_servos.side_effect = RuntimeError("scan failed")
    with patch("qtools.pctrl.servo_manager.find_serial_ports", return_value=["FAKE"]), patch(
        "qtools.pctrl.servo_manager.ServoBackend", return_value=backend
    ):
        assert auto_discover() is None
    backend.close.assert_called_once()


def test_manager_closes_backend_when_initial_scan_fails(manager):
    backend = MagicMock()
    backend.list_servos.side_effect = RuntimeError("scan failed")
    with patch("qtools.pctrl.servo_manager.ServoBackend", return_value=backend), pytest.raises(
        RuntimeError, match="scan failed"
    ):
        ServoManager(cfg=manager.cfg, mock_mode=True)
    backend.close.assert_called_once()
