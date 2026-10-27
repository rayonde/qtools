"""Entanglement measurement routines.

- Single-axis coincidence scan: fix Alice, sweep Bob.
- CHSH Bell inequality violation scan: measure S(β) vs. Bob basis offset.
"""

from __future__ import annotations

import ast
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from qtools.pmeas._path import get_subdir_path
from qtools.pmeas.analysis.fit import fit_calibration_curve
from qtools.pmeas.analysis.correlation import get_correlation

logger = logging.getLogger(__name__)


from qtools.pmeas.motor_manager import MotorManager
from qtools.pmeas.meas_manager import MeasManager
from qtools.pmeas.config import ConfigManager


def _fourier_phase_rad(scan_entry: dict) -> float | None:
    """Return the 4-theta fringe phase from fitted Fourier coefficients."""
    fit_info = scan_entry.get("fit") or {}
    coeffs = fit_info.get("coefficients") or {}
    bc = coeffs.get("Bc")
    bs = coeffs.get("Bs")
    if bc is None or bs is None:
        return None
    return float(np.arctan2(bs, bc))


def _state_phase_rad(scan_results: dict[str, dict]) -> float | None:
    """Estimate phi in |VV> + exp(i*phi)|HH> from the D/A fringe phase."""
    vis = {
        basis: scan_results.get(basis, {}).get("visibility")
        for basis in ("H", "D", "A")
    }
    vis = {
        basis: float(value) if value is not None else None
        for basis, value in vis.items()
    }
    phases = {
        basis: _fourier_phase_rad(scan_results.get(basis, {}))
        for basis in ("H", "D", "A")
    }

    da_values = [
        value for value in (vis.get("D"), vis.get("A"))
        if value is not None and np.isfinite(value)
    ]
    if not da_values:
        return None
    fringe_contrast = float(np.clip(np.mean(da_values), 0.0, 1.0))

    sign_terms: list[tuple[float, float]] = []
    phase_h = phases.get("H")
    for basis, factor in (("D", 1.0), ("A", -1.0)):
        phase_basis = phases.get(basis)
        visibility = vis.get(basis)
        if (
            phase_h is None
            or phase_basis is None
            or visibility is None
            or not np.isfinite(visibility)
        ):
            continue
        sign_terms.append(
            (
                float(visibility),
                float(np.sign(factor * np.sin(phase_basis - phase_h))),
            )
        )

    if sign_terms:
        total_weight = sum(weight for weight, _ in sign_terms)
        sign = sum(weight * term for weight, term in sign_terms) / total_weight
    else:
        sign = 1.0
    if abs(sign) < 1e-12:
        sign = 1.0

    signed_cos = float(np.clip(sign * fringe_contrast, -1.0, 1.0))
    return float(np.arccos(signed_cos))


def _get_basis_angle(cfg: ConfigManager | None, target: str | int | None, basis: str | float | int) -> float:
    """Extract a target angle for basis from the device config, or parse direct float angle."""
    if isinstance(basis, (int, float)):
        return float(basis)

    try:
        return float(basis)
    except (ValueError, TypeError):
        pass

    entry = (cfg.get_device(target) or {}) if (cfg is not None and target) else {}
    bases = entry.get("bases", {})

    if isinstance(bases, str):
        try:
            bases = ast.literal_eval(bases)
        except Exception:
            bases = {}

    b_str = str(basis).strip()
    if isinstance(bases, dict):
        val = bases.get(b_str.upper())
        if val is not None:
            return float(val)

    # Fallback: compute from theta_0 in device's calibration sub-dict
    cal = entry.get("calibration", {})
    theta_0_val = cal.get("theta_0") if cal.get("theta_0") is not None else entry.get("theta_0")
    if theta_0_val is None:
        # Legacy compat: also check old zero_offset key on calibration sub-dict
        theta_0_val = cal.get("zero_offset") if cal.get("zero_offset") is not None else entry.get("zero_offset")
    theta_0 = float(theta_0_val) if theta_0_val is not None else 0.0
    b = b_str.upper()
    if b == "H":
        return theta_0
    elif b == "D":
        return (theta_0 + 22.5) % 180.0
    elif b == "V":
        return (theta_0 + 45.0) % 180.0
    elif b == "A":
        return (theta_0 + 67.5) % 180.0
    raise ValueError(f"Unknown basis label or angle: {basis}")
    
# ═══════════════════════════════════════════════════════════════════════════
# Singles / Power sweep scan
# ═══════════════════════════════════════════════════════════════════════════

