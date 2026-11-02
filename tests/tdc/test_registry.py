"""Verify registration and discovery operations."""

from __future__ import annotations

import inspect
import time

import pytest

import qtools.tdc.api
import qtools.tdc.connection as connection
from qtools.tdc.backends.base import TDCBackend
from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND
from qtools.tdc.connection import get_backend, list_backends
from qtools.tdc.data import DeviceInfo


def test_registry_lookup():
    """Verify backend retrieval by name."""
    backends = list_backends()
    assert DEFAULT_TDC1_BACKEND in backends
    for name in ("s15_tdc1", "exp_s15_tdc1"):
        assert issubclass(get_backend(name), TDCBackend)
    with pytest.raises(KeyError):
        get_backend("non_existent_backend")


def test_default_backend_matches_selection():
    """Verify the public one-shot API uses the configured TDC1 backend."""
    for name in ("count_rate", "singles", "g2", "pairs", "triplet", "gate"):
        func = getattr(qtools.tdc.api, name)
        default = inspect.signature(func).parameters["backend"].default
        assert default == DEFAULT_TDC1_BACKEND


def test_cli_default_backend_matches_selection():
    """Verify the CLI uses the configured TDC1 backend."""
    from qtools.tdc.cli import make_parser

    assert make_parser().parse_args([]).backend == DEFAULT_TDC1_BACKEND


def test_auto_discover(monkeypatch):
    """Verify auto-discovery aggregates backend results without probing hardware."""
    expected = DeviceInfo(
        backend_name="fake_tdc",
        device_path="fake://tdc-1",
        serial_number="TEST-001",
        description="Fake TDC for registry tests",
    )

    class FakeBackend:
        @classmethod
        def discover_devices(cls):
            return [expected]

    monkeypatch.setattr(connection, "_REGISTRY", {"fake_tdc": FakeBackend})
    devices = connection.auto_discover()
    assert devices == [expected]


def test_auto_discover_skips_blocking_backend(monkeypatch):
    class HangingBackend:
        @classmethod
        def discover_devices(cls):
            time.sleep(0.5)
            return []

    monkeypatch.setattr(connection, "_REGISTRY", {"hanging": HangingBackend})
    started = time.monotonic()
    devices = connection.auto_discover(timeout=0.05)
    elapsed = time.monotonic() - started

    assert devices == []
    assert elapsed < 0.3


def test_auto_discover_scans_duplicate_class_once(monkeypatch):
    calls = 0

    class FakeBackend:
        @classmethod
        def discover_devices(cls):
            nonlocal calls
            calls += 1
            return []

    monkeypatch.setattr(
        connection,
        "_REGISTRY",
        {"fake_a": FakeBackend, "fake_b": FakeBackend},
    )

    assert connection.auto_discover(timeout=0.1) == []
    assert calls == 1
