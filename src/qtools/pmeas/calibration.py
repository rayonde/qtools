"""Waveplate calibration engine.

Physical setup
--------------
::

    Laser ──▶ [Input PBS] ──▶ HWP  ──▶ PBS ──▶ Detector (TDC or PM)
                  │                                │
              clean H-pol                    transmits H only

The upstream PBS guarantees a pure horizontal (H) input polarisation,
so the only unknown is the HWP fast-axis offset θ₀ relative to the
motor zero-reference.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime as _dt
from pathlib import Path
from typing import Any, Optional

import numpy as np

from qtools.pmeas._path import get_subdir_path
from qtools.pmeas.analysis.fit import fit_calibration_curve
from qtools.pmeas.analysis.jones import compute_target_angles
from qtools.pmeas.motor_manager import MotorManager
from qtools.pmeas.meas_manager import MeasManager
from qtools.pmeas.config import ConfigManager


logger = logging.getLogger(__name__)


def _fit_calibration_data(
    angles: np.ndarray,
    values: np.ndarray,
    errors: np.ndarray,
    *,
    waveplate: str,
    basis: str | float,
    input_pol: str,
    background: float | np.ndarray = 20.0,
    estimated_theta_0: float = 0.0,
    start_angle: float | None = None,
    end_angle: float | None = None,
) -> dict:
    """Fit stored or newly acquired calibration samples.

    Keeping this step independent of hardware lets live scans and ``--refit``
    use exactly the same, current fitting implementation.
    """
    angles = np.asarray(angles, dtype=float).reshape(-1)
    values = np.asarray(values, dtype=float).reshape(-1)
    errors = np.asarray(errors, dtype=float).reshape(-1)
    if angles.size != values.size:
        raise ValueError("Calibration angles and values must have the same length")
    if errors.size != angles.size:
        errors = np.full(angles.shape, np.nan, dtype=float)
    if angles.size < 3:
        raise ValueError("At least 3 finite calibration samples are required for fitting")

    retardance_deg = 180.0 if waveplate == "hwp" else 90.0
    fit_result = fit_calibration_curve(
        angles,
        values,
        input_pol=input_pol,
        basis=basis,
        background=background,
        estimated_theta_0=estimated_theta_0,
        retardance_deg=retardance_deg,
    )
    global_fit_result = fit_calibration_curve(
        angles,
        values,
        input_pol=input_pol,
        basis=basis,
        background=background,
        estimated_theta_0=estimated_theta_0,
        segment=False,
        retardance_deg=retardance_deg,
    )
    theta_0 = float(fit_result["theta_0"])
    v_raw = float(fit_result["visibility"])
    phi_rad = float(fit_result["phi"])
    r_squared = float(fit_result["r_squared"])
    g_theta_0 = float(global_fit_result["theta_0"])
    g_v_raw = float(global_fit_result["visibility"])
    g_phi_rad = float(global_fit_result["phi"])
    g_r_squared = float(global_fit_result["r_squared"])

    fit_start = float(np.min(angles) if start_angle is None else start_angle)
    fit_end = float(np.max(angles) if end_angle is None else end_angle)
    fine_n_steps = max(2, round(abs(fit_end - fit_start)) + 1)
    fitangles = np.linspace(fit_start, fit_end, fine_n_steps)
    fitvalues = np.asarray(fit_result["model_func"](fitangles), dtype=float)

    print("\n" + "─" * 60)
    print("  FIT RESULTS")
    print("─" * 60)
    print(f"  Zero offset / fast axis θ₀ : {theta_0:+.4f}°")
    print(f"  Raw visibility V           : {v_raw:.4f}  ({v_raw * 100:.1f}%)")
    print(f"  Retardance φ               : {phi_rad:.4f} rad  ({np.degrees(phi_rad):.4f}°)")
    print(f"  R² goodness-of-fit         : {r_squared:.6f}")

    print("\n" + "─" * 60)
    print("  GLOBAL FIT RESULTS (single amplitude)")
    print("─" * 60)
    print(f"  Zero offset / fast axis theta_0 : {g_theta_0:+.6f}°")
    print(f"  Raw visibility V               : {g_v_raw:.6f}  ({g_v_raw * 100:.2f}%)")
    print(f"  Retardance phi                 : {g_phi_rad:.6f} rad  ({np.degrees(g_phi_rad):.6f}°)")
    print(f"  R² goodness-of-fit             : {g_r_squared:.6f}")

    target_angles = compute_target_angles(theta_0, waveplate=waveplate)
    print("\n  Calculated Target Motor Angles:")
    for b_name, b_ang in target_angles.items():
        marker = " ← current" if b_name == str(basis).upper() else ""
        print(f"    Basis {b_name:2s} : {b_ang:7.4f}°{marker}")

    return {
        "theta_0": theta_0,
        "fast_axis": theta_0,
        "visibility": v_raw,
        "phi": phi_rad,
        "r_squared": r_squared,
        "global_fit_result": global_fit_result,
        "global_theta_0": g_theta_0,
        "global_fast_axis": g_theta_0,
        "global_visibility": g_v_raw,
        "global_phi": g_phi_rad,
        "global_r_squared": g_r_squared,
        "target_angles": target_angles,
        "fit_result": fit_result,
        "angles": angles,
        "values": values,
        "fitted_angles": fitangles,
        "fitted_values": fitvalues,
        "errors": errors,
    }


def _normalise_csv_field(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _metadata_value(metadata: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(_normalise_csv_field(key))
        if value not in (None, ""):
            return value
    return None


def load_calibration_csv(path: str | Path) -> dict:
    """Load measured calibration samples and metadata from a calibration CSV.

    Both the current exporter format and older comment-prefixed calibration
    files are accepted.  The stored fit curve is deliberately not loaded as
    fit input; the caller recomputes it with the current fit function.
    """
    csv_path = Path(path).expanduser()
    if not csv_path.is_file():
        raise FileNotFoundError(f"Calibration CSV not found: {csv_path}")

    metadata: dict[str, str] = {}
    rows: list[list[str]] = []
    with csv_path.open("r", newline="", encoding="utf-8-sig") as fh:
        for raw_row in csv.reader(fh):
            if not raw_row:
                rows.append([])
                continue
            row = [cell.strip() for cell in raw_row]
            first = row[0]
            if first.startswith("#"):
                comment = first[1:].strip()
                if len(row) > 1:
                    value = row[1].strip()
                    if "," in comment and not value:
                        comment, value = (part.strip() for part in comment.split(",", 1))
                    metadata[_normalise_csv_field(comment)] = value
                elif "," in comment:
                    key, value = (part.strip() for part in comment.split(",", 1))
                    metadata[_normalise_csv_field(key)] = value
                continue
            rows.append(row)

            if len(row) > 1 and _normalise_csv_field(first) in {
                "timestamp", "device_name", "device_serial", "device_role", "role",
                "wavelength_nm", "data_unit", "unit",
            }:
                metadata[_normalise_csv_field(first)] = row[1]

    header_index = next(
        (index for index, row in enumerate(rows) if row and _normalise_csv_field(row[0]) == "angle_deg"),
        None,
    )
    if header_index is None:
        raise ValueError(f"Calibration CSV has no angle_deg data header: {csv_path}")

    header = rows[header_index]
    normalised_header = [_normalise_csv_field(cell) for cell in header]
    try:
        angle_index = normalised_header.index("angle_deg")
    except ValueError as exc:
        raise ValueError(f"Calibration CSV has no angle_deg column: {csv_path}") from exc

    signal_index = next(
        (
            index
            for index, name in enumerate(normalised_header)
            if (name.startswith("signal") or name.startswith("signal_rate"))
            and "fit_curve" not in name
        ),
        None,
    )
    if signal_index is None:
        raise ValueError(f"Calibration CSV has no measured signal column: {csv_path}")
    error_index = next((index for index, name in enumerate(normalised_header) if name.startswith("error")), None)

    angles: list[float] = []
    values: list[float] = []
    errors: list[float] = []
    for row in rows[header_index + 1 :]:
        if not row or row[0].startswith("#"):
            break
        max_index = max(angle_index, signal_index, error_index or 0)
        if len(row) <= max_index:
            break
        try:
            angle = float(row[angle_index])
            value = float(row[signal_index])
        except (TypeError, ValueError):
            break
        error = np.nan
        if error_index is not None:
            try:
                error = float(row[error_index])
            except (TypeError, ValueError):
                error = np.nan
        angles.append(angle)
        values.append(value)
        errors.append(error)

    if not angles:
        raise ValueError(f"Calibration CSV contains no measured samples: {csv_path}")

    angles_arr = np.asarray(angles, dtype=float)
    values_arr = np.asarray(values, dtype=float)
    errors_arr = np.asarray(errors, dtype=float)
    finite = np.isfinite(angles_arr) & np.isfinite(values_arr)
    if finite.sum() < 3:
        raise ValueError(f"Calibration CSV contains fewer than 3 finite measured samples: {csv_path}")

    unit = _metadata_value(metadata, "data_unit", "unit")
    if unit is None:
        match = re.search(r"\(([^)]+)\)", header[signal_index])
        unit = match.group(1).strip() if match else "cps"
    wavelength_raw = _metadata_value(metadata, "wavelength_nm", "wavelength")
    try:
        wavelength_nm = float(wavelength_raw) if wavelength_raw is not None else None
    except ValueError:
        wavelength_nm = None

    return {
        "path": str(csv_path),
        "metadata": metadata,
        "angles": angles_arr[finite],
        "values": values_arr[finite],
        "errors": errors_arr[finite],
        "unit": unit,
        "wavelength_nm": wavelength_nm,
        "device_name": _metadata_value(metadata, "device_name", "device_role", "role") or csv_path.stem,
        "device_serial": _metadata_value(metadata, "device_serial", "serial") or "",
    }


def refit_calibration(
    refit_path: str | Path,
    *,
    waveplate: str = "hwp",
    basis: str | float = "H",
    input_pol: str = "H",
    background: float | np.ndarray = 20.0,
    estimated_theta_0: float = 0.0,
    wavelength_nm: float | None = None,
    unit: str | None = None,
    detector: str = "stored-data",
    config_label: str | None = None,
    device_name: str = "",
    export: bool = False,
    export_path: str | None = None,
    plot: bool = True,
) -> dict:
    """Re-fit a stored calibration CSV without initializing hardware."""
    data = load_calibration_csv(refit_path)
    resolved_wavelength = wavelength_nm if wavelength_nm is not None else data.get("wavelength_nm") or 1560.0
    resolved_unit = unit or data.get("unit") or "cps"
    resolved_name = device_name or str(data.get("device_name") or Path(refit_path).stem)
    resolved_serial = str(data.get("device_serial") or "")

    print("\n" + "=" * 60)
    print(f"  {waveplate.upper()} Calibration Refit")
    print(f"  Source: {data['path']}")
    print("  Hardware scan: skipped")
    print("=" * 60)

    result = _fit_calibration_data(
        data["angles"],
        data["values"],
        data["errors"],
        waveplate=waveplate,
        basis=basis,
        input_pol=input_pol,
        background=background,
        estimated_theta_0=estimated_theta_0,
    )
    result.update({
        "config_label": config_label or Path(refit_path).stem,
        "unit": resolved_unit,
        "device_name": resolved_name,
        "device_serial": resolved_serial,
        "wavelength_nm": resolved_wavelength,
        "refit_path": data["path"],
    })

    timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")

    result["cal_file"] = (
        export_calibration_csv(
            result,
            export_path=export_path,
            role=waveplate,
            wavelength_nm=resolved_wavelength,
            unit=resolved_unit,
            timestamp=timestamp,
        )
        if export
        else ""
    )
    result["plot_file"] = (
        _plot_calibration(
            result["angles"],
            result["values"],
            result["errors"],
            result["fit_result"],
            waveplate,
            detector,
            wavelength_nm=resolved_wavelength,
            unit=resolved_unit,
            device_name=resolved_name,
            waveplate=waveplate,
            timestamp=timestamp,
            global_fit_result=result.get("global_fit_result"),
        )
        if plot
        else ""
    )
    return result


def save_refit_calibration_config(
    result: dict,
    cfg: ConfigManager,
    *,
    waveplate: str = "hwp",
    detector: str = "stored-data",
) -> str:
    """Persist a refit result into the selected ConfigManager.

    Returns the device key used for the stored calibration record.
    """
    serial = str(result.get("device_serial") or "")
    device_name = str(result.get("device_name") or result.get("config_label") or "")
    dev = cfg.get_device(serial) if serial else None
    if dev is None and device_name:
        dev = cfg.get_device(device_name)

    if dev is not None:
        device_key = str(
            serial
            or dev.get("serial")
            or dev.get("id")
            or dev.get("name")
            or device_name
        )
    else:
        device_key = str(
            serial
            or device_name
            or Path(result.get("refit_path", "")).stem
            or waveplate
        )

    cal_entry = {
        "id": str(dev.get("id", device_key)) if dev else device_key,
        "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "serial": serial,
        "role": waveplate,
        "detector": detector,
        "meas_type": "",
        "wavelength": result.get("wavelength_nm"),
        "theta_0": float(result["theta_0"]),
        "fast_axis": float(result.get("fast_axis", result["theta_0"])),
        "visibility": float(result["visibility"]),
        "phi_rad": float(result["phi"]),
        "r_squared": float(result["r_squared"]),
        "bases": {str(k): float(v) for k, v in result.get("target_angles", {}).items()},
        "cal_file": str(result.get("cal_file") or ""),
        "plot_file": str(result.get("plot_file") or ""),
    }
    cfg.add_calibration(device_key, cal_entry)
    cfg.save()
    logger.info(
        "Calibration refit saved for device '%s' (theta_0 = %.3f deg)",
        device_key,
        float(result["theta_0"]),
    )
    return device_key


def run_calibration(
    target: str,
    *,
    waveplate: str = "hwp",
    motor_mgr: MotorManager | None = None,
    meas_mgr: MeasManager | None = None,
    cfg: ConfigManager | None = None,
    channel: Any = 0,
    meas_type: str = "power",
    duration: float = 1.0,
    repetitions: int = 10,
    start_angle: float = 0.0,
    end_angle: float = 360.0,
    step_angle: float = 5.0,
    detector: str = "powermeter",
    wavelength_nm: float = 1560.0,
    config_label: str | None = None,
    basis: str | float = "H",
    input_pol: str = "H",
    background: float | np.ndarray = 20.0,
    estimated_theta_0: float = 0.0,
    save_config: bool = True,
    export: bool = True,
    plot: bool = True,
    device_name: str = "",
    unit: str | None = None,
    export_path: str | None = None,
) -> dict:
    """Run a full waveplate calibration scan using MotorManager and MeasManager."""

    # ── initialising motor manager and config manager ───────────────────
    if cfg is None and motor_mgr is not None:
        cfg = motor_mgr.cfg

    stage = motor_mgr.get_motor(target) if motor_mgr is not None else None
    if meas_mgr is None:
        raise ValueError("meas_mgr must be provided")

    
    # ── scan angle parameters ──────────────────────────────────────────
    n_steps = round((end_angle - start_angle) / step_angle) + 1
    angles = np.linspace(start_angle, start_angle + (n_steps - 1) * step_angle, n_steps)
    values: list[float] = []
    errors: list[float] = []

    print("\n" + "=" * 60)
    print(f"  {waveplate.upper()} Calibration Scan")
    print(f"  Setup: {input_pol.upper()} → {waveplate.upper()} → PBS → {detector.upper()}")
    print(f"  Measurement basis: {basis}")
    print(f"  Range: {start_angle}° → {end_angle}°  (step {step_angle}°)")
    print(f"  Integration: {duration}s × {repetitions}")
    print("=" * 60)
    
    # ── scan angle parameters ──────────────────────────────────────────
    locked_unit: str | None = unit  # CLI --unit takes priority; otherwise auto-detect from first measurement
    for idx, angle in enumerate(angles):
        # 1. Move motor to target angle and wait until settled
        if stage is not None:
            stage.move_to(angle)
            stage.wait_move()

        # 2. Measure with powermeter or TDC via unified MeasurementResult
        res = meas_mgr.measure(
            detector=detector,
            meas_type=meas_type,
            channels=channel,
            duration=duration,
            samples=repetitions,
            task="calibration",
            unit=locked_unit,
            wavelength_nm=wavelength_nm,
        )
        if locked_unit is None:
            locked_unit = res.unit
            # Re-scale first value to locked unit if needed (already correct on first call)
        values.append(res.value)
        errors.append(res.error)
        unit = res.unit

        # 3. Single compact line per angle
        print(f"  [{idx+1:3d}/{n_steps}]  {angle:6.1f}°  {res.value:8.3f} ± {res.error:6.3f} {unit}  "
              f"({repetitions} samples/{duration:.1f}s)")
    
    fit_data = _fit_calibration_data(
        angles,
        np.asarray(values),
        np.asarray(errors),
        waveplate=waveplate,
        basis=basis,
        input_pol=input_pol,
        background=background,
        estimated_theta_0=estimated_theta_0,
        start_angle=start_angle,
        end_angle=end_angle,
    )
    fit_result = fit_data["fit_result"]
    theta_0 = fit_data["theta_0"]
    v_raw = fit_data["visibility"]
    phi_rad = fit_data["phi"]
    r_squared = fit_data["r_squared"]
    target_angles = fit_data["target_angles"]
    values_arr = fit_data["values"]
    errors_arr = fit_data["errors"]

    result = {
        **fit_data,
        "config_label": config_label,
        "unit": unit,
    }

    serial = str(getattr(stage, "serial", "") or "")
    dev_id = target
    if cfg is not None:
        dev_info = cfg.get_device(serial) or cfg.get_device(dev_id)
        if dev_info:
            dev_id = str(dev_info.get("id") or dev_info.get("name") or target)
    device_key = serial or dev_id

    # device_name priority: explicit parameter > config "name" field > stage.name > target
    resolved_device_name = device_name
    if not resolved_device_name and cfg is not None:
        dev_info = cfg.get_device(serial) or cfg.get_device(dev_id)
        if dev_info:
            resolved_device_name = str(dev_info.get("name") or dev_info.get("id") or "")
    resolved_device_name = resolved_device_name or str(getattr(stage, "name", "") or "").strip() or target
    result["device_serial"] = serial
    result["device_name"] = resolved_device_name

    timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")

    raw_file_path = (
        export_calibration_csv(
            result,
            export_path=export_path,
            role=waveplate,
            wavelength_nm=wavelength_nm,
            unit=unit,
            timestamp=timestamp,
        )
        if export
        else ""
    )

    plot_file_path = (
        _plot_calibration(
            angles,
            values_arr,
            errors_arr,
            fit_result,
            target,
            detector,
            wavelength_nm=wavelength_nm,
            unit=unit,
            device_name=resolved_device_name,
            waveplate=waveplate,
            timestamp=timestamp,
            global_fit_result=fit_data.get("global_fit_result"),
        )
        if plot
        else ""
    )

    result["cal_file"] = raw_file_path
    result["plot_file"] = plot_file_path

    cal_entry = {
        "id": dev_id,
        "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        "serial": serial,
        "role": waveplate,
        "detector": detector,
        "meas_type": meas_type,
        "wavelength": wavelength_nm,
        "theta_0": float(theta_0),
        "fast_axis": float(theta_0),
        "visibility": float(v_raw),
        "phi_rad": float(phi_rad),
        "r_squared": float(r_squared),
        "bases": {k: float(v) for k, v in target_angles.items()},
        "cal_file": str(raw_file_path or ""),
        "plot_file": str(plot_file_path or ""),
        "scan": {
            "start_angle": float(start_angle),
            "end_angle": float(end_angle),
            "step_angle": float(step_angle),
            "duration": float(duration),
            "repetitions": int(repetitions),
        },
    }

    if save_config and cfg is not None:
        cfg.add_calibration(device_key, cal_entry)
        cfg.save()
        logger.info("Calibration saved for device '%s' (theta_0 = %.3f°, basis = %s, input = %s)", device_key, theta_0, str(basis).upper(), input_pol.upper())
    else:
        logger.info("Calibration scan complete for '%s' (config update skipped)", device_key)

    return result


def _plot_calibration(
    angles: np.ndarray,
    values: np.ndarray,
    errors: np.ndarray,
    fit_result: dict,
    role: str,
    detector_type: str,
    wavelength_nm: float = 1550.0,
    unit: str = "cps",
    unit_scale: float = 1.0,
    output_path: str | Path | None = None,
    device_name: str = "",
    waveplate: str = "hwp",
    timestamp: str | None = None,
    global_fit_result: dict | None = None,
) -> str:
    try:
        import matplotlib.pyplot as plt

        fine_angles = np.linspace(angles.min(), angles.max(), 300)
        fit_model_raw = fit_result["model_func"](fine_angles)

        values_disp = values * unit_scale
        errors_disp = errors * unit_scale
        fit_model_disp = fit_model_raw * unit_scale

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.errorbar(angles, values_disp, yerr=errors_disp, fmt="o", color="navy", ecolor="lightsteelblue", elinewidth=1.5, capsize=3, label="Measured data")
        ax.plot(fine_angles, fit_model_disp, "-", color="crimson", lw=2, label=f"Fit (θ₀ = {fit_result['theta_0']:.2f}°)")
        if global_fit_result:
            global_model_raw = global_fit_result["model_func"](fine_angles)
            global_model_disp = global_model_raw * unit_scale
            ax.plot(
                fine_angles,
                global_model_disp,
                "--",
                color="seagreen",
                lw=2,
                label=f"Global fit (θ₀ = {global_fit_result['theta_0']:.4f}°)",
            )

        target_angles = compute_target_angles(float(fit_result["theta_0"]), waveplate=waveplate)
        h_basis_angle = target_angles.get("H")
        if h_basis_angle is not None:
            ax.axvline(
                h_basis_angle,
                color="darkgreen",
                linestyle="--",
                linewidth=1.6,
                label=f"H basis ({h_basis_angle:.2f}°)",
            )

        theta_0 = fit_result["theta_0"]
        vis = fit_result["visibility"]
        phi_rad = fit_result["phi"]
        phi_deg = np.degrees(phi_rad)
        r2 = fit_result["r_squared"]

        info_text = (
            f"θ₀ = {theta_0:+.2f}°\n"
            f"V = {vis:.3f}\n"
            f"φ = {phi_deg:.2f}° ({phi_rad:.3f} rad)\n"
            f"R² = {r2:.4f}"
        )
        if global_fit_result:
            g_theta_0 = global_fit_result["theta_0"]
            g_vis = global_fit_result["visibility"]
            g_phi_rad = global_fit_result["phi"]
            g_phi_deg = np.degrees(g_phi_rad)
            g_r2 = global_fit_result["r_squared"]
            info_text += (
                "\n\nGlobal fit\n"
                f"θ₀ = {g_theta_0:+.4f}°\n"
                f"V = {g_vis:.4f}\n"
                f"φ = {g_phi_deg:.2f}° ({g_phi_rad:.4f} rad)\n"
                f"R² = {g_r2:.4f}"
            )
        ax.text(
            0.03, 0.95, info_text, transform=ax.transAxes,
            fontsize=9, verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.85, edgecolor="silver")
        )

        ax.set_xlabel("Motor Angle (°)")
        ax.set_ylabel(f"Signal ({unit})")
        role_str = str(role) if not isinstance(role, str) else role
        ax.set_title(f"{role_str.upper()} Calibration Sweep @ {int(wavelength_nm)} nm")
        ax.legend(loc="upper right")
        ax.grid(True, linestyle="--", alpha=0.5)

        time_str = timestamp or _dt.now().strftime("%Y%m%d_%H%M%S")
        if output_path:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            fname = str(out_p)
        else:
            name_part = f"_{device_name}" if device_name else ""
            base_name = f"calibration_{role}{name_part}_{int(wavelength_nm)}nm_{time_str}"
            fname = get_subdir_path("cal_output", f"{base_name}.png")
            candidate = Path(fname)
            suffix = 1
            while candidate.exists():
                candidate = candidate.with_name(f"{base_name}_{suffix}.png")
                suffix += 1
            fname = str(candidate)
        fig.savefig(fname, dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Calibration plot → %s", fname)
        return fname
    except Exception as exc:
        logger.warning("Failed to generate calibration plot: %s", exc)
        return ""


def export_calibration_csv(
    cal_res: dict,
    export_path: str | None = None,
    role: str = "hwp",
    wavelength_nm: float = 1550.0,
    unit: str = "cps",
    unit_scale: float = 1.0,
    timestamp: str | None = None,
) -> str:
    """Export raw calibration scan data and fit results to a CSV file.

    Default path format: ``cal_data/calibration_<name>_<wavelength>nm_<time>.csv``
    """
    import csv
    from pathlib import Path

    now_str = timestamp or _dt.now().strftime("%Y%m%d_%H%M%S")
    name = cal_res.get("device_name") or cal_res.get("config_label") or role or "stage"
    wl = int(wavelength_nm)

    if not export_path or export_path in ("auto", "default", "true", "True", True):
        out_dir = Path.cwd() / "cal_data"
        out_dir.mkdir(exist_ok=True)
        export_path = str(out_dir / f"calibration_{name}_{wl}nm_{now_str}.csv")
    else:
        out_path = Path(export_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        export_path = str(out_path)

    angles = cal_res.get("angles", [])
    values = cal_res.get("values", [])
    errors = cal_res.get("errors", [])
    fit_res = cal_res.get("fit_result", {})
    phi_rad = cal_res.get("phi", 0.0)
    phi_deg = np.degrees(phi_rad)
    unit_str = cal_res.get("unit", unit)
    scale = cal_res.get("unit_scale", unit_scale)
    device_serial = cal_res.get("device_serial", "")
    target_angles = cal_res.get("target_angles", {})
    theta_0 = cal_res.get("theta_0", cal_res.get("zero_offset", 0.0))

    # Fit curve on fine 1° grid
    model_func = fit_res.get("model_func")
    if model_func is not None and len(angles) > 0:
        start_a = float(np.min(angles))
        end_a = float(np.max(angles))
        n_fine = int(round((end_a - start_a) / 1.0)) + 1
        fine_angles = np.linspace(start_a, start_a + (n_fine - 1) * 1.0, n_fine)
        fit_curve_fine = model_func(fine_angles) * scale
    else:
        fine_angles = np.array([])
        fit_curve_fine = np.array([])

    with open(export_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)

        # -- Metadata header --
        writer.writerow(["Timestamp", _dt.now().strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["Device Name", str(name)])
        writer.writerow(["Device Serial", str(device_serial)])
        writer.writerow(["Role", str(role)])
        writer.writerow(["Wavelength (nm)", wl])
        writer.writerow(["Data Unit", unit_str])

        # -- Fit curve on fine 1° grid (before scan data) --
        if len(fine_angles) > 0:
            writer.writerow([])
            writer.writerow(["fit_angle_deg", f"fit_curve ({unit_str})"])
            for fa, fc in zip(fine_angles, fit_curve_fine):
                writer.writerow([f"{float(fa):.4f}", f"{float(fc):.6f}"])

        writer.writerow([])

        # -- Scan data --
        writer.writerow(["angle_deg", f"signal ({unit_str})", f"error ({unit_str})"])
        for a, r, e in zip(angles, values, errors):
            writer.writerow([f"{float(a):.4f}", f"{float(r) * scale:.6f}", f"{float(e) * scale:.6f}"])

        writer.writerow([])

        # -- Fit summary --
        writer.writerow(["Theta_0 (deg)", f"{theta_0:.4f}"])
        writer.writerow(["Fast Axis (deg)", f"{theta_0:.4f}"])
        writer.writerow(["Visibility", f"{cal_res.get('visibility', 0.0):.6f}"])
        writer.writerow(["Retardance phi (rad)", f"{phi_rad:.6f}"])
        writer.writerow(["Retardance phi (deg)", f"{phi_deg:.4f}"])
        writer.writerow(["R Squared", f"{cal_res.get('r_squared', 0.0):.6f}"])

        # Target basis angles
        if target_angles:
            writer.writerow([])
            for b_name, b_ang in sorted(target_angles.items()):
                writer.writerow([f"Basis {b_name} (deg)", f"{float(b_ang):.4f}"])

    logger.info("Calibration data exported to CSV -> %s", export_path)
    return export_path




def _scan_single_wavelength(
    target: str,
    wl: float,
    *,
    role: str,
    controller: Any,
    channel: Any,
    meas_type: str,
    duration: float,
    repetitions: int,
    start_angle: float,
    end_angle: float,
    step_angle: float,
    detector_type: str,
    basis: str | float,
    input_pol: str,
    background: float | np.ndarray = 20.0,
    estimated_theta_0: float = 0.0,
    export: bool,
    export_path: str | None,
    plot: bool,
    unit: str | None,
    out_dir: Path,
) -> dict:
    """Run a single-wavelength calibration scan and optionally export CSV/plot.

    Returns a dict with keys ``wl``, ``phi_deg``, ``phi_rad``, ``theta_0``,
    ``vis``, ``csv_file``, ``plot_file``.  Raises on scan failure.
    """
    time_str = _dt.now().strftime("%Y%m%d_%H%M%S")

    motor_mgr = getattr(controller, "motor_mgr", None)
    meas_mgr = getattr(controller, "meas_mgr", None)
    cfg = getattr(controller, "cfg", None)

    res = run_calibration(
        target=target,
        waveplate=role,
        motor_mgr=motor_mgr,
        meas_mgr=meas_mgr,
        cfg=cfg,
        channel=channel,
        meas_type=meas_type,
        duration=duration,
        repetitions=repetitions,
        start_angle=start_angle,
        end_angle=end_angle,
        step_angle=step_angle,
        detector=detector_type,
        wavelength_nm=wl,
        config_label=f"achromatic_{wl:.0f}nm",
        save_config=False,
        basis=basis,
        input_pol=input_pol,
        background=background,
        estimated_theta_0=estimated_theta_0,
        export=False,   # we handle export ourselves below
        plot=False,     # we handle plot ourselves below
        unit=unit,
    )

    phi_rad = res["phi"]
    phi_deg = float(np.degrees(phi_rad))
    name = str(res.get("device_name") or role)

    csv_file = ""
    plot_file = ""

    if export:
        if export_path:
            export_target = Path(export_path)
            if export_target.suffix:
                # Treat a file-like path as a filename prefix in its parent dir.
                csv_dir = export_target.parent
                prefix = export_target.stem
            else:
                csv_dir = export_target
                prefix = f"ach_cal_{name}"
        else:
            csv_dir = out_dir
            prefix = f"ach_cal_{name}"
        csv_dir.mkdir(parents=True, exist_ok=True)
        csv_file = str(csv_dir / f"{prefix}_{wl:.0f}nm_{time_str}.csv")
        export_calibration_csv(
            res,
            export_path=csv_file,
            role=role,
            wavelength_nm=wl,
            unit=res.get("unit", "cps"),
        )
        logger.info("Saved CSV: %s", csv_file)

    if plot:
        plot_file = str(out_dir / f"ach_cal_{name}_{wl:.0f}nm_{time_str}.png")
        _plot_calibration(
            res["angles"],
            res["values"],
            res["errors"],
            res["fit_result"],
            role,
            detector_type,
            wavelength_nm=wl,
            unit=res.get("unit", "cps"),
            output_path=plot_file,
            waveplate=role,
            global_fit_result=res.get("global_fit_result"),
        )
        logger.info("Saved plot: %s", plot_file)

    return {
        "wl": wl,
        "phi_deg": phi_deg,
        "phi_rad": float(phi_rad),
        "theta_0": float(res["theta_0"]),
        "vis": float(res["visibility"]),
        "csv_file": csv_file,
        "plot_file": plot_file,
    }


# ── Achromatic Calibration ───────────────────────────────────────────────


def run_achromatic_calibration(
    controller: Any,
    target: str,
    *,
    role: str = "hwp",
    channel: Any = 0,
    meas_type: str = "singles",
    duration: float = 1.0,
    repetitions: int = 5,
    start_angle: float = 0.0,
    end_angle: float = 180.0,
    step_angle: float = 10.0,
    detector_type: str = "tdc",
    wavelength_nm: float | None = None,
    basis: str | float = "H",
    input_pol: str = "H",
    background: float | np.ndarray = 20.0,
    estimated_theta_0: float = 0.0,
    export: bool = True,
    export_path: str | None = None,
    plot: bool = True,
    unit: str | None = None,
) -> dict | None:
    """Interactive multi-wavelength achromatic calibration.

    Parameters
    ----------
    target : str
        Device identifier for motor resolution (id, name, serial, port, or index).
    role : str
        Display/label key (e.g. ``"hwp"`` or ``"qwp"``).  Used for plot titles,
        CSV file names, and the theoretical retardance target (180° or 90°).
    wavelength_nm : float | None
        Optional seed wavelength from ``--wavelength`` on the command line.
        When ``None``, the interactive wavelength prompt starts immediately.
        When a positive number, the first scan uses this wavelength, then
        the prompt appears for subsequent wavelengths.
    """
    print("\n" + "=" * 60)
    print(f"  ACHROMATIC {role.upper()} CALIBRATION")
    print("=" * 60)
    print("  1. Change laser wavelength manually.")
    print("  2. Enter the new wavelength (nm) at the prompt.")
    print("  3. System runs an angular scan (without updating config).")
    print("  4. Saves per-scan CSV and Plot to achromatic_cal_data/")
    print("  5. Type 'q' to finish.")
    print("=" * 60 + "\n")

    out_dir = Path.cwd() / "achromatic_cal_data"
    out_dir.mkdir(parents=True, exist_ok=True)

    wavelengths, retardances, offsets, visibilities = [], [], [], []

    # If --wavelength was given on the CLI, seed the first scan
    first_wl: float | None = None
    if wavelength_nm is not None and wavelength_nm > 0:
        first_wl = float(wavelength_nm)

    while True:
        if first_wl is not None:
            wl = first_wl
            first_wl = None
        else:
            inp = input("Wavelength (nm) / 'q' to finish > ").strip().lower()
            if inp == "q":
                break

            try:
                wl = float(inp)
                if wl <= 0:
                    raise ValueError
            except ValueError:
                logger.error("Enter a positive number for wavelength, or 'q' to finish.")
                continue

        logger.info("Running scan @ %.1f nm...", wl)

        try:
            entry = _scan_single_wavelength(
                target=target,
                wl=wl,
                role=role,
                controller=controller,
                channel=channel,
                meas_type=meas_type,
                duration=duration,
                repetitions=repetitions,
                start_angle=start_angle,
                end_angle=end_angle,
                step_angle=step_angle,
                detector_type=detector_type,
                basis=basis,
                input_pol=input_pol,
                background=background,
                estimated_theta_0=estimated_theta_0,
                export=export,
                export_path=export_path,
                plot=plot,
                unit=unit,
                out_dir=out_dir,
            )
            wavelengths.append(entry["wl"])
            retardances.append(entry["phi_deg"])
            offsets.append(entry["theta_0"])
            visibilities.append(entry["vis"])

            print(f"  → Extracted Retardance φ = {entry['phi_deg']:.4f}° "
                  f"({entry['phi_rad']:.4f} rad),  θ₀ = {entry['theta_0']:.4f}°\n")
            logger.info("Extracted Retardance φ = %.4f° (%.4f rad), θ₀ = %.4f°",
                        entry["phi_deg"], entry["phi_rad"], entry["theta_0"])
        except Exception as exc:
            logger.error("Scan failed @ %.1f nm: %s", wl, exc)
            continue

    if not wavelengths:
        logger.info("Achromatic calibration cancelled — no data collected.")
        return None

    result = {
        "role": role,
        "measurements": [
            {
                "wl": float(w),
                "phi_deg": float(r),
                "phi_rad": float(np.radians(r)),
                "theta_0": float(o),
                "vis": float(v),
            }
            for w, r, o, v in zip(wavelengths, retardances, offsets, visibilities)
        ],
        "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    now_str = _dt.now().strftime("%Y%m%d_%H%M%S")
    jpath = str(out_dir / f"ach_cal_{role}_summary_{now_str}.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print("\n" + "─" * 60)
    print(f"  ACHROMATIC {role.upper()} RESULTS")
    print("─" * 60)
    print("  Measured Points:")
    for w, r in zip(wavelengths, retardances):
        print(f"    - {w:6.1f} nm : φ = {r:7.3f}°")
    print(f"  Summary Data   : {jpath}")
    print("─" * 60 + "\n")

    logger.info("Achromatic calibration complete.")
    logger.info("Summary Data → %s", jpath)

    return result
