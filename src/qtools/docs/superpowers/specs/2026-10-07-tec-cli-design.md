# TEC Temperature Logging CLI Design

## Goal

Add a `tec` console command that reads a SenseFuture TEC channel continuously
and appends the setpoint and measured temperature at a configurable interval.

## Interface

```text
tec --device /dev/ttyUSB0
tec --device /dev/ttyUSB0 --logfile temp/water_temp.log --interval 1
```

Defaults:

- `--device ""`: use the existing automatic serial-device discovery;
- `--logfile tec.log`;
- `--interval 1.0` seconds;
- `--channel 1`.

`--mock` is available for hardware-free checks and `--once` performs one
sample for scripting and tests. `Ctrl-C` closes the controller cleanly. The
active channel is exposed as `TEC.ch_prefix`, which is `TC1:` or `TC2:`.

## Log formats

The format is selected from the logfile extension, case-insensitively.

For `.csv`, each line has no header and contains:

```text
ISO-8601 timestamp,setpoint,measured temperature,channel
2026-10-07T12:00:00+08:00,25.13,24.98,TC1:
```

The second and third values are `tec.settemp` and `tec.temp`, respectively; the
fourth value is the active channel prefix.

For other extensions, the CLI preserves the legacy `physicsutils` event-log
format and writes two lines per sample:

```text
20261007_120000\tsettemp\t25.13\tTC1:
20261007_120000\ttemp\t24.98\tTC1:
```

The parent directory is created automatically and existing files are appended.

## Implementation

The sampling loop lives in a new `qtools.tec.cli` module. It passes
`logfile=None` to `TEC` so the controller's internal legacy logger does not
duplicate records; the CLI owns formatting and writing. The console script is
registered in `pyproject.toml` as `tec = "qtools.tec.cli:main"`.

## Verification

Unit tests cover argument defaults, CSV and legacy formatting, parent-directory
creation, and one mock sampling cycle. Existing TEC controller tests remain
unchanged.
