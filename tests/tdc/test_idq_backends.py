"""Tests for IDQ TDC backends (ID801 and ID1000)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from qtools.tdc.backends.base import BackendCapability
from qtools.tdc.backends.idq import ID801Backend, ID1000Backend, IDQBackend
from qtools.tdc.connection import get_backend, list_backends
from qtools.tdc.data import SinglesResult, CoincidenceResult, G2Result


def test_idq_backends_registration():
    """Verify both ID801 and ID1000 are registered in the global registry."""
    backends = list_backends()
    assert "id1000" in backends
    assert "idq_id1000" in backends
    assert "id801" in backends
    assert "idq" in backends
    assert "idq_id801" in backends

    assert get_backend("id1000") is ID1000Backend
    assert get_backend("idq_id1000") is ID1000Backend
    assert get_backend("id801") is ID801Backend
    assert get_backend("idq") is ID801Backend
    assert IDQBackend is ID801Backend


def test_id1000_properties():
    """Verify ID1000 backend properties and capabilities."""
    dev = ID1000Backend()
    assert dev.name == "id1000"
    assert dev.vendor == "IDQ (ID Quantique)"
    assert dev.channel_count == 5
    assert dev.resolution_ps == 1.0
    assert not dev.is_connected()

    # Check capabilities
    assert BackendCapability.SINGLES in dev.capabilities
    assert BackendCapability.COINCIDENCE in dev.capabilities
    assert BackendCapability.HIST_HARDWARE in dev.capabilities
    assert BackendCapability.TIMESTAMPS in dev.capabilities
    assert BackendCapability.THRESHOLD_CONTROL in dev.capabilities


def test_id801_properties():
    """Verify ID801 backend properties and capabilities."""
    dev = ID801Backend()
    assert dev.name == "id801"
    assert dev.vendor == "IDQ (ID Quantique)"
    assert dev.channel_count == 8
    assert dev.resolution_ps == 81.0
    assert not dev.is_connected()


def test_id1000_safe_discovery():
    """Verify safe discovery executes without crashing or performing broad subnet scans."""
    devices = ID1000Backend.discover_devices()
    assert isinstance(devices, list)


@patch("socket.socket")
@patch("zmq.Context")
def test_id1000_connect_and_scpi(mock_zmq_ctx, mock_socket):
    """Test ID1000 connect and SCPI command execution with mocked ZMQ."""
    # Mock tcp pre-check socket
    mock_s = MagicMock()
    mock_socket.return_value = mock_s

    # Mock zmq socket
    mock_sock = MagicMock()
    mock_ctx_inst = MagicMock()
    mock_ctx_inst.socket.return_value = mock_sock
    mock_zmq_ctx.return_value = mock_ctx_inst

    # Mock SCPI responses
    mock_sock.recv.side_effect = [
        b"IDQ ID1000 Time Controller\n",  # *IDN?
        b"1\n",                           # DEVIce:RESolution HIRES (or DEVI:RES:BWID?)
        b"1\n",                           # DEVI:RES:BWID?
    ]

    dev = ID1000Backend()
    dev.connect("169.254.99.100")
    assert dev.is_connected()
    assert dev.resolution_ps == 1.0

    dev.disconnect()
    assert not dev.is_connected()


@patch("socket.socket")
@patch("zmq.Context")
def test_id1000_get_singles(mock_zmq_ctx, mock_socket):
    """Test get_singles SCPI queries."""
    mock_sock = MagicMock()
    mock_ctx_inst = MagicMock()
    mock_ctx_inst.socket.return_value = mock_sock
    mock_zmq_ctx.return_value = mock_ctx_inst

    # Connect handshake mocks
    mock_sock.recv.side_effect = [
        b"IDQ ID1000\n",
        b"1\n",
        b"1\n",
        # get_singles setup response
        b"\n",
        # get_singles count query response (5 lines: ch1..4, start)
        b"1000\n2000\n3000\n4000\n50000\n",
    ]

    dev = ID1000Backend()
    dev.connect("169.254.99.100")

    singles = dev.get_singles(integration_time=0.1)
    assert isinstance(singles, SinglesResult)
    assert singles.integration_time == 0.1
    np.testing.assert_array_equal(singles.counts, [1000, 2000, 3000, 4000, 50000])
    assert singles.count_rates[0] == 10000.0


@patch("socket.socket")
@patch("zmq.Context")
def test_id1000_get_coincidence_hardware(mock_zmq_ctx, mock_socket):
    """Test hardware-accelerated 2-fold coincidence counting."""
    mock_sock = MagicMock()
    mock_ctx_inst = MagicMock()
    mock_ctx_inst.socket.return_value = mock_sock
    mock_zmq_ctx.return_value = mock_ctx_inst

    mock_sock.recv.side_effect = [
        b"IDQ ID1000\n",
        b"1\n",
        b"1\n",
        # get_coincidence hardware commands:
        b"\n",  # DEVI:CONFI:LOAD COUNT
        b"\n",  # DELA6:VALU
        b"\n",  # DELA7:VALU
        b"\n",  # DELA8:VALU
        b"\n",  # TSCO6:WIND:BEGI:DELA 0
        b"\n",  # TSCO6:WIND:END:DELA 10000
        b"\n",  # TSCO6:COUN:MODE
        b"\n",  # INPU1:COUN:MODE
        b"\n",  # INPU2:COUN:MODE
        b"125\n",   # TSCO6:COUNter? (coincidences)
        b"10000\n", # INPU1:COUNter?
        b"20000\n", # INPU2:COUNter?
    ]

    dev = ID1000Backend()
    dev.connect("169.254.99.100")

    coinc = dev.get_coincidence(
        duration=0.1,
        ch_start=1,
        ch_stop=2,
        window_start=0,
        window_stop=10,
        unit="ns",
        method="hardware",
    )
    assert isinstance(coinc, CoincidenceResult)
    assert coinc.count == 125
    assert coinc.method == "hardware"
    assert coinc.order == 2


@patch("socket.socket")
@patch("zmq.Context")
def test_id1000_get_g2_hardware(mock_zmq_ctx, mock_socket):
    """Test hardware Start-Stop histogram calculation."""
    mock_sock = MagicMock()
    mock_ctx_inst = MagicMock()
    mock_ctx_inst.socket.return_value = mock_sock
    mock_zmq_ctx.return_value = mock_ctx_inst

    mock_sock.recv.side_effect = [
        b"IDQ ID1000\n",
        b"1\n",
        b"1\n",
        # get_g2 commands
        b"\n",  # DEVIce:CONF:LOAD HISTO
        b"\n",  # HIST1:REF:LINK
        b"\n",  # HIST1:STOP:LINK
        b"\n",  # REC:...
        b"\n",  # REC:DURation
        b"\n",  # HIST1:BCOUnt...
        b"\n",  # REC:PLAY
        b"IDLE\n",  # REC:STAGe?
        b"[0, 5, 20, 150, 20, 5, 0]\n",  # HIST1:DATA?
        b"1000\n",  # start singles
        b"2000\n",  # stop singles
    ]

    dev = ID1000Backend()
    dev.connect("169.254.99.100")

    with pytest.raises(NotImplementedError):
        dev.get_g2(duration=0.1, method="hardware")

    g2 = dev.get_hardware_histogram(
        duration=0.1,
        bins=7,
        ch_start=1,
        ch_stop=2,
    )
    assert isinstance(g2, G2Result)
    assert g2.integration_time == 0.1
    np.testing.assert_array_equal(g2.histogram, [0, 5, 20, 150, 20, 5, 0])
