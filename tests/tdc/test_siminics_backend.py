from __future__ import annotations

from qtools.tdc.backends.siminics import (
    SiminicsBackend,
    parse_blocks,
    parse_bytes,
    parse_file,
    parse_words,
)
from qtools.tdc.connection import get_backend


def test_siminics_is_registered_and_marker_words_are_sideband_events():
    assert get_backend("siminics") is SiminicsBackend

    parsed = parse_bytes(
        bytes.fromhex("EB90B712 02006AAB 82000000 86000000 FE000354 EEEEDDDD"),
        mode="T2",
        resolution_ps=64,
    )

    assert parsed.channels.tolist() == [2]
    assert parsed.timestamps.tolist() == [1_747_712]
    assert [marker.mask for marker in parsed.markers] == [0x1, 0x3]
    assert parsed.overflow_count == 1
    assert [event.kind for event in parsed.events] == [
        "channel",
        "marker",
        "marker",
        "overflow",
    ]


def test_siminics_t3_marker_and_sync_overflow():
    parsed = parse_words(
        [0x01095000, 0x84000000, 0xFE0002D4, 0x01095001],
        mode="T3",
        resolution_ps=64,
        sync_period_ps=100_000,
    )

    assert parsed.channels.tolist() == [1, 1]
    assert parsed.markers[0].mask == 0x2
    assert parsed.events[0].sync_index == 0
    assert parsed.events[-1].sync_index == (0x2D4 + 1) * 1024 + 1


def test_siminics_parser_reads_binary_files(tmp_path):
    path = tmp_path / "capture.t2"
    path.write_bytes(bytes.fromhex("EB90B712 02006AAB 82000000 EEEEDDDD"))

    parsed = parse_file(path, mode="T2", resolution_ps=64)

    assert parsed.channels.tolist() == [2]
    assert parsed.markers[0].mask == 1


def test_siminics_parser_joins_memory_blocks_before_decoding():
    parsed = parse_blocks(
        [bytes.fromhex("EB90B712 02006AAB"), bytes.fromhex("82000000 EEEEDDDD")],
        mode="T2",
        resolution_ps=64,
    )

    assert parsed.channels.tolist() == [2]
    assert parsed.markers[0].mask == 1


class _FakeSDK:
    loaded = True

    def __init__(self):
        self.blocks = [
            (0, bytes.fromhex("EB90B712 02006AAB 82000000 EEEEDDDD"))
        ]
        self.polls = 0
        self.calls = []

    def load(self):
        return self

    def init(self):
        self.calls.append(("init",))

    def uninit(self):
        self.calls.append(("uninit",))

    def connected(self, dev_id):
        return True

    def device_type(self, dev_id):
        return 0x1040

    def check(self, name, *args, **kwargs):
        self.calls.append((name, *args))
        return 0

    def invoke(self, name, *args):
        self.calls.append((name, *args))
        if name == "IsTaskCompleted":
            self.polls += 1
            return 0 if self.polls > 1 else 1
        return 0

    def get_memory_data(self, dev_id):
        return self.blocks.pop(0) if self.blocks else None


def test_siminics_backend_preserves_marker_events_with_fake_sdk():
    sdk = _FakeSDK()
    backend = SiminicsBackend(sdk=sdk, poll_interval=0, task_timeout=1)
    backend.connect()
    result = backend.get_timestamps(0.1)

    assert result.channels.tolist() == [2]
    assert backend.get_last_markers()[0].mask == 1
    assert [event.kind for event in backend.get_tttr_events()] == ["channel", "marker"]
    assert ("SetMemoryDataMode", False) in sdk.calls

