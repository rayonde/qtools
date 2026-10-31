# `qtools.camera`

`qtools.camera` provides a common facade for industrial-camera backends. The
current backend is FLIR through the vendor's Spinnaker SDK and `PySpin` binding.

Camera discovery is a module-level operation because it does not operate on an
already opened camera:

```python
from qtools.camera import RemoteCamera, list_camera

list_camera()
# [1] | brand=FLIR | model=Blackfly S BFS-U3-16S2M | SN=25354617 |
#      USB3Vision port=Port_#0011.Hub_#0004

with RemoteCamera(target=1, pitch_um=3.45) as camera:
    camera.set_exposure(0.01)
    frame = camera.capture(timeout_s=1.0)  # raw NumPy data
```

`list_camera()` prints the one-based number, vendor, model, serial number,
transport type, and USB port or Ethernet address. It returns `None`, so Jupyter
shows only one formatted list. Multiple cameras of the same model remain
selectable by serial number and port.

## Selecting a camera

Use the number, serial number, USB port, or Ethernet address reported by
`list_camera()` as `target`:

```python
from qtools.camera import Camera, RemoteCamera, list_camera

list_camera()
camera = RemoteCamera(target=1)
# camera = RemoteCamera(target="25354617")
# camera = RemoteCamera(target="Port_#0011.Hub_#0004")
# camera = RemoteCamera(target="192.168.1.10")
# camera = Camera(backend="flir", target=1)
```

`serial=...` remains available as a serial-number-only selector. When multiple
cameras are connected, omitting both `target` and `serial` raises an error rather
than silently choosing one. Numbers are ordered by serial number for the current
enumeration; prefer the serial, device ID, or port in persistent configuration.

## Managed runtime

`list_camera()` uses the installed Spinnaker SDK C runtime directly. It does not
import PySpin, create `.venv-camera`, download a wheel, or install another
Python version. If the Spinnaker SDK runtime is unavailable, it raises
`CameraDependencyError`.

Constructing `RemoteCamera` is the operation that prepares the Python worker.
When PySpin is unavailable in the main interpreter, it:

1. Selects `spinnaker_python-4.4.0.246-cp312-cp312-win_amd64.whl` from
   `backends/refs`.
2. Determines the Python version from the wheel's `cp3xx` tag.
3. On Windows, uses `winget` to install that Python version if it is missing.
4. Creates or repairs `.venv-camera`, installing `numpy<2` and the bundled wheel.
5. Starts a worker in that environment and reuses it for the camera lifetime.

The configured wheel is CPython 3.12/Windows x64. Preparing the worker requires
network access, winget, and the matching Spinnaker SDK runtime. The main
application remains on its own Python version and is not downgraded or
constrained by PySpin.

Automatic Python installation can be disabled for `RemoteCamera`:

```python
camera = RemoteCamera(auto_install_python=False)
```

A pre-existing interpreter can still be supplied explicitly:

```python
camera = RemoteCamera(r".venv-camera\Scripts\python.exe")
```

The managed environment can also be created or repaired directly:

```powershell
camera-venv --venv .venv-camera
```

`RemoteCamera` communicates with the worker over a loopback socket. Messages
contain length-prefixed JSON metadata; image frames are transferred as raw,
C-order NumPy bytes. No Python objects are pickled, so the parent and worker may
use different Python minor versions. Backend-specific methods are available
through `camera.call("method_name", ...)`.

The bridge adds an inter-process copy. This is simple and robust for ordinary
acquisition rates; very high frame rates should use a shared-memory ring buffer
instead.

## Adding another industrial camera

Concrete vendor backends belong in `qtools.camera.backends`. Implement the
small `CameraBackend` contract and register the class:

```python
from qtools.camera import CameraBackend, register_backend


class Basler(CameraBackend):
    backend_name = "basler"

    # Implement discover(), __init__(), name, model, shape, get_image(), close().


register_backend("basler", Basler)
```

The backend is then available without facade changes:

```python
from qtools.camera import Camera, list_camera

list_camera(backend="basler")
with Camera(backend="basler", target=1) as camera:
    image = camera.capture()
```

Vendor-specific functions can remain on the backend and are available through
the facade when needed. Shared operations such as acquisition, exposure,
saving, and context-manager cleanup stay in the common layer.
