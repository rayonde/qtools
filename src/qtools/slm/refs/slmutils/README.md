# slmutils

Lab scripts to interface with Holoeye LETO-II SLM.

## Installation

Only Python 3.10 is supported (due to Spinnaker requirements).

## Usage

Run the server serving a full-screen application on the secondary monitor:

```bash
python -m slmutils.display.server
```

then connect to the server and write a display mask to it:

```python
from ipyutils import Client

from slmutils.display import DisplayInterface
from slmutils.generate import DisplayMask

display = Client(DisplayInterface, port=4444, secret="slmmer")
mask = DisplayMask(display.resolution)

mask = mask.random()  # generates a random 8-bit image
display.load(mask)
```

For more general phase functions, use:

```python
from slmutils.generate import HoloeyeLETO

slm = HoloeyeLETO(wl=532e-9)  # 532nm
base = slm.to_phase()

phase = (
    base
    .spiral(order=2)
    .binary(period=16)
)
phase.save("spiral_binary.png")
mask = phase.to_display()
```

Support for FLIR cameras is available:

```python
from slmutils.camera.flir import Camera

camera = Camera()
camera.exposure_auto()
image = camera.capture()
```

## Others

Originally written for Hamamatsu's SLM (512x512, 14-bit resolution), but modified for Holoeye's LETO-II instead (1920x1080, 8-bit resolution).

At some point the code for high resolution (i.e. >8-bit) should be reintegrated back since it seems more universal. The old code works like this:

* `maskgen.py`:
  * Loads wavefront correction mask and LUT.
  * Exposes functions that generate phase mask, then discretizes using the LUT, and optionally force into the 8-bit RGB construct (least significant bits go into the red channel, followed by the remaining bits in the green channel).
  * Importantly, both the wavefront correction and LUT are applied manually, because we didn't have the software on hand to configure the device.
* `display.py`:
  * Opens a full-screen window on the secondary display.
  * Loads the discretized data into buffer, and creates an image from the buffer to be displayed.
* `display_server.py`:
  * Runs the main thread that sends image to the window, because the wxPython display thread needs to be run independently.
  * Opens a TCP port for receiving remote commands.
* `display_client.py`:
  * Connects to said TCP port and sends images.
