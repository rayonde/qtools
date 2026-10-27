"""Tests for the high-precision channel status table output."""
import sys
import io
import contextlib
from pathlib import Path


import pytest
from unittest.mock import patch


# Minimal 3-servo config YAML for testing
CONFIG_YAML = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    name: "Alice's test channel"
    servos:
      - name: "alice_1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
        fast_axis_angle: 0.0
        cal_scale: 1.0
        cal_offset_deg: 0.0
      - name: "alice_1550_hwp_2"
        group: "alice"
        servo_id: 2
        waveplate: "HWP"
        order: 2
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
        fast_axis_angle: 0.0
        cal_scale: 1.0
        cal_offset_deg: 0.0
      - name: "alice_1550_qwp_3"
        group: "alice"
        servo_id: 3
        waveplate: "QWP"
        order: 3
        zero_position: 512
        deg_per_step: 0.2933
        min_angle: -90.0
        max_angle: 90.0
        fast_axis_angle: 0.0
        cal_scale: 1.0
        cal_offset_deg: 0.0
"""


@pytest.fixture
def config_file(tmp_path):
    f = tmp_path / "polarization_config.yaml"
    f.write_text(CONFIG_YAML)
    return str(f)


def capture_status(config_file_path):
    """Run execute_status() inside run_cli_interactive and capture output."""
    from qtools.pctrl.repl import run_cli_interactive

    buf = io.StringIO()
    # 'exit' immediately after startup status is printed
    with patch("builtins.input", side_effect=["exit"]), \
         contextlib.redirect_stdout(buf):
        run_cli_interactive(config_file_path, mock=True)
    return buf.getvalue()


def test_status_table_has_headers(config_file):
    """Status output must contain required column headers."""
    output = capture_status(config_file)
    for header in ("Servo Name", "Group", "ID", "Current",
                   "Fast Axis", "Limits", "Zero (Deg/St)"):
        assert header in output, f"Missing header: {header!r}\nOutput:\n{output}"


def test_status_table_limits_resolution(config_file):
    """Limits column must show step-resolution angles and step counts.
    
    For zero_position=512, deg_per_step=0.2933, min_angle=-90.0, max_angle=90.0:
      min_steps = round(512 + (-90.0 / 0.2933)) = 205
      max_steps = round(512 + ( 90.0 / 0.2933)) = 819
      exact_min = (205 - 512) * 0.2933 = -90.043
      exact_max = (819 - 512) * 0.2933 =  90.043
    Expected format: "-90.043(205), 90.043(819)"
    """
    output = capture_status(config_file)
    assert "-90.043(205), 90.043(819)" in output, (
        f"Expected step-resolution limits not found in output:\\n{output}"
    )


def test_status_table_zero_resolution(config_file):
    """Zero column must show zero_position as deg and raw steps.
    
    zero_position=512 → 0.000° (512)
    """
    output = capture_status(config_file)
    assert "0.000" in output, f"3-decimal zero angle not found:\\n{output}"
    assert "(512)" in output, f"Zero step value not found:\\n{output}"


def test_status_table_group_column(config_file):
    """Each servo row must show its group name."""
    output = capture_status(config_file)
    # All three servos belong to group "alice"
    assert output.count("alice") >= 3, (
        f"Expected 'alice' to appear ≥3 times (group col):\n{output}"
    )


def test_status_table_channel_header(config_file):
    """Channel section header must include path and wavelength."""
    output = capture_status(config_file)
    assert "alice1550nm" in output or ("alice" in output and "1550" in output), (
        f"Channel header not found:\n{output}"
    )
