"""MotorBackend-compatible adapter for the Thorlabs KDC101."""

from __future__ import annotations

import logging
import time
from typing import Any

from qtools.motor.backends.motor import register_backend

logger = logging.getLogger(__name__)


@register_backend("kdc101")
class KDC101Backend:
    """DC-servo rotation-stage backend using the Kinesis C API.

    Parameters
    ----------
    port:
        KDC101 serial number. Despite the generic MotorBackend parameter
        name, Kinesis addresses KDC101 devices by serial number rather than
        COM port.
    stage_settings:
        Optional Kinesis stage settings name, for example ``"PRM1-Z8"``.
        When supplied it is loaded with ``CC_LoadNamedSettings``.
    steps_per_rev, gearbox_ratio, pitch:
        Optional explicit motor parameters. If supplied, ``steps_per_rev`` is
        required. These are applied with ``CC_SetMotorParamsExt``.
    travel_mode:
        Kinesis travel mode. Only ``"rotational"``/``2`` is accepted because
        the shared motor API expresses positions in degrees.
    """

    @staticmethod
    def list_devices() -> list[tuple[str, str]]:
        from qtools.motor.backends.kdc101.kdc101 import list_devices as kdc_list

        return kdc_list()

    def __init__(
        self,
        port: str = "",
        blocking: bool = True,
        config_mgr: Any = None,
        *,
        stage_settings: str | None = None,
        steps_per_rev: float | None = None,
        gearbox_ratio: float | None = None,
        pitch: float | None = None,
        travel_mode: str | int | None = None,
        load_settings: bool = True,
        move_timeout: float = 120.0,
    ) -> None:
        self.port = str(port or "")
        self.blocking = blocking
        self._config_mgr = config_mgr
        self._stage_settings = stage_settings
        self._steps_per_rev = steps_per_rev
        self._gearbox_ratio = gearbox_ratio
        self._pitch = pitch
        self._travel_mode = travel_mode
        self._load_settings = load_settings
        self._move_timeout = move_timeout
        self._motor: Any = None
        self._model = ""
        self._serial_no = self.port
        self.zero_offset = 0.0

    @property
    def is_connected(self) -> bool:
        return bool(self._motor is not None and self._motor.is_connected)

    @property
    def serial(self) -> str:
        return str(self._serial_no)

    def connect(self) -> bool:
        try:
            serial = self.port
            if not serial:
                devices = self.list_devices()
                if len(devices) != 1:
                    raise RuntimeError(
                        "KDC101 serial number is required; "
                        f"found {len(devices)} connected controller(s)."
                    )
                serial = devices[0][0]

            from qtools.motor.backends.kdc101.kdc101 import ThorlabsKDC101

            self._motor = ThorlabsKDC101(
                serial,
                blocking=self.blocking,
                move_timeout=self._move_timeout,
            )
            self._motor.connect()
            self._model, self._serial_no = self._motor.identity()
            if "KDC101" not in self._model.upper():
                raise RuntimeError(
                    f"Expected a KDC101 controller, but device {serial} reports "
                    f"model '{self._model}'."
                )

            entry = self._get_config_entry()
            self._configure_stage(entry)
            if not self._motor.is_rotational:
                mode = self._motor.get_travel_mode()
                raise RuntimeError(
                    f"KDC101 {serial} is not configured as a rotational stage "
                    f"(travel mode={mode}). Configure a rotational stage in "
                    "Kinesis or pass stage_settings/steps_per_rev explicitly."
                )

            self.zero_offset = float((entry or {}).get("zero_offset", 0.0) or 0.0)
            logger.info(
                "Connected to KDC101: model=%s, serial=%s, zero_offset=%s deg",
                self._model,
                self._serial_no,
                self.zero_offset,
            )
            return True
        except Exception as exc:
            logger.error("Failed to connect to KDC101: %s", exc)
            if self._motor is not None:
                try:
                    self._motor.close()
                except Exception:
                    pass
            self._motor = None
            return False

    def _get_config_entry(self) -> dict[str, Any] | None:
        try:
            from qtools.motor.config import MotorConfigManager

            mgr = self._config_mgr or MotorConfigManager.resolve()
            return mgr.get_device(str(self._serial_no))
        except Exception as exc:
            logger.warning("Could not load KDC101 configuration: %s", exc)
            return None

    def _configure_stage(self, entry: dict[str, Any] | None) -> None:
        if self._motor is None:
            raise RuntimeError("KDC101 is not connected.")
        entry = entry or {}

        if self._load_settings:
            try:
                self._motor.load_settings()
            except Exception as exc:
                logger.debug("Could not load persisted KDC101 settings: %s", exc)

        settings_name = self._stage_settings or entry.get("stage_settings")
        if settings_name:
            if not self._motor.load_named_settings(str(settings_name)):
                raise RuntimeError(
                    f"Kinesis stage settings '{settings_name}' could not be loaded."
                )

        steps_per_rev = (
            self._steps_per_rev
            if self._steps_per_rev is not None
            else entry.get("steps_per_rev")
        )
        if steps_per_rev is not None:
            gearbox = (
                self._gearbox_ratio
                if self._gearbox_ratio is not None
                else entry.get("gearbox_ratio", 1.0)
            )
            pitch = (
                self._pitch
                if self._pitch is not None
                else entry.get("pitch", 1.0)
            )
            self._motor.set_motor_params(
                float(steps_per_rev),
                float(gearbox),
                float(pitch),
            )

        mode = (
            self._travel_mode
            if self._travel_mode is not None
            else entry.get("travel_mode")
        )
        if mode is not None:
            self._motor.set_travel_mode(self._normalize_travel_mode(mode))

        try:
            self._motor.request_settings()
            time.sleep(0.1)
        except Exception:
            pass

    @staticmethod
    def _normalize_travel_mode(mode: str | int) -> int:
        if isinstance(mode, str):
            normalized = mode.strip().lower()
            if normalized in ("rotational", "rotation", "degrees", "degree"):
                return 0x02
            if normalized.isdigit():
                mode = int(normalized)
            else:
                raise ValueError("KDC101 travel_mode must be 'rotational' or 2.")
        if int(mode) != 0x02:
            raise ValueError(
                "KDC101 backend supports rotational stages only "
                "(travel_mode=2)."
            )
        return 0x02

    def disconnect(self) -> None:
        if self._motor is not None:
            try:
                self._motor.close()
            except Exception as exc:
                logger.error("Error closing KDC101: %s", exc)
            finally:
                self._motor = None

    def _require_connected(self) -> None:
        if self._motor is None:
            raise RuntimeError("KDC101 is not connected. Call connect() first.")

    def get_position(self) -> float:
        self._require_connected()
        return (self._motor.get_position() - self.zero_offset) % 360.0

    def move_to(self, position: float) -> None:
        self._require_connected()
        raw_target = (float(position) + self.zero_offset) % 360.0
        self._motor.move_to(raw_target)

    def move_by(self, displacement: float) -> None:
        self._require_connected()
        self._motor.move_by(float(displacement))

    def home(self) -> None:
        self._require_connected()
        self._motor.home()

    def zero(self) -> None:
        self.move_to(0.0)

    def wait_move(self) -> None:
        self._require_connected()
        self._motor.wait_move()

    def stop(self) -> None:
        self._require_connected()
        self._motor.stop()

    def set_zero_offset(self, offset_deg: float | None = None) -> None:
        self._require_connected()
        if offset_deg is None:
            self.zero_offset = self._motor.get_position()
        else:
            self.zero_offset = float(offset_deg) % 360.0

        try:
            from qtools.motor.config import MotorConfigManager

            mgr = self._config_mgr or MotorConfigManager.resolve()
            serial_str = str(self._serial_no)
            fields = {
                "serial": serial_str,
                "zero_offset": self.zero_offset,
                "backend": "kdc101",
            }
            if self._stage_settings:
                fields["stage_settings"] = self._stage_settings
            if self._steps_per_rev is not None:
                fields["steps_per_rev"] = self._steps_per_rev
            if self._gearbox_ratio is not None:
                fields["gearbox_ratio"] = self._gearbox_ratio
            if self._pitch is not None:
                fields["pitch"] = self._pitch
            mgr.upsert_device(key=serial_str, **fields)
            mgr.save()
        except Exception as exc:
            logger.error("Failed to save KDC101 configuration: %s", exc)

    def get_velocity(self) -> float:
        self._require_connected()
        return self._motor.get_velocity()

    def set_velocity(self, speed_deg_s: float) -> None:
        self._require_connected()
        self._motor.set_velocity(float(speed_deg_s))

    def identify(self) -> None:
        self._require_connected()
        self._motor.identify()

    def get_stage_name(self) -> str:
        if self._motor is None:
            return f"KDC101 (serial={self.port or 'auto'})"
        return f"KDC101 {self._model} (serial={self._serial_no})"
