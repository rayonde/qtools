"""Behavioral contracts for repeated TDC analysis and marker persistence."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from qtools.tdc import api
from qtools.tdc.analysis import g2 as analysis
from qtools.tdc.backends.s15_tdc1.exp_backend import ExpS15TDC1Backend
from qtools.tdc.data import (
    CoincidenceResult,
    HeraldingGateResult,
    MarkerEvent,
    MultiCoincidenceResult,
    TimestampResult,
    combine_samples,
    convert_time_unit,
    load_hdf5,
    load_ts_binary,
    save_hdf5,
    save_ts_binary,
    time_to_ps,
)
from qtools.tdc.measurement import TDC


def window_result(**changes):
    values = dict(
        mode="window_count",
        bin_width=1000,
        channel_start=2,
        channel_stop=7,
        counts_start=[20],
        counts_stop=[40],
        singles_start=[10.0],
        singles_stop=[20.0],
        integration_time=[2.0],
        stop_delay=[-1000],
        window_start=[0],
        window_stop=[5000],
        raw_counts=[10],
        accidental_counts=[2.0],
        accidental_method=["rate_product"],
    )
    values.update(changes)
    return CoincidenceResult(**values)


def acquisition():
    return TimestampResult(
        timestamps=np.array([0, 1000, 4000, 5000, 6000, 20000], dtype=np.int64),
        channels=np.array([0, 2, 0, 2, 7, 0], dtype=np.uint8),
        resolution_ps=1000,
        total_time_ns=1e9,
    )


def heralded(**options):
    ts = acquisition()
    return analysis.compute_gate_photons(
        ts.timestamps,
        ts.channels,
        ch_gate=0,
        ch_photons=[2, 7],
        bins=10,
        resolution_ps=1000,
        integration_time=ts.duration_s,
        **options,
    )


def multi_data():
    return np.array([0, 1, 2, 3, 4, 10, 11, 12], dtype=np.int64), np.array(
        [0, 2, 2, 5, 7, 0, 2, 5],
        dtype=np.uint8,
    )


def test_repetitions_use_each_live_time_and_sample_standard_deviation():
    first = window_result()
    second = window_result(
        counts_start=[30],
        counts_stop=[60],
        singles_start=[30.0],
        singles_stop=[60.0],
        integration_time=[1.0],
        raw_counts=[20],
        accidental_counts=[4.0],
    )
    result = combine_samples([first, second])
    assert result.samples == 2
    assert result.bin_width == 1000
    assert result.raw_pair_rate == [5.0, 20.0]
    assert result.net_pair_rate == [4.0, 16.0]
    assert result.raw_pair_rate_mean == 12.5
    assert result.net_pair_rate_mean == 10.0
    assert result.raw_pair_rate_std == pytest.approx(np.std([5, 20], ddof=1))
    assert result.net_pair_rate_std == pytest.approx(np.std([4, 16], ddof=1))
    assert first.raw_pair_rate_std is None
    assert first.net_pair_rate_std is None
    assert result.window_n_bins == [5, 5]
    assert not hasattr(result, "raw_pair_rate_var")


def test_unknown_background_stays_unknown_and_negative_net_is_preserved():
    unknown = window_result(accidental_counts=None, accidental_method=None)
    assert unknown.net_counts is None
    assert unknown.net_pair_rate_mean is None
    assert unknown.net_pair_rate_std is None
    assert window_result(accidental_counts=[12.0]).net_counts == [-2.0]


@pytest.mark.parametrize(
    "changes",
    [
        {"samples": 0},
        {"samples": True},
        {"samples": 2},
        {"bin_width": [1000]},
        {"integration_time": [0]},
        {"integration_time": [np.nan]},
        {"counts_start": None},
        {"singles_start": [1.0]},
        {"raw_counts": None},
        {"window_stop": None},
        {"window_start": [6000]},
        {"stop_delay": [1.5]},
        {"accidental_method": None},
        {"unit": "s"},
        {"channel_stop": 2},
    ],
)
def test_invalid_pair_metadata_is_rejected(changes):
    with pytest.raises(ValueError):
        window_result(**changes)


def test_combining_samples_rejects_changed_settings_and_partial_optional_data():
    first = window_result()
    for second in [
        window_result(stop_delay=[0]),
        window_result(window_stop=[6000]),
        window_result(bin_width=500),
        window_result(channel_stop=5),
        window_result(accidental_counts=None, accidental_method=None),
    ]:
        with pytest.raises(ValueError):
            combine_samples([first, second])
    with pytest.raises(ValueError):
        combine_samples([])


def test_hardware_unknown_counts_and_fixed_gate_are_explicit():
    result = window_result(
        method="hardware",
        counts_start=None,
        counts_stop=None,
        window_start=None,
        window_stop=None,
    )
    assert result.counts_start is None
    assert result.window_width is None
    assert result.raw_pair_rate == [5.0]


def test_histogram_metadata_and_normalization_are_physical():
    result = analysis.compute_g2(
        np.array([0, 1000, 2000], dtype=np.int64),
        np.array([2, 7, 7], dtype=np.uint8),
        2,
        7,
        bins=4,
        resolution_ps=1000,
        bin_offset=-1,
        integration_time=2,
        stop_delay=-1000,
    )
    assert result.mode == "histogram"
    assert result.stop_delay == [-1000]
    assert result.stop_offset == [-1000]
    np.testing.assert_array_equal(result.bin_edges[0], [-1000, 0, 1000, 2000, 3000])
    np.testing.assert_array_equal(result.histogram[0], [0, 1, 1, 0])
    np.testing.assert_allclose(result.normalized[0], [0, 1e9, 1e9, 0])
    converted = convert_time_unit(result, "ns")
    assert converted.bin_width == 1
    assert converted.stop_delay == [-1]
    np.testing.assert_allclose(converted.normalized[0], result.normalized[0])
    np.testing.assert_array_equal(
        convert_time_unit(converted, "ps").bin_edges[0], result.bin_edges[0]
    )
    for changes in [
        {"histogram": None},
        {"n_bins": [5]},
        {"stop_offset": [0]},
        {"bin_edges": [result.bin_edges[0].astype(float)]},
        {"histogram": [result.histogram[0].astype(np.int64)]},
    ]:
        with pytest.raises(ValueError):
            replace(result, **changes)
    with pytest.raises(ValueError):
        convert_time_unit(result, "us")


def test_zero_singles_normalization_is_finite():
    result = analysis.compute_g2(
        np.array([], dtype=np.int64),
        np.array([], dtype=np.uint8),
        2,
        7,
        bins=2,
        resolution_ps=1,
        integration_time=1,
    )
    np.testing.assert_array_equal(result.normalized[0], [0.0, 0.0])


def test_sub_bin_stop_delay_is_applied_once_before_quantization():
    result = analysis.compute_g2(
        np.array([0, 900], dtype=np.int64),
        np.array([2, 7], dtype=np.uint8),
        2,
        7,
        bins=3,
        resolution_ps=1000,
        integration_time=1,
        stop_delay=200,
    )
    np.testing.assert_array_equal(result.histogram[0], [0, 1, 0])
    assert result.stop_delay == [200]
    assert time_to_ps(1, "ms") == 1_000_000_000
    assert time_to_ps(0.5, "ns") == 500
    with pytest.raises(ValueError):
        time_to_ps(0.5, "ps")


def test_heralding_sub_bin_delay_is_applied_before_quantization():
    result = analysis.compute_gate_photons(
        np.array([0, 900], dtype=np.int64),
        np.array([0, 2], dtype=np.uint8),
        ch_gate=0,
        ch_photons=[2],
        bins=3,
        resolution_ps=1000,
        integration_time=1,
        stop_delay={2: 200},
        store_events=True,
    )
    np.testing.assert_array_equal(result.histogram[2][0], [0, 1, 0])
    assert result.gate_hits(0, 0) == [(1000, 2)]
    assert result.stop_delay == {2: [200]}


@pytest.mark.parametrize("native", [False, True])
def test_multi_channel_ids_directed_axes_and_distinct_count_definitions(
    monkeypatch, native
):
    if not native:
        monkeypatch.setattr(analysis, "_LIBCOINC", None)
    timestamps, channels = multi_data()
    triplet = analysis.compute_triplet_g2(
        timestamps,
        channels,
        0,
        2,
        5,
        bins=5,
        resolution_ps=1,
        integration_time=1,
        store_events=True,
    )
    gate = analysis.compute_gate_coincidence(
        timestamps,
        channels,
        0,
        [2, 5, 7],
        bins=5,
        resolution_ps=1,
        integration_time=1,
        store_events=True,
    )
    assert isinstance(triplet, MultiCoincidenceResult)
    assert triplet.channels == (0, 2, 5)
    assert set(triplet.pairwise_hists) == {(0, 2), (0, 5), (2, 5), (5, 2)}
    assert triplet.raw_counts == [3]
    assert triplet.count_mode == "combinations"
    assert len(triplet.events[0]) == 3
    np.testing.assert_array_equal(triplet.pair_hist(2, 5)[0], [0, 2, 1, 0, 0])
    np.testing.assert_array_equal(triplet.pair_hist(5, 2)[0], np.zeros(5))
    assert gate.raw_counts == [1]
    assert gate.count_mode == "reference_events"
    assert gate.histogram_scope == "all_pair_hits"
    assert len(gate.events[0]) == 2
    assert gate.events[0] == [((0, 1, 3, 4), 0), ((0, 2, 3, 4), 0)]
    assert gate.pair_hist(0, 2)[0].sum() == 3
    assert gate.net_coincidence_rate is None
    assert gate.raw_coincidence_rate_std is None
    with pytest.raises(ValueError):
        replace(gate, channels=(0, 2, 5))
    with pytest.raises(ValueError):
        replace(gate, channel_delays={0: [1], 2: [0], 5: [0], 7: [0]})


def test_multi_summary_omits_events_and_dedup_does_not_change_combination_count(
    monkeypatch,
):
    monkeypatch.setattr(analysis, "_LIBCOINC", None)
    args = (
        np.array([0, 1, 1, 2], dtype=np.int64),
        np.array([0, 2, 2, 5], dtype=np.uint8),
    )
    result = analysis.compute_triplet_g2(
        *args, 0, 2, 5, bins=5, resolution_ps=1000, integration_time=1, deduplicate=True
    )
    assert result.raw_counts == [2]
    assert result.pair_hist(0, 2)[0].sum() == 1
    assert result.events is None
    other_group = analysis.compute_triplet_g2(
        *args, 7, 2, 5, bins=5, resolution_ps=1000, integration_time=1
    )
    groups = {result.channels: result, other_group.channels: other_group}
    assert groups[(0, 2, 5)].pair_hist(2, 5)[0].sum() == 1
    assert groups[(7, 2, 5)].pair_hist(2, 5)[0].sum() == 0
    with pytest.raises(ValueError):
        combine_samples([result, other_group])


def test_multi_repetition_statistics_and_event_conversion():
    ts = np.array([0, 1000, 2000], dtype=np.int64)
    ch = np.array([0, 2, 5], dtype=np.uint8)
    first = analysis.compute_triplet_g2(
        ts,
        ch,
        0,
        2,
        5,
        bins=5,
        resolution_ps=1000,
        integration_time=1,
        bin_offset=-1,
        store_events=True,
    )
    second = analysis.compute_triplet_g2(
        ts,
        ch,
        0,
        2,
        5,
        bins=5,
        resolution_ps=1000,
        integration_time=2,
        bin_offset=-1,
        store_events=True,
    )
    result = combine_samples([first, second])
    assert result.raw_coincidence_rate == [1.0, 0.5]
    assert result.raw_coincidence_rate_mean == 0.75
    assert result.raw_coincidence_rate_std == pytest.approx(np.std([1, 0.5], ddof=1))
    assert result.stop_offset[(0, 2)] == [-1000, -1000]
    assert result.stop_offset[(2, 5)] == [0, 0]
    converted = convert_time_unit(result, "ns")
    assert converted.events == [[((0, 1, 2), 0)], [((0, 1, 2), 0)]]
    assert converted.channel_delays == {0: [0, 0], 2: [0, 0], 5: [0, 0]}
    assert converted.counts == result.counts
    with pytest.raises(ValueError):
        replace(result, bin_edges={(0, 2): result.bin_edges[(0, 2)]})


@pytest.mark.parametrize("detail_format", ["flat", "per_gate"])
def test_heralding_partial_hits_overlap_and_empty_gates(detail_format):
    result = heralded(store_events=True, detail_format=detail_format)
    assert isinstance(result, HeraldingGateResult)
    assert result.heralding_channel == 0
    assert result.gated_channels == (2, 7)
    assert result.n_gates == [3]
    assert result.raw_counts == {2: [3], 7: [2]}
    assert result.total_photons == [5]
    assert result.gate_hits(0, 0) == [(1000, 2), (5000, 2), (6000, 7)]
    assert result.gate_hits(0, 1) == [(1000, 2), (2000, 7)]
    assert result.gate_hits(0, 2) == []
    assert result.histogram[2][0].sum() == 3
    converted = convert_time_unit(result, "ns")
    assert converted.gate_hits(0, 0) == [(1, 2), (5, 2), (6, 7)]
    if detail_format == "flat":
        assert result.per_gate is None
        np.testing.assert_array_equal(result.flat_offsets[0], [0, 3, 5, 5])
        np.testing.assert_array_equal(converted.flat_offsets[0], result.flat_offsets[0])
    else:
        assert result.flat_photons is None
    with pytest.raises(IndexError):
        result.gate_hits(1, 0)


def test_heralding_summary_retains_counts_and_each_channel_statistics():
    first = heralded(store_histogram=False)
    second = replace(
        first,
        integration_time=[2.0],
        singles_heralding=[1.5],
        singles_gated={2: [1.0], 7: [0.5]},
    )
    result = combine_samples([first, second])
    assert result.samples == 2
    assert result.histogram is None
    assert result.flat_photons is None
    assert result.per_gate is None
    assert result.gate_hits(0, 0) is None
    assert result.n_gates == [3, 3]
    assert result.raw_pair_rate == {2: [3.0, 1.5], 7: [2.0, 1.0]}
    assert result.raw_pair_rate_mean == {2: 2.25, 7: 1.5}
    assert result.raw_pair_rate_std[2] == pytest.approx(np.std([3, 1.5], ddof=1))
    assert first.raw_pair_rate_std is None
    assert result.net_pair_rate is None
    assert result.net_pair_rate_std is None
    known = replace(
        result,
        accidental_counts={2: [1.0, 1.0], 7: [1.0, 1.0]},
        accidental_method={2: ["rate_product"] * 2, 7: ["rate_product"] * 2},
    )
    assert known.net_pair_rate_mean == {2: 1.5, 7: 0.75}
    assert known.net_pair_rate_std[7] == pytest.approx(np.std([1, 0.5], ddof=1))


def test_zero_heralds_and_zero_photons_are_distinct_from_missing_details():
    result = analysis.compute_gate_photons(
        np.array([], dtype=np.int64),
        np.array([], dtype=np.uint8),
        0,
        [2, 7],
        bins=3,
        resolution_ps=1,
        integration_time=1,
        store_events=True,
    )
    assert result.n_gates == [0]
    assert result.total_photons == [0]
    np.testing.assert_array_equal(result.flat_offsets[0], [0])
    empty = analysis.compute_gate_photons(
        np.array([1, 2], dtype=np.int64),
        np.array([0, 0], dtype=np.uint8),
        0,
        [2, 7],
        bins=3,
        resolution_ps=1,
        integration_time=1,
        store_events=True,
    )
    assert empty.gate_hits(0, 0) == []
    assert empty.n_gates == [2]
    with pytest.raises(ValueError):
        replace(result, raw_counts={2: [1], 7: [0]})


@pytest.mark.parametrize(
    "changes",
    [
        {"gated_channels": [2, 7]},
        {"gated_channels": (0, 2)},
        {"raw_counts": {2: [3]}},
        {"raw_counts": {2: [4], 7: [2]}},
        {"flat_offsets": [np.array([0, 3, 5], dtype=np.int64)]},
        {"flat_offsets": [np.array([0, 3, 6, 5], dtype=np.int64)]},
        {"flat_channels": [np.array([2, 2, 7, 2, 99], dtype=np.int32)]},
        {"flat_photons": None},
        {"bin_edges": None},
        {"per_gate": [[[], [], []]]},
    ],
)
def test_heralding_rejects_invalid_roles_details_and_counts(changes):
    with pytest.raises(ValueError):
        replace(heralded(store_events=True), **changes)


@pytest.mark.parametrize(
    "markers",
    [
        None,
        [],
        [
            MarkerEvent(mask=3, photon_index=0, timestamp_ps=None, stream_index=0),
            MarkerEvent(mask=1, photon_index=1, timestamp_ps=0, stream_index=2),
            MarkerEvent(mask=8, photon_index=1, timestamp_ps=None, stream_index=3),
            MarkerEvent(mask=2, photon_index=6, timestamp_ps=24000, stream_index=9),
        ],
    ],
)
@pytest.mark.parametrize(
    "save,load,extension",
    [(save_ts_binary, load_ts_binary, ".ts"), (save_hdf5, load_hdf5, ".h5")],
)
def test_marker_storage_preserves_availability_boundaries_and_timing(
    tmp_path, markers, save, load, extension
):
    original = replace(acquisition(), markers=markers)
    path = tmp_path / ("capture" + extension)
    save(path, original)
    result = load(path)
    np.testing.assert_array_equal(result.timestamps, original.timestamps)
    np.testing.assert_array_equal(result.channels, original.channels)
    assert result.markers == markers
    assert result.resolution_ps == original.resolution_ps
    assert result.total_time_ns == original.total_time_ns


@pytest.mark.parametrize(
    "markers",
    [
        [MarkerEvent(0, 0)],
        [MarkerEvent(1, 7)],
        [MarkerEvent(1, 2), MarkerEvent(2, 1)],
        [MarkerEvent(1, 0, stream_index=2), MarkerEvent(2, 0, stream_index=1)],
    ],
)
def test_invalid_marker_positions_are_rejected(markers):
    with pytest.raises(ValueError):
        replace(acquisition(), markers=markers)


def test_measurement_repeats_in_same_class_and_uses_actual_live_times():
    acquisitions = iter([acquisition(), replace(acquisition(), total_time_ns=2e9)])
    backend = SimpleNamespace(get_timestamps=lambda duration: next(acquisitions))
    result = TDC(backend).measure_heralding_gate(1, 0, [2, 7], bins=10, samples=2)
    assert isinstance(result, HeraldingGateResult)
    assert result.integration_time == [1, 2]
    assert result.raw_pair_rate_mean[2] == 2.25
    assert result.samples == 2
    with pytest.raises(ValueError):
        TDC(backend).measure_heralding_gate(1, 0, [2, 7], samples=0)


@pytest.mark.parametrize(
    "function,options,model",
    [
        (api.g2, {"ch_start": 0, "ch_stop": 2}, CoincidenceResult),
        (
            api.coincidence,
            {"ch_start": 0, "ch_stop": 2, "window_start": 0, "window_stop": 10},
            CoincidenceResult,
        ),
        (
            api.triplet,
            {"ch_ref": 0, "ch_sig1": 2, "ch_sig2": 7},
            MultiCoincidenceResult,
        ),
        (api.gate, {"ch_ref": 0, "ch_signals": [2, 7]}, MultiCoincidenceResult),
        (
            api.heralding_gate,
            {"heralding_channel": 0, "gated_channels": [2, 7]},
            HeraldingGateResult,
        ),
    ],
)
def test_public_measurements_keep_the_same_model_when_repeating(
    monkeypatch, function, options, model
):
    captures = iter([acquisition(), replace(acquisition(), total_time_ns=2e9)])
    backend = ExpS15TDC1Backend()
    monkeypatch.setattr(backend, "get_timestamps", lambda duration: next(captures))
    monkeypatch.setattr(backend, "connect", lambda: None)
    monkeypatch.setattr(backend, "disconnect", lambda: None)
    monkeypatch.setattr(api, "get_tdc", lambda *args: TDC(backend))
    result = function(duration=1, samples=2, **options)
    assert isinstance(result, model)
    assert result.samples == 2
    assert result.integration_time == [1, 2]
    assert result.unit == "ps"
    assert result.bin_width == 1000


def test_automatic_window_is_fixed_when_the_peak_moves_between_samples(monkeypatch):
    backend = ExpS15TDC1Backend()
    calls = []

    def acquire_histogram(**kwargs):
        calls.append(kwargs)
        duration = len(calls)
        hist = np.zeros(kwargs["bins"], dtype=np.uint64)
        hist[2:4] = [10, 1] if duration == 1 else [2, 20]
        return CoincidenceResult(
            mode="histogram",
            channel_start=0,
            channel_stop=2,
            bin_width=1000,
            counts_start=[100 * duration],
            counts_stop=[200 * duration],
            singles_start=[100.0],
            singles_stop=[200.0],
            integration_time=[duration],
            stop_delay=[0],
            n_bins=[len(hist)],
            stop_offset=[0],
            histogram=[hist],
            bin_edges=[np.arange(len(hist) + 1, dtype=np.int64) * 1000],
        )

    monkeypatch.setattr(backend, "get_g2", acquire_histogram)
    result = TDC(backend).measure_coincidence(1, ch_start=0, ch_stop=2, samples=2)
    assert result.window_start == [2000, 2000]
    assert result.window_stop == [3000, 3000]
    assert result.raw_counts == [10, 2]
    assert result.raw_pair_rate == [10, 1]
    assert result.raw_pair_rate_mean == 5.5
    assert [call["bins"] for call in calls] == [500, 500]
    np.testing.assert_array_equal(result.bin_edges[0], result.bin_edges[1])
