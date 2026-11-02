from unittest.mock import patch

import pytest

from qtools.pctrl import PolarizationController
from qtools.pctrl.config import ConfigManager
from qtools.pctrl.motion import move_to_position, wait_for_positions
from qtools.pctrl.servo_manager import ServoManager
from qtools.pctrl.utils import run_direct_set


class StickyServo:
    """A stopped flag can precede motion, and short commands do not move."""

    def __init__(self, position=512, deadband=8, dps=300 / 1023):
        self.position = position
        self.deadband = deadband
        self.dps = dps
        self.commands = []
        self.pending = None
        self.polls = 0

    def angle_to_pos(self, degrees):
        return round(degrees / self.dps)

    def ReadPosSpeed(self, sid):
        return self.position, 0, 0, 0

    def move(self, sid, position, speed, acc):
        self.commands.append(position)
        self.polls = 0
        self.pending = position if abs(position - self.position) > self.deadband else None
        return 0, 0

    def is_moving(self, sid):
        self.polls += 1
        if self.pending is not None and self.polls >= 2:
            self.position = self.pending
            self.pending = None
        return [False]

    def list_servos(self):
        return [1]

    def lock(self, servo_ids):
        return True

    def close(self):
        pass


@pytest.fixture
def no_poll_delay():
    with patch("qtools.pctrl.motion.time.sleep"):
        yield


def test_stopped_flag_does_not_mean_small_target_was_reached():
    backend = StickyServo()
    backend.move(1, 518, 34, 20)
    with (
        patch("qtools.pctrl.motion.time.monotonic", side_effect=[0, 0, 61]),
        patch("qtools.pctrl.motion.time.sleep"),
        pytest.raises(TimeoutError, match="encoder=512, target=518"),
    ):
        wait_for_positions(backend, {1: 518})


@pytest.mark.parametrize("dps,zero,deadband", [(300 / 1023, 512, 8), (360 / 4096, 2048, 28)])
def test_two_degree_move_overcomes_deadband_after_verified_pre_move(
    tmp_path, no_poll_delay, dps, zero, deadband
):
    cfg = ConfigManager(str(tmp_path / "pctrl.yaml"))
    cfg.servo_type = "scs" if zero == 512 else "sts"
    cfg.add_servo("alice", 1550, "QWP", 1, 1, zero_position=zero, deg_per_step=dps)
    name = "alice1550_qwp_1"
    backend = StickyServo(position=zero, deadband=deadband, dps=dps)
    with patch("qtools.pctrl.servo_manager.ServoBackend", return_value=backend):
        manager = ServoManager(cfg=cfg, mock_mode=True)
    manager.move_to_angle(name, 2.0, overshoot=True)
    # The pre-move must finish before the final command; it cannot be cancelled.
    assert backend.position == backend.commands[0]
    manager.wait_for_settle([name])
    assert len(backend.commands) == 2
    assert backend.position == zero + round(2.0 / dps)
    assert manager._pending_positions == {}


@pytest.mark.parametrize("current,target,expected", [(512, 518, 362), (512, 506, 662), (10, 16, 160)])
def test_overshoot_direction_and_bounds(no_poll_delay, current, target, expected):
    backend = StickyServo(position=current)
    move_to_position(
        backend, 1, target, 34, 20, limits=(0, 1023),
        deg_per_step=backend.dps, overshoot=True, wait=True,
    )
    assert backend.commands == [expected, target]
    assert backend.position == target


def test_no_room_for_overshoot_uses_existing_direct_move_fallback():
    backend = StickyServo()
    move_to_position(
        backend, 1, 518, 34, 20, limits=(500, 520),
        deg_per_step=backend.dps, overshoot=True,
    )
    assert backend.commands == [518]


def test_failed_pre_move_does_not_send_final_target():
    backend = StickyServo(deadband=200)
    with (
        patch("qtools.pctrl.motion.time.monotonic", side_effect=[0, 0, 61]),
        patch("qtools.pctrl.motion.time.sleep"),
        pytest.raises(TimeoutError, match="target=362"),
    ):
        move_to_position(
            backend, 1, 518, 34, 20, limits=(0, 1023),
            deg_per_step=backend.dps, overshoot=True,
        )
    assert backend.commands == [362]


@pytest.mark.parametrize("result,error", [(-1, 0), (0, 1)])
def test_overshoot_does_not_ignore_position_read_errors(result, error):
    backend = StickyServo()
    backend.ReadPosSpeed = lambda sid: (512, 0, result, error)
    with pytest.raises(ConnectionError, match="read servo 1"):
        move_to_position(
            backend, 1, 518, 34, 20, limits=(0, 1023),
            deg_per_step=backend.dps, overshoot=True,
        )
    assert backend.commands == []


