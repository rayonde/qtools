"""Unit tests for the TEC controller class."""

from unittest.mock import patch

import pytest


from qtools.tec import (
    TEC,
    SenseFutureTEC,
    TECMode,
    TECPolarity,
    TECProtocolError,
)
from qtools.tec.controller import _round


def test_round_utility():
    assert _round(30) == 30
    assert _round(30, 0) == 30
    assert _round(30, 2) == 3000
    assert _round(30, -3) == 0.03
    assert _round(40, 5) == 4000000
    assert _round(4000000, -5) == 40.0


def test_tec_mock_initialization():
    tec = TEC(is_mock=True)
    assert tec.is_connected
    assert tec.device == "mock://sensefuture-tec"
    assert "TEC(" in repr(tec)
    assert tec.model == "RD105"
    tec.close()
    assert not tec.is_connected


def test_tec_alias():
    tec = SenseFutureTEC(is_mock=True)
    assert isinstance(tec, TEC)
    assert tec.is_connected


def test_tec_context_manager():
    with TEC(is_mock=True) as tec:
        assert tec.is_connected
    assert not tec.is_connected


def test_tec_on_off_active():
    with TEC(is_mock=True) as tec:
        assert not tec.active()
        assert not tec.is_active

        tec.on()
        assert tec.active()
        assert tec.is_active

        tec.off()
        assert not tec.active()
        assert not tec.is_active


def test_tec_temperature_control():
    with TEC(is_mock=True) as tec:
        # Default mock initial temp is 25.0
        assert tec.settemp == 25.0
        assert tec.target_temp == 25.0
        assert tec.temp == 25.0
        assert tec.actual_temp == 25.0

        # Change setpoint via temp setter
        tec.temp = 38.5
        assert tec.settemp == 38.5
        assert tec.target_temp == 38.5

        # Change setpoint via settemp setter
        tec.settemp = 42.0
        assert tec.settemp == 42.0

        # Change setpoint via target_temp setter
        tec.target_temp = 20.0
        assert tec.target_temp == 20.0
        assert tec.settemp == 20.0


def test_tec_slope():
    with TEC(is_mock=True) as tec:
        assert tec.slope == 1.0  # Default 1000 in mock (1.0 K/s)

        tec.slope = 2.5
        assert tec.slope == 2.5


def test_tec_current_and_current_limit():
    with TEC(is_mock=True) as tec:
        assert tec.current == 0.0
        assert tec.current_limit == 1.5

        tec.current_limit = 2.0
        assert tec.current_limit == 2.0


def test_tec_voltage_limit():
    with TEC(is_mock=True) as tec:
        assert tec.voltage_limit == 80

        tec.voltage_limit = 90
        assert tec.voltage_limit == 90


def test_tec_polarity():
    with TEC(is_mock=True) as tec:
        assert tec.polarity == TECPolarity.NORMAL

        tec.polarity = TECPolarity.REVERSED
        assert tec.polarity == TECPolarity.REVERSED

        tec.polarity = 0
        assert tec.polarity == 0


def test_tec_mode():
    with TEC(is_mock=True) as tec:
        assert tec.mode == TECMode.BOTH

        tec.mode = TECMode.HEAT
        assert tec.mode == TECMode.HEAT

        tec.mode = TECMode.COOL
        assert tec.mode == TECMode.COOL


def test_tec_pid():
    with TEC(is_mock=True) as tec:
        p, i, d = tec.pid
        assert p == 1.0
        assert i == 0.5
        assert d == 0.05

        tec.pid = (1.2, 0.4, 0.08)
        p, i, d = tec.pid
        assert p == 1.2
        assert i == 0.4
        assert d == 0.08


def test_tec_autopid():
    with TEC(is_mock=True) as tec:
        tec.autopid()
        assert tec._transport.registers["TC1:AUTOPID"] == 1


def test_tec_status():
    with TEC(is_mock=True) as tec:
        st = tec.status()
        assert st["model"] == "RD105"
        assert st["active"] is False
        assert "temp" in st
        assert "settemp" in st
        assert "pid" in st


def test_tec_wait_for_temperature():
    with TEC(is_mock=True) as tec:
        tec.temp = 25.0
        # Should succeed immediately as mock matches target
        assert tec.wait_for_temperature(target=25.0, tolerance=0.1, timeout=1.0)


def test_tec_monitor(capsys):
    with TEC(is_mock=True) as tec:
        readings = []

        def cb(val):
            readings.append(val)

        tec.monitor(interval=0.01, duration=0.05, callback=cb)
        assert len(readings) >= 1
        captured = capsys.readouterr()
        assert "Press Ctrl-C to stop monitoring" in captured.out
        assert "°C" in captured.out


def test_tec_logging(tmp_path):
    log_file = tmp_path / "test_tec.log"
    with TEC(is_mock=True, logfile=str(log_file)) as tec:
        tec.temp = 30.0
        _ = tec.temp

    assert log_file.exists()
    content = log_file.read_text()
    assert "settemp\t30.0" in content
    assert "temp\t30.0" in content


def test_tec_set_fallback_failure():
    with TEC(is_mock=True) as tec:
        # Intentionally break mock write to simulate error
        with patch.object(tec, "_set", side_effect=ValueError("Simulated write fail")):
            success = tec._set_fallback("TC1:SPEED=2000")
            assert not success


