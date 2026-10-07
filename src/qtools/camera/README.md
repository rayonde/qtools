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
