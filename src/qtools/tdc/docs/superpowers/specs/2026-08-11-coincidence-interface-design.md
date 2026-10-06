# Coincidence Interface Design

## Scope

Unify two-fold coincidence measurement across software correlation, the S15
TDC1 fixed pairs counter, and the CIQTEK TDC1610 accord counter. Keep the
change focused on the public coincidence API, result timing semantics, and
automatic accidental estimates.

## Public API

`TDCBackend.get_coincidence()` and `TDC.measure_coincidence()` accept:

```python
get_coincidence(
    duration,
    ch_start=1,
    ch_stop=2,
    ch_stop_delay=0,
    unit="ns",
    window_start=None,
    window_stop=None,
    method="software",
)
```

The method is two-fold only. Three-fold hardware counting remains available
through the CIQTEK-specific low-level accord configuration and timestamp
triplets remain available through the existing triplet API. `bins` and
`bin_offset` remain parameters of `get_g2()` but are not public coincidence
parameters.

Windows are half-open physical-delay intervals, `[window_start, window_stop)`,
in `unit`. `ch_stop_delay` adjusts the stop channel before the window is
applied. Software mode may auto-select a single detected peak when no window
is given.

## Backend Behavior

Software coincidence is implemented by timestamp-capable backends on a fixed
zero-origin delay axis. `ch_stop_delay` is the only way to move the stop
channel relative to the start channel, so explicit windows must be
non-negative. The internal g2 range extends from zero through the requested
window and a right-side background region; automatic detection searches the
default 500-bin range and prints the recommended window. `get_g2()` retains
its independent low-level `bins` and `bin_offset` controls, but
`get_coincidence()` neither exposes nor passes an offset.

S15 TDC1 hardware uses its fixed pairs counter. It only accepts pairs exposed
by the device, does not accept a delay or explicit window, and reports no gate
width. Its accidental estimate is unavailable because the fixed gate width is
not exposed by the protocol.

CIQTEK TDC1610 hardware requires physical channel 1 as the start channel.
`window_start` is fixed at zero (or omitted); `window_stop` is the positive
gate width. `ch_stop_delay` configures the stop-channel delay. The gate width
must align to the configured resolution and the delay must fit the device
range.

## Accidentals

Software mode estimates accidentals from bins outside the signal window and
reports the mean sideband count per bin plus the scaled signal-window count.
CIQTEK hardware estimates two-fold accidentals from the measured singles
rates, gate width, and live integration time. Result metadata identifies the
estimate source. S15 fixed pairs returns no accidental estimate.

## Timing

`TimestampResult.total_time_ns` is the effective live collection time used as
the rate denominator, not the span between first and last recorded events.
Continuous timestamp backends use their requested or measured acquisition
time. A future gated backend sets it to the sum of open gate durations. A
timestamp-span property remains available for inspection without affecting
rates or normalized correlation results.

## Verification

Tests cover reduced signatures, software window selection and background
statistics, hardware capability validation, CIQTEK rate-product accidentals,
and live-time behavior for sparse and future gated timestamp acquisitions.
