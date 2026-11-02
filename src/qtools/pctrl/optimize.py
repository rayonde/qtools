#!/usr/bin/env python3
"""
optimize.py
-----------
Noise-aware Nelder-Mead optimization of TDC measurements over servo angles.

Only hill-climbing is performed: no full parameter sweep is used.  Each
evaluation averages the configured measurement and the optimizer termination
tolerance is tied to the measured noise so fluctuation is not mistaken for a
real signal change.
"""

import time
import logging
from typing import Callable, List, Dict, Any, Optional, Sequence
import numpy as np
from scipy.optimize import minimize

from qtools.pctrl.calibration import (
    servo_sweep_bounds,
)
from qtools.pctrl.config import channel_key_string

logger = logging.getLogger(__name__)


BasisPair = tuple[str, str]


def normalize_basis_pairs(basis: Sequence[Sequence[str]] | None) -> tuple[BasisPair, ...]:
    """Normalize user supplied two-arm basis labels."""
    if basis is None:
        return ()
    pairs = []
    for pair in basis:
        if len(pair) != 2:
            raise ValueError(f"Each basis combination must contain two labels: {pair!r}")
        pairs.append((str(pair[0]).upper(), str(pair[1]).upper()))
    if len(set(pairs)) != len(pairs):
        raise ValueError("Basis combinations must be unique")
    return tuple(pairs)


def compose_basis_loss(
    minimization_basis: Sequence[Sequence[str]] = (),
    maximization_basis: Sequence[Sequence[str]] = (),
) -> Callable[[dict[BasisPair, float]], float]:
    """Build a scalar loss from basis-pair rates.

    The optimizer minimizes the returned value.  Therefore minimizing terms
    contribute ``+rate**2`` and maximizing terms contribute ``-rate**2``.
    """
    minimize = normalize_basis_pairs(minimization_basis)
    maximize = normalize_basis_pairs(maximization_basis)
    if not minimize and not maximize:
        raise ValueError("At least one minimization or maximization basis is required")

    def loss(counts: dict[BasisPair, float]) -> float:
        return float(
            sum(float(counts[key]) ** 2 for key in minimize)
            - sum(float(counts[key]) ** 2 for key in maximize)
        )

    return loss