@pytest.mark.parametrize("enabled,delta,expected_moves", [
    (True, 0, 1),
    (True, 29, 2),
    (True, 30, 1),
    (True, 31, 1),
    (False, 20, 1),
])
def test_overshoot_is_opt_in_and_only_for_moves_under_three_degrees(
    no_poll_delay, enabled, delta, expected_moves
):
    backend = StickyServo(dps=0.1)
    move_to_position(
        backend, 1, 512 + delta, 34, 20, limits=(0, 1023),
        deg_per_step=0.1, overshoot=enabled,
    )
    assert len(backend.commands) == expected_moves


@pytest.mark.parametrize("degrees,moves", [(2.9, 2), (3.0, 1), (3.1, 1), (-3.0, 1)])
def test_degree_threshold_precedes_scs_encoder_rounding(no_poll_delay, degrees, moves):
    backend = StickyServo()
    move_to_position(
        backend, 1, 512 + degrees / backend.dps, 34, 20,
        limits=(0, 1023), deg_per_step=backend.dps, overshoot=True,
    )
    assert len(backend.commands) == moves


def test_manual_overshoot_waits_for_both_legs(tmp_path, no_poll_delay):
    cfg = ConfigManager(str(tmp_path / "pctrl.yaml"))
    cfg.port = "MOCK"
    cfg.add_servo("alice", 1550, "QWP", 1, 1)
    name = "alice1550_qwp_1"
    cfg.save()
    backend = StickyServo()
    run_direct_set(str(cfg.config_path), f"{name}:2", ph_sts=backend, accurate=True)
    assert len(backend.commands) == 2
    assert backend.position == backend.commands[-1]
    assert backend.commands[0] == 362
    assert all(205 <= pos <= 819 for pos in backend.commands)


def test_api_exposes_overshoot(tmp_path):
    cfg = ConfigManager(str(tmp_path / "pctrl.yaml"))
    cfg.add_servo("alice", 1550, "QWP", 1, 1)
    cfg.save()
    with PolarizationController(str(cfg.config_path), mock=True) as controller:
        with patch("qtools.pctrl.utils.run_direct_set") as direct_set:
            controller.set_angles("alice1550_qwp_1", 2, overshoot=True)
        assert direct_set.call_args.kwargs["accurate"] is True
        assert direct_set.call_args.kwargs["servo_type"] == "scs"


@pytest.mark.parametrize("target", ["alice1550_qwp_1", "alice1550_qwp_1,1"])
def test_optimizer_uses_overshoot_and_waits_before_measuring(tmp_path, no_poll_delay, target):
    from scipy.optimize import minimize

    cfg = ConfigManager(str(tmp_path / "pctrl.yaml"))
    cfg.add_servo("alice", 1550, "QWP", 1, 1)
    cfg.save()
    backend = StickyServo()

    class Detector:
        def __init__(self):
            self.positions = []

        def measure(self, **kwargs):
            assert backend.pending is None, "measurement started before encoder arrival"
            self.positions.append(backend.position)
            return [[100, 0]]

    detector = Detector()

    def optimize_small_steps(objective, x0, **kwargs):
        # Exercise a late-stage small simplex instead of the normal broad start.
        kwargs["options"]["initial_simplex"] = [[0.0], [2.0]]
        return minimize(objective, x0, **kwargs)

    with (
        patch("qtools.pctrl.servo_manager.ServoBackend", return_value=backend),
        patch("qtools.pctrl.optimize.minimize", side_effect=optimize_small_steps),
        PolarizationController(str(cfg.config_path), mock=True) as controller,
        patch.object(controller.servo_mgr, "_mock_mode", False),
    ):
        # Exercise the real settle path using simulated hardware.
        controller.optimize(
            target, overshoot=True, step_size_deg=2, maxiter=1,
            measurement_adapter=detector, verbose=False,
        )
    assert 362 in backend.commands  # the existing 150-count first leg
    assert 519 in detector.positions  # 2 degrees produced actual movement


def test_optimizer_cli_forwards_overshoot():
    from qtools.pctrl.cli import main

    with (
        patch("sys.argv", ["pctrl", "--mock", "optimize", "alice", "--overshoot"]),
        patch("qtools.pctrl.PolarizationController") as controller_class,
    ):
        main()
    assert controller_class.return_value.optimize.call_args.kwargs["overshoot"] is True
