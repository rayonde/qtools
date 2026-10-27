"""Isolated SDK contract tests: fabricated patterns are not optical simulations."""

from __future__ import annotations

import ctypes as ct
import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from qtools.dm import (
    DM,
    DMP40,
    DMCapabilityError,
    DMConnectionError,
    DMDependencyError,
    DMDriverError,
    DMDriverWarning,
    DMError,
    TipTilt,
    ZernikeMode,
    zernike_vector,
)
from qtools.dm.backends.Thorlabs.DMP40 import sdk as sdk_module
from qtools.dm.backends.Thorlabs.DMP40.sdk import (
    DMP40SDK,
    ViBoolean,
    ViInt32,
    ViReal64,
    ViSession,
    ViUInt32,
)


def assign(pointer, kind, value):
    ct.cast(pointer, ct.POINTER(kind))[0] = value


class FakeFunction:
    def __init__(self, sdk, name):
        self.sdk = sdk
        self.name = name

    def __call__(self, *args):
        self.sdk.calls.append((self.name, args))
        if self.name in self.sdk.failures:
            return self.sdk.failures[self.name]
        return self.sdk.invoke(self.name, *args)


class FakeLibraries:
    """Strict fake of the vendor entry points, with explicitly synthetic data."""

    def __init__(self):
        self.calls = []
        self.failures = {}
        self.devices = [(b"DMP40", b"SERIAL-A", b"USB::A", True)]
        self.segment_count = 40
        self.tilt_count = 3
        self.zernike_count = 12
        self.amplitude_minimum = -1.0
        self.amplitude_maximum = 1.0
        self.last_vector = None
        self.last_single = None
        self.last_polar = None
        self.segment_writes = []
        self.tilt_writes = []
        self.bad_pattern = False
        self.remaining = [1, 0]
        self.relax_targets = []
        self.base, self.extended = SimpleNamespace(), SimpleNamespace()
        for name in sdk_module._SIGNATURES:
            lib = self.extended if name.startswith("TLDFMX_") else self.base
            setattr(lib, name, FakeFunction(self, name))

    def sdk(self):
        return DMP40SDK(libraries=(self.base, self.extended))

    def names(self):
        return [name for name, _ in self.calls]

    def invoke(self, name, *args):
        if name.endswith("error_message"):
            args[2].value = b"Synthetic SDK status"
        elif name == "TLDFM_get_device_count":
            assign(args[1], ViUInt32, len(self.devices))
        elif name == "TLDFM_get_device_information":
            _, index, manufacturer, model, serial, available, resource = args
            model.value, serial.value, resource.value, ready = self.devices[index]
            manufacturer.value = b"Thorlabs"
            assign(available, ViBoolean, ready)
        elif name == "TLDFMX_init":
            assert args[1:3] == (1, 0)  # ID query, no implicit device reset
            assign(args[3], ViSession, 123)
        elif name == "TLDFMX_close":
            pass
        elif name == "TLDFM_get_segment_count":
            assign(args[1], ViUInt32, self.segment_count)
        elif name == "TLDFM_get_tilt_count":
            assign(args[1], ViUInt32, self.tilt_count)
        elif name.endswith("_minimum"):
            assign(args[1], ViReal64, 0)
        elif name.endswith("_maximum"):
            assign(args[1], ViReal64, 300)
        elif name == "TLDFMX_get_parameters":
            for ptr, kind, val in zip(
                args[1:],
                [ViReal64, ViReal64, ViInt32, ViInt32, ViInt32],
                [
                    self.amplitude_minimum,
                    self.amplitude_maximum,
                    self.zernike_count,
                    4,
                    2,
                ],
            ):
                assign(ptr, kind, val)
        elif name == "TLDFMX_set_pattern_range_check":
            assert args[1] == 1
        elif name in (
            "TLDFMX_calculate_single_zernike_pattern",
            "TLDFMX_calculate_zernike_pattern",
        ):
            if "single" in name:
                self.last_single = args[1:3]
            else:
                assert args[1] == 0xFFFFFFFF
                self.last_vector = tuple(args[2])
                assert len(self.last_vector) == 12
            # Isolated test pattern, intentionally not a voltage calibration.
            for index in range(self.segment_count):
                args[-1][index] = 60 + index
            if self.bad_pattern:
                args[-1][0] = 301
        elif name == "TLDFM_set_segment_voltages":
            self.segment_writes.append(tuple(args[1]))
        elif name == "TLDFM_set_tilt_voltages":
            self.tilt_writes.append(tuple(args[1]))
        elif name == "TLDFM_set_tilt_amplitude_angle":
            self.last_polar = args[1:]
        elif name == "TLDFMX_relax":
            _, target, first, reload, mirror, arms, remaining = args
            self.relax_targets.append((target, first, reload))
            for i in range(self.segment_count):
                mirror[i] = 50
            for i in range(self.tilt_count):
                arms[i] = 60
            assign(remaining, ViInt32, self.remaining.pop(0) if self.remaining else 1)
        elif name == "TLDFM_get_segment_voltages":
            for i in range(self.segment_count):
                args[1][i] = 60
        elif name == "TLDFM_get_tilt_voltages":
            for i in range(self.tilt_count):
                args[1][i] = 70
        else:
            raise AssertionError(f"Unhandled fake entry point: {name}")
        return 0


