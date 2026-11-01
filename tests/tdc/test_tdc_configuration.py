"""Verify public TDC construction, analysis bin widths, and hardware listing."""

from unittest.mock import MagicMock

import numpy as np
import pytest

import qtools.tdc as tdc_package
from qtools.tdc import TDC, api, connection, get_tdc, list_tdc
from qtools.tdc.backends.s15_tdc1.exp_backend import ExpS15TDC1Backend
from qtools.tdc.data import DeviceInfo, TimestampResult


class OneNsBackend(ExpS15TDC1Backend):
    """Provide deterministic timestamps with a one-nanosecond native resolution."""

    @property
    def resolution_ps(self):
        return 1000


@pytest.fixture
def backend(monkeypatch):
    result = OneNsBackend()
    timestamps = TimestampResult(
        timestamps=np.array([0, 1000, 3000, 3500], dtype=np.int64),
        channels=np.array([1, 2, 2, 3], dtype=np.uint8),
        resolution_ps=1000,
        total_time_ns=1e9,
    )
    monkeypatch.setattr(result, "get_timestamps", MagicMock(return_value=timestamps))
    monkeypatch.setattr(result, "connect", MagicMock())
    monkeypatch.setattr(result, "disconnect", MagicMock())
    return result


@pytest.mark.parametrize("factory", [TDC, get_tdc])
@pytest.mark.parametrize("name", ["s15_tdc1", "exp_s15_tdc1"])
def test_named_construction(factory, name):
    device = factory(backend=name, port="fake://tdc", bin_width=2_000)
    assert device.backend.name == name
    assert device.backend._device_path == "fake://tdc"
    assert device.bin_width == 2_000
    assert not device.backend.is_connected()
    assert not hasattr(tdc_package, "get_device")


@pytest.mark.parametrize("factory", [TDC, get_tdc])
def test_discovered_device_and_backend_options(factory, monkeypatch):
    class ConfiguredBackend(OneNsBackend):
        def __init__(self, path, *, label):
            super().__init__(path)
            self.label = label

    monkeypatch.setattr(connection, "_REGISTRY", {"fake": ConfiguredBackend})
    info = DeviceInfo("fake", "fake://tdc")
    device = factory(info, bin_width=2_000, label="test")
    assert device.backend._device_path == info.device_path
    assert device.backend.label == "test"
    assert device.bin_width == 2_000
    with pytest.raises(TypeError, match="port must be omitted"):
        factory(info, port="another-path")


def test_bin_width_changes_histogram_and_can_be_overridden(backend):
    device = TDC(backend, bin_width=2_000)
    result = device.measure_g2(1, 1, 2, bins=4, samples=2)
    assert result.bin_width == 2_000
    assert result.samples == 2
    for histogram, edges in zip(result.histogram, result.bin_edges):
        np.testing.assert_array_equal(histogram, [1, 1, 0, 0])
        np.testing.assert_array_equal(edges, [0, 2000, 4000, 6000, 8000])

    finer = device.measure_g2(1, 1, 2, bins=4, bin_width=1_000)
    np.testing.assert_array_equal(finer.histogram[0], [0, 1, 0, 1])
    assert device.bin_width == 2_000
    assert backend.resolution_ps == 1_000
    assert backend.get_timestamps.return_value.resolution_ps == 1_000
    assert TDC(backend).measure_g2(1, 1, 2, bins=4).bin_width == 1_000


def test_coincidence_window_and_delay_use_the_selected_width(backend):
    device = TDC(backend, bin_width=2_000)
    result = device.measure_coincidence(
        1,
        1,
        2,
        window_start=-1,
        window_stop=1,
        ch_stop_delay=-2,
        unit="ns",
        samples=2,
    )
    assert result.bin_width == 2_000
    assert result.stop_delay == [-2_000, -2_000]
    assert result.window_start == [-2_000, -2_000]
    assert result.window_stop == [2_000, 2_000]
    assert result.raw_counts == [2, 2]
    assert result.raw_pair_rate_mean == 2
    assert result.raw_pair_rate_std == 0
    for edges in result.bin_edges:
        assert edges[0] == -2_000
        np.testing.assert_array_equal(np.diff(edges), 2_000)


@pytest.mark.parametrize("width", [1_000, 2_000])
def test_automatic_window_repetitions_keep_the_selected_width(backend, width):
    backend.get_timestamps.return_value = TimestampResult(
        timestamps=np.array([0, 4000, 4000, 4000], dtype=np.int64),
        channels=np.array([1, 2, 2, 2], dtype=np.uint8),
        resolution_ps=1000,
        total_time_ns=1e9,
    )
    result = TDC(backend, bin_width=width).measure_coincidence(1, samples=2)
    assert result.bin_width == width
    assert result.window_start == [4_000, 4_000]
    assert result.window_stop == [4_000 + width, 4_000 + width]
    assert result.raw_counts == [3, 3]
    np.testing.assert_array_equal(result.bin_edges[0], result.bin_edges[1])


