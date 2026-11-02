from __future__ import annotations

from types import SimpleNamespace

import serial

from qtools.tdc.backends.s15_tdc1 import exp_backend


class _ProbeSerial:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = list(chunks or [])
        self.closed = False
        self.writes: list[bytes] = []
        self.timeout: float | None = None
        self.write_timeout: float | None = None

    @property
    def in_waiting(self) -> int:
        return len(self.chunks[0]) if self.chunks else 0

    def reset_input_buffer(self) -> None:
        return None

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def read(self, size: int = 1) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        return chunk[:size]

    def close(self) -> None:
        self.closed = True


def test_probe_reads_tdc_response_and_closes(monkeypatch) -> None:
    fake = _ProbeSerial([b"TDC1\n"])

    def fake_serial(*args, **kwargs):
        fake.timeout = kwargs.get("timeout")
        fake.write_timeout = kwargs.get("write_timeout")
        return fake

    monkeypatch.setattr(exp_backend.serial, "Serial", fake_serial)

    assert exp_backend._probe_tdc1_serial("COM7", timeout=0.25)
    assert fake.writes == [b"*IDN?\n"]
    assert fake.timeout == 0.1
    assert fake.write_timeout == 0.1
    assert fake.closed


def test_probe_has_hard_deadline_without_terminator(monkeypatch) -> None:
    fake = _ProbeSerial([b"X", b"X", b"X", b"X"])
    monkeypatch.setattr(exp_backend.serial, "Serial", lambda *args, **kwargs: fake)
    ticks = iter([0.0, 0.05, 0.3])
    monkeypatch.setattr(exp_backend.time, "monotonic", lambda: next(ticks))

    assert not exp_backend._probe_tdc1_serial("COM8", timeout=0.25)
    assert fake.closed


def test_probe_closes_port_when_open_or_read_fails(monkeypatch) -> None:
    fake = _ProbeSerial()

    def fail_read(size: int) -> bytes:
        raise serial.SerialException("device disappeared")

    fake.read = fail_read  # type: ignore[method-assign]
    monkeypatch.setattr(exp_backend.serial, "Serial", lambda *args, **kwargs: fake)
    ticks = iter([0.0, 0.01])
    monkeypatch.setattr(exp_backend.time, "monotonic", lambda: next(ticks))

    assert not exp_backend._probe_tdc1_serial("COM9", timeout=0.25)
    assert fake.closed


def test_find_tdc1_devices_skips_non_tdc_serial_ports(monkeypatch) -> None:
    thorlabs = SimpleNamespace(
        device="COM3",
        description="APT USB Device Serial Port",
        manufacturer="Thorlabs",
        serial_number="55119234",
        vid=0x0403,
        pid=0xFAF0,
    )
    fake = _ProbeSerial([b"TDC1\n"])
    monkeypatch.setattr(
        "serial.tools.list_ports.comports",
        lambda: [thorlabs],
    )
    monkeypatch.setattr(exp_backend.serial, "Serial", lambda *args, **kwargs: fake)

    assert exp_backend.find_tdc1_devices() == []
    assert not fake.closed


def test_probe_hard_timeout_when_driver_ignores_read_timeout(monkeypatch) -> None:
    fake = _ProbeSerial()

    def blocking_read(size: int) -> bytes:
        import time

        time.sleep(0.6)
        return b""

    fake.read = blocking_read  # type: ignore[method-assign]
    monkeypatch.setattr(exp_backend.serial, "Serial", lambda *args, **kwargs: fake)

    started = exp_backend.time.monotonic()
    assert not exp_backend._probe_tdc1_serial("COM10", timeout=0.05)
    elapsed = exp_backend.time.monotonic() - started

    assert elapsed < 0.5
    assert fake.closed