def run_singles_scan(
    motor_mgr: MotorManager,
    meas_mgr: MeasManager,
    cfg: ConfigManager,
    sweep: str = "bob",
    start_angle: float = 0.0,
    end_angle: float = 360.0,
    step_angle: float = 5.0,
    duration: float = 1.0,
    repetitions: int = 5,
    channel: Any = None,
    save_raw: bool = True,
    save_plot: bool = False,
    unit: str | None = None,
) -> dict:
    """Perform a single detector / power sweep scan on one motor stage."""

    # ── Step 1: Validate & Resolve Motor Stage Handle ─────────────────────
    if motor_mgr is None or meas_mgr is None or cfg is None:
        raise ValueError("motor_mgr, meas_mgr, and cfg are required parameters.")

    try:
        stage = motor_mgr.get_motor(sweep)
        stage.home()
    except Exception:
        stage = None

    name = getattr(stage, "name", sweep)
    sweep_label = name.capitalize() if name else sweep.capitalize()

    # ── Step 2: Initialize Angular Sweep Grid ─────────────────────────────
    n_steps = round((end_angle - start_angle) / step_angle) + 1
    angles = np.linspace(start_angle, start_angle + (n_steps - 1) * step_angle, n_steps)

    # ── Step 3: Print Scan Configuration Summary Header ───────────────────
    detector_type = "powermeter"
    if hasattr(meas_mgr, "detectors") and meas_mgr.detectors.get("powermeter") is None and meas_mgr.detectors.get("tdc") is not None:
        detector_type = "tdc"

    print("\n" + "=" * 60)
    print("  SINGLE DETECTOR / POWER SWEEP SCAN")
    print(f"  Stage ({sweep}): {name}  |  Range: {start_angle}° → {end_angle}° (step {step_angle}°)")
    print("=" * 60)

    values, errors = [], []
    unit_str = "signal"
    locked_unit: str | None = unit  # CLI --unit takes priority; otherwise auto-detect

    # ── Step 4: Execute Angular Sweep & Measurements ──────────────────────
    for idx, angle in enumerate(angles, 1):
        if stage is not None:
            stage.move_to(angle)
            if hasattr(stage, "wait_move"):
                stage.wait_move()
            time.sleep(0.1)

        res = meas_mgr.measure(
            duration=duration,
            samples=repetitions,
            channels=channel,
            detector=detector_type,
            meas_type="power" if detector_type == "powermeter" else "singles",
            task="scan",
            unit=locked_unit,
        )
        if locked_unit is None:
            locked_unit = res.unit
        val, err = res.value, res.error
        unit_str = res.unit
        values.append(val)
        errors.append(err)
        print(f"  [{idx:3d}/{len(angles)}] {angle:6.1f}°  Signal: {val:.4f} ± {err:.4f} {unit_str}")

    values_arr = np.array(values)
    errors_arr = np.array(errors)

    # ── Step 5: Save Visualization Plot (Optional) ────────────────────────
    if save_plot:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(9, 6))
            ax.errorbar(angles, values_arr, yerr=errors_arr, fmt="o-", color="navy", capsize=3, label=f"Signal ({sweep_label})")
            ax.set_xlabel(f"{sweep_label} Stage Angle (°)")
            ax.set_ylabel(f"Signal ({unit_str})")
            ax.set_title("Single Detector Polarization Sweep Scan")
            ax.legend()
            ax.grid(True, linestyle="--", alpha=0.5)
            fname = get_subdir_path("output", "singles_scan.png")
            fig.savefig(fname, dpi=150)
            plt.close(fig)
            print(f"\n[OK] Plot → {fname}")
        except Exception as exc:
            logger.warning("Plot failed: %s", exc)

    # ── Step 6: Export Raw Measurement Data (Optional) ────────────────────
    if save_raw:
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = get_subdir_path("data", f"singles_raw_{ts}.npz")
        np.savez(fname, angles=angles, values=values_arr, errors=errors_arr)
        print(f"[OK] Raw data → {fname}")

    # ── Step 7: Return Consolidated Scan Output ───────────────────────────
    return {"angles": angles, "values": values_arr, "errors": errors_arr}


# ═══════════════════════════════════════════════════════════════════════════
# Coincidence scan
# ═══════════════════════════════════════════════════════════════════════════

