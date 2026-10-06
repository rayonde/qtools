"""Verify backend interface correctness."""

from __future__ import annotations

import inspect

import pytest

from qtools.tdc.backends.base import TDCBackend, BackendCapability
from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND
from qtools.tdc.connection import list_backends


def test_backend_capability_members():
    """Keep the public backend capability vocabulary explicit."""
    assert set(BackendCapability.__members__) == {
        "SINGLES",
        "TIMESTAMPS",
        "HIST_HARDWARE",
        "HIST_SOFTWARE",
        "COINCIDENCE",
        "COINCIDENCE_SOFTWARE",
        "THRESHOLD_CONTROL",
    }


def test_backends_inherit_abc():
    """Verify all registered backends inherit from TDCBackend."""
    backends = list_backends()
    assert len(backends) > 0

    for name, cls in backends.items():
        assert issubclass(cls, TDCBackend), f"Backend class {cls.__name__} does not inherit from TDCBackend"


def test_backends_use_optional_threshold_channel():
    """Threshold values are required; channel is optional for global devices."""
    for cls in list_backends().values():
        params = list(inspect.signature(cls.set_threshold).parameters.values())
        assert [param.name for param in params] == ["self", "threshold", "channel"]
        assert params[1].default is inspect.Parameter.empty
        assert params[2].default is None
        assert not hasattr(cls, "threshold_is_global")


def test_backends_use_single_g2_method_selector():
    """All backends expose one g2 entry point with software as the default."""
    for cls in list_backends().values():
        params = list(inspect.signature(cls.get_g2).parameters.values())
        assert params[-1].name == "method"
        assert params[-1].default == "software"

        backend = cls()
        with pytest.raises(NotImplementedError):
            backend.get_g2(duration=0.1, method="hardware")
        with pytest.raises(ValueError):
            backend.get_g2(duration=0.1, method="invalid")


@pytest.mark.parametrize(
    "backend_name",
    [DEFAULT_TDC1_BACKEND, "s15_tdc2", "tdc1610", "idq"],
)
def test_backend_capabilities(backend_name):
    """Verify capabilities are properly exposed."""
    backends = list_backends()
    assert backend_name in backends
    
    cls = backends[backend_name]
    backend = cls()
    
    assert isinstance(backend.name, str)
    assert isinstance(backend.vendor, str)
    assert isinstance(backend.channel_count, int)
    assert isinstance(backend.capabilities, BackendCapability)
