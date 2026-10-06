from types import SimpleNamespace

import numpy as np
import pytest

from qtools.tdc.cli import (
    _plot_coincidence_samples,
    _validate_command_args,
    make_parser,
    monitor_coincidences,
    monitor_pairs,
)
from qtools.tdc.data import CoincidenceResult, G2Result


def pair_result():
    return {
        "histogram": np.asarray([1, 4, 2], dtype=np.uint64),
        "bin_edges": np.asarray([0, 1, 2, 3], dtype=np.float64),
        "integration_time": 1.0,
        "net_pair_rate": 10.0,
        "acc_pair_rate": 2.0,
        "start_rate": 100.0,
        "stop_rate": 200.0,
        "eff_start": 0.1,
        "eff_stop": 0.05,
        "eff_avg": 0.071,
    }


def test_pairs_cli_returns_histogram_and_maps_legacy_bin_options(capsys):
    calls = []

    class FakeApi:
        def measure_pairs(self, **kwargs):
            calls.append(kwargs)
            return pair_result()

    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=4,
        bins=20,
        ws=3,
        we=5,
        delay=2,
        bin_offset=0,
        histogram=0,
        plot=False,
        hardware=False,
        export=None,
        raw=None,
    )

    result = monitor_pairs(args)

    assert np.array_equal(result["histogram"], [1, 4, 2])
    assert calls == [
        {
            "duration": 1.0,
            "ch_start": 1,
            "ch_stop": 4,
            "bins": 20,
            "window_start": 3,
            "window_stop": 5,
            "delay": 2,
            "bin_offset": 0,
        }
    ]
    assert "Peak bin: 1, count: 4" in capsys.readouterr().out


def test_pairs_bin_offset_maps_to_bin_offset():
    calls = []

    class FakeApi:
        def measure_pairs(self, **kwargs):
            calls.append(kwargs)
            return pair_result()

    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=4,
        bins=20,
        ws=3,
        we=5,
        delay=0,
        bin_offset=7,
        histogram=0,
        plot=False,
        hardware=False,
        export=None,
        raw=None,
    )

    monitor_pairs(args)
    assert calls[0]["bin_offset"] == 7


def test_pairs_hardware_uses_hardware_counter(capsys):
    calls = []

    class FakeApi:
        def measure_coincidence(self, **kwargs):
            calls.append(kwargs)
            return CoincidenceResult(
                count=12,
                channel1_rate=50.0,
                channel2_rate=200.0,
                integration_time=2.0,
                method="hardware",
            )

    args = SimpleNamespace(
        api=FakeApi(),
        time=2.0,
        ch_start=1,
        ch_stop=3,
        ws=None,
        we=None,
        delay=0,
        hardware=True,
    )

    result = monitor_pairs(args)

    assert calls == [
        {"duration": 2.0, "ch_start": 1, "ch_stop": 3, "method": "hardware"}
    ]
    assert result.count == 12
    assert "Coincidence pairs (hardware): 12" in capsys.readouterr().out


def test_pairs_hardware_rejects_delay():
    args = SimpleNamespace(
        api=object(),
        time=1.0,
        ch_start=1,
        ch_stop=3,
        ws=None,
        we=None,
        delay=5,
        hardware=True,
    )

    with pytest.raises(ValueError, match="--hardware does not support --delay"):
        monitor_pairs(args)


def test_delay_alias_stop_delay():
    parser = make_parser()
    assert parser.parse_args(["pairs", "--delay", "3"]).delay == 3
    assert parser.parse_args(["pairs", "--stop_delay", "3"]).delay == 3


def test_coincidences_cli_prints_requested_samples():
    calls = []

    class FakeApi:
        def measure_pairs(self, **kwargs):
            calls.append(kwargs)
            return pair_result()

    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=2,
        ws=3,
        we=5,
        delay=2,
        auto=False,
        hardware=False,
        samples=2,
        export=None,
    )

    results = monitor_coincidences(args)

    assert len(results) == 2
    assert len(calls) == 2
    assert all(call["window_start"] == 3 for call in calls)
    assert all(call["window_stop"] == 5 for call in calls)
    assert all(call["delay"] == 2 for call in calls)


def test_coincidences_cli_displays_efficiency_as_percent(capsys):
    class FakeApi:
        def measure_pairs(self, **kwargs):
            return pair_result()

    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=2,
        ws=3,
        we=5,
        delay=2,
        auto=False,
        hardware=False,
        samples=1,
        export=None,
    )

    monitor_coincidences(args)

    out = capsys.readouterr().out
    assert "S1/S2" in out
    assert "0.500" in out
    assert "10.00" in out
    assert "5.00" in out
    assert "7.10" in out