def run_coincidence_scan(
    motor_mgr: MotorManager,
    meas_mgr: MeasManager,
    cfg: ConfigManager,
    fix: str = "alice",
    sweep: str = "bob",
    fix_label: str | None = None,
    sweep_label: str | None = None,
    fix_angles: str | float | list[str | float] | None = None,
    start_angle: float = 0.0,
    end_angle: float = 180.0,
    step_angle: float = 10.0,
    duration: float = 1.0,
    repetitions: int = 3,
    subtract_accidentals: bool = False,
    channel: list[int] = [1, 2],
    export: bool | str = True,
    save_plot: bool = False,
    delay: int | None = None,
    window_start: int | None = None,
    window_stop: int | None = None,
) -> dict:
    """Perform a singleaxis coincidence correlation scan: fix one arm at target bases/angles and sweep the other arm."""

    # ── Step 1: Validate & Resolve Motor Stage Handles ─────────────────────
    if motor_mgr is None or meas_mgr is None or cfg is None:
        raise ValueError("motor_mgr, meas_mgr, and cfg are required parameters.")

    try:
        stage_fix = motor_mgr.get_motor(fix)
    except Exception:
        stage_fix = None

    try:
        stage_sweep = motor_mgr.get_motor(sweep)
    except Exception:
        stage_sweep = None

    # Home both motors first so absolute basis angles reference the hardware
    # home position (matches the calibrate/singles flow).
    for stage in (stage_fix, stage_sweep):
        if stage is not None:
            try:
                with stage:
                    stage.home()
            except Exception:
                logger.warning("Failed to home motor '%s'", getattr(stage, "name", fix))

    name_fix = getattr(stage_fix, "name", fix)
    name_sweep = getattr(stage_sweep, "name", sweep)

    ts = time.strftime("%Y%m%d_%H%M%S")
    fix_tag = f"{fix}_{name_fix}" if name_fix and str(name_fix).lower() != str(fix).lower() else str(fix)
    sweep_tag = f"{sweep}_{name_sweep}" if name_sweep and str(name_sweep).lower() != str(sweep).lower() else str(sweep)
    fix_tag_clean = fix_tag.strip().replace(" ", "_").lower()
    sweep_tag_clean = sweep_tag.strip().replace(" ", "_").lower()

    if not fix_label:
        fix_label = (fix or name_fix or "").capitalize()
    if not sweep_label:
        sweep_label = (sweep or name_sweep or "").capitalize()

    # ── Step 2: Initialize Polarization Basis Angles / Fixed Angles & Sweep Grid
    if fix_angles is not None:
        target_spec = fix_angles if isinstance(fix_angles, list) else [fix_angles]
    else:
        target_spec = ["H", "V", "D", "A"]

    serial_fix = getattr(stage_fix, "serial", "") if stage_fix else ""
    target_fix = serial_fix or name_fix or fix

    # Look up target angles for the fixed arm across selected basis labels or angles
    fixed_angles: dict[str, float] = {}
    for item in target_spec:
        ang_val = _get_basis_angle(cfg, target_fix, item)
        label = str(item)
        fixed_angles[label] = ang_val

    # Calculate motor angular sweep grid for the swept arm
    n_steps = round((end_angle - start_angle) / step_angle) + 1
    sweep_angles = np.linspace(start_angle, start_angle + (n_steps - 1) * step_angle, n_steps)

    target_labels = [str(x) for x in target_spec]

    # ── Step 3: Print Scan Configuration Summary Header ───────────────────
    print("\n" + "=" * 60)
    print("  ENTANGLEMENT COINCIDENCE SCAN")
    print(f"  Fixed Arm ({fix}): {name_fix}  |  Swept Arm ({sweep}): {name_sweep}")
    print(f"  Bases/Angles: {', '.join(target_labels)}  |  {sweep_label} Range: {start_angle}° → {end_angle}°")
    print("=" * 60)

    scan_results: dict[str, dict] = {}

    # ── Step 4: Execute Angular Sweep & Coincidence Measurements ──────────
    for basis_name, fixed_ang in fixed_angles.items():
        print(f"\n[{fix_label} → {basis_name} ({fixed_ang:.4f}°)]")
        if stage_fix is not None:
            with stage_fix:
                stage_fix.move_to(fixed_ang)
                stage_fix.wait_move()
            time.sleep(0.2)

        sweep_rates, sweep_errs = [], []
        raw_rates, acc_rates = [], []
        raw_errors, acc_errors = [], []

        for j, sw_ang in enumerate(sweep_angles, 1):
            if stage_sweep is not None:
                with stage_sweep:
                    stage_sweep.move_to(sw_ang)
                    stage_sweep.wait_move()
                time.sleep(0.1)

            # Record coincidence rate via MeasManager
            if meas_mgr is not None:
                res = meas_mgr.measure(
                    detector="tdc",
                    meas_type="pairs",
                    channels=channel,
                    duration=duration,
                    samples=repetitions,
                    task="scan",
                    delay=delay,
                    window_start=window_start,
                    window_stop=window_stop,
                )
                
                if subtract_accidentals:
                    mean_r = float(res.value)
                    std_r = float(res.error)
                    raw_mean = float(res.metrics.get("raw_pair_rate", mean_r))
                    acc_mean = float(res.metrics.get("acc_pair_rate", 0.0))
                    raw_std = float(res.metrics.get("raw_pair_rate_std", std_r))
                    acc_std = float(res.metrics.get("acc_pair_rate_std", 0.0))
                else:
                    mean_r = float(res.metrics.get("raw_pair_rate", res.value))
                    std_r = float(res.metrics.get("raw_pair_rate_std", res.error))
                    raw_mean = mean_r
                    acc_mean = float(res.metrics.get("acc_pair_rate", 0.0))
                    raw_std = std_r
                    acc_std = float(res.metrics.get("acc_pair_rate_std", 0.0))

                label = "net" if subtract_accidentals else "raw"
                rates_str = f"{label}: {mean_r:.1f} ± {std_r:.1f} cps  (raw {raw_mean:.1f}, acc {acc_mean:.1f})"
                print(f"  [{j}/{len(sweep_angles)}] {sweep_label} → {sw_ang:.4f}°  {rates_str}")
            else:
                # Fallback zero values when no measurement manager / hardware is attached
                mean_r, std_r, raw_mean, acc_mean = 0.0, 0.0, 0.0, 0.0
                raw_std, acc_std = 0.0, 0.0

            sweep_rates.append(mean_r)
            sweep_errs.append(std_r)
            raw_rates.append(raw_mean)
            acc_rates.append(acc_mean)
            raw_errors.append(raw_std)
            acc_errors.append(acc_std)

        rates_arr = np.array(sweep_rates)
        errs_arr = np.array(sweep_errs)

        # Fit curve & statistical calculations for this scan
        fit_res = {}
        try:
            fit_res = fit_calibration_curve(
                sweep_angles,
                rates_arr,
                input_pol=basis_name,
                basis=basis_name,
                amplitude_init=max(1.0, float(np.ptp(rates_arr))),
            )
        except Exception as exc:
            logger.warning("Fit failed for basis %s: %s", basis_name, exc)
        min_rate = float(np.min(rates_arr)) if len(rates_arr) > 0 else 0.0
        max_rate = float(np.max(rates_arr)) if len(rates_arr) > 0 else 0.0
        mean_rate = float(np.mean(rates_arr)) if len(rates_arr) > 0 else 0.0

        raw_vis = (max_rate - min_rate) / (max_rate + min_rate) if (max_rate + min_rate) > 0 else 0.0
        fitted_vis = fit_res.get("visibility", 0.0)
        vis = fitted_vis if fitted_vis > 0 else raw_vis

        scan_results[basis_name] = {
            "rates": rates_arr,
            "errors": errs_arr,
            "raw_rates": np.array(raw_rates),
            "acc_rates": np.array(acc_rates),
            "raw_errors": np.array(raw_errors),
            "acc_errors": np.array(acc_errors),
            "min_rate": min_rate,
            "max_rate": max_rate,
            "mean_rate": mean_rate,
            "raw_visibility": raw_vis,
            "fitted_visibility": fitted_vis,
            "visibility": vis,
            "fit": fit_res,
        }

    # ── Step 4b: Compute Overall Entanglement Visibilities (V_HV, V_DA, V_avg) ──
    def _get_vis(bn: str) -> float | None:
        if bn in scan_results:
            return scan_results[bn]["visibility"]
        return None

    vis_h = _get_vis("H")
    vis_v = _get_vis("V")
    vis_d = _get_vis("D")
    vis_a = _get_vis("A")

    v_hv = (vis_h + vis_v) / 2.0 if (vis_h is not None and vis_v is not None) else None
    v_da = (vis_d + vis_a) / 2.0 if (vis_d is not None and vis_a is not None) else None

    all_vis = [data["visibility"] for data in scan_results.values() if "visibility" in data]
    v_avg = float(np.mean(all_vis)) if len(all_vis) > 0 else 0.0
    nonlocality_verified = bool(v_da is not None and v_da > (1.0 / np.sqrt(2)))

    # Print Entanglement Visibility Summary
    print("\n" + "=" * 60)
    print("  ENTANGLEMENT VISIBILITY SUMMARY")
    if vis_h is not None and vis_v is not None:
        print(f"  V_H: {vis_h:.2%}  |  V_V: {vis_v:.2%}  |  V_HV (H/V Basis): {v_hv:.2%}")
    if vis_d is not None and vis_a is not None:
        print(f"  V_D: {vis_d:.2%}  |  V_A: {vis_a:.2%}  |  V_DA (D/A Basis): {v_da:.2%}")
    print(f"  Overall Average Visibility V_avg: {v_avg:.2%}")
    if v_da is not None:
        if nonlocality_verified:
            print("  [OK] Quantum Non-Locality Verified (V_DA > 70.7%)")
        else:
            print("  [INFO] V_DA <= 70.7% (Classical bound threshold not surpassed)")
    print("=" * 60)

    # ── Step 5: Save Correlation Visualization Plot (Optional) ────────────
    if save_plot:
        try:
            import matplotlib.pyplot as plt
            colors = ["navy", "crimson", "forestgreen", "darkorange"]
            fig, ax = plt.subplots(figsize=(9, 6))
            for idx, (bn, data) in enumerate(scan_results.items()):
                c = colors[idx % len(colors)]
                # Data points with errorbars
                ax.errorbar(
                    sweep_angles, data["rates"], yerr=data["errors"],
                    fmt="o", capsize=3, label=f"{fix_label} @ {bn} (data)",
                    color=c,
                )
                # Fine-grid fitted curve
                model_func = data.get("fit", {}).get("model_func")
                if model_func is not None and len(sweep_angles) > 0:
                    start_a = float(np.min(sweep_angles))
                    end_a = float(np.max(sweep_angles))
                    n_fine = int(round((end_a - start_a) / 1.0)) + 1
                    fine_a = np.linspace(start_a, start_a + (n_fine - 1) * 1.0, n_fine)
                    ax.plot(fine_a, model_func(fine_a), "--", color=c, alpha=0.85, label=f"{fix_label} @ {bn} (fit)")

            ax.set_xlabel(f"{sweep_label} HWP angle (°)")
            ax.set_ylabel("Coincidence Rate (cps)")

            title_lines = ["Polarization Coincidence scan"]
            visibility_parts = []
            for basis_name in ("H", "V", "D", "A"):
                visibility = scan_results.get(basis_name, {}).get("visibility")
                if visibility is not None:
                    visibility_parts.append(f"{basis_name}: {float(visibility):.1%}")
            if visibility_parts:
                title_lines.append("  ".join(visibility_parts))

            state_phase_rad = _state_phase_rad(scan_results)
            if state_phase_rad is None:
                title_lines.append(
                    r"$|VV\rangle + \exp(i\phi)|HH\rangle$  (D/A phase unavailable)"
                )
            else:
                phase_deg = float(np.degrees(state_phase_rad))
                title_lines.append(
                    rf"$|VV\rangle + \exp(i\phi)|HH\rangle$, "
                    rf"$\phi = {state_phase_rad:.3f}$ rad "
                    rf"(${phase_deg:.1f}^\circ$)"
                )
            ax.set_title("\n".join(title_lines))
            ax.legend(ncols=2)
            ax.grid(True, linestyle="--", alpha=0.5)
            fname = get_subdir_path("output", f"coincidence_{fix_tag_clean}_vs_{sweep_tag_clean}_{ts}.png")
            fig.savefig(fname, dpi=150)
            plt.close(fig)
            print(f"\n[OK] Plot → {fname}")
        except Exception as exc:
            logger.warning("Plot failed: %s", exc)

    # ── Step 6: Export Measurement CSV Data (Optional) ─────────────────────
    if export and export not in (False, "false", "False"):
        import csv

        if isinstance(export, str) and export not in ("auto", "default", "true", "True", True):
            fname = str(export)
            Path(fname).parent.mkdir(parents=True, exist_ok=True)
        else:
            fname = get_subdir_path("output", f"coincidence_{fix_tag_clean}_vs_{sweep_tag_clean}_{ts}.csv")

        fixed_angle_str = "; ".join([f"{bn} ({ang:.4f}°)" for bn, ang in fixed_angles.items()])

        # Generate 1.0° fine grid for smooth fitted curves
        start_a = float(np.min(sweep_angles)) if len(sweep_angles) > 0 else float(start_angle)
        end_a = float(np.max(sweep_angles)) if len(sweep_angles) > 0 else float(end_angle)
        n_fine = int(round((end_a - start_a) / 1.0)) + 1
        fine_angles = np.linspace(start_a, start_a + (n_fine - 1) * 1.0, n_fine)

        fine_fits: dict[str, np.ndarray] = {}
        for bn, data in scan_results.items():
            model_func = data.get("fit", {}).get("model_func")
            if model_func is not None:
                fine_fits[bn] = model_func(fine_angles)
            else:
                fine_fits[bn] = np.zeros_like(fine_angles)

        with open(fname, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)

            # ── SECTION 1: EXPERIMENT METADATA & CONFIGURATION ─────────────────
            writer.writerow(["# SECTION 1: EXPERIMENT METADATA & CONFIGURATION"])
            writer.writerow(["Parameter", "Value"])
            writer.writerow(["Timestamp", time.strftime("%Y-%m-%d %H:%M:%S")])
            writer.writerow(["Fixed Arm Role", str(fix)])
            writer.writerow(["Fixed Arm Label", str(fix_label)])
            writer.writerow(["Fixed Arm Serial", str(serial_fix)])
            writer.writerow(["Swept Arm Role", str(sweep)])
            writer.writerow(["Swept Arm Label", str(sweep_label)])
            writer.writerow(["Swept Arm Serial", str(getattr(stage_sweep, "serial", "") if stage_sweep else "")])
            writer.writerow(["Fixed Arm Target Angles", fixed_angle_str])
            writer.writerow(["Sweep Start Angle (deg)", f"{start_angle:.4f}"])
            writer.writerow(["Sweep End Angle (deg)", f"{end_angle:.4f}"])
            writer.writerow(["Sweep Step Angle (deg)", f"{step_angle:.4f}"])
            writer.writerow(["Integration Duration (s)", duration])
            writer.writerow(["Repetitions", repetitions])
            writer.writerow(["Channels", str(channel)])
            writer.writerow(["Subtract Accidentals", subtract_accidentals])
            writer.writerow([])

            # ── SECTION 2: ENTANGLEMENT VISIBILITY SUMMARY ─────────────────────
            writer.writerow(["# SECTION 2: ENTANGLEMENT VISIBILITY SUMMARY"])
            writer.writerow(["Metric", "Value", "Description"])
            if v_hv is not None:
                writer.writerow(["Visibility HV Basis (V_HV)", f"{v_hv:.6f}", "Mean of H and V basis visibilities"])
            if v_da is not None:
                writer.writerow(["Visibility DA Basis (V_DA)", f"{v_da:.6f}", "Mean of D and A basis visibilities (Quantum Interference)"])
            writer.writerow(["Overall Average Visibility (V_avg)", f"{v_avg:.6f}", "Mean across all scanned bases"])
            if v_da is not None:
                writer.writerow(["Quantum Non-Locality Verified", str(nonlocality_verified), "V_DA > 70.71% (1/sqrt(2)) threshold"])
            writer.writerow([])

            # ── SECTION 3: PER-SCAN FIT & CALCULATION SUMMARY ─────────────────
            writer.writerow(["# SECTION 3: PER-SCAN FIT & CALCULATION SUMMARY"])
            writer.writerow([
                "Basis",
                "Fixed_Angle_deg",
                "Mean_Rate (cps)",
                "Min_Rate (cps)",
                "Max_Rate (cps)",
                "Fitted_Visibility",
                "Raw_Visibility",
                "R_Squared",
                "Theta_0_deg",
                "Phi_rad",
                "Coeff_A",
                "Coeff_Bc",
                "Coeff_Bs",
                "Coeff_C",
            ])
            for bn, data in scan_results.items():
                fit_info = data.get("fit", {})
                coeffs = fit_info.get("coefficients", {})
                fixed_ang = fixed_angles.get(bn, 0.0)
                writer.writerow([
                    str(bn),
                    f"{fixed_ang:.4f}",
                    f"{data.get('mean_rate', 0.0):.4f}",
                    f"{data.get('min_rate', 0.0):.4f}",
                    f"{data.get('max_rate', 0.0):.4f}",
                    f"{data.get('fitted_visibility', 0.0):.6f}",
                    f"{data.get('raw_visibility', 0.0):.6f}",
                    f"{fit_info.get('r_squared', 0.0):.6f}",
                    f"{fit_info.get('theta_0', 0.0):.4f}",
                    f"{fit_info.get('phi', 0.0):.6f}",
                    f"{coeffs.get('A', 0.0):.4f}",
                    f"{coeffs.get('Bc', 0.0):.4f}",
                    f"{coeffs.get('Bs', 0.0):.4f}",
                    f"{coeffs.get('C', 0.0):.6f}",
                ])
            writer.writerow([])

            # ── SECTION 4: 1.0° FINE-GRID FITTED CURVES ────────────────────────
            if len(fine_angles) > 0:
                writer.writerow(["# SECTION 4: FITTED CURVES DATA (Step = 1.0°)"])
                fit_headers = ["fit_angle_deg"] + [f"fit_curve_{bn} (cps)" for bn in scan_results.keys()]
                writer.writerow(fit_headers)
                for idx, fa in enumerate(fine_angles):
                    row = [f"{fa:.4f}"]
                    for bn in scan_results.keys():
                        row.append(f"{fine_fits[bn][idx]:.6f}")
                    writer.writerow(row)
                writer.writerow([])

            # ── SECTION 5: RAW MEASURED SCAN DATA ──────────────────────────────
            writer.writerow(["# SECTION 5: RAW MEASUREMENT SCAN DATA"])
            headers = ["sweep_angle_deg"]
            for bn, data in scan_results.items():
                headers.append(f"rate_{bn} (cps)")
                headers.append(f"error_{bn} (cps)")
                if "raw_rates" in data and len(data["raw_rates"]) > 0:
                    headers.append(f"raw_rate_{bn} (cps)")
                    headers.append(f"raw_error_{bn} (cps)")
                    headers.append(f"acc_rate_{bn} (cps)")
                    headers.append(f"acc_error_{bn} (cps)")
            writer.writerow(headers)

            for i, sw_ang in enumerate(sweep_angles):
                row = [f"{sw_ang:.4f}"]
                for bn, data in scan_results.items():
                    r = data["rates"][i]
                    e = data["errors"][i]
                    row.append(f"{r:.4f}")
                    row.append(f"{e:.4f}")
                    if "raw_rates" in data and len(data["raw_rates"]) > 0:
                        raw_r = data["raw_rates"][i]
                        acc_r = data["acc_rates"][i]
                        raw_e = data["raw_errors"][i]
                        acc_e = data["acc_errors"][i]
                        row.append(f"{raw_r:.4f}")
                        row.append(f"{raw_e:.4f}")
                        row.append(f"{acc_r:.4f}")
                        row.append(f"{acc_e:.4f}")
                writer.writerow(row)

        print(f"[OK] Raw data → {fname}")

    # ── Step 7: Return Consolidated Scan Output ───────────────────────────
    return {
        "bob_angles": sweep_angles,
        "sweep_angles": sweep_angles,
        "bases": target_labels,
        "v_hv": v_hv,
        "v_da": v_da,
        "v_avg": v_avg,
        "nonlocality_verified": nonlocality_verified,
        **scan_results,
    }


