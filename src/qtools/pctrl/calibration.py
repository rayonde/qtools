#!/usr/bin/env python3
"""
calibration.py
--------------
Polarization controller calibration orchestration engine.

Handles:
  - Calibration sweep generation and execution
  - Sensor readout via MeasManager (TDC / powermeter)
  - Retardance-aware MLE fitting via analysis.fit
  - Verification testing and fidelity evaluation
  - NPZ data persistence + YAML config update
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
import numpy as np
from typing import List, Dict, Any

from .config import ConfigManager, channel_key_string, resolve_target
from .analysis.modeling import JonesModel, map_servo_to_plate
from .analysis.fit import fit_polarization_system


# ══════════════════════════════════════════════════════════════
# Sweep generation
# ══════════════════════════════════════════════════════════════

def generate_sweep_angles(
    step_deg: float = 5.0,
    left: float = -90.0,
    right: float = 90.0
) -> List[float]:
    """Generate a sweep path: 0 -> left -> 0 -> right -> 0."""
    path = []
    ang = 0.0
    while ang > left:
        path.append(ang)
        ang -= step_deg
    path.append(left)
    ang = left + step_deg
    while ang < 0.0:
        path.append(ang)
        ang += step_deg
    path.append(0.0)
    ang = step_deg
    while ang < right:
        path.append(ang)
        ang += step_deg
    path.append(right)
    ang = right - step_deg
    while ang > 0.0:
        path.append(ang)
        ang -= step_deg
    path.append(0.0)
    return path


def generate_sweep(
    step_deg: float,
    left: float,
    right: float,
    deg_per_step: float,
    center_encoder: int,
) -> tuple[list[int], list[float]]:
    """Generate a quantised sweep: (encoder_positions, actual_angles).

    Servos move in discrete encoder steps, so the requested angle step is
    rounded to the nearest encoder increment.  Consecutive duplicate
    positions are collapsed.

    Parameters
    ----------
    step_deg : float — desired angle step (waveplate-relative degrees).
    left, right : float — sweep bounds (waveplate-relative, ≤ 0 / ≥ 0).
    deg_per_step : float — degrees per encoder step (from backend).
    center_encoder : int — encoder value at the centre (waveplate-0)
        position, e.g. 2048 (STS) or 512 (SCS).

    Returns
    -------
    (encoders, actuals) — list of encoder positions and the
        corresponding waveplate-relative angles actually achieved.
    """
    desired = generate_sweep_angles(step_deg, left, right)

    encoders: list[int] = []
    actuals: list[float] = []
    last_enc: int | None = None
    for ang_rel in desired:
        enc = center_encoder + int(round(ang_rel / deg_per_step))
        if enc != last_enc:
            encoders.append(enc)
            actuals.append((enc - center_encoder) * deg_per_step)
            last_enc = enc
    return encoders, actuals


def basis_to_analyzer_deg(basis: str) -> float:
    """Map polarization basis label to linear analyzer angle in degrees."""
    mapping = {"h": 0.0, "v": 90.0, "d": 45.0, "a": -45.0}
    return mapping.get(str(basis).lower(), 0.0)


def servo_sweep_bounds(s: dict) -> tuple[float, float]:
    """Return (lo_rel, hi_rel) waveplate-relative sweep bounds for a servo.

    The encoder-available range
    ``[(min_position - zero_position) * dps, (max_position - zero_position) * dps]``
    is intersected with the configured software angle limits (``min_angle`` /
    ``max_angle``, same frame) so a sweep never drives a servo past either.
    When the software limits don't overlap the encoder range the pair collapses
    to ``(0, 0)``.
    """
    zero = int(s.get("zero_position", 512))
    dps = float(s.get("deg_per_step", 0.2933))
    enc_lo = (int(s.get("min_position", 0)) - zero) * dps
    enc_hi = (int(s.get("max_position", 1023)) - zero) * dps
    sw_lo = float(s.get("min_angle", enc_lo))
    sw_hi = float(s.get("max_angle", enc_hi))
    lo_rel = max(enc_lo, sw_lo)
    hi_rel = min(enc_hi, sw_hi)
    if lo_rel > hi_rel:      # software limits don't overlap the range
        lo_rel = hi_rel = 0.0
    return lo_rel, hi_rel


# ══════════════════════════════════════════════════════════════
# Measurement helpers (via MeasManager)
# ══════════════════════════════════════════════════════════════

def read_measurement(meas_mgr, duration: float = 0.2, samples: int = 1,
                     channels: list[int] | None = None) -> np.ndarray:
    """Read from MeasManager.measure() and return as (C, 2) array.

    Each row is [mean, std_dev] for one channel.
    """
    result = meas_mgr.measure(duration=duration, samples=samples, channels=channels)
    return np.array(result, dtype=float)  # shape (C, 2)


def evaluate_metric(meas_mgr, duration: float = 0.2, samples: int = 1,
                    channels: list[int] | None = None,
                    metric_fn=None) -> float:
    """Compute scalar metric from MeasManager measurement.

    - 1 channel (powermeter or single TDC): returns channel mean.
    - 2+ channels with an explicit *metric_fn*: returns ``metric_fn(meas_mgr)``.
    - 2+ channels without *metric_fn* and without explicit *channels*: returns
      the channel-1 mean (the documented default for plain ``optimize`` /
      ``calibration``).  Only a caller that explicitly requests 2+ channels
      with no metric must provide one — summing singles is not a coincidence
      proxy.
    """
    data = read_measurement(meas_mgr, duration, samples, channels)
    if data.shape[0] == 1:
        return float(data[0, 0])  # single channel → mean
    if metric_fn is not None:
        return float(metric_fn(meas_mgr))
    if not channels:
        return float(data[0, 0])  # default metric: channel-1 mean
    raise ValueError(
        "Multi-channel measurement requires an explicit metric_fn. "
        "Sum of singles is NOT a valid proxy for coincidence."
    )


# ══════════════════════════════════════════════════════════════
# Calibration orchestration
# ══════════════════════════════════════════════════════════════

def run_calibration_group(
    cfg: ConfigManager,
    channel: Dict[str, Any],
    servo_mgr: Any,
    meas_mgr: Any,
    step_deg: float = 5.0,
    speed_deg_s: float = 10.0,
    basis: str = "h",
    fast: bool = False,
    target_servo_name: str | None = None,
    channels: list[int] | None = None,
    duration: float | None = None,
    plot: bool = False,
) -> None:
    """Run calibration sweep + fit for a single channel (servo group)."""
    group_name = channel_key_string(channel["path"], channel["wavelength"])
    wavelength = channel["wavelength"]
    servos = sorted(channel["servos"], key=lambda s: s["order"])
    n_servos = len(servos)

    if n_servos == 0:
        print(f"No servos configured in channel {group_name}. Skipping.")
        return

    is_mock = servo_mgr.mock_mode
    analyzer_deg = basis_to_analyzer_deg(basis)

    print("\n" + "=" * 60)
    print(f"Starting Calibration for Group: '{group_name}' ({wavelength} nm), "
          f"Basis: {basis.upper()}")
    if target_servo_name:
        print(f"Targeting Single Servo: {target_servo_name}")
    print(f"Servos: {[s['name'] for s in servos]}")
    print(f"Analyzer: {analyzer_deg} deg")
    print("=" * 60)

    # ── Active parameters ────────────────────────────────────────
    active_step_deg = step_deg * 2.0 if fast else step_deg
    # Per-step TDC read duration; an explicit --time overrides the default.
    active_duration = duration if duration is not None else (0.05 if fast else 0.2)
    active_samples = 1
    active_test_points = 1 if fast else 25
    # Single pass: sweep -> fit -> verification, then done (no adaptive retry).
    max_attempts = 1

    # ── Precompute per-servo info from config (same angle/encoder
    #    convention as the `set` command: encoder = zero + angle/dps) ──
    servo_info = {}
    for s in servos:
        name = s["name"]
        zero = int(s.get("zero_position", 512))
        dps = float(s.get("deg_per_step", 0.2933))
        lo_rel, hi_rel = servo_sweep_bounds(s)
        servo_info[name] = {
            "id": s["servo_id"],
            "center": 0.0,
            "center_encoder": zero,
            "deg_per_step": dps,
            "lo_native": lo_rel,
            "hi_native": hi_rel,
            "lo_rel": lo_rel,
            "hi_rel": hi_rel,
        }

    # ── Enable torque ────────────────────────────────────────────
    servo_mgr.lock([s["servo_id"] for s in servos])

    # ── Retardance guesses from config (units of pi → radians) ──
    retardance_guesses = [float(s.get("retardance", 0.25)) * np.pi
                          for s in servos]
    waveplate_types = ["RETARDER"] * n_servos

    # ══════════════════════════════════════════════════════════
    # Calibration loop (with retry)
    # ══════════════════════════════════════════════════════════
    fidelity = 0.0
    test_passed = False
    fit_res = {}

    for attempt in range(1, max_attempts + 1):
        # ── Build sweep configs ──────────────────────────────────
        # hold_angles are waveplate-relative (0 = center)
        configs: List[tuple] = []
        if n_servos == 3:
            configs = [
                ([0.0, 0.0, 0.0], 1),    # sweep HWP
                ([45.0, 0.0, 0.0], 1),   # sweep HWP, QWP1 offset
                ([0.0, 0.0, 45.0], 1),   # sweep HWP, QWP2 offset
                ([0.0, 0.0, 0.0], 0),    # sweep QWP1
                ([0.0, 0.0, 0.0], 2),    # sweep QWP2
            ]
        elif n_servos == 2:
            configs = [
                ([0.0, 0.0], 1),
                ([45.0, 0.0], 1),
                ([0.0, 0.0], 0),
            ]
        else:
            configs = [([0.0], 0)]

        if target_servo_name:
            target_idx = next((i for i, s in enumerate(servos)
                              if s["name"] == target_servo_name), None)
            if target_idx is not None:
                configs = [c for c in configs if c[1] == target_idx]

        # ── Precompute sweep paths (encoder-quantised) ──────────────
        config_sweep_encoders: List[List[int]] = []     # encoder positions
        config_sweep_actuals: List[List[float]] = []    # actual achieved angles
        for hold_angs, sweep_idx in configs:
            info = servo_info[servos[sweep_idx]["name"]]
            encs, actuals = generate_sweep(
                active_step_deg, info["lo_rel"], info["hi_rel"],
                info["deg_per_step"], info["center_encoder"],
            )
            config_sweep_encoders.append(encs)
            config_sweep_actuals.append(actuals)

        # ── Execute sweeps ───────────────────────────────────────
        data_angles: List[List[float]] = []
        data_encoders: List[List[int]] = []
        data_means: List[List[float]] = []
        data_stds: List[List[float]] = []
        sweep_ids: List[int] = []

        try:
            for c_idx, ((hold_angs, sweep_idx), sweep_actuals) in enumerate(
                zip(configs, config_sweep_actuals), 1
            ):
                s_name = servos[sweep_idx]["name"]
                print(f"\n[Sweep {c_idx}/{len(configs)}] Sweeping {s_name} "
                      f"({len(sweep_actuals)} points)")

                for ang_rel in sweep_actuals:
                    # Build target angles: waveplate-relative → servo-native
                    target_native = []
                    target_encs = []
                    for i, s in enumerate(servos):
                        info_s = servo_info[s["name"]]
                        if i == sweep_idx:
                            target_native.append(info_s["center"] + ang_rel)
                            target_encs.append(info_s["center_encoder"]
                                               + int(round(ang_rel / info_s["deg_per_step"])))
                        else:
                            target_native.append(info_s["center"] + hold_angs[i])
                            target_encs.append(info_s["center_encoder"]
                                               + int(round(hold_angs[i] / info_s["deg_per_step"])))

                    # Move all servos
                    for i, s in enumerate(servos):
                        servo_mgr.move_to_angle(s["name"], target_native[i],
                                                speed_deg_s)

                    if not is_mock:
                        servo_mgr.wait_for_settle([s["name"] for s in servos])
                        time.sleep(0.1)

                    # Measure
                    data = read_measurement(meas_mgr, active_duration, active_samples,
                                            channels=channels)

                    # Log the commanded angles and the measured TDC channel(s).
                    meas_channels = channels if channels else list(range(1, len(data) + 1))
                    reads = ", ".join(f"ch{c}={data[i, 0]:.1f}" for i, c in enumerate(meas_channels))
                    print(f"    angles={[round(float(a), 2) for a in target_native]} deg | {reads} cps")

                    data_angles.append(target_native)
                    data_encoders.append(target_encs)
                    data_means.append(data[:, 0].tolist())
                    data_stds.append(data[:, 1].tolist())
                    sweep_ids.append(c_idx)

            print("\nSweep completed!")

        finally:
            # Return to center
            for s in servos:
                servo_mgr.move_to_angle(s["name"], servo_info[s["name"]]["center"],
                                        speed_deg_s)
            if not is_mock:
                servo_mgr.wait_for_settle([s["name"] for s in servos])

        # ── Fit using Jones MLE fitter ───────────────────────────
        servo_sweeps = np.array(data_angles)
        intensities = np.array([m[0] for m in data_means])  # first channel mean
        sweep_ids_arr = np.array(sweep_ids)

        fit_res = fit_polarization_system(
            servo_sweeps, intensities, waveplate_types,
            analyzer_deg=analyzer_deg,
            retardance_guesses=retardance_guesses,
            fit_retardance=True,
            fix_first_offset=not bool(target_servo_name),  # fix only for group
        )
        print(f"Fitting completed! R-squared: {fit_res['r_squared']:.4f}")

        # ── Verification ─────────────────────────────────────────
        print(f"\nRunning verification ({active_test_points} points)...")
        test_angles = []
        test_measured = []

        for _ in range(active_test_points):
            native_angs = []
            for s in servos:
                info = servo_info[s["name"]]
                native_angs.append(
                    float(np.random.uniform(info["lo_native"], info["hi_native"]))
                )
            for i, s in enumerate(servos):
                servo_mgr.move_to_angle(s["name"], native_angs[i], speed_deg_s)

            if not is_mock:
                servo_mgr.wait_for_settle([s["name"] for s in servos])
                time.sleep(0.1)

            data = read_measurement(meas_mgr, active_duration, active_samples,
                                    channels=channels)

            # Log the commanded angles and the measured TDC channel(s).
            meas_channels = channels if channels else list(range(1, len(data) + 1))
            reads = ", ".join(f"ch{c}={data[i, 0]:.1f}" for i, c in enumerate(meas_channels))
            print(f"    [verify] angles={[round(float(a), 2) for a in native_angs]} deg | {reads} cps")

            test_angles.append(native_angs)
            test_measured.append(data[0, 0])  # first channel mean

        # Return to center
        for s in servos:
            servo_mgr.move_to_angle(s["name"], servo_info[s["name"]]["center"],
                                    speed_deg_s)
        if not is_mock:
            servo_mgr.wait_for_settle([s["name"] for s in servos])

        test_angles = np.array(test_angles)
        test_measured_arr = np.array(test_measured)

        # Compute model predictions for test points
        test_pred = []
        for k in range(active_test_points):
            angs = []
            for j in range(n_servos):
                s_fit = fit_res["servos"][j]
                angs.append(map_servo_to_plate(
                    test_angles[k, j],
                    s_fit["scale"], s_fit["offset"],
                    s_fit.get("a_wobble", 0.0), s_fit.get("b_wobble", 0.0)
                ))
            # Rebuild (theta, delta) pairs
            ang_pairs = [(angs[j], fit_res["servos"][j]["retardance"])
                         for j in range(n_servos)]
            pred = JonesModel.intensity(
                ["RETARDER"] * n_servos, ang_pairs,
                fit_res["alpha"], fit_res["beta"], analyzer_deg=analyzer_deg
            )
            test_pred.append(fit_res["gain"] * pred + fit_res["bg_offset"])
        test_pred_arr = np.array(test_pred)

        # Fidelity
        int_min = float(np.min(intensities))
        int_max = float(np.max(intensities))
        int_range = int_max - int_min if int_max > int_min else 1.0
        y_meas_n = np.clip((test_measured_arr - int_min) / int_range, 0, 1)
        y_pred_n = np.clip((test_pred_arr - int_min) / int_range, 0, 1)
        fidelity = float(np.mean(1.0 - np.abs(y_meas_n - y_pred_n)))
        print(f"Verification fidelity: {fidelity:.4f}")

        if fidelity >= 0.98:
            test_passed = True
            break

    # ── Plot results (optional) ─────────────────────────────────
    # Plotted regardless of pass/fail so failures can be diagnosed.
    if plot:
        from .analysis.plotting import plot_calibration
        plot_calibration(
            group_name=group_name,
            basis=basis,
            servos=servos,
            servo_sweeps=np.array(data_angles),
            measured_means=np.array(data_means),
            sweep_ids=sweep_ids_arr,
            fit_res=fit_res,
            test_angles=np.array(test_angles),
            test_measured=np.array(test_measured),
            test_pred=np.array(test_pred_arr),
            configs=configs,
            analyzer_deg=analyzer_deg,
            wavelength=wavelength,
            fidelity=fidelity,
        )

    # ══════════════════════════════════════════════════════════
    # Save results
    # ══════════════════════════════════════════════════════════
    if test_passed or fast:
        if fast and not test_passed:
            print("[Warning] Fast mode — skipping fidelity check.")
            test_passed = True

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("pctrl_calibration_data")
        out_dir.mkdir(exist_ok=True)

        # ── Save per-servo calibration CSVs ──────────────────────
        measured_means = np.array(data_means)  # (N, C)
        measured_stds = np.array(data_stds)    # (N, C)
        servo_encoders = np.array(data_encoders)  # (N, M)
        for i, s in enumerate(servos):
            if target_servo_name and s["name"] != target_servo_name:
                continue

            # Filter rows where this servo was the swept one (closest
            # approximation: rows from sweep configs targeting this servo).
            # For simplicity, save all rows — the sweep_id lets users
            # filter later.
            csv_path = out_dir / f"cal_{s['name']}_{basis}_{date_str}.csv"
            s_fit = fit_res["servos"][i]

            # Build per-row optical angles for this servo
            optical_angs = [
                map_servo_to_plate(
                    servo_sweeps[row, i],
                    s_fit["scale"], s_fit["offset"],
                    s_fit.get("a_wobble", 0.0), s_fit.get("b_wobble", 0.0),
                )
                for row in range(len(servo_sweeps))
            ]

            retardance_col = np.full(len(servo_sweeps), float(s_fit["retardance"] / np.pi))

            # CSV columns:
            #   servo_angle_deg, encoder_pos, optical_angle_deg,
            #   measured_mean, measured_std, sweep_id, predicted, retardance
            header = ("servo_angle_deg,encoder_pos,optical_angle_deg,"
                      "measured_mean,measured_std,sweep_id,predicted,retardance")
            csv_data = np.column_stack([
                servo_sweeps[:, i],
                servo_encoders[:, i],
                optical_angs,
                measured_means[:, 0] if measured_means.shape[1] == 1
                    else measured_means[:, i % measured_means.shape[1]],
                measured_stds[:, 0] if measured_stds.shape[1] == 1
                    else measured_stds[:, i % measured_stds.shape[1]],
                sweep_ids_arr,
                fit_res["predictions"],
                retardance_col,
            ])
            np.savetxt(csv_path, csv_data, delimiter=",", header=header,
                       comments="", fmt=["%.6f", "%d", "%.6f", "%.6f", "%.6f", "%d", "%.6f", "%.6f"])
            print(f"Saved calibration CSV: {csv_path}")

            # Store path in config (instead of raw arrays)
            sc = cfg.get_servo(s["name"])
            if sc:
                sc["calibration_file"] = str(csv_path)

        # ── Update YAML config with fit parameters ───────────────
        for i, s in enumerate(servos):
            if target_servo_name and s["name"] != target_servo_name:
                continue
            s_fit = fit_res["servos"][i]
            sc = cfg.get_servo(s["name"])
            if sc:
                sc["cal_offset_deg"] = float(s_fit["offset"])
                sc["cal_scale"] = float(s_fit["scale"])
                sc["a_wobble"] = float(s_fit.get("a_wobble", 0.0))
                sc["b_wobble"] = float(s_fit.get("b_wobble", 0.0))
                sc["retardance"] = float(s_fit["retardance"] / np.pi)
                sc["cal_type"] = "single" if target_servo_name else "group"
                sc["notes"] = (
                    f"{'Single' if target_servo_name else 'Group'} calibrated "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
                    f"Basis={basis}. Fitted retardance={s_fit['retardance']:.4f} rad."
                )

        channel["fidelity"] = float(fidelity)
        channel["basis"] = basis
        channel["input_alpha"] = float(fit_res["alpha"])
        channel["input_beta"] = float(fit_res["beta"])
        channel["gain"] = float(fit_res["gain"])
        channel["bg_offset"] = float(fit_res["bg_offset"])

        cfg.save()
        print("Calibration saved to config.")

        # ── Save NPZ (full arrays for analysis) ──────────────────
        npz_path = out_dir / f"cal_{group_name}_{basis}_{date_str}.npz"

        np.savez_compressed(
            npz_path,
            servo_angles=servo_sweeps,
            encoder_positions=servo_encoders,
            measured_means=measured_means,
            measured_stds=measured_stds,
            fitted_intensities=fit_res["predictions"],
            sweep_labels=sweep_ids_arr,
            test_angles=test_angles,
            test_measured=test_measured_arr,
            test_predicted=test_pred_arr,
            config_retardances_pi=np.array([s["retardance"] for s in servos]),
            fitted_retardances_rad=np.array(
                [fit_res["servos"][j]["retardance"] for j in range(n_servos)]
            ),
            fitted_alpha=fit_res["alpha"],
            fitted_beta=fit_res["beta"],
            fidelity=fidelity,
            analyzer_deg=analyzer_deg,
            wavelength_nm=wavelength,
            basis=basis,
        )
        print(f"Saved calibration NPZ: {npz_path}")
    else:
        print(f"\n[Warning] Verification FAILED (fidelity {fidelity:.4f} < 0.98). "
              "Config NOT updated.")


# ══════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════

def run_calibration(
    config: str,
    target: str,
    step_deg: float = 5.0,
    speed_deg_s: float = 10.0,
    basis: str = "h",
    fast: bool = False,
    port: str | None = None,
    mock: bool = False,
    servo_mgr: Any | None = None,
    channels: list[int] | None = None,
    duration: float | None = None,
    plot: bool = False,
) -> None:
    """Run polarization and waveplate calibration.

    *target* can be a servo name, servo ID, channel path, or 'all'.
    *servo_mgr* — optional pre-connected ServoManager. If None, a new one
      is created from *config* + *port*.
    *plot* — if True, save calibration fit / verification / Poincaré-sphere
      figures and display them (see ``analysis.plotting.plot_calibration``).
    """
    from qtools.pctrl.servo_manager import ServoManager
    from qtools.pctrl.meas_manager import MeasManager

    cfg = ConfigManager(config)
    if not cfg.load():
        print(f"Error: Config file not found: {config}")
        sys.exit(1)

    # ── Servo manager ────────────────────────────────────────────
    if servo_mgr is None:
        servo_mgr = ServoManager(config, port=port, mock_mode=mock)

    # ── Measurement manager ──────────────────────────────────────
    if mock:
        from qtools.pctrl.meas_manager import MockMeasManager
        meas_mgr = MockMeasManager()
        print("[Mock] Using MockMeasManager for calibration measurements.")
    else:
        try:
            meas_mgr = MeasManager(config_manager=cfg)
        except Exception as e:
            print(f"[Warning] MeasManager init failed: {e}")
            meas_mgr = None

        # Verify sensor
        if meas_mgr is not None:
            try:
                val = evaluate_metric(meas_mgr, channels=channels)
                ch_label = f" ch{channels}" if channels else ""
                print(f"Sensor OK. Reading{ch_label}: {val:.6e}")
            except Exception as e:
                print(f"\n[Warning] Sensor connection failed: {e}")
                print("Connect a powermeter or TDC first, or use --mock mode.")
                sys.exit(1)

    # ── Resolve target channels ──────────────────────────────────
    resolution = resolve_target(cfg, target)
    target_channels = resolution.channels
    target_servo_name = resolution.target_servo_name

    if not target_channels:
        print(f"Error: Target '{target}' not recognized.")
        sys.exit(1)

    # ── Run calibration for each channel ─────────────────────────
    for ch in target_channels:
        run_calibration_group(
            cfg=cfg,
            channel=ch,
            servo_mgr=servo_mgr,
            meas_mgr=meas_mgr,
            step_deg=step_deg,
            speed_deg_s=speed_deg_s,
            basis=basis,
            fast=fast,
            target_servo_name=target_servo_name,
            channels=channels,
            duration=duration,
            plot=plot,
        )

    # Cleanup
    servo_mgr.disconnect()
