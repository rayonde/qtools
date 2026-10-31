from __future__ import annotations

import types

import numpy as np
import pytest

from qtools.camera import DAHENG, Camera, CameraDiscoveryError, get_backend
from qtools.camera import _gxipy as gxipy_module
from qtools.camera._gxipy import GalaxyFeatureControl, discover_devices


ROWS = [
    {
        "sn": "DAHENG-001",
        "display_name": "Daheng MER2-502-79U3M",
        "model_name": "MER2-502-79U3M",
        "vendor_name": "Daheng Imaging",
        "device_id": "device-001",
        "user_id": "",
        "device_class": 3,
        "ip": "",
        "mac": "",
        "nic_description": "USB controller",
    },
    {
        "sn": "DAHENG-002",
        "display_name": "Daheng MER2-1220-32U3C",
        "model_name": "MER2-1220-32U3C",
        "vendor_name": "Daheng Imaging",
        "device_id": "device-002",
        "user_id": "cam-right",
        "device_class": 2,
        "ip": "192.168.1.20",
        "mac": "00:11:22:33:44:55",
        "nic_description": "Ethernet",
    },
]


class FakeEnumFeature:
    def __init__(self, symbol: str, values: dict[str, int]) -> None:
        self.symbol = symbol
        self.values = values

    def get(self) -> tuple[int, str]:
        return self.values[self.symbol], self.symbol

    def get_range(self) -> dict[str, int]:
        return dict(self.values)

    def set(self, value: int) -> None:
        for symbol, candidate in self.values.items():
            if candidate == value:
                self.symbol = symbol
                return
        raise ValueError(value)


class FakeFloatFeature:
    def __init__(self, value: float, minimum: float, maximum: float) -> None:
        self.value = value
        self.minimum = minimum
        self.maximum = maximum

    def get(self) -> float:
        return self.value

    def get_range(self) -> dict[str, float]:
        return {"min": self.minimum, "max": self.maximum, "inc": 0.0}

    def set(self, value: float) -> None:
        if not self.minimum <= value <= self.maximum:
            raise ValueError(value)
        self.value = float(value)


class FakeIntFeature:
    def __init__(self, value: int) -> None:
        self.value = value

    def get(self) -> int:
        return self.value


class FakeRemote:
    def __init__(self) -> None:
        self.enums = {
            "TriggerMode": FakeEnumFeature("Off", {"Off": 0, "On": 1}),
            "ExposureAuto": FakeEnumFeature("Off", {"Off": 0, "Continuous": 1}),
            "GainAuto": FakeEnumFeature("Off", {"Off": 0, "Continuous": 1}),
            "PixelFormat": FakeEnumFeature("Mono8", {"Mono8": 1, "Mono16": 2}),
        }
        self.floats = {
            "ExposureTime": FakeFloatFeature(10_000.0, 100.0, 1_000_000.0),
            "Gain": FakeFloatFeature(0.0, 0.0, 24.0),
        }
        self.ints = {"Width": FakeIntFeature(4), "Height": FakeIntFeature(2)}

    def get_enum_feature(self, name: str) -> FakeEnumFeature:
        return self.enums[name]

    def get_float_feature(self, name: str) -> FakeFloatFeature:
        return self.floats[name]

    def get_int_feature(self, name: str) -> FakeIntFeature:
        return self.ints[name]


class FakeRawImage:
    def __init__(self) -> None:
        self.values = np.arange(8, dtype=np.uint8).reshape(2, 4)

    def get_numpy_array(self) -> np.ndarray:
        return self.values


class FakeDataStream:
    def __init__(self) -> None:
        self.timeout = None

    def get_image(self, timeout: int) -> FakeRawImage:
        self.timeout = timeout
        return FakeRawImage()


class FakeCamera:
    def __init__(self) -> None:
        self.remote = FakeRemote()
        self.data_stream = [FakeDataStream()]
        self.streaming = False
        self.closed = False

    def get_remote_device_feature_control(self) -> FakeRemote:
        return self.remote

    def stream_on(self) -> None:
        self.streaming = True

    def stream_off(self) -> None:
        self.streaming = False

    def close_device(self) -> None:
        self.closed = True


