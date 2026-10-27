"""Full qtools.motor package integration tests.

Tests the complete API surface: device discovery, connection management,
all MotorBackend methods, and config persistence.

Run against real hardware:
    python -m tests.motor.hardware_integration
    python -m tests.motor.hardware_integration -U COM3
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from qtools.motor.api import get_motor
from qtools.motor.backends.motor import list_devices
from qtools.motor.config import MotorConfigManager


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_list_devices() -> list[tuple[str, str]]:
    """Scan for connected devices."""
    _section("list_devices()")
    devices = list_devices()
    print(f"  found {len(devices)} device(s)")
    for i, (port, label) in enumerate(devices, 1):
        print(f"  [{i}] {port}: {label}")
    assert len(devices) > 0, "no devices connected"
    return devices


def test_get_motor_auto(port: str = ""):
    """Auto-detect single device via get_motor()."""
    _section("get_motor() auto-detect")
    motor = get_motor()
    print(f"  resolved: {motor.serial}")
    assert motor.serial, "serial should be populated"
    return motor


def test_get_motor_by_port(port: str):
    """Connect by explicit port."""
    _section(f"get_motor(port='{port}')")
    motor = get_motor(port=port)
    print(f"  resolved: {motor.serial}")
    return motor


def test_connect_lifecycle(motor):
    """Test connect/disconnect context manager."""
    _section("connect lifecycle")
    with motor:
        print(f"  connected: {motor.is_connected}")
        assert motor.is_connected, "should be connected inside context"
    print(f"  disconnected: {not motor.is_connected}")
    assert not motor.is_connected, "should be disconnected after context"


def test_get_stage_name(motor):
    """Query stage name."""
    _section("get_stage_name()")
    with motor:
        name = motor.get_stage_name()
        print(f"  stage name: {name}")
        assert name, "stage name should not be empty"
        return name


def test_home_and_position(motor):
    """Home motor and check position."""
    _section("home() + get_position()")
    with motor:
        motor.home()
        pos = motor.get_position()
        print(f"  position after home: {pos:.4f}°")
        # zero_offset is applied, so position should be ~0 after home
        assert -1.0 <= pos <= 1.0, f"position {pos} not near 0 after home"


def test_move_to(motor):
    """Absolute positioning."""
    _section("move_to()")
    with motor:
        motor.home()
        targets = [45.0, 90.0, 135.0, 180.0]
        for target in targets:
            motor.move_to(target)
            pos = motor.get_position()
            diff = abs((pos - target + 180) % 360 - 180)
            print(f"  move_to({target:6.1f}°) -> {pos:6.4f}° (err={diff:.4f}°)")
            assert diff < 0.5, f"positioning error {diff}° too large"


def test_move_by(motor):
    """Relative displacement."""
    _section("move_by()")
    with motor:
        motor.home()
        start = motor.get_position()
        print(f"  start: {start:.4f}°")

        motor.move_by(30.0)
        after_30 = motor.get_position()
        print(f"  move_by(+30°) -> {after_30:.4f}°")

        motor.move_by(-30.0)
        after_back = motor.get_position()
        print(f"  move_by(-30°) -> {after_back:.4f}°")

        # should return to near start
        drift = abs((after_back - start + 180) % 360 - 180)
        print(f"  drift: {drift:.4f}°")
        assert drift < 0.5, f"return drift {drift}° too large"


def test_zero(motor):
    """Move to software zero."""
    _section("zero()")
    with motor:
        motor.home()
        motor.move_to(90.0)
        pos_90 = motor.get_position()
        print(f"  at 90°: {pos_90:.4f}°")

        motor.zero()
        pos_zero = motor.get_position()
        print(f"  after zero(): {pos_zero:.4f}°")
        assert abs(pos_zero) < 0.5, f"should be near 0 after zero(), got {pos_zero}"


def test_velocity(motor):
    """Get/set velocity."""
    _section("get_velocity() / set_velocity()")
    with motor:
        v_before = motor.get_velocity()
        print(f"  velocity before: {v_before:.2f}°/s")

        motor.set_velocity(5.0)
        v_after = motor.get_velocity()
        print(f"  set_velocity(5.0) -> {v_after:.2f}°/s")
        assert abs(v_after - 5.0) < 0.1, f"velocity not set correctly: {v_after}"

        # restore original
        motor.set_velocity(v_before)
        v_restored = motor.get_velocity()
        print(f"  restored: {v_restored:.2f}°/s")


def test_stop(motor):
    """Test stop (non-intrusive: just call it after move completes)."""
    _section("stop()")
    with motor:
        motor.home()
        motor.move_to(0.0)
        motor.stop()  # should be safe to call even when not moving
        print("  stop() called without error")


def test_wait_move(motor):
    """wait_move() after blocking move."""
    _section("wait_move()")
    with motor:
        motor.home()
        motor.move_to(45.0)
        motor.wait_move()  # should return immediately if already done
        pos = motor.get_position()
        print(f"  position after wait_move(): {pos:.4f}°")
        assert abs(pos - 45.0) < 0.5


def test_zero_offset_with_temp_config(temp_config_dir: Path):
    """set_zero_offset() with isolated config — passed via get_motor(config_mgr=...)."""
    _section("set_zero_offset() + config persistence")

    # Isolated temp config — never touches real motor_config.yaml
    config_path = temp_config_dir / "motor_config.yaml"
    config_mgr = MotorConfigManager(config_path)
    config_mgr.load_or_create()

    # Pass config_mgr through get_motor so MotorBackend forwards it to K10CR1Backend
    motor = get_motor(config_mgr=config_mgr)
    with motor:
        motor.home()

        # Register device in temp config
        serial = motor.serial
        config_mgr.upsert_device(_serial=serial, id=serial, name=f"test_{serial}")

        # Set zero offset to current position
        motor.set_zero_offset(None)
        offset1 = motor._impl.zero_offset
        print(f"  set_zero_offset(None) -> {offset1:.4f}°")

        # Set explicit offset
        motor.set_zero_offset(10.0)
        offset2 = motor._impl.zero_offset
        print(f"  set_zero_offset(10.0) -> {offset2:.4f}°")
        assert abs(offset2 - 10.0) < 0.1

        # Restore before we read config file
        motor.set_zero_offset(0.0)
        print(f"  restored zero_offset to 0.0°")

    # Re-read config and verify it was saved to tmp file
    config_mgr2 = MotorConfigManager(config_path)
    config_mgr2.load()
    dev = config_mgr2.get_device(serial)
    assert dev is not None, f"device {serial} not in config"
    saved_offset = float(dev.get("zero_offset", 0.0))
    print(f"  config saved offset: {saved_offset:.4f}°")
    assert abs(saved_offset - 0.0) < 0.1  # should be 0.0 after restore


def test_identify(motor):
    """Blink LED."""
    _section("identify()")
    with motor:
        if hasattr(motor, "identify"):
            motor.identify()
            print("  LED blink command sent")
        else:
            print("  (identify not available on this backend)")


def main() -> int:
    parser = argparse.ArgumentParser(description="qtools.motor full integration tests")
    parser.add_argument(
        "-U", "--device", default="", metavar="PORT",
        help="Serial port (e.g. COM3). Auto-detect if omitted.",
    )
    args = parser.parse_args()

    print(f"qtools.motor integration tests")
    print(f"port: '{args.device or 'auto'}'")

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_config_dir = Path(tmpdir)

        tests = [
            ("list_devices", lambda: test_list_devices()),
            ("get_motor_auto", lambda: test_get_motor_auto(args.device)),
            ("get_motor_by_port", lambda: test_get_motor_by_port(args.device) if args.device else None),
            ("connect_lifecycle", lambda: test_connect_lifecycle(test_get_motor_auto(args.device))),
            ("get_stage_name", lambda: test_get_stage_name(test_get_motor_auto(args.device))),
            ("home_and_position", lambda: test_home_and_position(test_get_motor_auto(args.device))),
            ("move_to", lambda: test_move_to(test_get_motor_auto(args.device))),
            ("move_by", lambda: test_move_by(test_get_motor_auto(args.device))),
            ("zero", lambda: test_zero(test_get_motor_auto(args.device))),
            ("velocity", lambda: test_velocity(test_get_motor_auto(args.device))),
            ("stop", lambda: test_stop(test_get_motor_auto(args.device))),
            ("wait_move", lambda: test_wait_move(test_get_motor_auto(args.device))),
            ("zero_offset_config", lambda: test_zero_offset_with_temp_config(temp_config_dir)),
            ("identify", lambda: test_identify(test_get_motor_auto(args.device))),
        ]

        failed: list[str] = []
        for name, test_fn in tests:
            try:
                result = test_fn()
                if name == "list_devices" and not result:
                    failed.append(f"{name}: no devices found")
            except Exception as e:
                failed.append(f"{name}: {e}")
                print(f"  [FAIL] {e}")

        _section("summary")
        print(f"  ran: {len(tests)}")
        print(f"  ok : {len(tests) - len(failed)}")
        print(f"  fail: {len(failed)}")
        for f in failed:
            print(f"    - {f}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
