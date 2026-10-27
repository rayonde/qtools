"""Basis optimization and live drift correction.

- ``optimize_basis`` : 2-D coordinate-descent search for θ₀(A), θ₀(B)
  that maximise |S| (CHSH Bell parameter).
- ``run_live_correction`` : background loop that monitors |S| and
  re-optimises when it drops below a threshold.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any

import numpy as np

from qtools.pmeas._path import get_subdir_path
from qtools.pmeas.analysis.correlation import get_correlation

logger = logging.getLogger(__name__)


def _measure_chsh_at_offsets(
    controller: Any,
    theta_a: float,
    theta_b: float,
    duration: float,
    repetitions: int,
    channel: Any,
) -> float:
    """Measure CHSH S for given zero-offsets."""
    stage_a = controller.motor_mgr.get_motor("alice")
    stage_b = controller.motor_mgr.get_motor("bob")

    alice_set = [theta_a % 180.0, (theta_a + 45.0) % 180.0,
                 (theta_a + 22.5) % 180.0, (theta_a + 67.5) % 180.0]
    bob_set   = [theta_b % 180.0, (theta_b + 45.0) % 180.0,
                 (theta_b + 22.5) % 180.0, (theta_b + 67.5) % 180.0]

    C = np.zeros((4, 4))
    for i, ang_a in enumerate(alice_set):
        if stage_a is not None:
            stage_a.move_to(ang_a)
            stage_a.wait_move()
        for j, ang_b in enumerate(bob_set):
            if stage_b is not None:
                stage_b.move_to(ang_b)
                stage_b.wait_move()
                time.sleep(0.05)

            if controller.meas_mgr is not None:
                res_r = controller.meas_mgr.measure(
                    detector="tdc", channels=channel,
                    duration=duration, samples=repetitions,
                    meas_type="pairs",
                )
                if isinstance(res_r, dict):
                    first_key = list(res_r.keys())[0]
                    mean_r, _ = res_r[first_key]
                else:
                    mean_r, _ = res_r
            else:
                mean_r = 0.0

            C[i, j] = mean_r

    E_ab, _   = get_correlation(C[0, 0], C[1, 1], C[0, 1], C[1, 0])
    E_abp, _  = get_correlation(C[0, 2], C[1, 3], C[0, 3], C[1, 2])
    E_apb, _  = get_correlation(C[2, 0], C[3, 1], C[2, 1], C[3, 0])
    E_apbp, _ = get_correlation(C[2, 2], C[3, 3], C[2, 3], C[3, 2])
    return E_ab - E_abp + E_apb + E_apbp


def optimize_basis(
    controller: Any,
    serial_a: str,
    serial_b: str,
    duration: float = 0.5,
    repetitions: int = 2,
    channel: Any = (0, 1),
    start_step: float = 4.0,
    tol: float = 0.1,
) -> tuple[float, float, float]:
    """2-D coordinate-descent search maximising |S|."""
    print("\n--- Basis Optimisation ---")

    cfg = controller.cfg
    dev_a = cfg.get_device(serial_a) or {}
    dev_b = cfg.get_device(serial_b) or {}
    x = float(dev_a.get("calibration", {}).get("theta_0") or dev_a.get("theta_0") or dev_a.get("calibration", {}).get("zero_offset") or dev_a.get("zero_offset", 15.0))
    y = float(dev_b.get("calibration", {}).get("theta_0") or dev_b.get("theta_0") or dev_b.get("calibration", {}).get("zero_offset") or dev_b.get("zero_offset", 15.0))

    def obj(ta, tb):
        S = _measure_chsh_at_offsets(
            controller=controller,
            theta_a=ta, theta_b=tb,
            duration=duration, repetitions=repetitions,
            channel=channel,
        )
        print(f"    A={ta:.4f}°  B={tb:.4f}°  →  |S|={abs(S):.4f}")
        return -abs(S)

    best_obj = obj(x, y)
    delta = start_step
    for iteration in range(15):
        if delta < tol:
            break
        improved = False
        for dx in (-delta, delta):
            o = obj((x + dx) % 180.0, y)
            if o < best_obj:
                x = (x + dx) % 180.0; best_obj = o; improved = True; break
        for dy in (-delta, delta):
            o = obj(x, (y + dy) % 180.0)
            if o < best_obj:
                y = (y + dy) % 180.0; best_obj = o; improved = True; break
        if not improved:
            delta *= 0.5

    best_s = -best_obj
    print(f"Optimised: A={x:.3f}°  B={y:.3f}°  →  |S|={best_s:.4f}")

    from qtools.pmeas.analysis.jones import compute_target_angles
    for sn, val in ((serial_a, x), (serial_b, y)):
        entry = cfg.get_device(sn) or {}
        entry.setdefault("calibration", {})["theta_0"] = val
        entry["bases"] = compute_target_angles(val, entry.get("waveplate", "hwp"))
        cfg.register_device(sn, **entry)
    cfg.save()
    print("[OK] Optimal offsets saved (theta_0 in calibration, bases on device).")

    return x, y, best_s


def _append_to_npz(filename: str, data_dict: dict, max_entries: int = 1000):
    """Append data to a ``.npz`` file with a rolling window."""
    path = get_subdir_path("data", filename)
    existing = {}
    if os.path.exists(path):
        try:
            with np.load(path, allow_pickle=True) as ld:
                for k in ld.files:
                    existing[k] = list(ld[k])
        except Exception:
            pass
    for k, v in data_dict.items():
        existing.setdefault(k, []).extend(list(v) if isinstance(v, (list, np.ndarray)) else [v])
    for k in existing:
        if len(existing[k]) > max_entries:
            existing[k] = existing[k][-max_entries:]
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "wb") as f:
            np.savez(f, **{k: np.array(v) for k, v in existing.items()})
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def run_live_correction(
    controller: Any,
    serial_a: str, serial_b: str,
    interval: float = 60.0,
    threshold: float = 2.5,
    duration: float = 1.0,
    repetitions: int = 2,
    channel: Any = (0, 1),
    filename: str = "drift_history.npz",
):
    """Background loop: periodically check |S|, re-optimise if drifted."""
    stage_a = controller.motor_mgr.get_motor("alice")
    stage_b = controller.motor_mgr.get_motor("bob")
    name_a = getattr(stage_a, "_name", "alice")
    name_b = getattr(stage_b, "_name", "bob")

    print("\n" + "=" * 60)
    print("  LIVE DRIFT TRACKING")
    print(f"  Alice: {name_a}  Bob: {name_b}")
    print(f"  Interval: {interval}s  |  Threshold: |S| < {threshold}")
    print("=" * 60)

    cfg = controller.cfg
    dev_a = cfg.get_device(serial_a) or {}
    dev_b = cfg.get_device(serial_b) or {}
    theta_a = float(dev_a.get("calibration", {}).get("theta_0") or dev_a.get("theta_0") or dev_a.get("calibration", {}).get("zero_offset") or dev_a.get("zero_offset", 15.0))
    theta_b = float(dev_b.get("calibration", {}).get("theta_0") or dev_b.get("theta_0") or dev_b.get("calibration", {}).get("zero_offset") or dev_b.get("zero_offset", 15.0))
    t0 = time.time()

    try:
        while True:
            elapsed = time.time() - t0
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n[{ts}] t={elapsed:.0f}s  —  checking |S|...")

            S = _measure_chsh_at_offsets(
                controller=controller,
                theta_a=theta_a, theta_b=theta_b,
                duration=duration, repetitions=repetitions,
                channel=channel,
            )
            print(f"  |S| = {abs(S):.4f}")

            if abs(S) < threshold:
                print(f"  [DRIFT] |S| < {threshold} — re-optimising...")
                theta_a, theta_b, S = optimize_basis(
                    controller=controller,
                    serial_a=serial_a,
                    serial_b=serial_b,
                    duration=0.5, repetitions=2,
                    channel=channel, start_step=3.0, tol=0.1,
                )
            else:
                print(f"  [STABLE] |S| ≥ {threshold}")

            _append_to_npz(filename, {
                "timestamp": time.time(),
                "elapsed": elapsed,
                "theta_a": theta_a, "theta_b": theta_b,
                "chsh_s": S, "chsh_s_abs": abs(S),
            })
            time.sleep(interval)

    except (KeyboardInterrupt, SystemExit):
        print("\n[INFO] Drift tracking terminated by user.")