class FakeManager:
    def __init__(self) -> None:
        self.camera = FakeCamera()

    def update_all_device_list(self, timeout: int = 200) -> tuple[int, list[dict[str, object]]]:
        del timeout
        return len(ROWS), [dict(row) for row in ROWS]

    def open_device_by_index(self, index: int) -> FakeCamera:
        if index not in (1, 2):
            raise ValueError(index)
        return self.camera


class FakeGxipy(types.SimpleNamespace):
    def __init__(self) -> None:
        super().__init__(
            DeviceManager=FakeManager,
            GxDeviceClassList=types.SimpleNamespace(USB2=1, GEV=2, U3V=3),
        )


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> FakeGxipy:
    fake = FakeGxipy()
    monkeypatch.setattr(gxipy_module, "_GXIPY_MODULE", fake)
    return fake


def test_gxipy_wrapper_normalizes_official_device_rows(
    fake_sdk: FakeGxipy,
) -> None:
    devices = discover_devices()

    assert [device.serial for device in devices] == ["DAHENG-001", "DAHENG-002"]
    assert devices[0].interface_type == "USB3 Vision"
    assert devices[0].port == "Daheng MER2-502-79U3M"
    assert devices[1].as_camera_info().port == "192.168.1.20"
    assert devices[1].raw["mac"] == "00:11:22:33:44:55"


def test_gxipy_wrapper_uses_symbolic_enum_values() -> None:
    remote = FakeRemote()
    features = GalaxyFeatureControl(remote)

    assert features.enum_symbol("PixelFormat") == "Mono8"
    features.set_enum_symbol("PixelFormat", "mono16")
    assert features.enum_symbol("PixelFormat") == "Mono16"


def test_daheng_is_registered() -> None:
    assert get_backend("daheng") is DAHENG


def test_daheng_discovery(fake_sdk: FakeGxipy, capsys: pytest.CaptureFixture[str]) -> None:
    cameras = DAHENG.discover()

    assert [camera.serial for camera in cameras] == ["DAHENG-001", "DAHENG-002"]
    assert cameras[0].interface_type == "USB3 Vision"
    assert cameras[1].port == "192.168.1.20"
    output = capsys.readouterr().out
    assert "[1]" in output
    assert "SN=DAHENG-001" in output


def test_daheng_facade_controls_and_capture(fake_sdk: FakeGxipy) -> None:
    with Camera(backend="daheng", target=2) as camera:
        backend = camera.backend
        sdk_camera = backend._camera._handle
        assert isinstance(backend, DAHENG)
        assert backend.name == "DAHENG-002"
        assert backend.model == "MER2-1220-32U3C"
        assert camera.shape == (2, 4)
        assert camera.format == "Mono8"
        assert camera.bitdepth == 8
        assert camera.exposure_s == pytest.approx(0.01)
        assert camera.gain == pytest.approx(0.0)

        assert camera.set_exposure(0.02) == pytest.approx(0.02)
        assert sdk_camera.remote.floats["ExposureTime"].value == pytest.approx(
            20_000.0
        )
        assert camera.set_gain(6.0) == pytest.approx(6.0)

        camera.auto_exposure = True
        camera.auto_gain = True
        assert camera.auto_exposure is True
        assert camera.auto_gain is True

        image = camera.capture(timeout=0.25)
        np.testing.assert_array_equal(image, np.arange(8, dtype=np.uint8).reshape(2, 4))
        assert sdk_camera.data_stream[0].timeout == 250
        assert image.info["backend"] == "daheng"

    assert sdk_camera.closed is True
    assert sdk_camera.streaming is False


def test_daheng_selects_by_user_id(fake_sdk: FakeGxipy) -> None:
    with Camera(backend="daheng", target="cam-right") as camera:
        assert camera.backend.serial == "DAHENG-002"


def test_daheng_requires_explicit_target_when_multiple(
    fake_sdk: FakeGxipy,
) -> None:
    with pytest.raises(CameraDiscoveryError, match="Multiple Daheng cameras"):
        DAHENG()
