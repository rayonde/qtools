from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Sequence, TYPE_CHECKING
import serial.tools.list_ports
import numpy as np

from qtools.pmeas.config import ConfigManager

if TYPE_CHECKING:
    from qtools.tdc import TDC
    from qtools.powermeter import PowerMeter

logger = logging.getLogger(__name__)

TASK_OPTIONS = ("calibration", "scan", "chsh")
MEAS_TYPES = ("power", "singles", "rates", "pairs", "timestamps")
DETECTORS = ("powermeter", "tdc")

_POWER_UNITS = {
    "W": 1.0,
    "mW": 1e3,
    "μW": 1e6,   "uW": 1e6,  # both Unicode and ASCII mu accepted
    "nW": 1e9,
    "pW": 1e12,
}


def _power_unit(
    values: float | Sequence[float] | np.ndarray,
    unit: str | None = None,
) -> tuple[float | np.ndarray, str]:
    """Convert power values (in Watts) to target or auto-selected engineering units.

    Args:
        values: Power value(s) in Watts (scalar, sequence, or numpy array).
        unit: Target unit string (e.g. 'W', 'mW', 'uW', 'nW', 'pW').
            If None, auto-selects the best unit based on absolute magnitude.

    Returns:
        Tuple of (converted_values, unit_string).
    """
    val_arr = np.asarray(values)

    if unit is None:
        max_val = float(np.max(np.abs(val_arr))) if val_arr.size > 0 else 0.0
        if max_val >= 1.0:
            target_unit = "W"
        elif max_val >= 1e-3:
            target_unit = "mW"
        elif max_val >= 1e-6:
            target_unit = "uW"
        elif max_val >= 1e-9:
            target_unit = "nW"
        else:
            target_unit = "pW"
    else:
        target_unit = unit
        if target_unit not in _POWER_UNITS:
            raise ValueError(
                f"Unknown power unit '{unit}'. Supported units: {list(_POWER_UNITS.keys())}"
            )

    factor = _POWER_UNITS[target_unit]
    converted = val_arr * factor

    if np.isscalar(values):
        return float(converted), target_unit
    return converted, target_unit

def _calc_stats(values: Sequence[float] | np.ndarray) -> tuple[float, float]:
    """Calculate mean and sample standard deviation for an array of numbers."""
    arr = np.asarray(values, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    return mean, std


@dataclass
class MeasurementResult:
    """Unified container for measurement results, supporting tuple unpacking and dict key access."""
    value: float
    error: float
    unit: str
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, int):
            if item == 0:
                return self.value
            elif item == 1:
                return self.error
            elif item == 2:
                return self.unit
            raise IndexError("MeasurementResult index out of range")
        elif isinstance(item, str):
            if item in self.metrics:
                return self.metrics[item]
            if item in self.metadata:
                return self.metadata[item]
            raise KeyError(f"Key '{item}' not found in metrics or metadata")
        raise TypeError(f"Invalid index type: {type(item)}")

    def __iter__(self):
        yield self.value
        yield self.error
        yield self.unit

    def __len__(self) -> int:
        return 3