class BasisMeasurement:
    """Measurement adapter for basis-dependent optimization.

    It owns basis motor movement and TDC readout while ``optimize_channel``
    remains the only optimization loop.  Pass ``minimization_basis`` and/or
    ``maximization_basis`` to generate the loss automatically, for example::

        BasisMeasurement(...,
            minimization_basis=[("H", "V"), ("V", "H")],
            maximization_basis=[("D", "D")])
    """

    def __init__(
        self,
        meas_mgr,
        polmeas_cfg,
        motor_mgr,
        *,
        basis_pairs: Sequence[Sequence[str]] | None = None,
        measurement_keys: Sequence[Sequence[str]] | None = None,
        minimization_basis: Sequence[Sequence[str]] = (),
        maximization_basis: Sequence[Sequence[str]] = (),
        loss_fn: Callable[[dict[BasisPair, float]], float] | None = None,
        basis_sides: tuple[str, str] = ("alice", "bob"),
        basis_settle: float = 0.05,
    ):
        self.meas_mgr = meas_mgr
        self.polmeas_cfg = polmeas_cfg
        self.motor_mgr = motor_mgr
        self.basis_sides = basis_sides
        self.basis_settle = float(basis_settle)
        self.minimization_basis = normalize_basis_pairs(minimization_basis)
        self.maximization_basis = normalize_basis_pairs(maximization_basis)
        if basis_pairs is None:
            basis_pairs = measurement_keys
        elif measurement_keys is not None:
            raise ValueError("Pass only one of basis_pairs and measurement_keys")
        if basis_pairs is None:
            basis_pairs = self.minimization_basis + self.maximization_basis
        self.measurement_keys = normalize_basis_pairs(basis_pairs)
        if not self.measurement_keys:
            raise ValueError("basis_pairs or a non-empty loss basis is required")
        missing = set(self.minimization_basis + self.maximization_basis) - set(self.measurement_keys)
        if missing:
            raise ValueError(f"Loss basis pairs are not measured: {sorted(missing)!r}")
        self.loss_fn = loss_fn or compose_basis_loss(
            self.minimization_basis, self.maximization_basis
        )
        self.basis_now: dict[str, str] = {}
        self.last_counts: dict[BasisPair, float] = {}
        # Notebook consumers can append evaluation snapshots here.
        self.history_rows: list = []

    def _basis_angle(self, side: str, basis: str) -> float:
        from qtools.pmeas.entanglement import _get_basis_angle
        return float(_get_basis_angle(self.polmeas_cfg, side, basis))

    def _move_basis(self, side: str, basis: str) -> None:
        key = str(basis).upper()
        if self.basis_now.get(side) == key:
            return
        stage = self.motor_mgr.get_motor(side)
        stage.move_to(self._basis_angle(side, key))
        stage.wait_move()
        time.sleep(self.basis_settle)
        self.basis_now[side] = key

    def _read(self, duration, samples, channels, measure_type, ch_start, ch_stop, delay, window_start, window_stop, threshvolt) -> float:
        if measure_type != "pairs":
            result = self.meas_mgr.measure(duration=duration, samples=samples, channels=channels)
        else:
            result = self.meas_mgr.measure(
                duration=duration, samples=samples, measure_type="pairs",
                ch_start=ch_start, ch_stop=ch_stop, delay=delay,
                window_start=window_start, window_stop=window_stop,
                threshvolt=threshvolt,
            )
        return float(result[0][0])

    def measure(self, duration=None, samples=None, channels=None, measure_type="singles",
                ch_start=None, ch_stop=None, delay=None, window_start=None,
                window_stop=None, threshvolt=None) -> list:
        counts = {}
        for basis_a, basis_b in self.measurement_keys:
            self._move_basis(self.basis_sides[0], basis_a)
            self._move_basis(self.basis_sides[1], basis_b)
            counts[(basis_a, basis_b)] = self._read(
                duration, samples, channels, measure_type, ch_start, ch_stop,
                delay, window_start, window_stop, threshvolt,
            )
        self.last_counts = counts
        return [(float(self.loss_fn(counts)), 0.0)]


class OptimizeResult(list):
    """Optimization result container. Subclasses list for backwards compatibility
    so it can be treated directly as a list of optimal physical angles."""

    def __init__(
        self,
        optimal_angles: List[float],
        success: bool,
        optimal_value: float,
        n_iterations: int,
        n_evaluations: int,
        message: str,
        history: List[Dict[str, Any]] | None = None,
    ):
        super().__init__(optimal_angles)
        self.optimal_angles = optimal_angles
        self.success = success
        self.optimal_value = optimal_value
        self.n_iterations = n_iterations
        self.n_evaluations = n_evaluations
        self.message = message
        self.history = history or []


def _relative_noise_tolerance(base_mean: float, noise_std: float) -> float:
    """Return a function-value stop tolerance from relative measurement noise.

    The absolute noise is capped as a fraction of the measured signal.  This
    keeps a very noisy measurement from producing an overly large ``fatol``
    and terminating Nelder-Mead before the simplex has explored enough points.
    """
    mean_scale = abs(float(base_mean))
    noise_scale = max(float(noise_std), 1e-12)
    if mean_scale <= 1e-12:
        return max(0.5 * noise_scale, 1e-6)

    relative_noise = noise_scale / mean_scale
    relative_tolerance = float(np.clip(relative_noise / 2.0, 0.005, 0.05))
    return max(
        min(0.5 * noise_scale, mean_scale * relative_tolerance),
        1e-6,
    )


def save_history_to_file(history: List[Dict[str, Any]], filepath: str, minimize_metric: bool = False) -> None:
    """Save optimization step history to JSON, CSV, or YAML file."""
    import os
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".csv":
        import csv
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            if not history:
                return
            n_angles = len(history[0]["angles"])
            angle_headers = [f"angle_{i+1}" for i in range(n_angles)]
            fieldnames = ["evaluation", "val", "loss"] + angle_headers
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in history:
                row = {
                    "evaluation": entry["evaluation"],
                    "val": entry["value"],
                    "loss": entry["value"] if minimize_metric else -entry["value"],
                }
                for i, ang in enumerate(entry["angles"]):
                    row[f"angle_{i+1}"] = ang
                writer.writerow(row)
    elif ext in (".yaml", ".yml"):
        import yaml
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.safe_dump(history, f, default_flow_style=False)
    else:  # Default to JSON
        import json
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)


