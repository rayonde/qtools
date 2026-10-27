#!/usr/bin/env python3
# Justin, 2022-07-19
#
# Communicates with Thorlabs K10CR1/M stepper motor directly,
# without use of Windows-dependent 'APT.dll' required in 'thorlabs-apt' library.
# Supports Windows (COMx via FTDI VCP driver) and Linux (/dev/ttyUSBx via ftdi_sio).
#
# Uses 'thorlabs_apt_protocol' for generating and reading messages.
# Documentation for APT protocol can be found in:
# https://www.thorlabs.com/drawings/c2590feb3514326e-D78FE62A-B46C-35CB-80E66667DC083047/K10CR1_M-ManualforAPT.pdf
#
# Changelog:
#     2024-02-28: Added notes on homing.
#     2025-04-24: Enable RTS/CTS for compatibility with K10CR2 as well

import warnings
import time

import serial
import serial.tools.list_ports
import thorlabs_apt_protocol as _apt

# Thorlabs K10CR1 USB identifiers (FTDI chip)
_THORLABS_VID = 0x0403
_THORLABS_PID = 0xFAF0


def list_devices() -> list[tuple[str, str]]:
    """Return [(port, label), ...] for every connected K10CR1 stage.

    Uses pyserial port enumeration; works on Windows (COMx) and Linux
    (/dev/ttyUSBx) without any additional drivers beyond the standard
    FTDI VCP driver.

    Returns an empty list when no matching device is found.
    """
    result = []
    for port_info in serial.tools.list_ports.comports():
        if port_info.vid == _THORLABS_VID and port_info.pid == _THORLABS_PID:
            label = (
                f"{port_info.description}"
                f" (SN={port_info.serial_number or 'N/A'})"
            )
            result.append((port_info.device, label))
    return result


def _find_k10cr1_port() -> str:
    """Auto-detect the first connected K10CR1 serial port.

    Scans by VID/PID via pyserial; works on Windows (COMx) and Linux
    (/dev/ttyUSBx) once the FTDI VCP driver / ftdi_sio module is loaded.
    Raises RuntimeError when no device is found.
    """
    devices = list_devices()
    if not devices:
        raise RuntimeError(
            "Thorlabs K10CR1 not found. "
            "Check USB connection and FTDI VCP driver installation."
        )
    return devices[0][0]


class Apt:
    """
    See Thorlabs APT protocol specification, page 12, for description of dest
    and source. Used when messages are broadcasted to sub-modules.
    In modern systems, typically connect one-to-one COM port connection,
    so can simply replace all source reference to 0x01 (host) and
    destination reference to 0x50 (generic USB).

    Source:
        https://www.thorlabs.com/software/apt/APT_Communications_Protocol_Rev_15.pdf
    """

    def __getattr__(self, name):
        """Intercepts calls to and injects apt.functions.

        Calls to every other function in apt is transparently passed
        through, unless they are defined in apt.functions.

        This monkey patch curries '0x50' as destination byte and
        '0x01' as source byte, since all apt.functions.[^_]* have them
        as first and second positional arguments.
        """
        target = getattr(_apt, name)  # could have been imported downstream
        if not hasattr(_apt.functions, name):
            return target

        # Patch APT function
        curry = [0x50, 0x01]
        if name.startswith("mot_") or name.startswith("mod_"):
            curry.append(0x01)  # always channel 1

        def f(*args, **kwargs):
            target = getattr(_apt, name)
            return target(*curry, *args, **kwargs)

        return f


# Module-level singleton — must be after Apt class definition, before ThorlabsK10CR1
apt = Apt()


