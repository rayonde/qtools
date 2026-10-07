from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from qtools.camera import (
    Camera,
    CameraBackend,
    CameraDependencyError,
    CameraInfo,
    FLIR,
    list_backends,
    register_backend,
)
from qtools.camera.backends import flir as flir_module
from qtools.camera.camera import _BACKEND_MODULES


class FakeNode:
    def __init__(self, value, minimum=0, maximum=1_000_000, increment=1):
        self.value = value
        self.minimum = minimum
        self.maximum = maximum
        self.increment = increment
        self.executions = 0

    def GetAccessMode(self):
        return 1

    def SetValue(self, value):
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
    assert "flir" in list_backends()
    assert issubclass(FLIR, flir_module.CameraBackend)


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

    assert FLIR.info(verbose=False) == ["123"]
    with FLIR(serial="123", pitch_um=3.45) as flir:
        assert flir.shape == (1, 2)
        assert flir.pitch_um == (3.45, 3.45)
        image = flir.capture()
        assert np.array_equal(image, np.array([[0x123, 0xFFF]], dtype=np.uint16))
        assert camera.TriggerSoftware.executions == 1
        assert flir.get_exposure() == pytest.approx(0.0001)
    assert camera.ended
    assert camera.deinitialized
    FLIR.close_sdk()
    assert system.released


def test_facade_delegates_and_saves_raw_data(tmp_path, fake_pyspin):
    path = tmp_path / "frame.npy"
    with Camera(backend="flir", serial="123") as camera:
        image = camera.save(path)
    assert np.array_equal(np.load(path), image)


def test_new_vendor_backend_can_be_registered_without_facade_changes(monkeypatch):
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
        assert Camera.info(backend="dummy", verbose=False) == ["dummy-1"]
        with Camera(backend="dummy") as camera:
            assert np.array_equal(camera.capture(), np.array([[7]], dtype=np.uint8))
    finally:
        monkeypatch.delitem(_BACKEND_MODULES, "dummy", raising=False)
