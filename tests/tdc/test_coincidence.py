"""Tests for the unified coincidence interface."""

import numpy as np
import pytest

from qtools.tdc.backends.ciqtek.backend import TDC1610Backend
from qtools.tdc.backends.s15_tdc1.exp_backend import ExpS15TDC1Backend
from qtools.tdc.data import G2Result, TimestampResult


def fake_g2(histogram, resolution_ps=1000.0):
    histogram = np.asarray(histogram, dtype=np.uint64)
    return G2Result(
        histogram=histogram,
        bin_edges=np.arange(len(histogram) + 1, dtype=np.float64),
        singles_start=100.0,
        singles_stop=200.0,
        integration_time=1.0,
        resolution_ps=resolution_ps,
    )


def test_software_coincidence_counts_window_and_normalized_background(monkeypatch):
    backend = ExpS15TDC1Backend()
    captured = {}

    def get_g2(**kwargs):
        captured.update(kwargs)
        return fake_g2([1, 2, 10, 3, 1, 2])

    monkeypatch.setattr(backend, "get_g2", get_g2)

    result = backend.get_coincidence(
        duration=1.0,
        ch_start=1,
        ch_stop=2,
        unit="ns",
        window_start=2,
        window_stop=4,
    )

    assert result.count == 13
    assert result.acc_count_perbin == pytest.approx(1.5)
    assert result.accidental_count == pytest.approx(3.0)
    assert result.background_count == pytest.approx(3.0)
    assert result.net_count == pytest.approx(10.0)
    assert result.accidental_method == "sideband"
    assert result.window_start_ps == pytest.approx(2000.0)
    assert result.window_stop_ps == pytest.approx(4000.0)
    assert result.method == "software"
    assert captured["bins"] > 4
    assert "bin_offset" not in captured


def test_software_coincidence_auto_detects_one_peak(monkeypatch, capsys):
    backend = ExpS15TDC1Backend()
    captured = {}

    def get_g2(**kwargs):
        captured.update(kwargs)
        return fake_g2([0, 1, 10, 1, 0])

    monkeypatch.setattr(backend, "get_g2", get_g2)

    result = backend.get_coincidence(duration=1.0)

    assert result.count == 10
    assert result.window_start_ps == pytest.approx(2000.0)
    assert result.window_stop_ps == pytest.approx(3000.0)
    assert "Recommended coincidence window: window_start=2 ns, window_stop=3 ns" in capsys.readouterr().out
    assert captured["bins"] == 500
    assert "bin_offset" not in captured


def test_software_coincidence_rejects_negative_window_start(monkeypatch):
    backend = ExpS15TDC1Backend()
    monkeypatch.setattr(backend, "get_g2", lambda **kwargs: fake_g2([0, 1, 10, 1, 0]))

    with pytest.raises(ValueError, match="use ch_stop_delay"):
        backend.get_coincidence(
            duration=1.0,
            window_start=-1,
            window_stop=1,
        )


def test_peak_width_bins_measures_fwhm():
    from qtools.tdc.backends.base import _peak_width_bins

    # Narrow single-bin spike -> width 1
    assert _peak_width_bins(np.asarray([0, 1, 10, 1, 0], dtype=float), 2) == 1
    # Broad peak: bins 1..4 all at/above half of 10 -> width 4
    assert _peak_width_bins(np.asarray([0, 5, 10, 9, 6, 3, 1], dtype=float), 2) == 4
    # Peak at an edge clamps to the available bins
    assert _peak_width_bins(np.asarray([10, 9, 5, 1, 0], dtype=float), 0) == 3


def test_software_coincidence_selects_highest_of_multiple_peaks(monkeypatch, capsys):
    backend = ExpS15TDC1Backend()

    def get_g2(**kwargs):
        return fake_g2([0, 3, 5, 2, 1])  # two prominent peaks; picks the highest

    monkeypatch.setattr(backend, "get_g2", get_g2)

    result = backend.get_coincidence(duration=1.0)

    assert result.count == 5
    assert result.window_start_ps == pytest.approx(2000.0)
    assert result.window_stop_ps == pytest.approx(3000.0)
    assert "Recommended coincidence window: window_start=2 ns, window_stop=3 ns" in capsys.readouterr().out


