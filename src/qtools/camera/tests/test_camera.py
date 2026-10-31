from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from qtools.camera import (
    Camera,
    CameraBackend,
    CameraDependencyError,
    CameraDiscoveryError,
    FLIR,
    list_camera,
    register_backend,
)
import qtools.camera._spinnaker_c as spinnaker_c_module
from qtools.camera.base import CameraInfo
from qtools.camera import camera as camera_module
from qtools.camera.backends import flir as flir_module


class FakeNode:
    def __init__(self, value, minimum=0, maximum=1_000_000, increment=1):
        self.value = value
        self.writes = []
        self.minimum = minimum
        self.maximum = maximum
        self.increment = increment
        self.executions = 0

    def GetAccessMode(self):
        return 1

    def SetValue(self, value):
        self.writes.append(value)
        self.value = value

    def GetValue(self):
        return self.value

    def GetMin(self):
        return self.minimum

    def GetMax(self):
        return self.maximum

    def GetInc(self):
        return self.increment

    def ToString(self):
        return str(self.value)

    def Execute(self):
        self.executions += 1


class FakeNodeMap:
    def __init__(self, nodes):
        self.nodes = nodes

    def GetNode(self, name):
        return self.nodes[name]


class FakeFrame:
    def __init__(self):
        self.released = False

    def IsIncomplete(self):
        return False

    def GetImageStatus(self):
        return 0

    def GetNDArray(self):
        return np.array([[0x1230, 0xFFF0]], dtype=np.uint16)

    def Release(self):
        self.released = True


class FakeCamera:
    def __init__(self, serial="123", model="Blackfly S"):
        self.serial = serial
        self.model = model
        self.streaming = False
        self.initialized = False
        self.ended = False
        self.deinitialized = False
        self.trigger_count = 0
        self.nodes = {
            "DeviceSerialNumber": FakeNode(serial),
            "DeviceModelName": FakeNode(model),
            "DeviceVendorName": FakeNode("FLIR"),
            "GainAuto": FakeNode(None),
            "Gain": FakeNode(0.0),
            "ExposureAuto": FakeNode(None),
            "ExposureMode": FakeNode(None),
            "BlackLevelSelector": FakeNode(None),
            "BlackLevel": FakeNode(0.0),
            "GammaEnable": FakeNode(True),
            "Gamma": FakeNode(1.0),
            "PixelFormat": FakeNode(None),
            "AdcBitDepth": FakeNode("Bit12"),
            "ExposureTime": FakeNode(1_000.0, minimum=100.0, maximum=1_000_000.0),
            "TriggerMode": FakeNode(None),
            "TriggerSource": FakeNode(None),
            "TriggerSelector": FakeNode(None),
            "TriggerSoftware": FakeNode(None),
            "AcquisitionFrameRateEnable": FakeNode(False),
            "AcquisitionFrameRate": FakeNode(30.0, maximum=120.0),
            "Width": FakeNode(2, maximum=2),
            "Height": FakeNode(1, maximum=1),
            "WidthMax": FakeNode(2),
            "HeightMax": FakeNode(1),
            "OffsetX": FakeNode(0, maximum=2),
            "OffsetY": FakeNode(0, maximum=1),
            "BinningHorizontal": FakeNode(1),
            "BinningVertical": FakeNode(1),
        }
        self.TLDeviceNodeMap = FakeNodeMap(self.nodes)
        for name, node in self.nodes.items():
            setattr(self, name, node)

    def GetTLDeviceNodeMap(self):
        return self.TLDeviceNodeMap

    def GetNodeMap(self):
        return FakeNodeMap(self.nodes)

    def Init(self):
        self.initialized = True

    def IsStreaming(self):
        return self.streaming

    def BeginAcquisition(self):
        self.streaming = True

    def EndAcquisition(self):
        self.streaming = False
        self.ended = True

    def DeInit(self):
        self.deinitialized = True

    def GetNextImage(self, timeout_ms):
        return FakeFrame()


class FakeCameraList:
    def __init__(self, cameras):
        self.cameras = cameras
        self.cleared = False

    def GetSize(self):
        return len(self.cameras)

    def GetByIndex(self, index):
        return self.cameras[index]

    def Clear(self):
        self.cleared = True


class FakeSystem:
    def __init__(self, camera_list):
        self.camera_list = camera_list
        self.released = False

    def GetCameras(self):
        return self.camera_list

    def ReleaseInstance(self):
        self.released = True