def test_hardware_scalar_counter_retains_configured_analysis_width(
    backend, monkeypatch
):
    backend._connected = True
    backend._com = object()
    monkeypatch.setattr(
        backend,
        "get_counts_and_coincidences",
        lambda duration: (10, 20, 30, 40, 5, 6, 7, 8),
    )
    result = TDC(backend, bin_width=4_000).measure_coincidence(
        1, ch_start=1, ch_stop=3, method="hardware"
    )
    assert result.bin_width == 4_000
    assert result.raw_counts == [5]
    assert result.histogram is None
    assert result.window_width is None
    assert backend.resolution_ps == 1_000
    backend.get_timestamps.assert_not_called()


@pytest.mark.parametrize(
    "method,channels",
    [
        ("measure_triplet", {"ch_ref": 1, "ch_sig1": 2, "ch_sig2": 3}),
        ("measure_gate", {"ch_ref": 1, "ch_signals": [2, 3]}),
        ("measure_heralding_gate", {"heralding_channel": 1, "gated_channels": [2, 3]}),
    ],
)
def test_multi_channel_and_heralding_windows_share_the_default_width(
    backend, method, channels
):
    device = TDC(backend, bin_width=2_000)
    result = getattr(device, method)(1, bins=2, samples=2, **channels)
    assert result.bin_width == 2_000
    assert result.window_start == [0, 0]
    assert result.window_stop == [4_000, 4_000]
    if method == "measure_triplet":
        assert result.raw_counts == [2, 2]
    elif method == "measure_gate":
        assert result.raw_counts == [1, 1]
    else:
        assert result.raw_counts == {2: [2, 2], 3: [1, 1]}

    finer = getattr(device, method)(1, bins=2, bin_width=1_000, **channels)
    assert finer.window_stop == [2_000]
    if method != "measure_heralding_gate":
        assert finer.raw_counts == [0]
    else:
        assert finer.raw_counts == {2: [1], 3: [0]}


def test_pairs_delay_is_measured_in_configured_bins(backend):
    device = TDC(backend, bin_width=2_000)
    result = device.measure_pairs(
        1,
        1,
        2,
        bins=150,
        delay=1,
        window_start=1,
        window_stop=2,
    )
    np.testing.assert_array_equal(result["histogram"][:4], [0, 1, 1, 0])
    np.testing.assert_array_equal(result["bin_edges"], np.arange(151))


@pytest.mark.parametrize(
    "width", [0, -1, 1.5, float("nan"), float("inf"), True, "2000"]
)
def test_invalid_width_fails_before_acquisition(backend, width):
    with pytest.raises(ValueError, match="bin_width"):
        TDC(backend, bin_width=width)
    device = TDC(backend)
    for measure, channels in [
        (device.measure_g2, {"ch_start": 1, "ch_stop": 2}),
        (device.measure_coincidence, {}),
        (device.measure_triplet, {"ch_ref": 1, "ch_sig1": 2, "ch_sig2": 3}),
        (device.measure_gate, {"ch_ref": 1, "ch_signals": [2, 3]}),
        (
            device.measure_heralding_gate,
            {"heralding_channel": 1, "gated_channels": [2, 3]},
        ),
    ]:
        with pytest.raises(ValueError, match="bin_width"):
            measure(1, bin_width=width, **channels)
    backend.get_timestamps.assert_not_called()


@pytest.mark.parametrize(
    "measure,channels",
    [
        (api.g2, {"ch_start": 1, "ch_stop": 2}),
        (api.coincidence, {"window_start": 0, "window_stop": 4}),
        (api.triplet, {"ch_ref": 1, "ch_sig1": 2, "ch_sig2": 3}),
        (api.gate, {"ch_ref": 1, "ch_signals": [2, 3]}),
        (api.heralding_gate, {"heralding_channel": 1, "gated_channels": [2, 3]}),
    ],
)
def test_one_shot_measurements_accept_bin_width(
    backend, monkeypatch, measure, channels
):
    monkeypatch.setattr(api, "get_tdc", lambda *args: TDC(backend))
    result = measure(duration=1, bin_width=2_000, samples=2, **channels)
    assert result.bin_width == 2_000
    assert result.samples == 2
    backend.connect.assert_called_once()
    backend.disconnect.assert_called_once()


def test_list_tdc_scans_prints_and_returns_device_records(monkeypatch, capsys):
    devices = [DeviceInfo("fake", "fake://tdc", "SN-001", "Test TDC", "usb")]
    discover = MagicMock(return_value=devices)
    monkeypatch.setattr(connection, "discover_all", discover)
    assert list_tdc(method="usb") is devices
    discover.assert_called_once_with(method="usb", timeout=1.0)
    output = capsys.readouterr().out
    for text in ["Discovered devices (1)", "fake://tdc", "SN-001", "Test TDC"]:
        assert text in output


def test_list_tdc_handles_no_hardware(monkeypatch, capsys):
    monkeypatch.setattr(connection, "discover_all", lambda **kwargs: [])
    assert list_tdc() == []
    assert "No devices found" in capsys.readouterr().out