@pytest.fixture
def hardware():
    fake = FakeLibraries()
    dm = DMP40(sdk=fake.sdk())
    yield dm, fake
    fake.failures.clear()
    dm.close()


def test_all_mode_indices_match_vendor_flags_and_named_modes():
    # Explicit reference values prevent accidental Noll/Thorlabs conflation.
    expected = [
        ("astigmatism_45", 4, 5, (2, -2), 0x001),
        ("defocus", 5, 4, (2, 0), 0x002),
        ("astigmatism_0", 6, 6, (2, 2), 0x004),
        ("trefoil_y", 7, 9, (3, -3), 0x008),
        ("coma_x", 8, 8, (3, 1), 0x010),
        ("coma_y", 9, 7, (3, -1), 0x020),
        ("trefoil_x", 10, 10, (3, 3), 0x040),
        ("tetrafoil_y", 11, 15, (4, -4), 0x080),
        ("secondary_astigmatism_y", 12, 13, (4, -2), 0x100),
        ("spherical", 13, 11, (4, 0), 0x200),
        ("secondary_astigmatism_x", 14, 12, (4, 2), 0x400),
        ("tetrafoil_x", 15, 14, (4, 4), 0x800),
    ]
    for name, thor, noll, nm, flag in expected:
        mode = ZernikeMode(name)
        assert (mode.thorlabs_index, mode.noll_index, mode.nm, mode.flag) == (
            thor,
            noll,
            nm,
            flag,
        )
        assert ZernikeMode.from_thorlabs(thor) is mode
        assert ZernikeMode.from_noll(noll) is mode
        assert ZernikeMode.from_nm(*nm) is mode


def test_vector_packing_rejects_ambiguous_indices_and_bad_amplitudes():
    assert zernike_vector({"defocus": 0.1, "spherical": -0.2}) == (
        0,
        0.1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        -0.2,
        0,
        0,
    )
    for coefficients in [{4: 0.1}, {"defocus": True}, {"defocus": "0.1"}]:
        with pytest.raises(TypeError):
            zernike_vector(coefficients)
    for coefficients in [
        {"piston": 0.1},
        {"defocus": math.nan},
        {"defocus": 1.1},
        {"defocus": math.inf},
        {"DEFOCUS": 0.1, "defocus": 0.2},
    ]:
        with pytest.raises(ValueError):
            zernike_vector(coefficients)
    for converter, index in [
        (ZernikeMode.from_noll, 2),
        (ZernikeMode.from_thorlabs, 16),
    ]:
        with pytest.raises(ValueError):
            converter(index)
    with pytest.raises(ValueError):
        ZernikeMode.from_nm(5, 1)


@pytest.mark.parametrize(
    "x,y,angle", [(1, 0, 0), (0, 1, 90), (-1, 0, 180), (0, -1, -90), (0, 0, 0)]
)
def test_pointing_quadrants(x, y, angle):
    command = TipTilt(x, y)
    assert command.azimuth_deg == angle
    assert command.amplitude == math.hypot(x, y)
    polar = TipTilt.from_polar(command.amplitude, command.azimuth_deg)
    assert (polar.x, polar.y) == pytest.approx((x, y), abs=1e-14)