# ══════════════════════════════════════════════════════════════
# Core optimizer
# ══════════════════════════════════════════════════════════════

def optimize_channel(
    cfg,
    channel: dict,
    servo_mgr,
    meas_mgr,
    *,
    target_servo_name: Optional[str] = None,
    metric_fn: Optional[Callable] = None,    # Callable[[MeasManager], float]
    callback: Optional[Callable] = None,      # Callable[[int, List[float], float, np.ndarray], None]
    minimize_metric: bool = False,
    method: str = "Nelder-Mead",
    maxiter: int = 30,
    tol: float = 1.0,
    step_size_deg: float = 15.0,
    speed_deg_s: float = 10.0,
    settle_time: float = 0.1,
    duration: float = 0.2,
    samples: int = 1,
    measure_type: str = "singles",
    channels: Optional[List[int]] = None,     # TDC channels for coincidence
    ch_start: Optional[int] = None,
    ch_stop: Optional[int] = None,
    delay: Optional[int] = None,
    window_start: Optional[int] = None,
    window_stop: Optional[int] = None,
    threshvolt: Optional[float] = None,
    verbose: bool = True,
    save_config: bool = False,
    save_process: Optional[Any] = None,
    save: bool = False,                      # Deprecated alias for save_config
    plot: bool = False,
) -> OptimizeResult:
    """Optimize servo angles to maximise/minimise a scalar metric.

    Parameters
    ----------
    metric_fn : Callable[[MeasManager], float], optional
        Required when the sensor has 2+ TDC channels.  For a single-channel
        device (powermeter or single TDC) the default returns the channel mean.
    callback : Callable, optional
        ``callback(iteration, angles, scalar_value, raw_measurement_ndarray)``
        fired after each hardware evaluation.  *raw_measurement* is the
        ``(C, 2)`` array of ``[[mean, std], ...]`` from the sensor.
    channels : list[int], optional
        TDC channel numbers for multi-channel readout (e.g. ``[1, 2]`` for
        coincidence measurement).
    samples : int
        Number of readings averaged per evaluation.  Increase this when
        measurement fluctuation is high.
    tol : float
        Nelder-Mead angle tolerance in degrees.  The default 1.0 deg is
        intentionally loose so the optimizer does not chase measurement noise.
    plot : bool, optional
        If True, save and display the metric / servo-angle convergence
        figures (see ``analysis.plotting.plot_optimization_history``).
    """
    servos = sorted(channel["servos"], key=lambda s: s["order"])
    if not servos:
        raise ValueError(
            f"No servos configured in channel '{channel.get('path', 'unknown')}'"
        )

    is_mock = servo_mgr.mock_mode

    # ── Precompute per-servo info from config (same angle/encoder
    #    convention as the `set` command: encoder = zero + angle/dps) ──
    servo_info = {}
    for s in servos:
        name = s["name"]
        lo_rel, hi_rel = servo_sweep_bounds(s)
        servo_info[name] = {
            "center": 0.0,
            "lo_rel": lo_rel,
            "hi_rel": hi_rel,
        }

    # ── Current physical angles (waveplate-relative) ─────────────
    current_phys = []
    for s in servos:
        native = servo_mgr.get_angle(s["name"])
        current_phys.append(native - servo_info[s["name"]]["center"])

    # ── Determine optimisable indices ────────────────────────────
    if target_servo_name:
        opt_indices = [i for i, s in enumerate(servos)
                       if s["name"] == target_servo_name]
        if not opt_indices:
            raise ValueError(
                f"Servo '{target_servo_name}' not found in "
                f"channel '{channel.get('path')}'"
            )
    else:
        opt_indices = list(range(len(servos)))

    x0 = [current_phys[idx] for idx in opt_indices]

    # ── Bounds ───────────────────────────────────────────────────
    bounds = []
    for idx in opt_indices:
        info = servo_info[servos[idx]["name"]]
        bounds.append((info["lo_rel"], info["hi_rel"]))

    # ── Initial simplex ──────────────────────────────────────────
    # Spread the initial simplex over most of the allowed range instead of a
    # small neighbourhood of the current angle: with noisy TDC singles, a
    # narrow simplex makes Nelder-Mead converge on measurement noise.  Each
    # vertex moves a large step (at least 60% of the allowed span) toward one
    # bound along its axis, so the -90..90 window is probed early.
    n_opt = len(opt_indices)
    lo_b = np.array([b[0] for b in bounds])
    hi_b = np.array([b[1] for b in bounds])
    x0c = np.clip(np.asarray(x0, dtype=float), lo_b, hi_b)
    step = np.maximum(np.full(n_opt, float(step_size_deg)), 0.6 * (hi_b - lo_b))
    vertices = [x0c]
    for i in range(n_opt):
        v = x0c.copy()
        if hi_b[i] - x0c[i] >= x0c[i] - lo_b[i]:
            v[i] = min(x0c[i] + step[i], hi_b[i])
        else:
            v[i] = max(x0c[i] - step[i], lo_b[i])
        if abs(v[i] - x0c[i]) < 1e-9:  # guard against a degenerate vertex
            v[i] = lo_b[i] if x0c[i] > (lo_b[i] + hi_b[i]) / 2.0 else hi_b[i]
        vertices.append(v)
    simplex = np.array(vertices)

    servo_mgr.lock([s["servo_id"] for s in servos])

    def read_point(measure_duration, measure_samples):
        measure_kwargs = {}
        if measure_type == "pairs":
            measure_kwargs = {
                "measure_type": measure_type,
                "ch_start": ch_start,
                "ch_stop": ch_stop,
                "delay": delay,
                "window_start": window_start,
                "window_stop": window_stop,
                "threshvolt": threshvolt,
            }
        data = meas_mgr.measure(
            duration=measure_duration,
            samples=measure_samples,
            channels=channels,
            **measure_kwargs,
        )
        return np.asarray(data, dtype=float)

    # ---- Measure baseline noise at the current angles ----
    if verbose:
        print(f"\n[optimize] Measuring baseline {measure_type} to estimate noise...")
    for i, idx in enumerate(opt_indices):
        s = servos[idx]
        native = servo_info[s["name"]]["center"] + x0c[i]
        servo_mgr.move_to_angle(s["name"], native, speed_deg_s)
    if not is_mock:
        servo_mgr.wait_for_settle(
            [servos[idx]["name"] for idx in opt_indices]
        )
        time.sleep(settle_time)

    baseline = read_point(duration, samples)
    base_mean = float(baseline[0, 0])
    base_std = float(baseline[0, 1]) if baseline.shape[0] > 0 else 0.0
    poisson_std = np.sqrt(
        abs(base_mean) / max(float(duration), 1e-9) / max(int(samples), 1)
    )
    if base_std <= 0.0 or base_std < poisson_std:
        base_std = float(poisson_std)
    noise_std = max(base_std, 1.0)
    stop_tolerance = _relative_noise_tolerance(base_mean, noise_std)
    relative_noise = (
        base_std / abs(base_mean) if abs(base_mean) > 1e-12 else float("inf")
    )
    if verbose:
        print(f"[optimize] baseline {measure_type}={base_mean:.4e} +/- {base_std:.4e}")
        print(
            f"[optimize] relative noise={relative_noise:.3e}, "
            f"stop tolerance={stop_tolerance:.4e}"
        )

    # ── Enable torque ────────────────────────────────────────────
    # ── Hardware loss function ───────────────────────────────────
    history: List[Dict[str, Any]] = []
    eval_count = 0

    def measure_point(x, measure_duration, measure_samples):
        """Move to *x*, settle, then return (mean, std, raw measurement)."""
        for i, idx in enumerate(opt_indices):
            s = servos[idx]
            native = servo_info[s["name"]]["center"] + x[i]
            servo_mgr.move_to_angle(s["name"], native, speed_deg_s)

        if not is_mock:
            servo_mgr.wait_for_settle(
                [servos[idx]["name"] for idx in opt_indices]
            )
            time.sleep(settle_time)

        data = read_point(measure_duration, measure_samples)
        val = float(data[0, 0])
        std = float(data[0, 1]) if data.shape[0] > 0 else 0.0
        return val, std, data

    def hardware_loss(x):
        nonlocal eval_count
        eval_count += 1

        val, raw_std, raw_data = measure_point(x, duration, samples)
        if metric_fn:
            val = float(metric_fn(meas_mgr))
            raw_std = 0.0

        history.append({
            "angles": [float(a) for a in x],
            "value": float(val),
            "std": float(raw_std),
            "evaluation": eval_count,
        })

        if verbose:
            print(f"  Eval {eval_count:3d}: "
                  f"angles={[round(float(a), 2) for a in x]} "
                  f"-> value={val:.4e} +/- {raw_std:.4e}",
                  flush=True)

        # Callback with raw measurement data for entanglement analysis
        if callback:
            callback(eval_count, [float(a) for a in x], float(val), raw_data)

        return val if minimize_metric else -val

    # ── Run optimisation ─────────────────────────────────────────
    if verbose:
        print(f"\n[optimize] Running {method} on hardware...")

    opts = {"maxiter": maxiter, "xatol": max(float(tol), 0.05)}
    if method == "Nelder-Mead":
        opts["initial_simplex"] = simplex
        opts["adaptive"] = True
        # Stop once objective changes are below the measurement uncertainty,
        # but cap that threshold relative to the signal for noisy readouts.
        opts["fatol"] = stop_tolerance

    res = minimize(
        hardware_loss, x0, bounds=bounds,
        method=method, options=opts,
    )

    if verbose:
        print(f"\n[optimize] Complete: {res.message}")

    optimal_angles = [float(a) for a in res.x]

    # ── Move to optimum ──────────────────────────────────────────
    for i, idx in enumerate(opt_indices):
        s = servos[idx]
        native = servo_info[s["name"]]["center"] + optimal_angles[i]
        servo_mgr.move_to_angle(s["name"], native, speed_deg_s)

    if not is_mock:
        servo_mgr.wait_for_settle(
            [servos[idx]["name"] for idx in opt_indices]
        )
        time.sleep(settle_time)

    # Re-measure the optimum with the same averaged-readout settings so the
    # reported value is not just one lucky noisy sample.
    final_raw = read_point(duration, samples)
    if metric_fn:
        final_val = float(metric_fn(meas_mgr))
        final_std = 0.0
    else:
        final_val = float(final_raw[0, 0])
        final_std = float(final_raw[0, 1]) if final_raw.shape[0] > 0 else 0.0
    if verbose:
        print(f"[optimize] Final {measure_type} at optimum: "
              f"{final_val:.4e} +/- {final_std:.4e}")

    # ── Save config ──────────────────────────────────────────────
    if save_config or save:
        for i, idx in enumerate(opt_indices):
            s = servos[idx]
            sc = cfg.get_servo(s["name"])
            if sc:
                sc["optimal_phys_angle"] = optimal_angles[i]
        cfg.save()
    # ── Save process / history ───────────────────────────────────
    if save_process:
        if isinstance(save_process, str):
            proc_filepath = save_process
        else:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            proc_filepath = f"optimize_process_{timestamp}.csv"
        save_history_to_file(history, proc_filepath, minimize_metric=minimize_metric)
        if verbose:
            print(f"[optimize] Optimization process history saved to '{proc_filepath}'.")

    # ── Plot convergence (optional) ──────────────────────────────
    if plot:
        from .analysis.plotting import plot_optimization_history
        plot_optimization_history(
            title=channel_key_string(channel["path"], channel["wavelength"]),
            servo_names=[servos[idx]["name"] for idx in opt_indices],
            history=history,
            success=bool(res.success),
            optimal_value=final_val,
        )

    return OptimizeResult(
        optimal_angles=optimal_angles,
        success=bool(res.success),
        optimal_value=final_val,
        n_iterations=int(getattr(res, "nit", 0)),
        n_evaluations=eval_count,
        message=str(res.message),
        history=history,
    )