class MeasManager:
    """Manages physical TDC and PowerMeter connections and measurement execution."""

    def __init__(self, config_mgr: ConfigManager):
        self.cfg = config_mgr
        self.detectors: dict[str, Any] = {"tdc": None, "powermeter": None}
        self._init_configed_detectors()
    
    def _init_configed_detectors(self):
        available_ports = [p.device for p in serial.tools.list_ports.comports()]

        pm_cfg = self.cfg.get("detectors.powermeter") or {}
        tdc_cfg = self.cfg.get("detectors.tdc") or {}

        # If ports are missing in config, trigger auto-scan (in-memory only)
        if not pm_cfg.get("port") and not tdc_cfg.get("port"):
            scanned = self.cfg.scan_detectors(save=False)
            pm_cfg = scanned.get("powermeter", {})
            tdc_cfg = scanned.get("tdc", {})

        pm_backend, pm_port = pm_cfg.get("backend"), pm_cfg.get("port")
        if pm_backend and pm_port in available_ports:
            try:
                from qtools import powermeter
                self.detectors["powermeter"] = powermeter.get_device(pm_backend, pm_port)
                logger.info("PowerMeter '%s' is available at %s", pm_backend, pm_port)
            except Exception as ex:
                logger.warning("PowerMeter '%s' failed at %s: %s", pm_backend, pm_port, ex)
        else:
            logger.warning("PowerMeter '%s' is not available at %s", pm_backend, pm_port)

        self._init_tdc(tdc_cfg.get("backend"), tdc_cfg.get("port"))

    @staticmethod
    def _connect_tdc(backend: str, port: str):
        """Create a TDC wrapper and verify the configured port works."""
        from qtools import tdc
        device = tdc.get_device(backend, port)
        device.backend.connect()
        if not device.backend.is_connected():
            raise ConnectionError(
                f"TDC backend '{backend}' did not report connected at {port}."
            )
        device.backend.disconnect()
        return device

    def _init_tdc(self, backend: str | None, port: str | None) -> None:
        """Connect the configured TDC, then rescan and save config on failure."""
        if not backend or not port:
            scanned = self.cfg.scan_detectors(save=False)
            tdc_scanned = scanned.get("tdc", {}) or {}
            backend = tdc_scanned.get("backend")
            port = tdc_scanned.get("port")

        if backend and port:
            try:
                self.detectors["tdc"] = self._connect_tdc(backend, port)
                logger.info("TDC '%s' is available at %s", backend, port)
                return
            except Exception as ex:
                logger.warning("TDC '%s' failed at configured port %s: %s", backend, port, ex)
        else:
            logger.warning("TDC is not configured (backend=%s, port=%s)", backend, port)

        logger.warning("TDC configured connection failed; starting automatic rescan")
        try:
            scanned = self.cfg.scan_detectors(save=True)
        except Exception as ex:
            logger.warning("TDC auto-scan failed: %s", ex)
            return

        tdc_scanned = scanned.get("tdc", {}) or {}
        new_backend, new_port = tdc_scanned.get("backend"), tdc_scanned.get("port")
        if not new_backend or not new_port:
            logger.warning("TDC auto-scan did not find a device")
            return

        try:
            self.detectors["tdc"] = self._connect_tdc(new_backend, new_port)
            logger.info("TDC reconnected at %s (%s); config updated", new_port, new_backend)
        except Exception as ex:
            logger.warning(
                "TDC '%s' failed at auto-scanned port %s: %s",
                new_backend,
                new_port,
                ex,
            )

    def get_tdc(self) -> TDC:
        detector = self.detectors.get("tdc")
        if detector is None:
            raise ConnectionError("TDC detector is not connected.")
        return detector

    def get_powermeter(self) -> PowerMeter:
        detector = self.detectors.get("powermeter")
        if detector is None:
            raise ConnectionError("PowerMeter detector is not connected.")
        return detector

    def __enter__(self) -> MeasManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect_all()

    def disconnect_all(self) -> None:
        """Force disconnect all detectors"""
        for key, dev in list(self.detectors.items()):
            if dev is not None:
                try:
                    if hasattr(dev, "disconnect"):
                        dev.disconnect()
                    elif hasattr(dev, "close"):
                        dev.close()
                    logger.info("Disconnected %s.", key)
                except Exception:
                    logger.warning("Error disconnecting %s.", key, exc_info=True)
                self.detectors[key] = None

    def measure(
        self,
        duration: float = 1.0,
        samples: int = 1,
        channels: list[int] | None = None,
        task: str = "calibration",
        detector: str = "powermeter",
        meas_type: str = "power",
        save_raw: bool = False,
        unit: str | None = None,
        wavelength_nm: float | None = None,
        delay: int | None = None,
        window_start: int | None = None,
        window_stop: int | None = None,
    ) -> MeasurementResult:
        if detector not in DETECTORS:
            raise ValueError("Invalid detector type.")
        if meas_type not in MEAS_TYPES:
            raise ValueError("Invalid measurement type.")
        if task not in TASK_OPTIONS:
            raise ValueError("Invalid task.")

        if detector == "powermeter":
            from qtools.powermeter import measure_power

            task_cfg = self.cfg.get(task, {})
            pm = self.get_powermeter()
            pm_wavelength = (
                wavelength_nm
                or task_cfg.get("wavelength_nm")
                or task_cfg.get("wavelength")
                or 1560
            )

            with pm:
                pm.auto_range = task_cfg.get("auto_range", True)
                pm.set_wavelength(pm_wavelength)
                logger.info("PowerMeter: wavelength=%.0f nm, auto_range=%s", pm_wavelength, pm.auto_range)

                mean, std = measure_power(pm, duration=duration, samples=samples)

            converted_mean, unit = _power_unit(mean, unit=unit)
            converted_std, _ = _power_unit(std, unit=unit)
            return MeasurementResult(
                value=converted_mean,
                error=converted_std,
                unit=unit,
                metrics={"mean": converted_mean, "std": converted_std},
                metadata={"detector": detector, "meas_type": meas_type, "duration": duration, "samples": samples, "task": task},
            )
        
        elif detector == "tdc":
            task_cfg = self.cfg.get(task, {})
            tdc = self.get_tdc()
            tdc_thresvolt = task_cfg.get("thresvolt", 0.6)

            with tdc:
                # Unified threshold API: global-threshold backends (S15) set the
                # shared threshold; per-channel backends (CIQTEK/IDQ) apply the
                # value to all channels when channel is None.
                tdc.set_threshold(tdc_thresvolt)

                if meas_type == "singles":
                    res = tdc.measure_singles(duration=duration, num=samples)
                    counts = [float(np.sum(s.counts)) if hasattr(s, "counts") else float(s) for s in res]
                    mean_cnt, std_cnt = _calc_stats(counts)
                    return MeasurementResult(
                        value=mean_cnt,
                        error=std_cnt,
                        unit="counts",
                        metrics={"samples": res, "counts": counts},
                        metadata={"detector": detector, "meas_type": meas_type, "duration": duration, "samples": samples, "task": task},
                    )

                elif meas_type == "rates":
                    res = tdc.measure_rates(duration=duration, num=samples)
                    rates = [float(np.sum(r[1])) for r in res]
                    mean_rate, std_rate = _calc_stats(rates)
                    return MeasurementResult(
                        value=mean_rate,
                        error=std_rate,
                        unit="cps",
                        metrics={"samples": res, "rates": rates},
                        metadata={"detector": detector, "meas_type": meas_type, "duration": duration, "samples": samples, "task": task},
                    )

                elif meas_type == "pairs":
                    ch_start = task_cfg.get("ch_start", 0)
                    ch_stop = task_cfg.get("ch_stop", 1)
                    if isinstance(channels, (tuple, list)) and len(channels) >= 2:
                        ch_start, ch_stop = channels[0], channels[1]
                    delay = delay if delay is not None else task_cfg.get("delay_bin", 0)  # bins; TDC converts to ns/ps via `unit` internally
                    bins = task_cfg.get("bins", 500)
                    peak = task_cfg.get("peak", 0)
                    loffset = task_cfg.get("loffset", 0)
                    roffset = task_cfg.get("roffset", 0)
                    window_start = window_start if window_start is not None else task_cfg.get("window_start", None)
                    window_stop = window_stop if window_stop is not None else task_cfg.get("window_stop", None)
                    bin_offset = task_cfg.get("bin_offset", 0)
                    unit = task_cfg.get("unit", "ns")
                    
                    res = tdc.measure_pairs_samples(
                        duration=duration,
                        ch_start=ch_start,
                        ch_stop=ch_stop,
                        delay=delay,
                        bins=bins,
                        peak=peak,
                        loffset=loffset,
                        roffset=roffset,
                        window_start=window_start,
                        window_stop=window_stop,
                        bin_offset=bin_offset,
                        unit=unit,
                        num=samples,
                    )

                    return MeasurementResult(
                        value=float(res["net_pair_rate"]),
                        error=float(res["net_pair_rate_std"]),
                        unit="cps",
                        metrics=res,
                        metadata={"detector": detector, "meas_type": meas_type, "duration": duration, "samples": samples, "task": task},
                    )

                elif meas_type == "timestamps":
                    ts_data = tdc.measure_timestamps(duration=duration, unit="ps", channels=channels)
                    channel_rates = {}
                    for ch_idx, total_time_ns, ts_arr in ts_data:
                        duration_s = total_time_ns * 1e-9
                        count_rate = len(ts_arr) / duration_s if duration_s > 0 else 0.0
                        channel_rates[ch_idx] = {
                            "channel": ch_idx,
                            "counts": len(ts_arr),
                            "count_rate": count_rate,
                            "total_time_ns": total_time_ns,
                        }
                    # Pick the first selected channel's rate as value/error
                    first_ch = channels[0] if channels else list(channel_rates.keys())[0]
                    primary_rate = channel_rates[first_ch]["count_rate"]
                    return MeasurementResult(
                        value=primary_rate,
                        error=0.0,
                        unit="cps",
                        metrics={"channel_rates": channel_rates},
                        metadata={"detector": detector, "meas_type": meas_type, "duration": duration, "samples": samples, "task": task},
                    )

                else:
                    raise ValueError("Invalid measurement type.")
        else:
            raise ValueError("Invalid detector.")