class ThorlabsK10CR1:
    """Wrapper for APT commands relevant to K10CR1.

    Examples:
        >>> motor = ThorlabsK10CR1(port)
        >>> motor.identify()  # blinks LED
        >>> print("Serial:", motor.identity)  # prints identity information

        # Perform rotations
        >>> motor.stop()  # stop any existing rotations
        >>> motor.home()  # go to home, non-blocking
        >>> while motor.is_moving():  # wait until homing completed
        ...     pass

        # Perform blocking rotations
        >>> motor.blocking = True
        >>> motor.home()  # go to home, blocking
        >>> motor.angle = 45  # go to 45 degree position
        >>> motor.angle += 45  # go to 90 degree position

        # Perform continuous jog
        >>> motor.spin(clockwise=True)  # turn clockwise perpetually, non-blocking
        >>> time.sleep(3)
        >>> print(motor.angle)  # motor angle after 3 seconds
        >>> motor.stop()
    """

    def __init__(self, port: str = "", blocking: bool = True):
        """Creates the motor instance.

        If blocking is set to 'True', both homing and moving
        commands will block until completion. Spinning is
        non-blocking by default.

        Important: Ensure that the homing parameter 'offset_position'
        is correct for your stage.

        For usage, see main script at the bottom of the file.
        """
        if port == "":
            port = _find_k10cr1_port()

        self._com = serial.Serial(
            port=port,
            baudrate=115200,
            rtscts=True,  # required by K10CR2
            timeout=0.1,
        )

        # Reset input/output buffers thoroughly
        time.sleep(0.05)
        self._com.reset_input_buffer()
        self._com.reset_output_buffer()
        try:
            if self._com.in_waiting:
                self._com.read(self._com.in_waiting)
        except Exception:
            pass

        # Reader for device output - unpacks messages
        self.reader = apt.Unpacker(self._com)

        # Device constants
        self.steps_per_revolution = 49_152_000
        # self.steps_per_revolution = 409_600
        self.blocking = blocking

        # Required initialization as per APT protocol
        self.w(apt.hw_no_flash_programming())

        # Initialize device defaults, defined below in 'Parameters'
        # self.params_velocity = {}
        # self.params_jog = {}
        # self.params_homing = {}  # important: check homing offset
        # self.params_limswitch = {}

    def close(self) -> None:
        """Close the connection to the motor."""
        if hasattr(self, "_com") and self._com is not None:
            try:
                self._com.close()
            except Exception:
                pass

    ################
    #   COMMANDS   #
    ################

    # Most usage will only require interfacing via these commands.
    #   For customizing operating parameters, see 'Parameters' section.
    #   For direct interfacing with motor, see 'Helper' section.

    @property
    def identity(self) -> tuple[str, int]:
        """Returns model and serial number of motor.

        Note that Thorlabs software typically distinguish devices
        by serial number.
        """
        result = self.rw(apt.hw_req_info())
        model: bytes = result.model_number  # pyright: ignore[reportAttributeAccessIssue]
        serial: int = result.serial_number  # pyright: ignore[reportAttributeAccessIssue]
        model_str = model.strip(b"\x00").decode()
        return model_str, serial

    def home(self):
        """Requests motor to go to home based on homing parameters.

        Note the K10CR1 does not seem to respond to status queries, i.e.
        0x480 requests do not yield 0x481 replies, so the homing status
        cannot be directly retrieved. Some mechanism needs to be in place
        to be careful of motor loss of homing during power-off.

        If ``params_homing`` has already been set by the caller (e.g. for a
        multi-pass homing sequence), those values are preserved. Otherwise
        a fast default is used.
        """
        # Only set a default velocity if the caller hasn't already configured one
        try:
            if not hasattr(self, "_homing_params_set") or not self._homing_params_set:
                self.params_homing = {"home_velocity": 73301283}
        except Exception as e:
            warnings.warn(f"Could not set home parameters: {e}")

        self.w(apt.mot_move_home())
        time.sleep(0.15)  # Wait for motor to start moving
        if self.blocking:
            while self.is_moving():
                time.sleep(0.1)

    def stop(self, abrupt=False):
        """Stops motor movement."""
        self.w(apt.mot_move_stop(0x01 if abrupt else 0x02))

    def spin(self, clockwise=True):
        """Continuously moves motor (non-blocking) based on velocity parameters."""
        self.w(apt.mot_move_velocity(0x02 if clockwise else 0x01))

    @property
    def angle(self) -> float:
        """Returns angular position in degrees."""
        return self.angle_absolute % 360

    @angle.setter
    def angle(self, value: float):
        self.move(self.posdiff(self.deg2pos(value), self.position))
        if self.blocking:
            while self.is_moving():
                time.sleep(0.1)

    @property
    def pangle(self) -> float:
        """Returns angular position in degrees, bounded [-180,180)."""
        return (self.angle_absolute + 180) % 360 - 180

    def is_moving(self) -> bool:
        """Queries if motor is still rotating."""
        import time
        p1 = self.position
        time.sleep(0.08)
        p2 = self.position
        return p1 != p2

    ########################
    #   HELPER FUNCTIONS   #
    ########################

    # Note: Forward corresponds to counter-clockwise rotation, so
    #       reverse corresponds to clockwise rotation.
    #
    # There are 49,152,000 microsteps per revolution.
    #
    # Initial settings via Kinesis sets:
    # - Homing: Reverse direction with hardware reverse limit switch
    #           Zero offset = 4.0deg, velocity = 10.0deg/s
    # - Hardware limit switch: CCW makes (home), CW ignore.
    # - Software limit switch policy: Complete moves only
    # - Motor: Steps/revolution 200, gearbox ratio 120:1
    # - Backlash: 1deg

    def w(self, command: bytes):
        """Writes byte command to motor."""
        self._com.write(command)

    def r(self):
        """Reads from motor.

        As far as possible, we want to keep only a single message in buffer,
        for ease of debugging, and since use cases for multiple REQs before
        a single GET is rare, e.g. high resolution motor positioning.

        If multiple messages exist, a warning is raised and only the latest
        message is returned.

        Note that the status update messages pushed by the motor is generally
        ignored, since similar functionality is achieved by actually
        querying the motor directly.
        """
        resp = [msg for msg in self.reader]

        # Filter status update responses
        # TODO: Force '_apt.mot_suspend_endofmovemsges(0x50, 0x01)' instead,
        #       which disables said unsolicited EOM messages.
        status = ["mot_move_completed", "mot_move_stopped", "mot_move_homed"]
        responses = [m for m in resp if m.msg not in status]
        if not responses:
            raise ValueError("No reply from motor.")

        if len(responses) > 1:
            warning = [
                "Multiple messages received:",
                *list(map(repr, responses)),
            ]
            warnings.warn("\n  * ".join(warning))
        return responses[-1]

    def rw(self, command: bytes) -> list:
        """Writes and reads motor controller."""
        self.w(command)
        return self.r()

    def pos2deg(self, position: int) -> float:
        return position / self.steps_per_revolution * 360

    def deg2pos(self, degree: float) -> int:
        return round(degree / 360 * self.steps_per_revolution)

    def posdiff(self, target_position, curr_position):
        """Returns relative move distance based on absolute position."""

        # Normalize
        target = target_position % self.steps_per_revolution
        curr = curr_position % self.steps_per_revolution

        # Get smallest rotation
        diff = target - curr
        if abs(diff) > self.steps_per_revolution / 2:
            if diff > 0:
                return diff - self.steps_per_revolution
            else:
                return diff + self.steps_per_revolution
        return diff

    @property
    def angle_absolute(self):
        """Returns absolute angular position since homing.

        Generally not used since only the actual angle is
        relevant. Might be useful when excessive number of
        revolutions are performed -> warn user.
        """
        return self.position * 360 / self.steps_per_revolution

    @angle_absolute.setter
    def angle_absolute(self, value: float):
        self.goto(self.deg2pos(value))
        if self.blocking:
            while self.is_moving():
                time.sleep(0.1)

    @property
    def position(self):
        """Returns absolute position based on encoder value.

        Accurate only after homing. Does not normalize within
        revolution steps.

        Equivalent representation using encoder_count:
        `self.rw(apt.mot_req_enccounter()).encoder_count`
        """
        return self.rw(apt.mot_req_poscounter()).position  # pyright: ignore[reportAttributeAccessIssue]

    def move(self, distance: int = 0):
        """Move motor along 'distance' in units of microsteps."""
        self.w(apt.mot_move_relative(distance))
        import time
        time.sleep(0.15)  # Wait for motor to start moving
        if self.blocking:
            while self.is_moving():
                time.sleep(0.1)

    def goto(self, position: int = 0):
        """Move motor to 'position' in units of microsteps."""
        self.w(apt.mot_move_absolute(position))
        import time
        time.sleep(0.15)  # Wait for motor to start moving
        if self.blocking:
            while self.is_moving():
                time.sleep(0.1)

    def jog(self, direction: int):
        """Performs a jog based on jog parameters.

        Currently not used, similar functionality to spin.

        Args:
            direction: 0x01 (forward) or 0x02 (backward)
        """
        self.w(apt.mot_move_jog(direction))

    def identify(self):
        """Blinks LED."""
        self.w(apt.mod_identify())

    ##################
    #   PARAMETERS   #
    ##################

    # Units are in microsteps, see 'position()' for details.

    @staticmethod
    def extract(message, *fields):
        return {key: getattr(message, key) for key in fields}

    @property
    def backlash(self):
        """Returns backlash correction distance.

        Typically 1 deg == 136,533 microsteps.

        Usage:
            >>> motor.backlash = 136000
            >>> motor.backlash
            136000
        """
        return self.rw(apt.mot_req_genmoveparams()).backlash_distance  # pyright: ignore[reportAttributeAccessIssue]

    @backlash.setter
    def backlash(self, distance: int = 136533):
        self.w(apt.mot_set_genmoveparams(distance))

    @property
    def params_velocity(self):
        """Returns trapezoidal velocity parameters used for move.

        These parameters are used during general move, move_velocity,
        and homing (prior to hitting limit switch). Empirical
        measurements find that 73301283 corresponds to a
        10 deg/s rotation.

                       ^  Factory ^  Kinesis ^
        | min_velocity |        0 |        0 |
        | acceleration |    15020 |    15011 |
        | max_velocity | 73300775 | 73286848 |

        Usage:
            >>> motor.params_velocity = {"acceleration": 15000}
            >>> motor.params_velocity
            {
                "min_velocity": 0,
                "acceleration": 15000,     # newly set
                "max_velocity": 73301283,  # see setter defaults
            }
        """
        data = self.rw(apt.mot_req_velparams())
        return self.extract(
            data,
            "min_velocity",
            "acceleration",
            "max_velocity",
        )

    @params_velocity.setter
    def params_velocity(self, value):
        settings = {
            "min_velocity": 0,
            "acceleration": 15011,
            "max_velocity": 73301283,
            **value,  # override by value
        }
        return self.w(apt.mot_set_velparams(**settings))

    @property
    def params_jog(self):
        """Returns jog parameters.

          - 'jog_mode': 1 (continuous), 2 (single step)
          - 'stop_mode': 1 (immediate), 2 (controlled deceleration)

                       ^  Factory ^   Kinesis ^
        | jog_mode     |     0x02 |      0x02 |
        | step_size    |   136533 |    682667 |
        | min_velocity |        0 |         0 |
        | acceleration |     7506 |     22530 |
        | max_velocity | 36643424 | 109951163 |
        | stop_mode    |     0x02 |      0x02 |
        """
        data = self.rw(apt.mot_req_jogparams())
        return self.extract(
            data,
            "jog_mode",
            "step_size",
            "min_velocity",
            "acceleration",
            "max_velocity",
            "stop_mode",
        )

    @params_jog.setter
    def params_jog(self, value):
        settings = {
            "jog_mode": 0x02,
            "step_size": 682667,  # 5 degrees
            "min_velocity": 0,
            "acceleration": 22530,
            "max_velocity": 109951163,
            "stop_mode": 0x02,
            **value,  # override by value
        }
        return self.w(apt.mot_set_jogparams(**settings))

    @property
    def params_homing(self):
        """Returns homing parameters, typically stage-specific.

        Avoid setting a large offset_distance, since a slower
        rate of revolution is used to accurately move to the
        home position.

                           ^ Factory ^ Kinesis ^
        | home_dir        |    0x02 |    0x02 |
        | limit_switch    |    0x01 |       - |  # undocumented
        | home_velocity   |   73290 |       - |
        | offset_distance |  819200 |       - |
        """
        data = self.rw(apt.mot_req_homeparams())
        return self.extract(
            data,
            "home_dir",
            "limit_switch",
            "home_velocity",
            "offset_distance",
        )

    @params_homing.setter
    def params_homing(self, value):
        self._homing_params_set = True
        settings = {
            "home_dir": 0x02,
            "limit_switch": 0x01,
            "home_velocity": 73301283,  # align with velocity param
            "offset_distance": 546133,
            **value,  # override by value
        }
        return self.w(apt.mot_set_homeparams(**settings))

    @property
    def params_limswitch(self):
        """Returns limit switch parameters.

        Unknown whether software limit switch is used.

        For the hardware limit switches:
          - '0x01': ignore switch
          - '0x02': switch makes on contact
          - '0x03': switch breaks on contact
          - '0x04': switch makes on contact (only used for homing)
          - '0x05': switch breaks on contact (only used for homing)
        """
        data = self.rw(apt.mot_req_limswitchparams())
        return self.extract(
            data,
            "cw_hardlimit",
            "ccw_hardlimit",
            "cw_softlimit",
            "ccw_softlimit",
            "soft_limit_mode",
        )

    @params_limswitch.setter
    def params_limswitch(self, value):
        settings = {
            "cw_hardlimit": 2,
            "ccw_hardlimit": 2,
            "cw_softlimit": 0,
            "ccw_softlimit": 0,
            "soft_limit_mode": 1,
            **value,  # override by value
        }
        return self.w(apt.mot_set_limswitchparams(**settings))



# Helper
def bytes2hex(b):
    """Displays bytes as formatted hexstring.

    Useful for showing the hex values for comparison with
    the APT command manual. Python display for bytestrings will
    render ASCII and control keys as well.

    Examples:
        >>> msg = apt.mot_move_home()
        >>> msg
        b'C\x04\x01\x00P\x01'
        >>> bytes2hex(msg)
        '43 04 01 00 50 01'
    """
    return " ".join([f"{v:0>2x}" for v in b])


def hex2bytes(h):
    """Converts formatted hexstring to bytes.

    The reverse of 'bytes2hex'.

    Examples:
        >>> h = '43 04 01 00 50 01'
        >>> hex2bytes(h)
        b'C\x04\x01\x00P\x01'
    """
    return bytes.fromhex(h)


# Quick tests
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Controls Thorlabs K10CR1/2 motors.")
    parser.add_argument(
        "-U",
        "--device",
        metavar="",
        default="",
        help="Thorlabs device path (default: %(default)s)",
    )
    args = parser.parse_args()
    port = args.device

    # Connect to motor
    motor = ThorlabsK10CR1(port)
    motor.identify()  # blinks LED
    print("Serial:", motor.identity)  # prints identity information
