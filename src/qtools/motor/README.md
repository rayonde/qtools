# qtools.motor — Motor Control

A Python library and Command Line Interface (CLI) for controlling Thorlabs **K10CR1**
(and compatible) stepper-motor rotation stages via the APT protocol over USB.

本库提供一个 Python 接口和命令行工具（CLI），通过 APT 协议经 USB 直接控制
Thorlabs **K10CR1** 步进电机旋转台。

> **Note:** This package handles motor control **only**. For waveplate calibration,
> polarization measurement, entanglement scans, and CHSH Bell tests, see the
> companion package **`qtools.pmeas`**.

---

## Installation

Install from the **qtools repository root**. This is a subpackage of qtools,
with dependencies and the CLI entry point managed by the root `pyproject.toml`.

```bash
pip install -e .
```


---

## Command Line Interface (CLI) Guide

The package installs the command **`motor`**.

### Subcommands Overview

```bash
motor --help
```

```
Thorlabs K10CR1 Stepper Motor CLI

commands:
  list                  List connected K10CR1 devices
  config                Interactive naming and configuration wizard
  status                Connect and query motor status
  identify              Blink the device LED
  move                  Move the motor stage (to: absolute, by: relative)
  position              Query current software and physical angle
  set-zero              Set software zero offset
  zero                  Move the motor stage to software zero (0.0°)
  home                  Home the motor stage
  repl                  Start interactive REPL
```

#### Specifying a Device

Every command that operates on a motor accepts an optional positional *device* argument.
If only one device is connected it is auto-detected.  The device can be:

- **Index** (1, 2, … from `motor list` output)
- **Configured name** (e.g. `alice`)
- **Serial port** (e.g. `COM3`, `/dev/ttyUSB0`)
- **Serial-number substring**

```bash
motor status alice          # query device "alice"
motor position 1            # query device index 1
motor move 1 to 90          # move device 1 to 90°
motor move alice to 45      # move device "alice" to 45°
motor move to 90            # auto-detect, move to 90°
motor home COM3             # home device on COM3
```

---

### `list` — List connected K10CR1 devices

Scans USB ports for connected Thorlabs K10CR1 devices and lists them.

```bash
motor list
```

> [!TIP]
> **Troubleshooting / 常见搜索不到设备问题**:
> - **Windows**: 新连接的设备有时可能无法被搜索到。这是因为驱动默认未加载虚拟串口（Virtual COM Port, VCP）。请在 Windows 的**设备管理器**中找到对应的 USB Serial Converter 设备（通常在“通用串行总线控制器”或“端口”下），右键选择属性 -> 切换到 **Advanced** 选项卡 -> 勾选 **"Load VCP"**，保存后重新拔插 USB 即可。
> - **macOS**: 如果 `pyserial` 占用设备失败，可能需要卸载系统的 FTDI 驱动以释放控制权：`sudo kextunload -bundle-id com.FTDI.driver.FTDIUSBSerialDriver`。

---

### `config` — Interactive configuration wizard

Launches an interactive command line wizard to configure all connected Thorlabs K10CR1 devices one-by-one.

```bash
motor config
```

During configuration, it prompts for the naming schema fields:
1. **Alias** (e.g. `alice`, `bob`)
2. **Wavelength** (e.g. `1550`)
3. **Role** (e.g. `basis`, `state`)
4. **Waveplate type** (e.g. `hwp`, `qwp`)

It automatically generates a name like `alice1550_basis_hwp` and stores it into `devices.yaml`. If a device is already configured, it lets you choose whether to reconfigure it.

---

### `status` — Connect and query motor status

Connects to a device and prints model, serial number, current physical angle, and software zero-offset.

```bash
motor status
motor status alice
motor status 1
```

---

### `identify` — Blink the device LED

Flashes the device LED so you can physically locate the stage.

```bash
motor identify
motor identify alice
```

---

### `position` — Query current software and physical angle

Connects to a device and prints its current software angle, physical angle, and software zero offset.

```bash
# Query position of the auto-detected device
motor position

# Query position of device 'alice'
motor position alice

motor position 1
```

---

### `move to` — Move to an absolute angle

Moves the motor stage to a specific absolute angle.

