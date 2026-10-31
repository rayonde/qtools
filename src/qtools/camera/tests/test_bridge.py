from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from qtools.camera import CameraBridgeError, CameraImage, FLIR, RemoteCamera


def _remote_camera() -> RemoteCamera:
    return RemoteCamera(
        sys.executable,
        camera_factory="fake_bridge_backend:FakeBridgeCamera",
        cwd=Path(__file__).parent,
        startup_timeout_s=10.0,
        request_timeout_s=10.0,
        serial="unit-test-camera",
    )


def test_remote_camera_round_trip() -> None:
    with _remote_camera() as camera:
        assert camera.pid is not None
        assert camera.name == "unit-test-camera"
        assert camera.model == "FakeBridge"
        assert camera.shape == (2, 3)
        assert camera.ping() == "pong"
        assert camera.get_exposure() == pytest.approx(0.01)
        assert camera.set_exposure(0.025) == pytest.approx(0.025)

        image = camera.capture(timeout_s=0.1)
        assert isinstance(image, CameraImage)
        assert image.info["serial"] == "unit-test-camera"
        assert image.info["dtype"] == "<u2"
        np.testing.assert_array_equal(
            image,
            np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16),
        )
        camera.auto_exposure = False
        camera.auto_gain = False
        camera.format = "Mono8"
        assert camera.auto_exposure is False
        assert camera.auto_gain is False
        assert camera.format == "Mono8"
        assert camera.set_gain(0.0) == pytest.approx(0.0)
        assert camera.capture(timeout=0.1).info["timeout_s"] == pytest.approx(0.1)

        images = camera.get_images(2, timeout_s=0.1)
        assert images.shape == (2, 2, 3)
        np.testing.assert_array_equal(images[1], image + 1)
        assert camera.autoexpose(fraction=0.7) == pytest.approx(0.7)
        assert camera.call("get_exposure") == pytest.approx(0.025)

    assert camera.closed


def test_remote_camera_forwards_camera_target() -> None:
    with RemoteCamera(
        sys.executable,
        target="Port_#0001.Hub_#0002",
        camera_factory="fake_bridge_backend:FakeBridgeCamera",
        cwd=Path(__file__).parent,
        request_timeout_s=10.0,
    ) as camera:
        assert camera.call("get_extra") == {"target": "Port_#0001.Hub_#0002"}


def test_remote_camera_forwards_worker_errors() -> None:
    with _remote_camera() as camera:
        with pytest.raises(CameraBridgeError, match="intentional bridge failure"):
            camera.call("explode")
        assert camera.ping() == "pong"


def test_remote_camera_auto_provisions_flir_python(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, bool]] = []

    def fake_ensure(cls: object, venv_dir: object, *, auto_install_python: bool = True) -> Path:
        calls.append((venv_dir, auto_install_python))
        return Path(sys.executable)

    monkeypatch.setattr(FLIR, "pyspin_available", classmethod(lambda cls: False))
    monkeypatch.setattr(FLIR, "ensure_bridge_python", classmethod(fake_ensure))

    with RemoteCamera(
        camera_factory="fake_bridge_backend:FakeBridgeCamera",
        cwd=Path(__file__).parent,
        request_timeout_s=10.0,
    ) as camera:
        assert camera.ping() == "pong"

    assert calls == [(".venv-camera", True)]