def load_coincidence_csv(file_path: str | Path) -> dict[str, Any]:
    """Load and parse a multi-section coincidence scan CSV file into a structured dictionary.

    Parameters
    ----------
    file_path : str or Path
        Path to the CSV file exported by :func:`run_coincidence_scan`.

    Returns
    -------
    dict
        Dictionary containing:
        - ``metadata``: dict of experiment configuration parameters
        - ``visibility_summary``: dict of high-level visibility metrics (V_HV, V_DA, V_avg)
        - ``scan_summary``: dict of per-basis fit results and statistics
        - ``fine_fits``: dict of 1.0° fine-grid fitted curve arrays
        - ``raw_data``: dict of measured sweep scan arrays
    """
    import csv
    from pathlib import Path

    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"CSV file not found: {path}")

    raw_sections: dict[str, list[list[str]]] = {}
    current_sec_key = "HEADER"
    raw_sections[current_sec_key] = []

    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row:
                continue
            first_cell = row[0].strip()
            if first_cell.startswith("# SECTION"):
                current_sec_key = first_cell
                raw_sections[current_sec_key] = []
            else:
                raw_sections[current_sec_key].append(row)

    # 1. Parse Metadata (Section 1)
    metadata: dict[str, Any] = {}
    for row in raw_sections.get("# SECTION 1: EXPERIMENT METADATA & CONFIGURATION", []):
        if len(row) >= 2 and row[0] != "Parameter":
            metadata[row[0].strip()] = row[1].strip()

    # 2. Parse Visibilities (Section 2)
    vis_summary: dict[str, Any] = {}
    for row in raw_sections.get("# SECTION 2: ENTANGLEMENT VISIBILITY SUMMARY", []):
        if len(row) >= 2 and row[0] != "Metric":
            try:
                vis_summary[row[0].strip()] = float(row[1])
            except ValueError:
                vis_summary[row[0].strip()] = row[1].strip()

    # 3. Parse Per-Scan Fit & Calculation Summary (Section 3)
    scan_summary: dict[str, dict[str, Any]] = {}
    sec3_rows = raw_sections.get("# SECTION 3: PER-SCAN FIT & CALCULATION SUMMARY", [])
    if len(sec3_rows) > 1:
        headers = [h.strip() for h in sec3_rows[0]]
        for row in sec3_rows[1:]:
            if not row:
                continue
            bn = row[0].strip()
            item = {}
            for h, v in zip(headers[1:], row[1:]):
                try:
                    item[h] = float(v)
                except ValueError:
                    item[h] = v.strip()
            scan_summary[bn] = item

    # 4. Parse Fine Grid Fitted Curves (Section 4)
    fine_fits: dict[str, np.ndarray] = {}
    sec4_rows = raw_sections.get("# SECTION 4: FITTED CURVES DATA (Step = 1.0°)", [])
    if len(sec4_rows) > 1:
        headers = [h.strip() for h in sec4_rows[0]]
        col_data: dict[str, list[float]] = {h: [] for h in headers}
        for row in sec4_rows[1:]:
            for h, val in zip(headers, row):
                try:
                    col_data[h].append(float(val))
                except ValueError:
                    pass
        for h, vals in col_data.items():
            fine_fits[h] = np.array(vals)

    # 5. Parse Raw Measurement Scan Data (Section 5)
    raw_data: dict[str, np.ndarray] = {}
    sec5_rows = raw_sections.get("# SECTION 5: RAW MEASUREMENT SCAN DATA", [])
    if len(sec5_rows) > 1:
        headers = [h.strip() for h in sec5_rows[0]]
        col_data = {h: [] for h in headers}
        for row in sec5_rows[1:]:
            for h, val in zip(headers, row):
                try:
                    col_data[h].append(float(val))
                except ValueError:
                    pass
        for h, vals in col_data.items():
            raw_data[h] = np.array(vals)

    return {
        "metadata": metadata,
        "visibility_summary": vis_summary,
        "scan_summary": scan_summary,
        "fine_fits": fine_fits,
        "raw_data": raw_data,
    }