@pytest.fixture
def fake_pyspin(monkeypatch):
    camera = FakeCamera()
    camera_list = FakeCameraList([camera])
    system = FakeSystem(camera_list)
    module = types.SimpleNamespace(
        RW=1,
        TriggerMode_On="trigger-on",
        TriggerMode_Off="trigger-off",
        TriggerSource_Software="software",
        TriggerSelector_FrameStart="frame-start",
        GainAuto_Off="gain-off",
        ExposureAuto_Off="exposure-off",
        ExposureMode_Timed="timed",
        BlackLevelSelector_All="all",
        PixelFormat_Mono16="mono16",
        PixelFormat_Mono8="mono8",
        AdcBitDepth_Bit12="bit12",
        AdcBitDepth_Bit10="bit10",
        AdcBitDepth_Bit8="bit8",
        System=types.SimpleNamespace(GetInstance=lambda: system),
        CStringPtr=lambda node: node,
        CIntegerPtr=lambda node: node,
        CCategoryPtr=lambda node: node,
        CValuePtr=lambda node: node,
        IsReadable=lambda node: True,
        IsWritable=lambda node: True,
        intfICategory="category",
    )
    monkeypatch.setitem(sys.modules, "PySpin", module)
    FLIR._pyspin = None
    FLIR.sdk = None
    yield camera, system
    FLIR.close_sdk()
    FLIR._pyspin = None


def test_camera_imports_without_loading_pyspin():
    assert issubclass(FLIR, flir_module.CameraBackend)
    assert "PySpin" not in sys.modules


def test_missing_pyspin_has_actionable_error(monkeypatch):
    FLIR._pyspin = None

    def fail_import(name):
        if name == "PySpin":
            raise ImportError("missing fake SDK")
        raise AssertionError(name)

    monkeypatch.setattr(flir_module.importlib, "import_module", fail_import)
    with pytest.raises(CameraDependencyError, match="Spinnaker SDK"):
        FLIR()


def test_flir_discovery_initialization_and_12bit_capture(fake_pyspin):
    camera, system = fake_pyspin

    with FLIR(serial="123", pitch_um=3.45) as flir:
        assert flir.shape == (1, 2)
        assert flir.pitch_um == (3.45, 3.45)
        assert camera.TriggerMode.value == "trigger-on"
        assert camera.TriggerMode.writes == ["trigger-off", "trigger-on"]
        image = flir.capture()
        assert np.array_equal(image, np.array([[0x123, 0xFFF]], dtype=np.uint16))
        assert camera.TriggerSoftware.executions == 1
        assert flir.get_exposure() == pytest.approx(0.0001)
    assert camera.ended
    assert camera.deinitialized
    FLIR.close_sdk()
    assert system.released


def test_enum_setting_supports_genicam_node_map_style(fake_pyspin):
    class EnumEntry:
        def __init__(self, value):
            self.value = value

        def GetValue(self):
            return self.value

    class EnumerationNode:
        def __init__(self):
            self.value = None
            self.symbols = {"Software": 7}

        def GetAccessMode(self):
            return 1

        def GetEntryByName(self, name):
            return EnumEntry(self.symbols[name])

        def SetIntValue(self, value):
            self.value = value

    _, _ = fake_pyspin
    camera = EnumerationNode()
    flir = object.__new__(FLIR)
    flir._pyspin = sys.modules["PySpin"]
    assert flir._set_enum_value(camera, "Software", 0)
    assert camera.value == 7


def test_facade_delegates_and_saves_raw_data(tmp_path, fake_pyspin):
    path = tmp_path / "frame.npy"
    with Camera(backend="flir", serial="123") as camera:
        image = camera.save(path)
    assert np.array_equal(np.load(path), image)


def test_new_vendor_backend_can_be_registered_without_facade_changes():
    class DummyBackend(CameraBackend):
        backend_name = "dummy"

        @classmethod
        def discover(cls, verbose=True):
            return [CameraInfo(serial="dummy-1", model="TestCam", vendor="Test")]

        def __init__(self, **kwargs):
            self.closed = False

        @property
        def name(self):
            return "dummy-1"

        @property
        def model(self):
            return "TestCam"

        @property
        def shape(self):
            return (1, 1)

        def get_image(self, timeout_s=1.0):
            return np.array([[7]], dtype=np.uint8)

        def close(self):
            self.closed = True

    register_backend("dummy", DummyBackend)
    try:
        assert list_camera(backend="dummy") is None
        with Camera(backend="dummy") as camera:
            assert np.array_equal(camera.capture(), np.array([[7]], dtype=np.uint8))
    finally:
        camera_module._BACKEND_MODULES.pop("dummy", None)


