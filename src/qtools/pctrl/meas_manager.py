#!/usr/bin/env python3
"""
Measurement manager for polarization controller.

Encapsulates TDC / powermeter readout: connect → read → disconnect.
Device addresses are persisted in CalConfigManager / OptConfigManager.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import numpy as np

from qtools.pctrl.config import CalConfigManager, OptConfigManager

logger = logging.getLogger(__name__)

try:
    from qtools import tdc
except Exception as e:
    logger.debug("tdc module not found; TDC readout will be unavailable")

try:
    from qtools import powermeter
except Exception:
    logger.debug("powermeter module not found; powermeter readout will be unavailable.")


def _now_str() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class MockMeasManager:
    """Offline stand-in for MeasManager used in --mock mode and unit tests."""

    def __init__(self, value: float = 1.0, noise: float = 0.0):
        self.value = float(value)
        self.noise = float(noise)

    def measure(
        self,
        duration: float | None = None,
        samples: int | None = None,
        channels: Optional[List[int]] = None,
        measure_type: str = "singles",
        **kwargs,
    ) -> List:
        # Single-channel (mean, std) layout expected by calibration/optimize
        return [(self.value, self.noise)]

    def read_raw(self, duration: float | None = None, channels: Optional[List[int]] = None) -> np.ndarray:
        return np.array([self.value], dtype=float)


class MeasManager:
    """Manages TDC/powermeter measurement readout via config-driven connections.

    Device settings come from the main :class:`ConfigManager` ``detectors:``
    section (preferred) and fall back to the legacy *cal_cfg* / *opt_cfg*.
    All connection work is delegated to the ``tdc`` / ``powermeter`` packages.
    """

    def __init__(self,
                 config_manager: Optional["ConfigManager"] = None,
                 cal_config_path: Optional[str] = None,
                 opt_config_path: Optional[str] = None):
        self.cfg = config_manager
        self.cal_cfg = CalConfigManager(cal_config_path)
        self.opt_cfg = OptConfigManager(opt_config_path)

        self.tdc = None
        self.pm = None

        self.tdc = self._init_tdc()
        self.pm = self._init_pm()

        if self.tdc:
            logger.info("TDC initialized: %s", self.tdc.backend.name)
        if self.pm:
            logger.info("Powermeter initialized: %s", self.pm.get_info())

    # ── config helpers ───────────────────────────────────────────────

    def _tdc_config(self) -> dict:
        """TDC ``{port, backend}`` from the main config, else the cal config."""
        if self.cfg is not None:
            cfg = self.cfg.tdc_config
            if cfg.get("backend"):
                return cfg
        return self.cal_cfg.tdc_config

    def _pm_config(self) -> dict:
        """Powermeter ``{port, backend}`` from the main config, else the cal config."""
        if self.cfg is not None:
            cfg = self.cfg.pm_config
            if cfg.get("backend"):
                return cfg
        return self.cal_cfg.pm_config

    def _prefer_tdc(self) -> bool:
        """True when the TDC is the more likely usable detector.

        Prefer the TDC when a powermeter port is not configured — a powermeter
        facade without a port can only fall back to auto-detection, which is
        the slow path.  A powermeter with a configured port keeps its legacy
        first try.
        """
        if self.tdc is None:
            return False
        return not bool(self._pm_config().get("port"))

    # ── device initialization ────────────────────────────────────────

    def _init_tdc(self) -> "Optional[tdc.TDC]":
        """Create (and probe) a TDC from config; auto-rescan + save on failure.

        Connection is delegated to ``tdc.get_device`` — the backend handles
        auto-discovery when no port is configured.  If the configured device
        cannot be reached, scan for a connected TDC and persist the new
        port/backend (pmeas-style) before returning the fresh device.
        """
        cfg = self._tdc_config()
        backend = cfg.get("backend")
        if not backend:
            return None
        port = cfg.get("port") or None
        try:
            dev = tdc.get_device(backend, port)
            dev.backend.connect()
            dev.backend.disconnect()
            return dev
        except Exception as e:
            logger.warning("TDC initialization failed (backend=%s, port=%s): %s",
                           backend, port, e)

        # Auto-rescan and persist, then retry once.
        try:
            new_cfg = self._rescan_tdc()
        except Exception as e:
            logger.warning("TDC auto-rescan failed: %s", e)
            return None
        backend, port = new_cfg.get("backend"), new_cfg.get("port")
        if not backend or not port:
            logger.warning("TDC auto-rescan did not find a device")
            return None
        try:
            dev = tdc.get_device(backend, port)
            dev.backend.connect()
            dev.backend.disconnect()
            return dev
        except Exception as e:
            logger.warning("TDC reconnect failed at %s (%s): %s", port, backend, e)
            return None

    def _rescan_tdc(self) -> dict:
        """Discover a connected TDC and persist it to the main + cal/opt configs."""
        from qtools.tdc.connection import discover_all as tdc_discover_all
        devices = tdc_discover_all(method="usb", timeout=1.0)
        if not devices:
            devices = tdc_discover_all(method="ethernet", timeout=1.0)
        if not devices:
            return {}
        dev = devices[0]
        backend, path = dev.backend_name, dev.device_path
        if self.cfg is not None:
            self.cfg._cfg.setdefault("detectors", {}).setdefault("tdc", {})["backend"] = backend
            self.cfg.set_device_port("tdc", path)
            self.cfg.save()
        for mgr in (self.cal_cfg, self.opt_cfg):
            mgr._cfg.setdefault("devices", {}).setdefault("tdc", {})["backend"] = backend
            mgr.set_device_port("tdc", path)
            mgr.save()
        logger.info("TDC auto-rescan found: %s (%s)", path, backend)
        return {"backend": backend, "port": path}

    def _init_pm(self) -> "Optional[powermeter.BasePowerMeter]":
        """Create powermeter instance from config via the unified get_device entry.

        Passes ``port`` (may be None) directly — the backend handles
        auto-discovery internally when no port is given.  Applies
        wavelength / range overrides from config on success.
        """
        cfg = self._pm_config()
        backend = cfg.get("backend")
        if not backend:
            return None
        port = cfg.get("port") or None
        try:
            dev = powermeter.get_device(backend, port)
        except Exception as e:
            logger.warning("Powermeter initialization failed: %s", e)
            return None

        # Optional config overrides
        wavelength = cfg.get("wavelength")
        if wavelength:
            try:
                dev.set_wavelength(float(wavelength))
            except NotImplementedError:
                logger.error("Wavelength is not correctly set.")

        range_val = cfg.get("range")
        try:
            dev.set_range(float(range_val) if range_val is not None else 0)
        except NotImplementedError:

            logger.error("Range is not correctly set.")
        return dev

    # ── read ────────────────────────────────────────────────────

    def _measure_pm(self, duration: float, samples: int) -> tuple:
        """Read from qtools.powermeter — connect, sample, disconnect."""
        with self.pm:
            mean_power, std_dev = self.pm.measure_power()
        return mean_power, std_dev

    def _measure_tdc(self, duration: float = 1, samples: int = 1,  channels: Optional[List[int]] = None) -> List:
        """Read from TDC — connect, measure singles, disconnect."""
        with self.tdc:
            results = self.tdc.measure_singles(duration=duration, num=samples)

        n_channels = len(results[0][1])
        if not channels:
            channel_indices = list(range(n_channels))
        else:
            channel_indices = [int(ch) - 1 for ch in channels]
        invalid = [ch + 1 for ch in channel_indices if ch < 0 or ch >= n_channels]
        if invalid:
            raise ValueError(
                f"TDC channel(s) {invalid} out of range (1-{n_channels})"
            )

        # Each result is an (integration_time, counts) tuple; convert the
        # selected channel's raw counts to counts/s before averaging.
        rate_res = []
        for idx in channel_indices:
            rates = [
                float(sample[1][idx]) / float(sample[0])
                for sample in results
                if sample[0] > 0
            ]
            if not rates:
                raise RuntimeError("TDC returned zero integration time")
            mean_rate = np.mean(rates)
            std_dev = np.std(rates, ddof=1) if len(rates) > 1 else 0.0
            rate_res.append((mean_rate, std_dev))
        return rate_res

    def _measure_tdc_pairs(
        self,
        duration: float,
        samples: int,
        *,
        ch_start: int,
        ch_stop: int,
        delay: int,
        window_start: int,
        window_stop: int,
        threshvolt: float,
    ) -> List:
        """Read coincidence pairs through the public tdc package API."""
        with self.tdc:
            self.tdc.set_threshold(threshvolt)
            result = self.tdc.measure_pairs_samples(
                duration=duration,
                ch_start=ch_start,
                ch_stop=ch_stop,
                delay=delay,
                window_start=window_start,
                window_stop=window_stop,
                num=samples,
            )
        return [(
            float(result["net_pair_rate"]),
            float(result["net_pair_rate_std"]),
        )]

    def measure(self,
                duration: float | None = None,
                samples: int | None = None,
                channels: Optional[List[int]] = None,
                measure_type: str = "singles",
                ch_start: Optional[int] = None,
                ch_stop: Optional[int] = None,
                delay: Optional[int] = None,
                window_start: Optional[int] = None,
                window_stop: Optional[int] = None,
                threshvolt: Optional[float] = None) -> List:
        """
        Connect → read → disconnect.

        *duration*, *samples* and *channels* default to the values in
        *cal_cfg* (or *opt_cfg*).

        Raises ConnectionError if no device can be reached.
        """
        if measure_type == "pairs":
            if self.tdc is None:
                raise ConnectionError("Pairs measurement requires a TDC.")
            if ch_start is None or ch_stop is None:
                raise ValueError("Pairs measurement requires ch_start and ch_stop.")
            if (window_start is None) != (window_stop is None):
                raise ValueError(
                    "Pairs measurement requires window_start and window_stop together."
                )
            if window_start is None or window_stop is None:
                raise ValueError("Pairs measurement requires window_start and window_stop.")
            return self._measure_tdc_pairs(
                1 if duration is None else duration,
                1 if samples is None else samples,
                ch_start=ch_start,
                ch_stop=ch_stop,
                delay=0 if delay is None else delay,
                window_start=window_start,
                window_stop=window_stop,
                threshvolt=0.6 if threshvolt is None else threshvolt,
            )
        if measure_type != "singles":
            raise ValueError(f"Unsupported TDC measurement type: {measure_type!r}")

        params = self.cal_cfg.meas_params
        duration = duration if duration is not None else params.get("duration", 1)
        samples = samples if samples is not None else params.get("samples", 1)
        channels = channels if channels is not None else params.get("channels")

        # Try the explicitly-configured detector first (e.g. TDC-only setup
        # should not pay a failing powermeter probe on every read).
        if self._prefer_tdc():
            candidates = [("tdc", self.tdc), ("powermeter", self.pm)]
        else:
            candidates = [("powermeter", self.pm), ("tdc", self.tdc)]

        for name, dev in candidates:
            if dev is None:
                continue
            try:
                if name == "tdc":
                    return self._measure_tdc(duration, samples, channels)
                return [self._measure_pm(duration, samples)]
            except Exception as e:
                logger.warning("%s measurement failed (%s), trying the other detector.",
                               name.capitalize(), e)

        msg = (
            "No measurement device found. "
            "Configure one via cal/opt config or connect a TDC/powermeter."
        )
        logger.error(msg)
        raise ConnectionError(msg)

    # ── raw TDC timestamps ─────────────────────────────────────

    def read_raw(self, duration: float | None = None, channels: Optional[List[int]] = None) -> np.ndarray:
        """Connect to TDC, collect raw timestamps, disconnect.

        Returns a 1-D array of timestamp values (in seconds).
        Only supported when a TDC is configured / discoverable.
        """
        if self.tdc is None:
            raise ConnectionError("No TDC configured — raw timestamps require a TDC.")

        params = self.cal_cfg.meas_params
        duration = duration if duration is not None else params.get("duration", 1)

        with self.tdc:
            stamps = self.tdc.measure_timestamps(duration=duration, channels=channels)
        return stamps
    
    # ── expert data saving ─────────────────────────────────────

    def _save_data(self, data: np.ndarray, tag: str) -> Path | None:
        """Save *data* to the expert raw-data directory, if enabled in config."""
        params = self.cal_cfg.meas_params
        if not params.get("expert"):
            return None
        out_dir = Path(params.get("raw_data_dir", "pctrl_calibration_data"))
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = out_dir / f"{tag}_{_now_str()}.npz"
        np.savez_compressed(fname, data=data, timestamp=_now_str())
        logger.info("Expert data saved: %s", fname)
        return fname

    # ── discovery + save ───────────────────────────────────────

    def discover_and_save(self) -> None:
        """Auto-discover TDC/powermeter and write addresses to both configs."""
        # TDC
        try:
            candidates = tdc.auto_discover()
            if candidates:
                d = candidates[0]
                for cfg in (self.cal_cfg, self.opt_cfg):
                    cfg.set_device_port("tdc", d.device_path)
                    cfg.save()
                logger.info("Saved TDC config: %s (%s)", d.device_path, d.backend_name)
        except Exception as e:
            logger.warning("TDC discovery failed: %s", e)

        # Powermeter
        try:
            from qtools.powermeter.cli import auto_detect_connected_device
            addr, backend = auto_detect_connected_device()
        except Exception as e:
            logger.warning("Powermeter discovery failed: %s", e)
            addr, backend = None, None
        if addr:
            for cfg in (self.cal_cfg, self.opt_cfg):
                cfg.set_device_port("powermeter", addr)
                cfg.save()
            logger.info("Saved PM config: %s (%s)", addr, backend)
