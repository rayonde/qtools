# Siminics FT10xx backend

This backend wraps the 64-bit V2.2 `smncsftmt.dll` API used by FT1010,
FT1040, and FT1080 instruments. The DLL is loaded lazily, so importing
`qtools.tdc` is safe on non-Windows systems. Hardware access requires a
64-bit Windows Python process and the Siminics USB driver.

The Win64 SDK files are bundled under `libs/win64/`:

- `smncsftmt.dll` — runtime DLL;
- `smncsftmt.lib` — vendor import library for native development;
- `smncsftmt.h` — V2.2 API declarations.

## Generic API

```python
from qtools.tdc.backends.siminics import SiminicsBackend

backend = SiminicsBackend(tttr_mode="T2", resolution_ps=64)
backend.connect()
try:
    singles = backend.get_singles(1.0)
    timestamps = backend.get_timestamps(1.0)
    events = backend.get_tttr_events()
    markers = backend.get_last_markers()
finally:
    backend.disconnect()
```

Saved TTTR files use the same parser as live acquisitions:

```python
from qtools.tdc.backends.siminics import parse_file

parsed = parse_file("capture.t2", mode="T2", resolution_ps=64)
print(parsed.timestamps, parsed.markers)
```

Binary file I/O, SDK block joining, and TTTR decoding are kept in `parser.py`;
the backend only handles SDK task acquisition and passes the returned blocks
to the parser.

Channels are exposed as 1-based `CH1..CHN`. The backend automatically detects
the FT10xx model when the device connects. `SYNC` and `M1..M4` are not counted
as ordinary channels.

## Marker events

TTTR Marker records are decoded as separate `MarkerEvent` values. M1, M2, M3,
and M4 use masks `0x1`, `0x2`, `0x4`, and `0x8`; simultaneous inputs are
represented by their bitwise combination. Marker records remain in
`get_tttr_events()` stream order and are not inserted into the generic
`TimestampResult` arrays because the vendor format does not store an
independent Marker timestamp.
Use `get_markers(duration)` when a new acquisition and its Marker list are
needed in one call.

## Siminics-specific modes

```python
t1 = backend.get_t1_histogram(1.0, channel=1, bins=65536)
ittr_t = backend.get_ittr(1.0, mode="ITTR-T", interval_us=1000)
ittr_m = backend.get_ittr(1.0, mode="ITTR-M", interval_us=1000)
coinc = backend.get_coincidence(1.0, 1, 2, method="hardware")
```

`ITTR-M` uses M1 as the external segmentation signal. The vendor examples
label both ITTR modes in comments but call mode `6`; the backend uses the SDK
constants correctly: `ITTR-T = 6`, `ITTR-M = 7`.

## Raw data and endian order

The vendor TTTR file format displays each word in big-endian byte order, for
example `02 00 6A AB` for a CH2 event and `82 00 00 00` for M1. The parser
therefore defaults to `byteorder="big"`. If an application has already
converted the memory buffer to host-order integers, use `parse_words()`
directly or pass `byteorder="little"` to `parse_bytes()`.
