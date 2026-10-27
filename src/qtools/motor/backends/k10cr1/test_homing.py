"""Real-hardware homing tests for K10CR1.

Run directly against a connected motor:
    python -m qtools.motor.backends.k10cr1.test_homing
    python -m qtools.motor.backends.k10cr1.test_homing -U COM3
"""
from __future__ import annotations

import argparse
import time
import sys

from qtools.motor.backends.k10cr1.k10cr1 import ThorlabsK10CR1


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def test_identity(motor: ThorlabsK10CR1) -> None:
    _section("identity")
    model, serial = motor.identity
    print(f"  model  = {model}")
    print(f"  serial = {serial}")
    assert serial and serial != 0, "identity query returned no serial"


def test_homing_params(motor: ThorlabsK10CR1) -> dict:
    _section("homing params (before)")
    hp = motor.params_homing
    for k, v in hp.items():
        print(f"  {k:16s} = {v}")
    assert hp["home_velocity"] > 0, "home_velocity must be > 0"
    return hp


def test_blocking_home(motor: ThorlabsK10CR1) -> None:
    """Blocking home must return only after motor has settled at home."""
    _section("blocking home")
    assert motor.blocking is True, "precondition: motor.blocking must be True"

    t0 = time.perf_counter()
    motor.home()  # should block until homed
    elapsed = time.perf_counter() - t0
    print(f"  home() returned after {elapsed:.2f}s")

    # blocking flag must NOT have been mutated by home()
    assert motor.blocking is True, (
        f"motor.blocking was mutated by home()! now={motor.blocking}"
    )

    # after homing, position should be near the offset_distance (~4 deg)
    pos = motor.angle
    print(f"  position after home = {pos:.4f} deg")
    assert 0.0 <= pos <= 15.0, (
        f"position {pos:.4f} not near home (expected ~0-15 deg)"
    )


def test_move_after_home(motor: ThorlabsK10CR1) -> None:
    """After home, blocking move must still respect blocking flag."""
    _section("move after home (regression check)")
    assert motor.blocking is True, "precondition: blocking must still be True"

    target = 45.0
    motor.angle = target
    actual = motor.angle
    print(f"  moved to {target} deg, actual = {actual:.4f} deg")
    # wrap-aware closeness
    diff = abs((actual - target + 180) % 360 - 180)
    assert diff < 0.5, f"position error {diff:.4f} deg too large"


def test_double_home(motor: ThorlabsK10CR1) -> None:
    """Second home() must still block — regression for the old
    `self.blocking = False` bug that mutated object state."""
    _section("double home (regression check)")
    assert motor.blocking is True

    motor.home()
    assert motor.blocking is True, "blocking mutated after first home()"

    t0 = time.perf_counter()
    motor.home()
    elapsed = time.perf_counter() - t0
    print(f"  second home() returned after {elapsed:.2f}s")
    assert motor.blocking is True, "blocking mutated after second home()"


def test_nonblocking_home(motor: ThorlabsK10CR1) -> None:
    _section("non-blocking home")
    motor.blocking = False
    try:
        t0 = time.perf_counter()
        motor.home()
        ret_early = time.perf_counter() - t0 < 0.5
        print(f"  home() returned immediately: {ret_early}")

        # now wait for completion via is_moving
        waited = 0.0
        while motor.is_moving():
            time.sleep(0.1)
            waited += 0.1
            if waited > 60:
                raise TimeoutError("homing did not finish within 60s")
        print(f"  homing completed after polling for {waited:.2f}s")
        print(f"  position = {motor.angle:.4f} deg")
    finally:
        motor.blocking = True


def main() -> int:
    parser = argparse.ArgumentParser(description="K10CR1 homing real-hardware tests")
    parser.add_argument(
        "-U", "--device", default="", metavar="PORT",
        help="Serial port (e.g. COM3). Auto-detect if omitted.",
    )
    args = parser.parse_args()

    print(f"Opening K10CR1 on port '{args.device or 'auto'}'...")
    motor = ThorlabsK10CR1(port=args.device, blocking=True)

    tests = [
        test_identity,
        test_homing_params,
        test_blocking_home,
        test_move_after_home,
        test_double_home,
        test_nonblocking_home,
    ]
    failed: list[str] = []
    for t in tests:
        try:
            t(motor)
        except Exception as e:
            failed.append(f"{t.__name__}: {e}")
            print(f"  [FAIL] {e}")

    _section("summary")
    print(f"  ran: {len(tests)}")
    print(f"  ok : {len(tests) - len(failed)}")
    print(f"  fail: {len(failed)}")
    for f in failed:
        print(f"    - {f}")

    motor.stop()
    motor.close()
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