def test_list_camera_does_not_provision_camera_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = CameraInfo(serial="camera-a", model="TestCam", vendor="Test", index=1)

    def fail_ensure(*args, **kwargs):
        raise AssertionError("list_camera must not provision the camera worker")

    monkeypatch.setattr(FLIR, "discover", classmethod(lambda cls, verbose=True: [info]))
    monkeypatch.setattr(FLIR, "ensure_bridge_python", classmethod(fail_ensure))

    assert list_camera() is None


def test_list_camera_prints_identity_and_connection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    info = CameraInfo(
        serial="camera-a",
        model="SameModel",
        vendor="FLIR",
        index=1,
        interface_type="USB3Vision",
        port="Port_#0001.Hub_#0002",
        interface_name="USB Host Controller",
    )
    def fake_discover(cls, verbose=True):
        if verbose:
            flir_module.print_camera_list([info])
        return [info]

    monkeypatch.setattr(FLIR, "discover", classmethod(fake_discover))

    assert list_camera() is None
    output = capsys.readouterr().out
    assert "[1]" in output
    assert "FLIR" in output
    assert "SameModel" in output
    assert "SN=camera-a" in output
    assert "USB3Vision port=Port_#0001.Hub_#0002" in output
    assert "adapter=" not in output
    assert "CameraInfo(" not in output


def test_flir_discover_does_not_import_pyspin(monkeypatch: pytest.MonkeyPatch) -> None:
    info = CameraInfo(serial="camera-a", model="TestCam", vendor="Test", index=1)
    monkeypatch.setattr(
        flir_module, "discover_spinnaker_cameras", lambda: [info]
    )

    def fail_import(name):
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(flir_module.importlib, "import_module", fail_import)

    assert FLIR.discover(verbose=False) == [info]


def test_formats_gige_ip_values() -> None:
    assert spinnaker_c_module._format_gige_ip("192.168.1.10") == "192.168.1.10"
    assert spinnaker_c_module._format_gige_ip("0xC0A8010A") == "192.168.1.10"
    assert spinnaker_c_module._format_gige_ip("3232235786") == "192.168.1.10"
    assert spinnaker_c_module._format_gige_ip("") == ""


def test_select_camera_by_number_serial_and_port() -> None:
    entries = [
        flir_module._CameraEntry(
            CameraInfo(
                serial="serial-a",
                model="SameModel",
                index=1,
                device_id="device-a",
                port="Port_#0001.Hub_#0002",
                interface_id="usb-controller-a",
            ),
            "handle-a",
        ),
        flir_module._CameraEntry(
            CameraInfo(
                serial="serial-b",
                model="SameModel",
                index=2,
                device_id="device-b",
                port="Port_#0003.Hub_#0004",
                interface_id="usb-controller-b",
            ),
            "handle-b",
        ),
    ]
    flir = object.__new__(FLIR)

    assert flir._select_camera(entries, "", 1) == ("handle-a", entries[0].info)
    assert flir._select_camera(entries, "", "serial-b") == ("handle-b", entries[1].info)
    assert flir._select_camera(
        entries, "", "Port_#0003.Hub_#0004"
    ) == ("handle-b", entries[1].info)


def test_select_camera_requires_explicit_target_for_multiple_cameras() -> None:
    entries = [
        flir_module._CameraEntry(CameraInfo(serial="serial-a", index=1), "handle-a"),
        flir_module._CameraEntry(CameraInfo(serial="serial-b", index=2), "handle-b"),
    ]
    flir = object.__new__(FLIR)

    with pytest.raises(CameraDiscoveryError, match="Multiple FLIR cameras"):
        flir._select_camera(entries, "", None)


def test_select_camera_rejects_ambiguous_interface_target() -> None:
    entries = [
        flir_module._CameraEntry(
            CameraInfo(serial="serial-a", index=1, interface_id="shared-controller"),
            "handle-a",
        ),
        flir_module._CameraEntry(
            CameraInfo(serial="serial-b", index=2, interface_id="shared-controller"),
            "handle-b",
        ),
    ]
    flir = object.__new__(FLIR)

    with pytest.raises(CameraDiscoveryError, match="matches multiple cameras"):
        flir._select_camera(entries, "", "shared-controller")


def test_camera_class_only_represents_an_opened_camera():
    assert not hasattr(Camera, "info")
    assert not hasattr(Camera, "list_backends")
    assert not hasattr(camera_module, "list_backends")
