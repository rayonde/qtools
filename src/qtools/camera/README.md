# `qtools.camera`

`qtools.camera` provides one common facade for industrial-camera backends. The
current backend is FLIR through the vendor's Spinnaker SDK and `PySpin` binding.

```python
from qtools.camera import Camera

print(Camera.list_backends())
print(Camera.info(backend="flir"))

with Camera(backend="flir", serial="25354617", pitch_um=3.45) as camera:
    camera.exposure_auto()
    frame = camera.capture()       # raw NumPy data, normally 12-bit values
    camera.save("image.npy", preview=True)
```

Importing the package does not require PySpin. Using a real FLIR camera does:
install the full Spinnaker SDK and the matching `spinnaker-python` wheel from
Teledyne's official download page. The SDK and wheel must match the operating
system, Python version, and each other.

## Python and PySpin compatibility

`qtools` supports Python 3.10--3.13, but the vendor binding is a separate
native extension with a strict ABI and platform tag. For example,
`spinnaker_python-3.2.0.65-cp310-cp310-win_amd64.whl` means CPython 3.10 on
64-bit Windows. It cannot be installed on Python 3.11--3.13, macOS, or ARM.
Changing the examples' syntax does not remove this native-extension constraint.

Keep the main application on Python 3.13 if desired, and run the camera code
on a Windows/Linux environment for which Teledyne provides a matching wheel:

```powershell
py -3.10 -m venv .venv-camera
.venv-camera\Scripts\python -m pip install numpy
.venv-camera\Scripts\python -m pip install spinnaker_python-3.2.0.65-cp310-cp310-win_amd64.whl
.venv-camera\Scripts\python -m pip install -e path\to\qtools
```

On Linux, use the matching interpreter and wheel instead:

```bash
python3.10 -m venv .venv-camera
.venv-camera/bin/python -m pip install numpy
.venv-camera/bin/python -m pip install spinnaker_python-<version>-cp310-cp310-linux_x86_64.whl
.venv-camera/bin/python -m pip install -e /path/to/qtools
```

Install the same Spinnaker SDK release as the wheel. On a Python 3.13 machine
without PySpin, importing `qtools.camera`, reading its documentation, and
running the fake-SDK tests remain supported. If Teledyne publishes a `cp313`
wheel for the target OS and architecture, upgrade the SDK and wheel together
and run a hardware smoke test before switching environments.

The checked-in reference wheel is an older 3.2.0.65 Windows/CPython 3.10
package. Teledyne's current download page lists Spinnaker SDK 4.3.0.189 for
Ubuntu 22.04 x64 and ARM64 (January 2026); that SDK release must be paired with
its own matching Python binding rather than with the checked-in 3.2 wheel.

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

The facade then works without changes:

```python
camera = Camera(backend="basler")
image = camera.capture()
```

Vendor-specific functions can remain on the backend and are available through
the facade when needed. Shared operations such as acquisition, exposure,
saving, and context-manager cleanup stay in the common layer. A future backend
can use `pypylon` for Basler, VimbaX for Allied Vision, or a GenICam/GenTL SDK
without adding those packages to the core dependency list.