def test_coincidences_cli_colors_pairs_and_efficiencies(capsys, monkeypatch):
    class FakeApi:
        def measure_pairs(self, **kwargs):
            return pair_result()

    def fake_style(text, *args, **kwargs):
        return f"<{kwargs.get('fg')}>{text}</{kwargs.get('fg')}>"

    monkeypatch.setattr("tdc.cli.style", fake_style)
    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=2,
        ws=3,
        we=5,
        delay=2,
        auto=False,
        hardware=False,
        samples=1,
        export=None,
    )

    monitor_coincidences(args)

    out = capsys.readouterr().out
    assert "<green>10.0</green>" in out
    assert "<blue>10.00</blue>" in out
    assert "<blue>5.00</blue>" in out


def test_coincidences_plot_records_all_samples(monkeypatch):
    class FakeApi:
        def measure_pairs(self, **kwargs):
            return pair_result()

    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=4,
        samples=3,
        export=None,
        plot=True,
    )
    calls = []

    def fake_plot(args, results):
        calls.append((args, results))

    monkeypatch.setattr("tdc.cli._plot_coincidence_samples", fake_plot)

    results = monitor_coincidences(
        SimpleNamespace(
            **vars(args),
            ws=3,
            we=5,
            delay=2,
            auto=False,
            hardware=False,
        )
    )

    assert len(results) == 3
    assert len(calls) == 1
    called_args, called_results = calls[0]
    assert called_args.samples == 3
    assert called_results == results


def test_plot_coincidence_samples_has_pairs_and_singles_subplots(monkeypatch):
    import matplotlib.pyplot as plt

    fig = SimpleNamespace()
    ax_pairs = SimpleNamespace(
        plot=lambda *args, **kwargs: None,
        set_ylabel=lambda *args, **kwargs: None,
        set_title=lambda *args, **kwargs: None,
    )
    ax_singles = SimpleNamespace(
        plot=lambda *args, **kwargs: None,
        set_xlabel=lambda *args, **kwargs: None,
        set_ylabel=lambda *args, **kwargs: None,
        set_title=lambda *args, **kwargs: None,
        legend=lambda *args, **kwargs: None,
    )
    fig.tight_layout = lambda: None
    monkeypatch.setattr(
        plt, "subplots", lambda *args, **kwargs: (fig, (ax_pairs, ax_singles))
    )
    monkeypatch.setattr(plt, "show", lambda: None)

    args = SimpleNamespace(ch_start=1, ch_stop=4, hardware=False)
    _plot_coincidence_samples(args, [pair_result(), pair_result()])


def test_coincidences_auto_detects_window_and_prints(capsys):
    class FakeApi:
        backend = SimpleNamespace(resolution_ps=2000.0)

        def measure_g2(self, **kwargs):
            return G2Result(
                histogram=np.asarray([0, 1, 10, 1, 0], dtype=np.uint64),
                bin_edges=np.arange(6, dtype=np.float64),
                singles_start=100.0,
                singles_stop=200.0,
                integration_time=1.0,
                resolution_ps=2000.0,
            )

        def measure_pairs(self, **kwargs):
            calls.append(kwargs)
            return pair_result()

    calls = []
    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=2,
        ws=None,
        we=None,
        delay=0,
        auto=True,
        hardware=False,
        samples=1,
        export=None,
    )

    results = monitor_coincidences(args)

    assert len(results) == 1
    assert calls[0]["window_start"] == 1
    assert calls[0]["window_stop"] == 3
    assert "Auto-detected coincidence window: window_start=1, window_stop=3" in (
        capsys.readouterr().out
    )


def test_coincidences_auto_sizes_window_to_peak_width(capsys):
    class FakeApi:
        backend = SimpleNamespace(resolution_ps=2000.0)

        def measure_g2(self, **kwargs):
            # Broad peak spanning ~5 bins (FWHM): window should be wider than
            # the narrow-peak case above, not a fixed +/- 5.
            return G2Result(
                histogram=np.asarray([0, 0, 1, 3, 8, 6, 4, 2, 1, 0], dtype=np.uint64),
                bin_edges=np.arange(11, dtype=np.float64),
                singles_start=100.0,
                singles_stop=200.0,
                integration_time=1.0,
                resolution_ps=2000.0,
            )

        def measure_pairs(self, **kwargs):
            calls.append(kwargs)
            return pair_result()

    calls = []
    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=2,
        ws=None,
        we=None,
        delay=0,
        auto=True,
        hardware=False,
        samples=1,
        export=None,
    )

    results = monitor_coincidences(args)

    assert len(results) == 1
    assert calls[0]["window_start"] == 2
    assert calls[0]["window_stop"] == 6
    assert "Auto-detected coincidence window: window_start=2, window_stop=6" in (
        capsys.readouterr().out
    )


