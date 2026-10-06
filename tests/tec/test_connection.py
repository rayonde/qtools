"""Unit tests for TEC serial connection and device discovery."""

from unittest.mock import MagicMock, patch

import pytest

from qtools.tec.connection import (
    MockSerialTransport,
    SerialTransport,
    find_serial_device,
    list_serial_ports,
)
from qtools.tec.exceptions import (
    TECConnectionError,
    TECDeviceNotFoundError,
)


def test_mock_serial_transport():
    transport = MockSerialTransport()
    assert transport.is_open
    transport.write("TEC=?@")
    assert transport.read() == "OKTEC=RD105@"

    transport.write("TC1:TG=3000000@")
    assert transport.read() == "OKTC1:TG=3000000@"

    transport.close()
    assert not transport.is_open
    with pytest.raises(TECConnectionError):
        transport.write("TEC=?@")


def test_find_serial_device_success():
    mock_port = MagicMock()
    mock_port.device = "/dev/ttyUSB0"
    mock_port.description = "USB-Serial CH340"
    mock_port.vid = 0x1A86
    mock_port.pid = 0x7523
    mock_port.serial_number = "12345"
    mock_port.manufacturer = "wch.cn"
    mock_port.hwid = "USB VID:PID=1A86:7523"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
        port_path = find_serial_device()
        assert port_path == "/dev/ttyUSB0"


def test_find_serial_device_pattern_match():
    mock_port = MagicMock()
    mock_port.device = "/dev/cu.usbserial-110"
    mock_port.description = "1a86_USB_Serial controller"
    mock_port.vid = None
    mock_port.pid = None
    mock_port.serial_number = None
    mock_port.manufacturer = None
    mock_port.hwid = ""

    with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
        port_path = find_serial_device(pattern="1a86_usb_serial")
        assert port_path == "/dev/cu.usbserial-110"


def test_find_serial_device_not_found():
    with patch("serial.tools.list_ports.comports", return_value=[]):
        with pytest.raises(TECDeviceNotFoundError) as exc_info:
            find_serial_device()
        assert "No TEC serial device found" in str(exc_info.value)


def test_find_serial_device_multiple_found():
    port1 = MagicMock(device="/dev/ttyUSB0", description="CH340", vid=0x1A86, pid=0x7523, hwid="")
    port2 = MagicMock(device="/dev/ttyUSB1", description="CH340", vid=0x1A86, pid=0x7523, hwid="")

    with patch("serial.tools.list_ports.comports", return_value=[port1, port2]):
        with pytest.raises(TECDeviceNotFoundError) as exc_info:
            find_serial_device()
        assert "Multiple matching serial devices found" in str(exc_info.value)


def test_list_serial_ports():
    mock_port = MagicMock()
    mock_port.device = "/dev/ttyUSB0"
    mock_port.description = "USB-Serial"
    mock_port.vid = 0x1A86
    mock_port.pid = 0x7523
    mock_port.serial_number = "abc"
    mock_port.manufacturer = "wch"
    mock_port.hwid = "hw1"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
        ports = list_serial_ports()
        assert len(ports) == 1
        assert ports[0]["device"] == "/dev/ttyUSB0"
        assert ports[0]["vid"] == 0x1A86


def test_serial_transport_invalid_port():
    with pytest.raises(TECConnectionError):
        SerialTransport(port="/nonexistent/port/path")