def test_tdc1_hardware_pairs_mapping(monkeypatch):
    backend = ExpS15TDC1Backend()
    backend._connected = True
    backend._com = object()
    monkeypatch.setattr(
        backend,
        "get_counts_and_coincidences",
        lambda duration: (100, 200, 300, 400, 11, 12, 13, 14),
    )

    result = backend.get_coincidence(
        duration=2.0,
        ch_start=1,
        ch_stop=4,
        method="hardware",
    )

    assert result.count == 12
    assert result.channel1_rate == pytest.approx(50.0)
    assert result.channel2_rate == pytest.approx(200.0)
    assert result.acc_count_perbin is None
    assert result.accidental_count is None
    assert result.background_count is None
    assert result.method == "hardware"


def test_tdc1_hardware_rejects_unrepresentable_window():
    backend = ExpS15TDC1Backend()
    with pytest.raises(ValueError, match="fixed coincidence gate"):
        backend.get_coincidence(
            duration=1.0,
            ch_start=1,
            ch_stop=3,
            method="hardware",
            window_start=0,
            window_stop=2,
        )


def test_coincidence_does_not_expose_g2_tuning_or_third_channel():
    backend = ExpS15TDC1Backend()

    with pytest.raises(TypeError):
        backend.get_coincidence(duration=1.0, bins=20)
    with pytest.raises(TypeError):
        backend.get_coincidence(duration=1.0, bin_offset=0)
    with pytest.raises(TypeError):
        backend.get_coincidence(duration=1.0, ch_third=3)


def test_ciqtek_hardware_accord_mapping(monkeypatch):
    backend = TDC1610Backend()
    backend._connected = True
    backend._dev = object()
    backend._collecting = False
    calls = []
    monkeypatch.setattr(backend, "set_channel_config", lambda **kwargs: calls.append(("channel", kwargs)))
    monkeypatch.setattr(backend, "configure_accord", lambda *args: calls.append(("accord", args)))
    monkeypatch.setattr(backend, "set_algorithm", lambda value: calls.append(("algorithm", value)))
    monkeypatch.setattr(backend, "start_collect", lambda: calls.append(("start", None)))
    monkeypatch.setattr(backend, "stop_collect", lambda: calls.append(("stop", None)))
    monkeypatch.setattr(backend, "get_accord_counts", lambda: [17, 101, 202, 0])

    result = backend.get_coincidence(
        duration=0.001,
        ch_start=1,
        ch_stop=2,
        unit="ns",
        ch_stop_delay=4,
        window_start=0,
        window_stop=8,
        method="hardware",
    )

    assert result.count == 17
    assert result.channel1_rate == 101
    assert result.channel2_rate == 202
    assert result.window_ps == 8000
    assert result.acc_count_perbin is None
    assert result.accidental_count == pytest.approx(
        101 * 202 * 8e-9 * result.integration_time
    )
    assert result.accidental_method == "rate_product"
    assert ("algorithm", 2) in calls
    assert ("accord", (8000, 1, 2)) in calls
    assert ("channel", {"channels": [2], "delay": 4000}) in calls


def test_ciqtek_hardware_rejects_nonzero_window_start():
    backend = TDC1610Backend()
    with pytest.raises(ValueError, match="window_start is fixed at 0"):
        backend.get_coincidence(
            duration=1.0,
            ch_start=1,
            ch_stop=2,
            window_start=1,
            window_stop=8,
            method="hardware",
        )


def test_ciqtek_hardware_requires_fixed_trigger_channel():
    backend = TDC1610Backend()
    with pytest.raises(ValueError, match="fixed trigger channel 1"):
        backend.get_coincidence(
            duration=1.0,
            ch_start=2,
            ch_stop=3,
            window_start=0,
            window_stop=8,
            method="hardware",
        )


def test_timestamp_live_time_is_independent_of_timestamp_span():
    result = TimestampResult(
        timestamps=np.asarray([1_000_000, 3_000_000], dtype=np.int64),
        channels=np.asarray([1, 2], dtype=np.uint8),
        resolution_ps=1000.0,
        total_time_ns=5_000_000.0,
    )

    assert result.duration_s == pytest.approx(0.005)
    assert result.span_s == pytest.approx(0.000002)
