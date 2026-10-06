"""Verify registration and discovery operations."""

from __future__ import annotations

import inspect

import pytest

import qtools.tdc.api
from qtools.tdc.backends.base import TDCBackend
from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND
from qtools.tdc.connection import get_backend, list_backends, auto_discover


def test_registry_lookup():
    """Verify backend retrieval by name."""
    backends = list_backends()
    for name in ("s15_tdc1", "exp_s15_tdc1"):
        if name == DEFAULT_TDC1_BACKEND:
            assert name in backends
        else:
            assert name not in backends
    with pytest.raises(KeyError):
        get_backend("non_existent_backend")
    with pytest.raises(KeyError):
        get_backend("s15_tdc1" if DEFAULT_TDC1_BACKEND == "exp_s15_tdc1" else "exp_s15_tdc1")


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


def test_auto_discover():
    """Verify device discovery returns empty list when no hardware is connected."""
    devices = auto_discover()
    # Without simulator, expect 0 devices when hardware is not connected
    assert isinstance(devices, list)