def test_coincidences_auto_conflicts_with_window():
    args = SimpleNamespace(ws=3, we=None, auto=True)
    with pytest.raises(ValueError, match="--auto cannot be combined"):
        from qtools.tdc.cli import _resolve_coincidence_window

        _resolve_coincidence_window(args)


def test_coincidences_requires_window_or_auto():
    args = SimpleNamespace(ws=None, we=None, auto=False)
    with pytest.raises(ValueError, match="requires --window-start and --window-stop"):
        from qtools.tdc.cli import _resolve_coincidence_window

        _resolve_coincidence_window(args)


def test_coincidences_hardware_loop():
    calls = []

    class FakeApi:
        def measure_coincidence(self, **kwargs):
            calls.append(kwargs)
            return CoincidenceResult(
                count=12,
                channel1_rate=50.0,
                channel2_rate=200.0,
                integration_time=2.0,
                method="hardware",
            )

    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=3,
        ws=None,
        we=None,
        delay=0,
        auto=False,
        hardware=True,
        samples=2,
        export=None,
    )

    results = monitor_coincidences(args)

    assert len(results) == 2
    assert len(calls) == 2
    assert all(call["method"] == "hardware" for call in calls)


def test_removed_cli_options_are_not_defined():
    parser = make_parser()
    args = parser.parse_args(["pairs"])

    assert not hasattr(args, "no_color")
    assert not hasattr(args, "average")
    assert not hasattr(args, "peak")
    assert not hasattr(args, "left")
    assert not hasattr(args, "right")
    assert not hasattr(args, "avgtime")
    assert not hasattr(args, "histogram")


def test_coincidences_rejects_bins():
    parser = make_parser()
    args = parser.parse_args(["coincidences", "--bins", "20"])

    with pytest.raises(SystemExit):
        _validate_command_args(parser, args, ["coincidences", "--bins", "20"])


def test_coincidences_rejects_bin_offset():
    parser = make_parser()
    args = parser.parse_args(["coincidences", "--bin_offset", "5"])

    with pytest.raises(SystemExit):
        _validate_command_args(parser, args, ["coincidences", "--bin_offset", "5"])


def test_pairs_rejects_auto():
    parser = make_parser()
    args = parser.parse_args(["pairs", "--auto"])

    with pytest.raises(SystemExit):
        _validate_command_args(parser, args, ["pairs", "--auto"])


def test_coincidences_software_export_flushes_each_row(tmp_path):
    export_path = tmp_path / "coincidences.csv"
    observed_during_run = []

    class FakeApi:
        def __init__(self):
            self.calls = 0

        def measure_pairs(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                observed_during_run.append(export_path.read_text(encoding="utf-8"))
            return pair_result()

    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=2,
        ws=3,
        we=5,
        delay=2,
        auto=False,
        hardware=False,
        samples=2,
        export=str(export_path),
        plot=False,
    )

    monitor_coincidences(args)

    assert len(observed_during_run) == 1
    lines = observed_during_run[0].splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("TIME,")
    assert "S1/S2" in lines[0]


def test_coincidences_hardware_export_flushes_each_row(tmp_path):
    export_path = tmp_path / "coincidences_hardware.csv"
    observed_during_run = []

    class FakeApi:
        def __init__(self):
            self.calls = 0

        def measure_coincidence(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                observed_during_run.append(export_path.read_text(encoding="utf-8"))
            return CoincidenceResult(
                count=12,
                channel1_rate=50.0,
                channel2_rate=200.0,
                integration_time=2.0,
                method="hardware",
            )

    args = SimpleNamespace(
        api=FakeApi(),
        time=1.0,
        ch_start=1,
        ch_stop=3,
        ws=None,
        we=None,
        delay=0,
        auto=False,
        hardware=True,
        samples=2,
        export=str(export_path),
        plot=False,
    )

    monitor_coincidences(args)

    assert len(observed_during_run) == 1
    lines = observed_during_run[0].splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("TIME,")
    assert "S1/S2" in lines[0]