# ═══════════════════════════════════════════════════════════════════════════
# CHSH Bell scan
# ═══════════════════════════════════════════════════════════════════════════

def run_bell_scan(
    motor_mgr: MotorManager,
    meas_mgr: MeasManager,
    cfg: ConfigManager,
    fix: str = "alice",
    sweep: str = "bob",
    start_offset: float = 0.0,
    end_offset: float = 90.0,
    step_offset: float = 5.0,
    duration: float = 1.0,
    repetitions: int = 3,
    subtract_accidentals: bool = False,
    channel: Any = (0, 1),
    save_raw: bool = True,
    save_plot: bool = False,
    full_stats: bool = False,
    delay: int | None = None,
    window_start: int | None = None,
    window_stop: int | None = None,
) -> dict:
    """Scan Bob basis offset β and compute CHSH S(β) curve."""
    if motor_mgr is None or meas_mgr is None or cfg is None:
        raise ValueError("motor_mgr, meas_mgr, and cfg are required parameters.")

    try:
        stage_a = motor_mgr.get_motor(fix)
    except Exception:
        stage_a = None

    try:
        stage_b = motor_mgr.get_motor(sweep)
    except Exception:
        stage_b = None

    # Home both motors first so absolute basis angles reference the hardware
    # home position (matches the calibrate/singles flow).
    for stage in (stage_a, stage_b):
        if stage is not None:
            try:
                with stage:
                    stage.home()
            except Exception:
                logger.warning("Failed to home motor '%s'", getattr(stage, "name", fix))

    name_a = getattr(stage_a, "name", fix)
    name_b = getattr(stage_b, "name", sweep)

    print("\n" + "=" * 60)
    print("  CHSH BELL INEQUALITY SCAN")
    print(f"  Fixed Arm ({fix}): {name_a}  |  Swept Arm ({sweep}): {name_b}")
    print(f"  Offset range: {start_offset}° → {end_offset}°")
    print("=" * 60)

    serial_a = getattr(stage_a, "serial", "") if stage_a else ""
    serial_b = getattr(stage_b, "serial", "") if stage_b else ""
    target_a = serial_a or name_a or fix
    target_b = serial_b or name_b or sweep

    dev_a = cfg.get_device(target_a) if cfg is not None else {}
    dev_b = cfg.get_device(target_b) if cfg is not None else {}

    def _get_theta_0(dev: dict) -> float:
        cal = dev.get("calibration", {})
        val = cal.get("theta_0") or dev.get("theta_0") or cal.get("zero_offset") or dev.get("zero_offset")
        return float(val) if val is not None else 15.0

    theta_0_a = _get_theta_0(dev_a)
    theta_0_b = _get_theta_0(dev_b)

    n_steps_off = round((end_offset - start_offset) / step_offset) + 1
    offsets = np.linspace(start_offset, start_offset + (n_steps_off - 1) * step_offset, n_steps_off)
    s_vals, s_errs = [], []
    coincidence_matrices = []

    a = theta_0_a % 180.0
    a_prime = (theta_0_a + 22.5) % 180.0
    alice_set = [a, (a + 45.0) % 180.0, a_prime, (a_prime + 45.0) % 180.0]

    for k, offset in enumerate(offsets, 1):
        b = (theta_0_b + offset) % 180.0
        b_prime = (theta_0_b + offset + 22.5) % 180.0
        bob_set = [b, (b + 45.0) % 180.0, b_prime, (b_prime + 45.0) % 180.0]

        C = np.zeros((4, 4))
        Cerr = np.zeros((4, 4))

        for i, ang_a in enumerate(alice_set):
            if stage_a is not None:
                stage_a.move_to(ang_a)
                stage_a.wait_move()
            for j, ang_b in enumerate(bob_set):
                if stage_b is not None:
                    stage_b.move_to(ang_b)
                    stage_b.wait_move()
                    time.sleep(0.1)

                if meas_mgr is not None:
                    res = meas_mgr.measure(
                        detector="tdc",
                        meas_type="pairs",
                        channels=channel,
                        duration=duration,
                        samples=repetitions,
                        task="chsh",
                        delay=delay,
                        window_start=window_start,
                        window_stop=window_stop,
                    )
                    if subtract_accidentals:
                        mean_r = res.value
                        std_r = res.error
                    else:
                        mean_r = res["raw_pair_rate"]
                        std_r = res["raw_pair_rate_std"]
                else:
                    mean_r, std_r = 0.0, 0.0

                C[i, j] = mean_r
                Cerr[i, j] = std_r

        E_ab, e_ab = get_correlation(C[0, 0], C[1, 1], C[0, 1], C[1, 0],
                                     Cerr[0, 0], Cerr[1, 1], Cerr[0, 1], Cerr[1, 0])
        E_abp, e_abp = get_correlation(C[0, 2], C[1, 3], C[0, 3], C[1, 2],
                                       Cerr[0, 2], Cerr[1, 3], Cerr[0, 3], Cerr[1, 2])
        E_apb, e_apb = get_correlation(C[2, 0], C[3, 1], C[2, 1], C[3, 0],
                                       Cerr[2, 0], Cerr[3, 1], Cerr[2, 1], Cerr[3, 0])
        E_apbp, e_apbp = get_correlation(C[2, 2], C[3, 3], C[2, 3], C[3, 2],
                                         Cerr[2, 2], Cerr[3, 3], Cerr[2, 3], Cerr[3, 2])

        S = E_ab - E_abp + E_apb + E_apbp
        err_S = np.sqrt(e_ab**2 + e_abp**2 + e_apb**2 + e_apbp**2)
        s_vals.append(S)
        s_errs.append(err_S)
        coincidence_matrices.append(C)

        print(f"[β={offset:.1f}°]  S = {S:.4f} ± {err_S:.4f}")

    s_vals = np.array(s_vals)
    s_errs = np.array(s_errs)

    max_idx = np.argmax(np.abs(s_vals))
    max_s = s_vals[max_idx]
    max_s_err = s_errs[max_idx]
    max_off = offsets[max_idx]

    print("\n" + "=" * 60)
    print(f"  Max |S| = {abs(max_s):.4f} ± {max_s_err:.4f}  @ β = {max_off:.1f}°")
    if abs(max_s) > 2.0:
        sigmas = (abs(max_s) - 2.0) / max_s_err if max_s_err > 0 else 0
        print(f"  *** BELL VIOLATION ***  (by {sigmas:.1f} σ)")
    else:
        print("  No Bell violation observed.")
    print("=" * 60 + "\n")

    if save_plot:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(9, 6))
            ax.axhspan(-2, 2, color="gray", alpha=0.15, label="Classical bound |S|≤2")
            ax.axhline(2, color="gray", ls="--"); ax.axhline(-2, color="gray", ls="--")
            ax.errorbar(offsets, s_vals, yerr=s_errs, fmt="o-", color="crimson", capsize=4, label="S(β)")
            ax.scatter([max_off], [max_s], color="gold", edgecolor="black", s=120, zorder=5, label=f"Max |S|={max_s:.3f}")
            ax.set_xlabel("Bob Basis Offset β (°)")
            ax.set_ylabel("CHSH S Parameter")
            ax.set_title("CHSH Bell Parameter vs. Bob Basis Offset")
            ax.legend(); ax.grid(True, linestyle="--", alpha=0.5)
            fname = get_subdir_path("output", "bell_inequality_scan.png")
            fig.savefig(fname, dpi=150)
            plt.close(fig)
            print(f"\n[OK] Plot → {fname}")
        except Exception as exc:
            logger.warning("Plot failed: %s", exc)

    if save_raw:
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = get_subdir_path("data", f"bell_raw_{ts}.npz")
        np.savez(
            fname,
            offsets=offsets,
            s_values=s_vals,
            s_errors=s_errs,
            max_s=max_s,
            max_s_err=max_s_err,
            max_offset=max_off,
        )
        print(f"[OK] Raw data → {fname}")

    res = {
        "offsets": offsets,
        "s_values": s_vals,
        "s_errors": s_errs,
        "max_s": max_s,
        "max_s_err": max_s_err,
        "max_offset": max_off,
    }
    if full_stats:
        res["coincidence_matrices"] = coincidence_matrices
    return res
