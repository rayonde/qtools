"""Cross-version subprocess bridge for camera backends.

``PySpin`` is a CPython extension with a strict ABI.  A process running Python
3.14 therefore cannot import a wheel built for Python 3.12.  This module keeps
the camera inside a compatible worker interpreter and communicates with it
over a loopback socket.

Message headers are length-prefixed JSON; NumPy frames are sent as raw C-order
bytes.  No Python objects are pickled, so the two processes may use different
Python minor versions.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from qtools.camera.exceptions import CameraBridgeError

_PREFIX = struct.Struct("!I")
_MAX_HEADER_BYTES = 1 << 20


def _jsonable(value: Any) -> Any:
    """Convert common values into JSON-compatible data."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _send_packet(sock: socket.socket, header: Mapping[str, Any], payload: bytes = b"") -> None:
    data = json.dumps(_jsonable(header), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > _MAX_HEADER_BYTES:
        raise CameraBridgeError("Camera bridge message header is too large.")
    sock.sendall(_PREFIX.pack(len(data)))
    sock.sendall(data)
    if payload:
        sock.sendall(payload)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    if size < 0:
        raise CameraBridgeError("Camera bridge received a negative payload size.")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(min(remaining, 1 << 20))
        if not chunk:
            raise EOFError("Camera worker closed the socket.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_header(sock: socket.socket) -> dict[str, Any]:
    prefix = _recv_exact(sock, _PREFIX.size)
    (size,) = _PREFIX.unpack(prefix)
    if size > _MAX_HEADER_BYTES:
        raise CameraBridgeError("Camera bridge message header is too large.")
    raw = _recv_exact(sock, size)
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise CameraBridgeError("Camera bridge message header must be a JSON object.")
    return decoded


def _send_image(
    sock: socket.socket,
    header: Mapping[str, Any],
    image: npt.ArrayLike,
) -> None:
    array = np.ascontiguousarray(image)
    message = dict(header)
    message["image"] = {
        "shape": list(array.shape),
        "dtype": array.dtype.str,
        "nbytes": array.nbytes,
    }
    _send_packet(sock, message, array.tobytes(order="C"))


def _recv_image(sock: socket.socket, header: Mapping[str, Any]) -> npt.NDArray[np.generic]:
    metadata = header.get("image")
    if not isinstance(metadata, Mapping):
        raise CameraBridgeError("Camera bridge response is missing image metadata.")
    try:
        shape = tuple(int(value) for value in metadata["shape"])
        dtype = np.dtype(str(metadata["dtype"]))
        nbytes = int(metadata["nbytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CameraBridgeError("Camera bridge image metadata is invalid.") from exc
    payload = _recv_exact(sock, nbytes)
    array = np.frombuffer(payload, dtype=dtype)
    try:
        array = array.reshape(shape)
    except ValueError as exc:
        raise CameraBridgeError(
            f"Camera bridge image size does not match shape {shape}: {nbytes} bytes."
        ) from exc
    return np.array(array, copy=True, order="C")


class RemoteCamera:
    """Control a camera in a separate, ABI-compatible Python process.

    Parameters
    ----------
    python_executable:
        Interpreter that has both ``qtools`` and the matching PySpin wheel.
    backend:
        Backend name passed to :class:`qtools.camera.Camera` in the worker.
    worker_module:
        Worker module.  The default is the Qtools bridge worker.
    camera_factory:
        Optional ``module:callable`` factory for a custom camera backend.  The
        factory is called with the remaining keyword arguments instead of
        constructing ``Camera(backend=..., **kwargs)``.
    startup_timeout_s:
        Maximum time to wait for the worker to connect.
    request_timeout_s:
        Socket timeout for each request, or ``None`` for no timeout.
    cwd, env:
        Optional working directory and environment override for the worker.
    **camera_kwargs:
        Options passed to the camera constructor in the worker.
    """

    def __init__(
        self,
        python_executable: str | Path,
        *,
        backend: str = "flir",
        worker_module: str = "qtools.camera.bridge_worker",
        camera_factory: str | None = None,
        startup_timeout_s: float = 30.0,
        request_timeout_s: float | None = 60.0,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        **camera_kwargs: Any,
    ) -> None:
        self._python_executable = str(python_executable)
        self._process: subprocess.Popen[bytes] | None = None
        self._listener: socket.socket | None = None
        self._sock: socket.socket | None = None
        self._next_request_id = 1
        self._closed = False
        self._name = ""
        self._model = ""
        self._shape: tuple[int, ...] = (0, 0)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(float(startup_timeout_s))
            port = int(listener.getsockname()[1])
            self._listener = listener

            command = [
                self._python_executable,
                "-u",
                "-m",
                worker_module,
                "--port",
                str(port),
            ]
            if camera_factory:
                command.extend(["--camera-factory", camera_factory])

            child_env = os.environ.copy()
            if env:
                child_env.update({str(key): str(value) for key, value in env.items()})
            try:
                self._process = subprocess.Popen(
                    command,
                    cwd=None if cwd is None else str(cwd),
                    env=child_env,
                    stdin=subprocess.DEVNULL,
                )
            except OSError as exc:
                raise CameraBridgeError(
                    f"Could not start camera worker {self._python_executable!r}: {exc}"
                ) from exc

            try:
                self._sock, _ = listener.accept()
            except OSError as exc:
                raise CameraBridgeError(
                    "Camera worker did not connect within "
                    f"{startup_timeout_s:g} seconds (exit code "
                    f"{self._process.poll()})."
                ) from exc
            finally:
                listener.close()
                self._listener = None

            self._sock.settimeout(request_timeout_s)
            response = self._request(
                "open",
                backend=backend,
                kwargs=camera_kwargs,
            )
            result = response.get("result")
            if not isinstance(result, Mapping):
                raise CameraBridgeError("Camera worker returned invalid camera metadata.")
            self._name = str(result.get("name", ""))
            self._model = str(result.get("model", ""))
            self._shape = tuple(int(value) for value in result.get("shape", (0, 0)))
        except Exception:
            self._stop_process()
            self._closed = True
            raise

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    @property
    def shape(self) -> tuple[int, ...]:
        return self._shape

    @property
    def pid(self) -> int | None:
        return None if self._process is None else self._process.pid

    @property
    def closed(self) -> bool:
        return self._closed

    def capture(self, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        header = self._request("capture", timeout_s=timeout_s)
        return _recv_image(self._require_socket(), header)

    def get_image(self, timeout_s: float = 1.0) -> npt.NDArray[np.generic]:
        return self.capture(timeout_s=timeout_s)

    def get_images(
        self,
        image_count: int,
        timeout_s: float = 1.0,
    ) -> npt.NDArray[np.generic]:
        header = self._request(
            "get_images",
            image_count=image_count,
            timeout_s=timeout_s,
        )
        return _recv_image(self._require_socket(), header)

    def get_exposure(self) -> float:
        response = self._request("get_exposure")
        return float(response["result"])

    def set_exposure(self, exposure_s: float) -> float:
        response = self._request("set_exposure", exposure_s=exposure_s)
        return float(response["result"])

    def autoexpose(self, *args: Any, **kwargs: Any) -> float:
        response = self._request("autoexpose", args=args, kwargs=kwargs)
        return float(response["result"])

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call a backend method and return its JSON value or NumPy array."""

        header = self._request("call", method=method, args=args, kwargs=kwargs)
        if "image" in header:
            return _recv_image(self._require_socket(), header)
        return header.get("result")

    def ping(self) -> str:
        response = self._request("ping")
        return str(response["result"])

    def close(self) -> None:
        if self._closed:
            return
        if self._process is not None and self._process.poll() is None and self._sock is not None:
            try:
                self._request("shutdown")
            except CameraBridgeError:
                pass
        self._closed = True
        self._stop_process()

    def __enter__(self) -> "RemoteCamera":
        if self._closed:
            raise CameraBridgeError("RemoteCamera is already closed.")
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self._stop_process()
        except Exception:
            pass

    def _require_socket(self) -> socket.socket:
        if self._sock is None:
            raise CameraBridgeError("Camera worker connection is closed.")
        return self._sock

    def _request(self, command: str, **arguments: Any) -> dict[str, Any]:
        sock = self._require_socket()
        request_id = self._next_request_id
        self._next_request_id += 1
        request = {"id": request_id, "cmd": command, **_jsonable(arguments)}
        try:
            _send_packet(sock, request)
            response = _recv_header(sock)
        except (EOFError, OSError, json.JSONDecodeError) as exc:
            exit_code = None if self._process is None else self._process.poll()
            raise CameraBridgeError(
                f"Camera worker communication failed for {command!r} "
                f"(exit code {exit_code}): {exc}"
            ) from exc
        if response.get("id") != request_id:
            raise CameraBridgeError(
                f"Camera worker returned response id {response.get('id')!r}; "
                f"expected {request_id}."
            )
        if not response.get("ok"):
            raise CameraBridgeError(str(response.get("error", "Unknown camera worker error.")))
        return response

    def _stop_process(self) -> None:
        sock, self._sock = self._sock, None
        listener, self._listener = getattr(self, "_listener", None), None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        process = getattr(self, "_process", None)
        if process is None:
            return
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


__all__ = ["RemoteCamera"]
