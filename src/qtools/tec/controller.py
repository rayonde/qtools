"""Controller for SenseFuture (光测未来) TEC devices."""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any, Callable, Optional, Tuple, Union

from qtools.tec.connection import (
    BaseTransport,
    MockSerialTransport,
    SerialTransport,
    find_serial_device,
)
from qtools.tec.enums import (
    ERROR_BIT_MAP,
    TEC_MODEL_MAP,
    PowerMode,
    SensorModel,
    TECMode,
    TECPolarity,
)
from qtools.tec.exceptions import TECProtocolError

logger = logging.getLogger(__name__)


def _round(v: Union[int, float], exponent: int = 0) -> Union[int, float]:
    """Prepares nice round numbers, e.g. _round(3, -5) -> 3e-5.

    Examples:
        >>> _round(30)
        30
        >>> _round(30, 0)
        30
        >>> _round(30, 2)
        3000
        >>> _round(30, -3)
        0.03
    """
    _v = v * 10**exponent
    if exponent >= 0:
        return round(_v)
    else:
        return round(_v, -exponent)


class TECChannel:
    """Channel-specific view for a SenseFuture TEC device (Channel 1 or 2).

    Supports independent configuration, temperature measurement, and output
    control for either Channel 1 (TC1) or Channel 2 (TC2).
    """

    def __init__(self, tec: "TEC", channel: int):
        if channel not in (1, 2):
            raise ValueError(f"Invalid channel {channel}; SenseFuture TEC supports channel 1 or 2.")
        self._tec = tec
        self.channel = channel
        self.ch_prefix = f"TC{channel}:"

    ##########################
    #  HIGH-LEVEL INTERFACE  #
    ##########################

    def active(self) -> bool:
        """Check if this channel's output is active/enabled."""
        return self._tec._get(f"{self.ch_prefix}ENABLE") == 1

    @property
    def is_active(self) -> bool:
        """Whether this channel's output is currently active (enabled)."""
        return self.active()

    def on(self) -> None:
        """Switch on this channel's output."""
        self._tec._set(f"{self.ch_prefix}ENABLE=1")

    def off(self) -> None:
        """Switch off this channel's output."""
        self._tec._set(f"{self.ch_prefix}ENABLE=0")

    @property
    def settemp(self) -> float:
        """Gets target setpoint temperature [degC]."""
        return _round(self._tec._get(f"{self.ch_prefix}TG"), -5)

    @settemp.setter
    def settemp(self, value: float):
        """Sets target setpoint temperature [degC]."""
        self.temp = value

    @property
    def target_temp(self) -> float:
        """Gets target setpoint temperature [degC] (alias for settemp)."""
        return self.settemp

    @target_temp.setter
    def target_temp(self, value: float):
        """Sets target setpoint temperature [degC]."""
        self.settemp = value

    @property
    def temp(self) -> float:
        """Gets current measured temperature [degC]."""
        result = _round(self._tec._get(f"{self.ch_prefix}TCADJTEMP"), -5)
        self._tec._log(f"CH{self.channel}_temp", result)
        return float(result)

    @temp.setter
    def temp(self, value: float):
        """Sets target setpoint temperature [degC].

        Args:
            value: Temperature in degC, between -400 and 1000.
        """
        _value = _round(value, 5)
        if not self._tec._set_fallback(f"{self.ch_prefix}TG={_value}"):
            raise ValueError(f"Failed to write CH{self.channel} settemp = {value}")
        self._tec._log(f"CH{self.channel}_settemp", value)

    @property
    def actual_temp(self) -> float:
        """Alias for temp (measured temperature)."""
        return self.temp

    @property
    def slope(self) -> float:
        """Gets maximum temperature slope [K/s]."""
        return float(_round(self._tec._get(f"{self.ch_prefix}SPEED"), -3))

    @slope.setter
    def slope(self, value: float):
        """Sets maximum temperature slope [K/s]."""
        _value = _round(value, 3)
        if not self._tec._set_fallback(f"{self.ch_prefix}SPEED={_value}"):
            raise ValueError(f"Failed to write CH{self.channel} slope = {value}")

    @property
    def resistance(self) -> float:
        """Gets sensor resistance in Ohms [Ω].

        According to spec 3.2.2 & 3.6.2: 1 LSB = 1 µΩ.
        """
        raw = self._tec._get(f"{self.ch_prefix}RESISTOR")
        return round(raw / 1e6, 6)

    @property
    def resistance_kohm(self) -> float:
        """Gets sensor resistance in kilo-Ohms [kΩ]."""
        raw = self._tec._get(f"{self.ch_prefix}RESISTOR")
        return round(raw / 1e9, 6)

    @property
    def current(self) -> float:
        """Gets the output current [A]."""
        return float(_round(self._tec._get(f"{self.ch_prefix}CURRENT"), -3))

    @property
    def current_limit(self) -> float:
        """Gets maximum/minimum current limit [A]."""
        return float(_round(self._tec._get(f"{self.ch_prefix}SETCURRENT"), -1))

    @current_limit.setter
    def current_limit(self, value: float):
        """Sets maximum/minimum current limit [A]."""
        _value = _round(value, 1)
        if not self._tec._set_fallback(f"{self.ch_prefix}SETCURRENT={_value}"):
            raise ValueError(f"Failed to set current_limit = {value}")

    @property
    def voltage_limit(self) -> int:
        """Gets maximum voltage as percentage of input voltage [%]."""
        return self._tec._get(f"{self.ch_prefix}LIMITED")

    @voltage_limit.setter
    def voltage_limit(self, value: int):
        """Sets maximum voltage as percentage of input voltage [%] (0~90%)."""
        if not self._tec._set_fallback(f"{self.ch_prefix}LIMITED={int(value)}"):
            raise ValueError(f"Failed to set voltage_limit = {value}")

    @property
    def polarity(self) -> int:
        """Gets TEC output polarity: 0-normal, 1-reversed."""
        return self._tec._get(f"{self.ch_prefix}PIDPOL")

    @polarity.setter
    def polarity(self, value: Union[int, TECPolarity]):
        """Sets TEC output polarity: 0-normal, 1-reversed."""
        val = int(value)
        if not self._tec._set_fallback(f"{self.ch_prefix}PIDPOL={val}"):
            raise ValueError(f"Failed to set polarity = {value}")

    @property
    def mode(self) -> int:
        """Gets heating mode: 0-both, 1-cool, 2-heat, 3-voltage."""
        return self._tec._get(f"{self.ch_prefix}MODE")

    @mode.setter
    def mode(self, value: Union[int, TECMode]):
        """Sets heating mode: 0-both, 1-cool, 2-heat, 3-voltage."""
        val = int(value)
        if not self._tec._set_fallback(f"{self.ch_prefix}MODE={val}"):
            raise ValueError(f"Failed to set mode = {value}")

    @property
    def pwm_duty(self) -> float:
        """Gets output voltage/duty percentage [%] when mode=3 (-100% ~ 100%)."""
        raw = self._tec._get(f"{self.ch_prefix}PWMDUTY")
        return round(raw / 20000.0, 2)

    @pwm_duty.setter
    def pwm_duty(self, percent: float):
        """Sets output voltage/duty percentage [%] (-100% ~ 100%)."""
        val = int(round(percent * 20000.0))
        if not self._tec._set_fallback(f"{self.ch_prefix}PWMDUTY={val}"):
            raise ValueError(f"Failed to set pwm_duty = {percent}")

    @property
    def pid(self) -> Tuple[float, float, float]:
        """Returns PID parameters (Kp [A/K], Ki [As/K], Kd [A/sK])."""
        p = float(_round(self._tec._get(f"{self.ch_prefix}KP"), -3))
        i = float(_round(self._tec._get(f"{self.ch_prefix}KI"), -3))
        d = float(_round(self._tec._get(f"{self.ch_prefix}KD"), -3))
        return (p, i, d)

    @pid.setter
    def pid(self, values: Tuple[float, float, float] | list[float]):
        """Sets PID parameters (Kp, Ki, Kd)."""
        rounded_values = [_round(v, 3) for v in values]
        for key, val in zip(
            [f"{self.ch_prefix}KP", f"{self.ch_prefix}KI", f"{self.ch_prefix}KD"],
            rounded_values,
        ):
            if not self._tec._set_fallback(f"{key}={val}"):
                raise ValueError(f"Failed to set {key} = {val}")

    def autopid(self) -> None:
        """Trigger automatic tuning of PID parameters."""
        self._tec._set(f"{self.ch_prefix}AUTOPID=1")

    ########################################
    #  SECTION 3.2 SENSOR & PROTECTIONS    #
    ########################################

    @property
    def sensor_model(self) -> SensorModel:
        """Gets temperature sensor calculation model (spec section 3.2.3)."""
        return SensorModel(self._tec._get(f"{self.ch_prefix}POLYOMIAL"))

    @sensor_model.setter
    def sensor_model(self, value: Union[int, SensorModel]):
        """Sets temperature sensor calculation model."""
        if not self._tec._set_fallback(f"{self.ch_prefix}POLYOMIAL={int(value)}"):
            raise ValueError(f"Failed to set sensor_model = {value}")

    @property
    def b_value(self) -> float:
        """Gets NTC thermistor B value (spec section 3.2.4)."""
        return self._tec._get(f"{self.ch_prefix}BX") / 100.0

    @b_value.setter
    def b_value(self, value: float):
        """Sets NTC thermistor B value (e.g. 3950.0)."""
        val = int(round(value * 100.0))
        if not self._tec._set_fallback(f"{self.ch_prefix}BX={val}"):
            raise ValueError(f"Failed to set NTC B value = {value}")

    @property
    def r0(self) -> float:
        """Gets NTC thermistor R0 (25°C) in kΩ (spec section 3.2.5)."""
        return self._tec._get(f"{self.ch_prefix}RP") / 1000.0

    @r0.setter
    def r0(self, value_kohm: float):
        """Sets NTC thermistor R0 (25°C) in kΩ (e.g. 10.0 for 10k)."""
        val = int(round(value_kohm * 1000.0))
        if not self._tec._set_fallback(f"{self.ch_prefix}RP={val}"):
            raise ValueError(f"Failed to set NTC R0 = {value_kohm}")

    @property
    def overtemp_high(self) -> float:
        """Gets sensor over-temperature upper cutoff threshold [°C] (spec section 3.2.17)."""
        return float(_round(self._tec._get(f"{self.ch_prefix}OVERTEMPUP"), -5))

    @overtemp_high.setter
    def overtemp_high(self, temp_deg: float):
        """Sets sensor over-temperature upper cutoff threshold [°C]."""
        val = _round(temp_deg, 5)
        if not self._tec._set_fallback(f"{self.ch_prefix}OVERTEMPUP={val}"):
            raise ValueError(f"Failed to set overtemp_high = {temp_deg}")

    @property
    def overtemp_low(self) -> float:
        """Gets sensor over-temperature lower cutoff threshold [°C] (spec section 3.2.18)."""
        return float(_round(self._tec._get(f"{self.ch_prefix}OVERTEMPLOWER"), -5))

    @overtemp_low.setter
    def overtemp_low(self, temp_deg: float):
        """Sets sensor over-temperature lower cutoff threshold [°C]."""
        val = _round(temp_deg, 5)
        if not self._tec._set_fallback(f"{self.ch_prefix}OVERTEMPLOWER={val}"):
            raise ValueError(f"Failed to set overtemp_low = {temp_deg}")

    @property
    def sensor_protection(self) -> bool:
        """Check if open/short circuit output protection is active (spec section 3.2.19)."""
        return self._tec._get(f"{self.ch_prefix}ONSENSOR") == 1

    @sensor_protection.setter
    def sensor_protection(self, enabled: bool):
        """Enable or disable open/short circuit protection."""
        val = 1 if enabled else 0
        if not self._tec._set_fallback(f"{self.ch_prefix}ONSENSOR={val}"):
            raise ValueError(f"Failed to set sensor_protection = {enabled}")

    @property
    def power_mode(self) -> PowerMode:
        """Gets power-on output mode (spec section 3.2.20)."""
        return PowerMode(self._tec._get(f"{self.ch_prefix}POWERMODE"))

    @power_mode.setter
    def power_mode(self, mode: Union[int, PowerMode]):
        """Sets power-on output mode."""
        if not self._tec._set_fallback(f"{self.ch_prefix}POWERMODE={int(mode)}"):
            raise ValueError(f"Failed to set power_mode = {mode}")

    def monitor(
        self,
        interval: float = 1.0,
        duration: Optional[float] = None,
        callback: Optional[Callable[[float], None]] = None,
    ) -> None:
        """Monitor this channel's temperature continuously."""
        print(f"Monitoring CH{self.channel}... Press Ctrl-C to stop monitoring...")
        start_time = time.time()
        try:
            while True:
                now_str = dt.datetime.now().strftime("%H:%M:%S")
                current_temp = self.temp
                print(f"{now_str}  CH{self.channel}: {current_temp:.4f}°C")
                if callback is not None:
                    callback(current_temp)

                if duration is not None and (time.time() - start_time) >= duration:
                    break

                time.sleep(interval)
        except KeyboardInterrupt:
            print(end="\r")


    def wait_for_temperature(
        self,
        target: Optional[float] = None,
        tolerance: float = 0.05,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> bool:
        """Wait until measured temperature stabilizes near target within tolerance."""
        if target is None:
            target = self.settemp
        deadline = time.time() + timeout
        while time.time() < deadline:
            current = self.temp
            if abs(current - target) <= tolerance:
                return True
            time.sleep(poll_interval)
        return False

    def status(self) -> dict[str, Any]:
        """Return a dictionary snapshot of this channel's state."""
        return {
            "channel": self.channel,
            "active": self.is_active,
            "temp": self.temp,
            "settemp": self.settemp,
            "resistance": self.resistance,
            "slope": self.slope,
            "current": self.current,
            "current_limit": self.current_limit,
            "voltage_limit": self.voltage_limit,
            "polarity": self.polarity,
            "mode": self.mode,
            "pwm_duty": self.pwm_duty,
            "pid": self.pid,
            "sensor_model": self.sensor_model.name,
            "b_value": self.b_value,
            "r0": self.r0,
            "overtemp_high": self.overtemp_high,
            "overtemp_low": self.overtemp_low,
        }


class TEC:
    """Controller for SenseFuture (光测未来) TEC devices.

    Supports both single-channel and dual-channel hardware configurations,
    with comprehensive access to temperature control, sensor parameters,
    batch diagnostic queries, and alarms.

    Examples:
        >>> from qtools.tec import TEC
        >>> device = TEC(is_mock=True)

        # Access default channel (TC1)
        >>> device.on()
        >>> device.temp = 25.0
        >>> print(device.temp)

        # Access both channels independently
        >>> device.tc1.temp = 20.0
        >>> device.tc2.temp = 35.0
        >>> print(device.tc1.resistance, device.tc2.resistance)

        # Batch queries
        >>> fast_data = device.demand_data(mode=1)
        >>> print(fast_data)
    """

    def __init__(
        self,
        device: str = "",
        logfile: Optional[str] = "tec.log",
        channel: int = 1,
        baudrate: int = 38400,
        timeout: float = 0.5,
        is_mock: bool = False,
        transport: Optional[BaseTransport] = None,
    ):
        """Initialize the TEC controller.

        Args:
            device: Serial port path (e.g. '/dev/ttyUSB0' or 'COM3').
            logfile: Path to log file for recording temperature data, or None.
            channel: Default active channel (1 or 2). Default: 1.
            baudrate: Baudrate (default: 38400).
            timeout: Communication timeout in seconds (default: 0.5).
            is_mock: If True, uses in-memory mock transport for testing.
            transport: Custom transport instance.
        """
        self._channel = channel
        self.logfile = logfile if logfile else None
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_mock = is_mock

        if transport is not None:
            self._transport: BaseTransport = transport
            self.device = getattr(transport, "port", "custom")
        elif is_mock:
            self._transport = MockSerialTransport()
            self.device = self._transport.port
        else:
            if not device:
                device = find_serial_device()
            self.device = device
            self._transport = SerialTransport(
                port=device,
                baudrate=baudrate,
                timeout=timeout,
            )

        # Channel proxies
        self._ch_views = {
            1: TECChannel(self, 1),
            2: TECChannel(self, 2),
        }

    @property
    def channel(self) -> int:
        """Active default channel index (1 or 2)."""
        return self._channel

    @channel.setter
    def channel(self, ch: int):
        """Switch active default channel."""
        if ch not in (1, 2):
            raise ValueError(f"Invalid channel {ch}; must be 1 or 2.")
        self._channel = ch

    @property
    def tc1(self) -> TECChannel:
        """Channel 1 controller interface."""
        return self._ch_views[1]

    @property
    def tc2(self) -> TECChannel:
        """Channel 2 controller interface."""
        return self._ch_views[2]

    @property
    def _active_ch(self) -> TECChannel:
        return self._ch_views[self._channel]

    @property
    def is_connected(self) -> bool:
        """Return True if connection to the device is currently open."""
        return self._transport is not None and self._transport.is_open

    def close(self) -> None:
        """Close connection to the device."""
        if self._transport is not None:
            self._transport.close()

    def disconnect(self) -> None:
        """Alias for close()."""
        self.close()

    def __enter__(self) -> "TEC":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"TEC(channel={self.channel}, device='{self.device}', connected={self.is_connected})"

    # -------------------------------------------------------------------------
    # Forward default channel methods & properties for backward compatibility
    # -------------------------------------------------------------------------

    def active(self) -> bool:
        return self._active_ch.active()

    @property
    def is_active(self) -> bool:
        return self._active_ch.is_active

    def on(self) -> None:
        self._active_ch.on()

    def off(self) -> None:
        self._active_ch.off()

    @property
    def settemp(self) -> float:
        return self._active_ch.settemp

    @settemp.setter
    def settemp(self, value: float):
        self._active_ch.settemp = value

    @property
    def target_temp(self) -> float:
        return self._active_ch.target_temp

    @target_temp.setter
    def target_temp(self, value: float):
        self._active_ch.target_temp = value

    @property
    def temp(self) -> float:
        return self._active_ch.temp

    @temp.setter
    def temp(self, value: float):
        self._active_ch.temp = value

    @property
    def actual_temp(self) -> float:
        return self._active_ch.actual_temp

    @property
    def slope(self) -> float:
        return self._active_ch.slope

    @slope.setter
    def slope(self, value: float):
        self._active_ch.slope = value

    @property
    def resistance(self) -> float:
        return self._active_ch.resistance

    @property
    def resistance_kohm(self) -> float:
        return self._active_ch.resistance_kohm

    @property
    def current(self) -> float:
        return self._active_ch.current

    @property
    def current_limit(self) -> float:
        return self._active_ch.current_limit

    @current_limit.setter
    def current_limit(self, value: float):
        self._active_ch.current_limit = value

    @property
    def voltage_limit(self) -> int:
        return self._active_ch.voltage_limit

    @voltage_limit.setter
    def voltage_limit(self, value: int):
        self._active_ch.voltage_limit = value

    @property
    def polarity(self) -> int:
        return self._active_ch.polarity

    @polarity.setter
    def polarity(self, value: Union[int, TECPolarity]):
        self._active_ch.polarity = value

    @property
    def mode(self) -> int:
        return self._active_ch.mode

    @mode.setter
    def mode(self, value: Union[int, TECMode]):
        self._active_ch.mode = value

    @property
    def pwm_duty(self) -> float:
        return self._active_ch.pwm_duty

    @pwm_duty.setter
    def pwm_duty(self, percent: float):
        self._active_ch.pwm_duty = percent

    @property
    def pid(self) -> Tuple[float, float, float]:
        return self._active_ch.pid

    @pid.setter
    def pid(self, values: Tuple[float, float, float] | list[float]):
        self._active_ch.pid = values

    def autopid(self) -> None:
        self._active_ch.autopid()

    def monitor(
        self,
        interval: float = 1.0,
        duration: Optional[float] = None,
        callback: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._active_ch.monitor(interval=interval, duration=duration, callback=callback)

    def wait_for_temperature(
        self,
        target: Optional[float] = None,
        tolerance: float = 0.05,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> bool:
        return self._active_ch.wait_for_temperature(
            target=target, tolerance=tolerance, timeout=timeout, poll_interval=poll_interval
        )

    # -------------------------------------------------------------------------
    # Section 3.5 System Parameters & Diagnostics
    # -------------------------------------------------------------------------

    @property
    def model(self) -> str:
        """Return device model identifier (e.g. 'RD105' or raw code)."""
        return self._get_command("TEC").partition("=")[-1]

    @property
    def model_name(self) -> str:
        """Return human-readable model name looked up from protocol code (spec 3.5.1)."""
        raw = self.model
        try:
            code = int(raw)
            return TEC_MODEL_MAP.get(code, f"Model_{code}")
        except ValueError:
            return raw

    @property
    def firmware_version(self) -> str:
        """Return firmware version string (spec 3.5.2, e.g. '1.0.0')."""
        val = self._get("FPV")
        major = val // 100
        minor = (val % 100) // 10
        patch = val % 10
        return f"{major}.{minor}.{patch}"

    @property
    def interior_temp(self) -> int:
        """Return internal controller board temperature in °C (spec 3.5.6)."""
        return self._get("SINTERIORTEMP")

    @property
    def interior_overtemp_limit(self) -> int:
        """Gets internal over-temperature threshold in °C (spec 3.5.7)."""
        return self._get("OVERTVPT")

    @interior_overtemp_limit.setter
    def interior_overtemp_limit(self, deg_c: int):
        """Sets internal over-temperature power-reduction threshold [40~100 °C]."""
        if not (40 <= deg_c <= 100):
            raise ValueError(f"interior_overtemp_limit must be in range 40~100 °C, got {deg_c}")
        if not self._set_fallback(f"OVERTVPT={int(deg_c)}"):
            raise ValueError(f"Failed to set interior_overtemp_limit = {deg_c}")

    @property
    def error_code(self) -> int:
        """Return 16-bit status/error word from device (spec 3.5.8)."""
        return self._get("ERRORCODE")

    @property
    def errors(self) -> list[str]:
        """Return human-readable descriptions of any active alarms/errors."""
        code = self.error_code
        errs = []
        for bit, msg in ERROR_BIT_MAP.items():
            if code & (1 << bit):
                errs.append(msg)
        return errs

    def reset_factory_defaults(self) -> None:
        """Reset TEC controller to factory default settings (spec section 3.5.9)."""
        self._set("RESET=1")

    # -------------------------------------------------------------------------
    # Section 3.6 Batch Data Queries
    # -------------------------------------------------------------------------

    def inquire(self) -> dict[str, Any]:
        """Query comprehensive device configuration (spec section 3.6.1: INQUIRE=1@)."""
        raw = self.rw("INQUIRE=1")
        tokens = raw.replace("OK", "").split("@")
        info: dict[str, Any] = {}
        for token in tokens:
            token = token.strip()
            if not token or "=" not in token:
                continue
            k, _, v = token.partition("=")
            info[k] = v
        return info

    def demand_data(self, mode: int = 1) -> dict[str, Any]:
        """Query key operational data in a single batch transaction (spec section 3.6.2).

        Args:
            mode: 1 for temperature, resistance & PWM; 2 for actual output voltage.

        Returns:
            Dictionary with parsed data for Channel 1, Channel 2, and interior temp.
        """
        raw = self.rw(f"DATADEMAND={mode}")
        tokens = raw.replace("OK", "").split("@")
        parsed: dict[str, str] = {}
        for token in tokens:
            token = token.strip()
            if not token or "=" not in token:
                continue
            k, _, v = token.partition("=")
            parsed[k] = v

        def _parse_temp(val_str: Optional[str]) -> Optional[float]:
            if not val_str:
                return None
            val = int(val_str)
            return None if val >= 999999999 else val / 100000.0

        def _parse_res(val_str: Optional[str]) -> Optional[float]:
            if not val_str:
                return None
            val = int(val_str)
            return None if val == 0 else round(val / 1e6, 6)

        return {
            "ch1": {
                "temp": _parse_temp(parsed.get("TC1:TCADJTEMP")),
                "resistance": _parse_res(parsed.get("TC1:RESISTOR")),
                "pwm": float(parsed.get("TC1:PWM", 0)) if "TC1:PWM" in parsed else None,
                "voltage": (float(parsed.get("TC1:OUTV", 0)) / 1e8) if "TC1:OUTV" in parsed else None,
            },
            "ch2": {
                "temp": _parse_temp(parsed.get("TC2:TCADJTEMP")),
                "resistance": _parse_res(parsed.get("TC2:RESISTOR")),
                "pwm": float(parsed.get("TC2:PWM", 0)) if "TC2:PWM" in parsed else None,
                "voltage": (float(parsed.get("TC2:OUTV", 0)) / 1e8) if "TC2:OUTV" in parsed else None,
            },
            "interior_temp": int(parsed.get("SINTERIORTEMP", 0)) if "SINTERIORTEMP" in parsed else None,
        }

    def status(self) -> dict[str, Any]:
        """Return a dictionary snapshot of current device state."""
        return {
            "channel": self.channel,
            "device": self.device,
            "model": self.model,
            "model_name": self.model_name,
            "firmware_version": self.firmware_version,
            "interior_temp": self.interior_temp,
            "interior_overtemp_limit": self.interior_overtemp_limit,
            "error_code": self.error_code,
            "errors": self.errors,
            "active": self.is_active,
            "temp": self.temp,
            "settemp": self.settemp,
            "resistance": self.resistance,
            "slope": self.slope,
            "current": self.current,
            "current_limit": self.current_limit,
            "voltage_limit": self.voltage_limit,
            "polarity": self.polarity,
            "mode": self.mode,
            "pid": self.pid,
        }

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    def w(self, command: str) -> None:
        """Send command to TEC device."""
        self._transport.write(command)

    def r(self) -> str:
        """Read raw response from TEC device."""
        return self._transport.read()

    def rw(self, command: str) -> str:
        """Write command and read response."""
        return self._transport.rw(command)

    def _log(self, *tokens: Any) -> None:
        if not self.logfile:
            return
        now = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        line = "\t".join(map(str, [now, *tokens])) + "\n"
        try:
            with open(self.logfile, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            logger.warning("Failed writing to logfile '%s': %s", self.logfile, e)

    def _set_fallback(self, command: str, fallback: Union[str, bool] = True) -> bool:
        """Sets parameter, with fallback in case of failed writes."""
        if fallback is True:
            try:
                fallback = self._get_command(command)
            except Exception as e:
                logger.debug("Failed pre-query fallback for '%s': %s", command, e)
                fallback = False
        try:
            self._set(command)
            return True
        except Exception:
            if fallback is not False and isinstance(fallback, str):
                try:
                    self._set(fallback)
                except Exception as restore_err:
                    logger.error("Failed to restore fallback '%s': %s", fallback, restore_err)
            return False

    def _get_command(self, command: str) -> str:
        """Query stored value, returns set command."""
        if "=" not in command:
            cmd = f"{command}=?"
        elif "=?" not in command:
            base, *_ = command.partition("=")
            cmd = f"{base}=?"
        else:
            cmd = command
        return self._query(cmd)

    def _get(self, command: str) -> int:
        """Extract integer value from query command."""
        result = self._get_command(command)
        *_, value = result.partition("=")
        return int(value)

    def _set(self, command: str) -> None:
        """Assert correct write response."""
        response = self._query(command)
        if response != command:
            raise TECProtocolError(
                f"Device failed write: expected '{command}', got '{response}'"
            )

    def _query(self, command: str) -> str:
        """Send command and parse 'OK<response>@' frame."""
        result = self.rw(command)
        if not result.startswith("OK") or not result.endswith("@"):
            raise TECProtocolError(f"Device returned failure: '{result}'")
        return result[2:-1]


# Canonical alias for clarity
SenseFutureTEC = TEC
