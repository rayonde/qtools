from typing import List, Dict, Any, Union
from qtools.pctrl.servo_manager import ServoManager
from qtools.pctrl.meas_manager import MeasManager
from qtools.pctrl.config import ConfigManager, channel_key_string, resolve_target
from qtools.pctrl.calibration import run_calibration, evaluate_metric
from qtools.pctrl.utils import run_torque_control

class PolarizationController:
    """
    High-level programmatic API for the Polarization Controller.
    Allows external Python scripts and applications to control waveplates,
    query sensors, and run calibration routines programmatically.
    """

    def __init__(self, config_path: str = "pctrl_config.yaml", mock: bool = False):
        self.config_path = config_path
        self.cfg = ConfigManager(config_path)
        self.cfg.load()

        # ── Servo manager (share the same ConfigManager instance) ──
        self.servo_mgr = ServoManager(cfg=self.cfg, mock_mode=mock)
        if mock:
            import qtools.pctrl.backends.scservo_sdk as sdk
            sdk.mock_mode = True

        # ── Measurement manager ──────────────────────────────────
        if mock:
            from qtools.pctrl.meas_manager import MockMeasManager
            self.meas_mgr = MockMeasManager()
        else:
            try:
                self.meas_mgr = MeasManager(config_manager=self.cfg)
            except Exception:
                self.meas_mgr = None

    def __enter__(self) -> "PolarizationController":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ── servo helpers ───────────────────────────────────────────

    def set_angles(self, target: str, angles: Union[float, List[float], str],
                   speed_deg_s: float = 10.0) -> None:
        """Move target servo(s) to target physical angle(s) in degrees."""
        from qtools.pctrl.utils import run_direct_set
        if isinstance(angles, list):
            angles_str = ",".join(map(str, angles))
            set_str = f"{target}:{angles_str}"
        else:
            set_str = f"{target}:{angles}"

        run_direct_set(
            config=self.config_path,
            set_str=set_str,
            speed_deg_s=speed_deg_s,
            port=self.cfg.port,
            baud=self.cfg.baudrate,
            ph_sts=self.servo_mgr.backend,
        )

    def get_angles(self, target: str) -> Dict[str, float]:
        """Query current physical angles of the target servo(s)."""
        servos = []
        if target.lower() == "all":
            servos = self.cfg.all_servos()
        else:
            names = [n.strip() for n in target.split(",") if n.strip()]
            for name in names:
                s = None
                if name.isdigit():
                    s = self.cfg.find_by_id(int(name))
                if not s:
                    s = self.cfg.get_servo(name)
                if not s:
                    try:
                        resolution = resolve_target(self.cfg, name)
                        for ch in resolution.channels:
                            servos.extend(ch["servos"])
                    except ValueError:
                        pass
                else:
                    servos.append(s)

        results = {}
        for s in servos:
            try:
                native = self.servo_mgr.get_angle(s["name"])
                center = self.servo_mgr.get_servo_center(s["name"])
                results[s["name"]] = native - center
            except Exception:
                results[s["name"]] = None
        return results

    def get_sensor_value(self, duration: float = 0.2, samples: int = 1) -> float:
        """Read raw sensor count rate or power value."""
        if self.meas_mgr is None:
            raise ConnectionError("No measurement device configured.")
        return evaluate_metric(self.meas_mgr, duration=duration, samples=samples)

    # ── calibration ─────────────────────────────────────────────

    def calibrate(
        self,
        target: str = "all",
        basis: str = "h",
        fast: bool = False,
        step_deg: float = 5.0,
        speed_deg_s: float = 10.0,
        channels: List[int] | None = None,
        duration: float | None = None,
        plot: bool = False,
    ) -> None:
        """Run automated waveplate calibration.

        *plot* — if True, save and display the calibration figures.
        """
        run_calibration(
            config=self.config_path,
            target=target,
            step_deg=step_deg,
            speed_deg_s=speed_deg_s,
            basis=basis,
            fast=fast,
            port=self.cfg.port,
            mock=self.servo_mgr.mock_mode,
            channels=channels,
            duration=duration,
            plot=plot,
        )

    # ── optimization ────────────────────────────────────────────

    def optimize(
        self,
        target: str = "all",
        metric_fn: Any = None,
        *,
        minimize: bool = False,
        method: str = "Nelder-Mead",
        maxiter: int = 30,
        tol: float = 1.0,
        step_size_deg: float = 15.0,
        speed_deg_s: float = 10.0,
        settle_time: float = 0.1,
        duration: float = 0.2,
        samples: int = 1,
        measure_type: str = "singles",
        channels: List[int] | None = None,
        ch_start: int | None = None,
        ch_stop: int | None = None,
        delay: int | None = None,
        window_start: int | None = None,
        window_stop: int | None = None,
        threshvolt: float | None = None,
        verbose: bool = True,
        callback: Any = None,
        save_config: bool = False,
        save_process: Any = None,
        save: bool = False,
        plot: bool = False,
    ) -> Any:
        """Run multi-servo angle optimization to maximize or minimize a metric.

        Parameters
        ----------
        metric_fn : Callable[[MeasManager], float], optional
            Required when using 2+ TDC channels.  Default: channel-1 mean.
        channels : list[int], optional
            TDC channel numbers, e.g. ``[1, 2]`` for coincidence readout.
        measure_type : str, default "singles"
            TDC measurement type: ``"singles"`` or ``"pairs"``.
        samples : int
            Number of readings averaged per evaluation.
        callback : Callable, optional
            ``callback(iteration, angles, scalar_value, raw_measurement)``
            where *raw_measurement* is the ``(C, 2)`` ndarray of
            ``[[mean, std], ...]`` from the current evaluation.
        save_config : bool, default False
            Save optimal physical angles back to config file.
        save_process : str or bool, optional
            Save optimization step history (angles, values) to JSON/CSV/YAML file.
        plot : bool, optional
            If True, save and display the convergence figures.
        """
        from qtools.pctrl.optimize import optimize_channel

        if self.meas_mgr is None:
            raise ConnectionError(
                "No measurement device configured. "
                "Run 'pctrl device tdc <COM_PORT>' first."
            )

        # Resolve target channels
        resolution = resolve_target(self.cfg, target)
        target_channels = resolution.channels
        target_servo_name = resolution.target_servo_name

        if not target_channels:
            raise ValueError(
                f"Target '{target}' not recognized as a channel, servo, or 'all'."
            )

        results = {}
        for ch in target_channels:
            res = optimize_channel(
                cfg=self.cfg,
                channel=ch,
                servo_mgr=self.servo_mgr,
                meas_mgr=self.meas_mgr,
                target_servo_name=target_servo_name,
                metric_fn=metric_fn,
                minimize_metric=minimize,
                method=method,
                maxiter=maxiter,
                tol=tol,
                step_size_deg=step_size_deg,
                speed_deg_s=speed_deg_s,
                settle_time=settle_time,
                duration=duration,
                samples=samples,
                measure_type=measure_type,
                channels=channels,
                ch_start=ch_start,
                ch_stop=ch_stop,
                delay=delay,
                window_start=window_start,
                window_stop=window_stop,
                threshvolt=threshvolt,
                verbose=verbose,
                callback=callback,
                save_config=save_config or save,
                save_process=save_process,
                plot=plot,
            )
            results[channel_key_string(ch["path"], ch["wavelength"])] = res

        if len(target_channels) == 1:
            return results[channel_key_string(
                target_channels[0]["path"], target_channels[0]["wavelength"]
            )]
        return results

    # ── torque ──────────────────────────────────────────────────

    def set_torque(self, enable: bool, target: str = "all") -> None:
        """Enable (lock) or disable (release) torque for the target servos."""
        run_torque_control(
            config=self.config_path,
            enable=enable,
            port=self.cfg.port,
            baud=self.cfg.baudrate,
            target=target,
            ph_sts=self.servo_mgr.backend,
        )

    def close(self) -> None:
        """Close connection to servo controller."""
        self.servo_mgr.disconnect()
        if self.servo_mgr.mock_mode:
            import qtools.pctrl.backends.scservo_sdk as sdk
            sdk.mock_mode = False
            sdk._mock_ph = None
            sdk._mock_sts = None
