r"""Worker process for :class:`qtools.camera.RemoteCamera`.

Run this module with the interpreter that has the matching PySpin wheel, for
example::

    .venv-camera\Scripts\python -m qtools.camera.bridge_worker --port 12345

Users normally do not start it directly; ``RemoteCamera`` creates and manages
the process.
"""

from __future__ import annotations

import argparse
import importlib
import socket
import sys
import traceback
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from qtools.camera import Camera
from qtools.camera.bridge import (
    _jsonable,
    _recv_header,
    _send_image,
    _send_packet,
)


def _load_factory(specification: str) -> Callable[..., Any]:
    module_name, separator, attribute = specification.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("camera factory must use the form 'module:callable'.")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise TypeError(f"Camera factory {specification!r} is not callable.")
    return factory


def _camera_metadata(camera: Any) -> dict[str, Any]:
    shape = tuple(int(value) for value in getattr(camera, "shape", (0, 0)))
    return {
        "name": str(getattr(camera, "name", "")),
        "model": str(getattr(camera, "model", "")),
        "shape": list(shape),
    }


def _send_result(socket_: socket.socket, request_id: Any, result: Any) -> None:
    if isinstance(result, np.ndarray):
        _send_image(socket_, {"id": request_id, "ok": True}, result)
        return
    _send_packet(
        socket_,
        {"id": request_id, "ok": True, "result": _jsonable(result)},
    )


def _close_camera(camera: Any | None) -> None:
    if camera is None:
        return
    try:
        camera.close()
    finally:
        del camera


def serve(
    port: int,
    *,
    camera_factory: Callable[..., Any] | None = None,
) -> None:
    """Connect to the parent and serve camera requests until shutdown."""

    socket_ = socket.create_connection(("127.0.0.1", int(port)), timeout=10.0)
    socket_.settimeout(None)
    camera: Any | None = None
    try:
        while True:
            try:
                request = _recv_header(socket_)
            except EOFError:
                break

            request_id = request.get("id")
            command = request.get("cmd")
            try:
                if command == "open":
                    _close_camera(camera)
                    camera = None
                    kwargs = request.get("kwargs", {})
                    if not isinstance(kwargs, Mapping):
                        raise TypeError("open.kwargs must be an object.")
                    if camera_factory is None:
                        camera = Camera(
                            backend=str(request.get("backend", "flir")),
                            **dict(kwargs),
                        )
                    else:
                        camera = camera_factory(**dict(kwargs))
                    _send_packet(
                        socket_,
                        {
                            "id": request_id,
                            "ok": True,
                            "result": _camera_metadata(camera),
                        },
                    )
                elif command == "ping":
                    _send_result(socket_, request_id, "pong")
                elif command == "capture":
                    if camera is None:
                        raise RuntimeError("Camera is not open.")
                    image = camera.capture(timeout_s=float(request.get("timeout_s", 1.0)))
                    _send_image(socket_, {"id": request_id, "ok": True}, image)
                elif command == "get_images":
                    if camera is None:
                        raise RuntimeError("Camera is not open.")
                    images = camera.get_images(
                        int(request["image_count"]),
                        timeout_s=float(request.get("timeout_s", 1.0)),
                    )
                    _send_image(socket_, {"id": request_id, "ok": True}, images)
                elif command == "get_exposure":
                    if camera is None:
                        raise RuntimeError("Camera is not open.")
                    _send_result(socket_, request_id, camera.get_exposure())
                elif command == "set_exposure":
                    if camera is None:
                        raise RuntimeError("Camera is not open.")
                    _send_result(
                        socket_,
                        request_id,
                        camera.set_exposure(float(request["exposure_s"])),
                    )
                elif command == "autoexpose":
                    if camera is None:
                        raise RuntimeError("Camera is not open.")
                    result = camera.autoexpose(
                        *request.get("args", ()),
                        **dict(request.get("kwargs", {})),
                    )
                    _send_result(socket_, request_id, result)
                elif command == "call":
                    if camera is None:
                        raise RuntimeError("Camera is not open.")
                    method = str(request["method"])
                    if method.startswith("_"):
                        raise ValueError("Private camera methods cannot be called remotely.")
                    result = getattr(camera, method)(
                        *request.get("args", ()),
                        **dict(request.get("kwargs", {})),
                    )
                    _send_result(socket_, request_id, result)
                elif command == "close":
                    _close_camera(camera)
                    camera = None
                    _send_result(socket_, request_id, None)
                elif command == "shutdown":
                    _close_camera(camera)
                    camera = None
                    _send_result(socket_, request_id, None)
                    break
                else:
                    raise ValueError(f"Unknown camera bridge command {command!r}.")
            except Exception as exc:
                traceback.print_exc(file=sys.stderr)
                _send_packet(
                    socket_,
                    {
                        "id": request_id,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
    finally:
        _close_camera(camera)
        socket_.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--camera-factory",
        help="Optional module:callable used instead of qtools.camera.Camera.",
    )
    args = parser.parse_args()
    factory = _load_factory(args.camera_factory) if args.camera_factory else None
    serve(args.port, camera_factory=factory)


if __name__ == "__main__":
    main()
