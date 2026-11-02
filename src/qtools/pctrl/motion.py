"""Encoder feedback and the existing CLI two-step overshoot movement."""

from __future__ import annotations

import math
import time

from qtools.pctrl.backends import COMM_SUCCESS


def read_position(backend, servo_id: int) -> int:
    position, _, result, error = backend.ReadPosSpeed(servo_id)
    if result != COMM_SUCCESS or error:
        raise ConnectionError(
            f"Failed to read servo {servo_id} (communication={result}, error={error})"
        )
    return position


def wait_for_positions(backend, targets: dict[int, int | None], *,
                       tolerances: dict[int, int] | None = None,
                       timeout: float = 60.0) -> None:
    """Wait for stopped servos AND their encoder targets, when supplied.

    A stopped motor can still be outside its target because of deadband,
    friction or a delayed start. Keep polling until arrival or timeout.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and greater than zero")
    if not targets:
        return
    tolerances = tolerances or {}
    start = time.monotonic()
    pending = {}
    while time.monotonic() - start < timeout:
        pending = {}
        for sid, target in targets.items():
            status = backend.is_moving(sid)
            if not status or status[0] is None:
                raise ConnectionError(f"Cannot read moving status for servo {sid}")
            if status[0]:
                pending[sid] = "moving"
            if target is not None:
                actual = read_position(backend, sid)
                tolerance = tolerances.get(sid, 2)
                if abs(actual - target) > tolerance:
                    pending[sid] = f"encoder={actual}, target={target}, tolerance={tolerance}"
        if not pending:
            return
        time.sleep(0.05)
    raise TimeoutError(f"Servos did not settle within {timeout} seconds: {pending}")


def move_to_position(backend, servo_id: int, target: float, speed: int, acc: int, *,
                     limits: tuple[int, int], deg_per_step: float,
                     overshoot: bool = False,
                     tolerance_steps: int = 2, wait: bool = False) -> None:
    """Run the CLI overshoot move, waiting for the first leg before returning.

    For a nonzero displacement under 3 degrees, first move 150 counts away
    from the target, or toward it if only that direction has room. Keep the
    existing CLI behavior of moving directly if neither direction has room.
    """
    lo, hi = limits
    if not lo <= target <= hi:
        raise ValueError(f"Servo {servo_id} target {target} is outside limits {limits}")
    if not math.isfinite(deg_per_step) or deg_per_step <= 0:
        raise ValueError("deg_per_step must be finite and greater than zero")
    requested = target
    target = round(target)

    def command(position):
        result, error = backend.move(servo_id, position, speed, acc)
        if result != COMM_SUCCESS or error:
            raise ConnectionError(
                f"Failed to move servo {servo_id} (communication={result}, error={error})"
            )

    def arrive(position):
        wait_for_positions(
            backend, {servo_id: position}, tolerances={servo_id: tolerance_steps}
        )

    if overshoot:
        current = read_position(backend, servo_id)
        delta_deg = abs(requested - current) * deg_per_step
        # Compare before encoder quantization so exactly 3 degrees stays direct.
        if (target != current and delta_deg < 3.0
                and not math.isclose(delta_deg, 3.0, rel_tol=0.0, abs_tol=1e-9)):
            to_target = 1 if target >= current else -1
            for direction in (-to_target, to_target):
                waypoint = max(lo, min(hi, current + direction * 150))
                if abs(waypoint - current) >= 150:
                    command(waypoint)
                    arrive(waypoint)
                    break

    command(target)
    if wait:
        arrive(target)