```bash
# Move to absolute 45.0° (auto-detect device)
motor move to 45.0

# Move alice to absolute 45.0°
motor move alice to 45.0

# Move to the software zero point (0.0°)
motor move to zero

# Move alice to the software zero point (0.0°)
motor move alice to zero

# Move device 1 to absolute 45.0°
motor move 1 to 45.0
```

---

### `move by` — Rotate by a relative angle

Rotates the motor stage by a relative displacement.

```bash
# Rotate +22.5° relative (auto-detect device)
motor move by 22.5

# Rotate device alice relative by -15.0°
motor move alice by -15.0

# Rotate by 45.0° relative at speed 5.0°/s
motor move by 45.0 --speed 5.0
```

---

### `set-zero` — Set software zero offset

Maps the current physical angle (or an explicit angle) to 0.0° in software.

```bash
# Zero the auto-detected device at current position
motor set-zero

# Zero device 'alice' at current position
motor set-zero alice

# Set zero offset to physical 15.0° for device 'alice'
motor set-zero alice 15.0
# Or using option flag:
motor set-zero 15.0 -n alice
```

---

### `zero` — Move to software zero (0.0°)

Moves the motor stage to the software zero position (0.0°) defined by the software zero offset.

```bash
# Move the auto-detected device to software zero
motor zero

# Move device 'alice' to software zero
motor zero alice

# Move device 1 to software zero (using option)
motor zero -id 1
```

---

### `home` — Home the motor stage

Sends the motor to its physical home limit switch.

```bash
motor home
motor home alice
```



---

### `repl` — Start interactive REPL

Starts an interactive Read-Eval-Print Loop for motor control.

```bash
motor repl
```

---

## Python API Usage

```python
from qtools.motor import get_motor, list_devices, ThorlabsK10CR1

# 1. List all connected devices
for port, label in list_devices():
    print(port, label)

# 2. Connect via convenience helper
stage = get_motor(name="alice1550_basis_hwp")

# 3. Basic operations
print(f"Current angle: {stage.get_position():.2f}°")

# Rotate to 45° and block until complete
stage.move_to(45.0)
stage.wait_move()

# Relative move
stage.move_by(22.5)
stage.wait_move()

# Home the stage
stage.home()
stage.wait_move()

# Set software zero-offset to current position
stage.set_zero_offset()

# Clean up
stage.disconnect()

# 4. Low-level APT driver (advanced)
motor = ThorlabsK10CR1(port="/dev/ttyUSB0")
motor.identify()              # blink LED
model, serial = motor.identity
motor.angle = 90              # blocking absolute move
motor.close()
```

---

## Configuration

Device metadata (name, optical path, wavelength, waveplate type, zero-offset)
is stored in **`devices.yaml`** at the project root.

On first connection to a new serial number, the CLI prompts interactively to
generate a standard name (e.g. `alice1550_basis_hwp`).

Example `devices.yaml`:

```yaml
55119234:
  name: alice1550_basis_hwp
  optical_path: alice
  role: basis
  wavelength: 1550
  waveplate: hwp
  zero_offset: 15.0
```

---

## Project Structure

```text
src/qtools/motor/
├── __init__.py          # Public API
├── _path.py             # Configuration/output path helpers
├── api.py               # Convenience API re-exports
├── cli.py               # motor command
├── connection.py        # Device discovery and connection helpers
├── config.py            # YAML configuration management
├── motor_config.yaml    # Existing device configuration
├── README.md
├── backends/
│   ├── __init__.py
│   ├── motor.py         # MotorBackend facade and registry
│   └── k10cr1/
│       ├── __init__.py
│       ├── k10cr1.py    # Low-level APT driver
│       └── stage.py     # K10CR1 backend
└── vendor/              # Reference SDK sources (excluded from the wheel)

tests/motor/
├── test_cli_move_syntax.py
├── hardware_integration.py  # Manual hardware exercise
├── hardware_homing.py       # Manual homing checks
└── k10cr1.ipynb             # Interactive hardware diagnostics
```

Run unit tests from the qtools repository root:

```bash
uv run pytest tests/motor
```

Run the hardware exercise explicitly (this moves the connected motor):

```bash
uv run python -m tests.motor.hardware_integration -U COM3
uv run python -m tests.motor.hardware_homing -U COM3
```
