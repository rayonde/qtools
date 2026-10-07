"""Tests for the TEC temperature logging CLI."""

import datetime as dt

from qtools.tec.cli import _write_record, build_parser, main


def test_cli_defaults():
    args = build_parser().parse_args([])

    assert args.device == ""
    assert args.logfile == "tec.log"
    assert args.interval == 1.0
    assert args.channel == 1
    assert args.mock is False


def test_csv_record_contains_setpoint_and_measured_temperature(tmp_path):
    logfile = tmp_path / "nested" / "water.csv"
    timestamp = dt.datetime(
        2026, 10, 7, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))
    )

    _write_record(logfile, 25.13, 24.98, timestamp=timestamp)

    assert logfile.read_text() == "2026-10-07T12:00:00+08:00,25.13,24.98,TC1:\n"


def test_csv_extension_is_case_insensitive(tmp_path):
    logfile = tmp_path / "water.CSV"
    timestamp = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.timezone.utc)

    _write_record(logfile, 25.0, 24.5, timestamp=timestamp)

    assert logfile.read_text() == "2026-10-07T12:00:00+00:00,25.0,24.5,TC1:\n"


def test_legacy_record_keeps_physicsutils_format(tmp_path):
    logfile = tmp_path / "water.log"
    timestamp = dt.datetime(
        2026, 10, 7, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))
    )

    _write_record(logfile, 25.13, 24.98, timestamp=timestamp)

    assert logfile.read_text() == (
        "20261007_120000\tsettemp\t25.13\tTC1:\n"
        "20261007_120000\ttemp\t24.98\tTC1:\n"
    )


def test_mock_cli_can_record_one_sample(tmp_path):
    logfile = tmp_path / "water.csv"

    assert main(["--mock", "--once", "--logfile", str(logfile)]) == 0
    fields = logfile.read_text().strip().split(",")

    assert len(fields) == 4
    assert fields[1:] == ["25.0", "25.0", "TC1:"]


def test_record_can_include_channel_prefix(tmp_path):
    logfile = tmp_path / "water.csv"

    _write_record(logfile, 30.0, 29.5, ch_prefix="TC2:")

    assert logfile.read_text().rstrip().endswith(",30.0,29.5,TC2:")