def test_tec_protocol_error_on_bad_response():
    with TEC(is_mock=True) as tec:
        with patch.object(tec, "rw", return_value="ERROR_BAD_CMD"):
            with pytest.raises(TECProtocolError):
                tec._query("TC1:TG=?")


def test_tec_channel_selection():
    with TEC(is_mock=True, channel=2) as tec2:
        assert tec2.channel == 2
        assert tec2.ch_prefix == "TC2:"
        tec2.temp = 31.0
        assert tec2.settemp == 31.0
        assert tec2._transport.registers["TC2:TG"] == 3100000

    with pytest.raises(ValueError):
        TEC(is_mock=True, channel=3)


def test_tec_channel_prefix_tracks_active_channel():
    with TEC(is_mock=True) as tec:
        assert tec.ch_prefix == "TC1:"
        tec.channel = 2
        assert tec.ch_prefix == "TC2:"


def test_tec_extended_protocol_properties():
    with TEC(is_mock=True) as tec:
        # Resistance
        assert tec.resistance == 10000.0  # 10 kΩ in Ohms
        assert tec.resistance_kohm == 10.0

        # Interior temperature
        assert tec.interior_temp == 25

        # Firmware version
        assert tec.firmware_version == "1.0.0"

        # PWM Duty
        assert tec.pwm_duty == 0.0
        tec.pwm_duty = 15.0
        assert tec.pwm_duty == 15.0

        # Mode VOLTAGE
        tec.mode = TECMode.VOLTAGE
        assert tec.mode == TECMode.VOLTAGE

        # Model name
        tec._transport.registers["TEC"] = "5"
        assert tec.model_name == "215"


def test_tec_error_parsing():
    with TEC(is_mock=True) as tec:
        tec._transport.registers["ERRORCODE"] = (1 << 0) | (1 << 6)
        assert tec.error_code == 65
        errs = tec.errors
        assert any("Interior high temperature" in e for e in errs)
        assert any("Channel 1 current limited" in e for e in errs)


def test_tec_dual_channel_views():
    with TEC(is_mock=True) as tec:
        # Both channels independent control
        assert tec.tc1.channel == 1
        assert tec.tc2.channel == 2

        tec.tc1.temp = 22.0
        tec.tc2.temp = 34.0
        assert tec.tc1.temp == 22.0
        assert tec.tc2.temp == 34.0

        tec.tc1.on()
        assert tec.tc1.active()
        assert not tec.tc2.active()

        tec.tc2.on()
        assert tec.tc2.active()

        # Switch active default channel on parent
        tec.channel = 2
        assert tec.temp == 34.0
        tec.temp = 35.0
        assert tec.tc2.temp == 35.0


def test_tec_sensor_params_section_3_2():
    with TEC(is_mock=True) as tec:
        # Sensor model
        assert tec.tc1.sensor_model == 0
        tec.tc1.sensor_model = 1  # PT1000
        assert tec.tc1.sensor_model == 1

        # NTC B-value and R0
        assert tec.tc1.b_value == 3950.0
        tec.tc1.b_value = 3450.0
        assert tec.tc1.b_value == 3450.0

        assert tec.tc1.r0 == 10.0  # 10 kΩ
        tec.tc1.r0 = 5.0
        assert tec.tc1.r0 == 5.0

        # Overtemp thresholds
        assert tec.tc1.overtemp_high == 5000.0
        tec.tc1.overtemp_high = 85.0
        assert tec.tc1.overtemp_high == 85.0

        assert tec.tc1.overtemp_low == -3000.0
        tec.tc1.overtemp_low = -10.0
        assert tec.tc1.overtemp_low == -10.0

        # Sensor protection & power mode
        assert tec.tc1.sensor_protection is True
        tec.tc1.sensor_protection = False
        assert tec.tc1.sensor_protection is False

        assert tec.tc1.power_mode == 0
        tec.tc1.power_mode = 1
        assert tec.tc1.power_mode == 1


def test_tec_system_params_and_reset_section_3_5():
    with TEC(is_mock=True) as tec:
        assert tec.interior_overtemp_limit == 70
        tec.interior_overtemp_limit = 65
        assert tec.interior_overtemp_limit == 65

        with pytest.raises(ValueError):
            tec.interior_overtemp_limit = 120  # Out of range 40~100

        tec.on()
        assert tec.active()
        tec.reset_factory_defaults()
        assert not tec.active()


def test_tec_batch_queries_section_3_6():
    with TEC(is_mock=True) as tec:
        # Inquire
        info = tec.inquire()
        assert "TC1:TG" in info
        assert "TC2:TG" in info
        assert "TEC" in info

        # Fast Demand Data (mode 1: temp, resistor, pwm)
        fast_status = tec.demand_data(mode=1)
        assert fast_status["ch1"]["temp"] == 25.0
        assert fast_status["ch1"]["resistance"] == 10000.0
        assert fast_status["interior_temp"] == 25

        # Fast Demand Data (mode 2: output voltage)
        v_status = tec.demand_data(mode=2)
        assert "voltage" in v_status["ch1"]