class TaskController:
    """High-level task controller and orchestrator for qtools.pmeas.

    Coordinates configuration management, motor control, and measurement tasks.
    Dispatches tasks to calibration, entanglement scan, and optimization modules.
    """

    def __init__(self, config_path: str = "polmeas_config.yaml"):
        from qtools.pmeas.motor_manager import MotorManager
        self.config_path = config_path
        self.cfg = ConfigManager.resolve(config_path)
        self.motor_mgr = MotorManager(self.cfg)
        self._meas_mgr: Any = None

    def __enter__(self) -> TaskController:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def meas_mgr(self) -> MeasManager | None:
        """Lazily-created :class:`MeasManager`, cached for the session."""
        if self._meas_mgr is None:
            try:
                self._meas_mgr = MeasManager(self.cfg)
            except Exception as ex:
                logger.warning("Could not initialize MeasManager — tdc/powermeter unavailable: %s", ex)
                self._meas_mgr = None
        return self._meas_mgr

    def get_default_detector(self, task: str = "calibration") -> tuple[str, str]:
        task_cfg = self.cfg.get(task, {})
        if isinstance(task_cfg, dict) and task_cfg.get("detector"):
            det = str(task_cfg["detector"]).lower()
            meas = task_cfg.get("meas_type") or ("power" if det == "powermeter" else "singles")
            return det, meas

        detectors = self.cfg.get("detectors", {})
        if detectors.get("powermeter", {}).get("port") or detectors.get("powermeter", {}).get("backend"):
            return "powermeter", "power"
        if detectors.get("tdc", {}).get("port") or detectors.get("tdc", {}).get("backend"):
            return "tdc", "singles"

        return "powermeter", "power"

    def calibrate(
        self,
        waveplate: str = "hwp",
        *,
        motor_target: str | None = None,
        channel: Any = None,
        meas_type: str | None = None,
        duration: float | None = None,
        repetitions: int | None = None,
        start_angle: float | None = None,
        end_angle: float | None = None,
        step_angle: float | None = None,
        wavelength_nm: float | None = None,
        config_label: str | None = None,
        detector: str | None = None,
        basis: str = "H",
        input_pol: str = "H",
        estimated_theta_0: float = 0.0,
        background: float = 20.0,
        export: bool = True,
        export_path: str | None = None,
        plot: bool = True,
        device_name: str = "",
        unit: str | None = None,
    ) -> dict:
        """Run a waveplate calibration routine."""
        cal = self.cfg.get("calibration", {})
        def_det, def_meas = self.get_default_detector("calibration")
        resolved_detector = detector or cal.get("detector") or def_det
        resolved_meas = meas_type or cal.get("meas_type") or def_meas

        from qtools.pmeas.calibration import run_calibration
        return run_calibration(
            target=motor_target,
            waveplate=waveplate,
            motor_mgr=self.motor_mgr,
            meas_mgr=self.meas_mgr,
            cfg=self.cfg,
            channel=channel if channel is not None else cal.get("channel", 0),
            meas_type=resolved_meas,
            duration=duration if duration is not None else float(cal.get("duration", self.cfg.get("measurement.duration", 1.0))),
            repetitions=repetitions if repetitions is not None else int(cal.get("repetitions", self.cfg.get("measurement.repetitions", 10))),
            start_angle=start_angle if start_angle is not None else float(cal.get("start_angle", 0.0)),
            end_angle=end_angle if end_angle is not None else float(cal.get("end_angle", 360.0)),
            step_angle=step_angle if step_angle is not None else float(cal.get("step_angle", 5.0)),
            wavelength_nm=wavelength_nm if wavelength_nm is not None else float(cal.get("wavelength", cal.get("wavelength_nm", 1560.0))),
            config_label=config_label,
            detector=resolved_detector,
            basis=basis,
            input_pol=input_pol,
            estimated_theta_0=estimated_theta_0,
            background=background,
            export=export,
            export_path=export_path,
            plot=plot,
            device_name=device_name,
            unit=unit,
        )

    def scan_singles(
        self,
        sweep: str = "bob",
        start_angle: float | None = None,
        end_angle: float | None = None,
        step_angle: float | None = None,
        duration: float | None = None,
        repetitions: int | None = None,
        channel: Any = None,
        save_raw: bool = True,
        save_plot: bool = False,
        unit: str | None = None,
    ) -> dict:
        """Run single-detector / power sweep scan on a motor stage."""
        if self.meas_mgr is None:
            raise ConnectionError("MeasManager is unavailable — detector is not connected.")

        scan_cfg = self.cfg.get("scan", {})
        from qtools.pmeas.entanglement import run_singles_scan
        return run_singles_scan(
            motor_mgr=self.motor_mgr,
            meas_mgr=self.meas_mgr,
            cfg=self.cfg,
            sweep=sweep,
            start_angle=start_angle if start_angle is not None else float(scan_cfg.get("start_angle", 0.0)),
            end_angle=end_angle if end_angle is not None else float(scan_cfg.get("end_angle", 360.0)),
            step_angle=step_angle if step_angle is not None else float(scan_cfg.get("step_angle", 5.0)),
            duration=duration if duration is not None else float(scan_cfg.get("duration", 1.0)),
            repetitions=repetitions if repetitions is not None else int(scan_cfg.get("repetitions", 5)),
            channel=channel if channel is not None else scan_cfg.get("channels"),
            save_raw=save_raw,
            save_plot=save_plot,
            unit=unit,
        )

    def scan_coincidence(
        self,
        fix_angles: str | float | list[str | float] | None = None,
        start_angle: float | None = None,
        end_angle: float | None = None,
        step_angle: float | None = None,
        duration: float | None = None,
        repetitions: int | None = None,
        subtract_accidentals: bool = False,
        channel: Any = None,
        export: bool | str = True,
        save_plot: bool = False,
        fix: str = "alice",
        sweep: str = "bob",
        fix_label: str | None = None,
        sweep_label: str | None = None,
        fix_angle: str | float | list[str | float] | None = None,
        bases: list[str] | None = None,
        delay: int | None = None,
        window_start: int | None = None,
        window_stop: int | None = None,
    ) -> dict:
        """Run single-axis coincidence scan (fix fixed arm, sweep swept arm)."""
        if self.meas_mgr is None:
            raise ConnectionError("MeasManager is unavailable — TDC detector not connected.")

        scan_cfg = self.cfg.get("scan", {})
        resolved_targets = (
            fix_angles
            if fix_angles is not None
            else (fix_angle if fix_angle is not None else (bases if bases is not None else scan_cfg.get("bases")))
        )
        from qtools.pmeas.entanglement import run_coincidence_scan
        return run_coincidence_scan(
            motor_mgr=self.motor_mgr,
            meas_mgr=self.meas_mgr,
            cfg=self.cfg,
            fix=fix,
            sweep=sweep,
            fix_label=fix_label,
            sweep_label=sweep_label,
            fix_angles=resolved_targets,
            start_angle=start_angle if start_angle is not None else float(scan_cfg.get("start_angle", 0.0)),
            end_angle=end_angle if end_angle is not None else float(scan_cfg.get("end_angle", 180.0)),
            step_angle=step_angle if step_angle is not None else float(scan_cfg.get("step_angle", 10.0)),
            duration=duration if duration is not None else float(scan_cfg.get("duration", 1.0)),
            repetitions=repetitions if repetitions is not None else int(scan_cfg.get("repetitions", 3)),
            subtract_accidentals=subtract_accidentals if subtract_accidentals is not None else bool(scan_cfg.get("subtract_accidentals", True)),
            channel=channel if channel is not None else scan_cfg.get("channels", (0, 1)),
            export=export,
            save_plot=save_plot,
            delay=delay,
            window_start=window_start,
            window_stop=window_stop,
        )

    def scan_bell(
        self,
        start_offset: float | None = None,
        end_offset: float | None = None,
        step_offset: float | None = None,
        duration: float | None = None,
        repetitions: int | None = None,
        subtract_accidentals: bool | None = None,
        channel: Any = None,
        save_raw: bool = True,
        save_plot: bool = False,
        fix: str = "alice",
        sweep: str = "bob",
        delay: int | None = None,
        window_start: int | None = None,
        window_stop: int | None = None,
    ) -> dict:
        """Run CHSH Bell parameter S scan."""
        if self.meas_mgr is None:
            raise ConnectionError("MeasManager is unavailable — TDC detector not connected.")

        chsh_cfg = self.cfg.get("chsh", {})
        from qtools.pmeas.entanglement import run_bell_scan
        return run_bell_scan(
            motor_mgr=self.motor_mgr,
            meas_mgr=self.meas_mgr,
            cfg=self.cfg,
            fix=fix,
            sweep=sweep,
            start_offset=start_offset if start_offset is not None else float(chsh_cfg.get("start_offset", 0.0)),
            end_offset=end_offset if end_offset is not None else float(chsh_cfg.get("end_offset", 90.0)),
            step_offset=step_offset if step_offset is not None else float(chsh_cfg.get("step_offset", 5.0)),
            duration=duration if duration is not None else float(chsh_cfg.get("duration", 1.0)),
            repetitions=repetitions if repetitions is not None else int(chsh_cfg.get("repetitions", 3)),
            subtract_accidentals=subtract_accidentals if subtract_accidentals is not None else bool(chsh_cfg.get("subtract_accidentals", True)),
            channel=channel if channel is not None else chsh_cfg.get("channels", (0, 1)),
            save_raw=save_raw,
            save_plot=save_plot,
            delay=delay,
            window_start=window_start,
            window_stop=window_stop,
        )

    def optimize_basis(
        self,
        serial_a: str | None = None,
        serial_b: str | None = None,
        duration: float = 0.5,
        repetitions: int = 2,
        channel: Any = (0, 1),
        start_step: float = 4.0,
        tol: float = 0.1,
    ) -> tuple[float, float, float]:
        """Run 2-D coordinate descent basis optimization."""
        if not serial_a or not serial_b:
            devs = self.cfg.get_all_devices()
            if len(devs) >= 2:
                serial_a = serial_a or str(devs[0].get("serial") or devs[0].get("name", ""))
                serial_b = serial_b or str(devs[1].get("serial") or devs[1].get("name", ""))
        from qtools.pmeas.optimization import optimize_basis
        return optimize_basis(
            controller=self,
            serial_a=serial_a or "",
            serial_b=serial_b or "",
            duration=duration,
            repetitions=repetitions,
            channel=channel,
            start_step=start_step,
            tol=tol,
        )

    def live_correction(
        self,
        serial_a: str | None = None,
        serial_b: str | None = None,
        interval: float = 60.0,
        threshold: float = 2.5,
        duration: float = 1.0,
        repetitions: int = 2,
        channel: Any = (0, 1),
        filename: str = "drift_history.npz",
    ) -> None:
        """Run continuous live drift correction loop."""
        if not serial_a or not serial_b:
            devs = self.cfg.get_all_devices()
            if len(devs) >= 2:
                serial_a = serial_a or str(devs[0].get("serial") or devs[0].get("name", ""))
                serial_b = serial_b or str(devs[1].get("serial") or devs[1].get("name", ""))
        from qtools.pmeas.optimization import run_live_correction
        run_live_correction(
            controller=self,
            serial_a=serial_a or "",
            serial_b=serial_b or "",
            interval=interval,
            threshold=threshold,
            duration=duration,
            repetitions=repetitions,
            channel=channel,
            filename=filename,
        )

    def close(self) -> None:
        try:
            self.motor_mgr.disconnect_all()
        finally:
            if self._meas_mgr is not None:
                self._meas_mgr.disconnect_all()


# Backward compatibility alias
MeasController = TaskController
