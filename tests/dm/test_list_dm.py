"""Tests for the human-readable DM discovery facade."""

from __future__ import annotations

import pytest

from qtools import dm as dm_package
from qtools.dm import DeviceInfo, DMError, list_dm
from qtools.dm import dm as dm_module


def _device(*, available: bool = True) -> DeviceInfo:
    return DeviceInfo(
        serial="SERIAL-A",
        model="DMP40-P01",
        manufacturer="Thorlabs",
        resource="USB0::TEST::INSTR",
        available=available,
        index=0,
    )


def test_list_dm_prints_backend_and_constructor(monkeypatch, capsys):
    devices = [_device()]
    monkeypatch.setattr(
        dm_module.DMP40,
        "discover",
        classmethod(lambda cls: list(devices)),
    )

    result = list_dm()

    assert result == devices
    assert result[0].backend == "dmp40"
    assert dm_module.DM(
        backend=result[0].backend,
        serial=result[0].serial,
    ).is_connected is False
    output = capsys.readouterr().out
    assert "[0] backend=dmp40" in output
    assert "manufacturer=Thorlabs" in output
    assert "model=DMP40-P01" in output
    assert "serial=SERIAL-A" in output
    assert "DM(backend='dmp40', serial='SERIAL-A')" in output
    assert dm_package.list_dm is list_dm


def test_list_dm_verbose_false_only_returns_devices(monkeypatch, capsys):
    devices = [_device(available=False)]
    monkeypatch.setattr(
        dm_module.DMP40,
        "discover",
        classmethod(lambda cls: list(devices)),
    )

    assert list_dm(verbose=False) == devices
    assert capsys.readouterr().out == ""


def test_list_dm_reports_empty_discovery(monkeypatch, capsys):
    monkeypatch.setattr(
        dm_module.DMP40,
        "discover",
        classmethod(lambda cls: []),
    )

    assert list_dm() is None
    assert "No connected deformable mirror found." in capsys.readouterr().out


def test_list_dm_rejects_unknown_backend():
    with pytest.raises(ValueError, match="supported DM backend"):
        list_dm(backend="other")


def test_list_dm_returns_none_when_discovery_fails(monkeypatch, capsys):
    def fail(cls):
        raise DMError("discovery unavailable")

    monkeypatch.setattr(dm_module.DMP40, "discover", classmethod(fail))

    assert list_dm() is None
    output = capsys.readouterr().out
    assert "DM discovery failed: DMError: discovery unavailable" in output