def test_pointing_rejects_outside_disk_and_nonfinite():
    for values in [(1, 1), (math.nan, 0), (0, math.inf)]:
        with pytest.raises(ValueError):
            TipTilt(*values)
    with pytest.raises(TypeError):
        TipTilt(True, 0)
    for angle in range(360):
        assert TipTilt.from_polar(1, angle).amplitude <= 1


def test_lazy_import_and_construction_do_not_load_libraries():
    code = """
import ctypes, sys
def forbidden(*a, **k): raise AssertionError('DLL loaded during import')
ctypes.CDLL = forbidden
import qtools
assert 'qtools.dm' not in sys.modules
from qtools import dm
assert dm.DM().is_connected is False
assert 's15lib' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True)


def test_windows_visa_abi_is_fixed_width_and_bool_pointers_are_16_bit(hardware):
    dm, fake = hardware
    dm.connect()
    assert ct.sizeof(ViSession) == 4
    assert ct.sizeof(ViInt32) == 4
    assert ct.sizeof(ViBoolean) == 2
    assert fake.extended.TLDFMX_init.argtypes == [
        ct.c_char_p,
        ViBoolean,
        ViBoolean,
        ct.POINTER(ViSession),
    ]
    assert fake.base.TLDFM_get_device_information.argtypes[-2] == ct.POINTER(ViBoolean)
    assert fake.extended.TLDFMX_close.restype == ct.c_int32


def test_discovery_and_connection_do_not_change_outputs(hardware):
    dm, fake = hardware
    assert not fake.calls
    assert dm.connect() is dm
    assert dm.info.serial == "SERIAL-A"
    assert dm.capabilities.segment_count == 40
    assert dm.zernikes is None and dm.tip_tilt is None
    assert not fake.segment_writes and not fake.tilt_writes
    assert "TLDFMX_relax" not in fake.names()
    dm.connect()
    assert fake.names().count("TLDFMX_init") == 1
    dm.close()
    dm.close()
    assert not dm.is_connected
    assert fake.names().count("TLDFMX_close") == 1


def test_selection_requires_unambiguous_available_device():
    fake = FakeLibraries()
    fake.devices.append((b"DMP40", b"SERIAL-B", b"USB::B", True))
    with pytest.raises(DMConnectionError, match="Multiple"):
        DMP40(sdk=fake.sdk()).connect()
    with DMP40(serial="SERIAL-B", sdk=fake.sdk()) as dm:
        assert dm.info.resource == "USB::B"
    with DMP40(resource="USB::A", sdk=fake.sdk()) as dm:
        assert dm.info.serial == "SERIAL-A"
    with pytest.raises(DMConnectionError, match="No matching"):
        DMP40(serial="missing", sdk=fake.sdk()).connect()
    fake.devices = [(b"DMP40", b"SERIAL-A", b"USB::A", False)]
    with pytest.raises(DMConnectionError, match="already in use"):
        DMP40(sdk=fake.sdk()).connect()


def test_post_init_failure_closes_session(hardware):
    dm, fake = hardware
    fake.failures["TLDFMX_get_parameters"] = -7
    with pytest.raises(DMDriverError) as caught:
        dm.connect()
    assert caught.value.function == "TLDFMX_get_parameters"
    assert caught.value.status == -7
    assert "Synthetic SDK status" in str(caught.value)
    assert "TLDFMX_close" in fake.names()
    assert not dm.is_connected


def test_unexpected_capabilities_are_rejected(hardware):
    dm, fake = hardware
    fake.zernike_count = 13
    with pytest.raises(DMCapabilityError, match="12"):
        dm.connect()
    assert not dm.is_connected
    assert "TLDFMX_close" in fake.names()


def test_single_mode_matches_reference_flag_and_resets_other_shape_modes(hardware):
    dm, fake = hardware
    dm.connect()
    dm.set_zernikes({"defocus": 0.2, "coma_x": 0.3})
    dm.set_zernike("astigmatism_0", 0.99)
    assert fake.last_single == (
        4,
        0.99,
    )  # exact flag/amplitude of the supplied Python example
    assert len(fake.segment_writes[-1]) == 40
    assert dm.zernikes[ZernikeMode.DEFOCUS] == 0
    assert dm.zernikes[ZernikeMode.ASTIGMATISM_0] == 0.99


def test_combined_and_incremental_updates_use_full_sdk_vector(hardware):
    dm, fake = hardware
    dm.connect()
    with pytest.raises(DMError, match="unknown"):
        dm.update_zernikes({"defocus": 0.2})
    dm.set_zernikes({"defocus": 0.1, "coma_x": 0.03})
    dm.update_zernikes({"defocus": 0.2})
    assert fake.last_vector == (0, 0.2, 0, 0, 0.03, 0, 0, 0, 0, 0, 0, 0)
    copy = dm.zernikes
    copy[ZernikeMode.COMA_X] = 0.9
    assert dm.zernikes[ZernikeMode.COMA_X] == 0.03
    dm.zero_zernikes()
    assert fake.last_vector == (0,) * 12


def test_connected_amplitude_bounds_and_pattern_checks_prevent_writes(hardware):
    dm, fake = hardware
    fake.amplitude_maximum = 0.5
    dm.connect()
    with pytest.raises(ValueError):
        dm.set_zernike("defocus", 0.6)
    assert not fake.segment_writes
    fake.bad_pattern = True
    with pytest.raises(DMError, match="out-of-range"):
        dm.set_zernike("defocus", 0.2)
    assert not fake.segment_writes


def test_preview_calculates_without_writing_or_mutating_modal_state(hardware):
    dm, fake = hardware
    dm.connect()
    pattern = dm.calculate_zernikes({"defocus": 0.1})
    assert pattern.shape == (40,) and pattern.dtype == np.float64
    assert not fake.segment_writes
    assert dm.zernikes is None


def test_calculation_failure_retains_state_but_write_failure_invalidates_it(hardware):
    dm, fake = hardware
    dm.connect()
    dm.set_zernike("defocus", 0.1)
    fake.failures["TLDFMX_calculate_zernike_pattern"] = -9
    with pytest.raises(DMDriverError):
        dm.update_zernikes({"defocus": 0.2})
    assert dm.zernikes[ZernikeMode.DEFOCUS] == 0.1
    assert len(fake.segment_writes) == 1
    fake.failures.clear()
    fake.failures["TLDFM_set_segment_voltages"] = -10
    with pytest.raises(DMDriverError):
        dm.update_zernikes({"defocus": 0.2})
    assert dm.zernikes is None


def test_pitch_yaw_and_zernikes_are_independent(hardware):
    dm, fake = hardware
    dm.connect()
    dm.set_zernike("defocus", 0.1)
    dm.set_orientation(pitch=0.3, yaw=0.4)
    assert fake.last_polar == pytest.approx((0.5, math.degrees(math.atan2(0.3, 0.4))))
    assert dm.zernikes[ZernikeMode.DEFOCUS] == 0.1
    dm.zero_zernikes()
    assert dm.tip_tilt == TipTilt(0.4, 0.3)
    assert not fake.tilt_writes  # mapping delegated to SDK, no piezo formulas


def test_tilt_write_failure_invalidates_pointing_only(hardware):
    dm, fake = hardware
    dm.connect()
    dm.set_zernike("defocus", 0.1)
    dm.set_tip_tilt(x=0.1, y=0.2)
    fake.failures["TLDFM_set_tilt_amplitude_angle"] = -9
    with pytest.raises(DMDriverError):
        dm.set_tip_tilt(x=0, y=0)
    assert dm.tip_tilt is None
    assert dm.zernikes[ZernikeMode.DEFOCUS] == 0.1


def test_positive_sdk_status_is_a_warning_not_a_failure(hardware):
    dm, fake = hardware
    dm.connect()
    fake.failures["TLDFM_set_tilt_amplitude_angle"] = 0x3FFC0900
    with pytest.warns(DMDriverWarning):
        dm.set_tip_tilt(x=0.1, y=0.2)
    assert dm.tip_tilt == TipTilt(0.1, 0.2)


def test_relaxation_matches_reference_sequence_and_invalidates_state(
    hardware, monkeypatch
):
    dm, fake = hardware
    sleeps = []
    monkeypatch.setattr(
        "qtools.dm.backends.Thorlabs.DMP40.backend.time.sleep", sleeps.append
    )
    dm.connect()
    dm.set_zernike("defocus", 0.1)
    dm.set_tip_tilt(x=0.1, y=0.2)
    assert dm.relax() == 2
    assert fake.relax_targets == [(2, 1, 0), (2, 0, 0)]
    assert sleeps == [0.01]
    assert len(fake.segment_writes) == 3 and len(fake.tilt_writes) == 2
    assert dm.zernikes is None and dm.tip_tilt is None


def test_relaxation_is_bounded_and_checks_each_step(hardware):
    dm, fake = hardware
    dm.connect()
    fake.remaining = [5, 4]
    with pytest.raises(DMError, match="did not finish"):
        dm.relax(max_steps=2, interval_s=0)
    assert len(fake.segment_writes) == 2
    fake.failures["TLDFMX_relax"] = -8
    with pytest.raises(DMDriverError):
        dm.relax(interval_s=0)
    assert len(fake.segment_writes) == 2


def test_no_tilt_hardware_supports_mirror_modes_and_relaxation(hardware):
    dm, fake = hardware
    fake.tilt_count = 0
    dm.connect()
    dm.set_zernike("defocus", 0.1)
    with pytest.raises(DMCapabilityError):
        dm.set_orientation(pitch=0.1, yaw=0.1)
    with pytest.raises(DMCapabilityError):
        dm.relax(part="tilt")
    dm.relax(interval_s=0)
    assert fake.relax_targets == [(0, 1, 0), (0, 0, 0)]
    assert not fake.tilt_writes
    assert dm.read_voltages()[1].shape == (0,)


def test_dm_facade_context_manager_closes_on_exception():
    fake = FakeLibraries()
    dm = DM(sdk=fake.sdk())
    with pytest.raises(ValueError, match="body"), dm as connected:
        assert connected is dm
        dm.set_orientation(pitch=0.1, yaw=-0.1)
        dm.set_zernikes({"defocus": 0.1})
        raise ValueError("body")
    assert not dm.is_connected
    assert fake.names().count("TLDFMX_close") == 1


def test_portable_example_never_loads_sdk(monkeypatch, capsys):
    from qtools.dm.examples.dmp40_modes import main

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run loaded the SDK")

    monkeypatch.setattr(DMP40SDK, "load", forbidden)
    main(["--dry-run"])
    output = capsys.readouterr().out
    assert "DRY RUN" in output and "astigmatism_0" in output
    assert "no DLLs" in output


def test_loader_reports_platform_and_missing_dlls(monkeypatch, tmp_path):
    monkeypatch.setattr(sdk_module.sys, "platform", "darwin")
    with pytest.raises(DMDependencyError, match="Windows"):
        DMP40SDK(tmp_path).load()
    monkeypatch.setattr(sdk_module.sys, "platform", "win32")
    with pytest.raises(DMDependencyError, match="TLDFM_64.dll"):
        DMP40SDK(tmp_path).load()


def test_loader_uses_package_paths_and_retains_directory_handle(monkeypatch):
    fake = FakeLibraries()
    loaded = []
    paths = []
    closed = []
    monkeypatch.setattr(sdk_module.sys, "platform", "win32")
    monkeypatch.setattr(Path, "is_file", lambda p: True)
    monkeypatch.setattr(
        sdk_module.os,
        "add_dll_directory",
        lambda p: paths.append(p) or SimpleNamespace(close=lambda: closed.append(True)),
        raising=False,
    )

    def load(path):
        loaded.append(path)
        return fake.extended if "TLDFMX" in path else fake.base

    monkeypatch.setattr(sdk_module.ct, "CDLL", load)
    sdk = DMP40SDK().load()
    assert loaded == [
        str(sdk_module.LIBRARY_DIR / name) for name in sdk_module.DLL_NAMES
    ]
    assert paths == [str(sdk_module.LIBRARY_DIR)]
    assert not closed
    sdk.unload()
    assert closed == [True]


def test_disconnected_calls_fail_before_pattern_generation(hardware):
    dm, fake = hardware
    with pytest.raises(DMConnectionError):
        dm.set_zernike("defocus", 0.1)
    with pytest.raises(DMConnectionError):
        dm.set_tip_tilt(x=0, y=0)
    assert not fake.calls
