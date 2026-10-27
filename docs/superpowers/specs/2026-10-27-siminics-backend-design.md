# Siminics FT10 TDC Backend Design

## Goal

Add a `siminics` backend to `qtools.tdc` based on the vendor's V2.2 Python/C API examples. The backend must follow the existing `TDCBackend` lifecycle and result models while exposing Siminics-specific acquisition modes and Marker metadata.

The implementation targets the 64-bit Windows FT10xx DLL distributed in the repository refs. Non-Windows imports remain safe; connecting to hardware raises a clear platform/dependency error.

## Scope

The backend covers:

- device initialization and connection state;
- FT1010, FT1040, and FT1080 channel counts (1, 4, and 8);
- singles acquisition through the vendor signal counters;
- T2 and T3 TTTR acquisition through the vendor memory-data API;
- T2/T3 overflow reconstruction;
- Marker M1-M4 decoding and preservation as separate metadata events;
- hardware coincidence through the vendor DMTCH API;
- threshold, edge, impedance, delay, resolution, and start-frequency settings;
- T1 histogram acquisition and ITTR-T/ITTR-M as explicit Siminics extensions.

The existing generic `TimestampResult` cannot represent Marker records, so the backend will retain the raw words and expose a vendor-specific parsed event structure alongside the generic channel/timestamp arrays. Marker timestamps are optional metadata: T2 can reconstruct a stream position, while T3 provides a sync sequence and delta; neither format carries an independent Marker time field.

## Package and dependency layout

Create:

```text
src/qtools/tdc/backends/siminics/
    __init__.py
    backend.py
    parser.py
    models.py
    errors.py
    README.md
    libs/
        win64/
            smncsftmt.dll
            smncsftmt.lib
            smncsftmt.h
```

The three files are copied from the V2.2 `refs/PYTHON(64位)范例-V2.2/win64` directory without modifying the vendor files. The DLL is loaded only on Windows and only when a backend instance connects. The `.h` and `.lib` files are kept beside it for SDK traceability and native development; they are not imported by Python.

## Backend architecture

`SiminicsBackend` subclasses `TDCBackend` and is registered under `"siminics"` from `backends/__init__.py`.

Public generic properties:

- `name == "siminics"`;
- `vendor == "Siminics"`;
- `channel_count` is selected from the detected FT10xx device type, or from an explicit constructor override;
- capabilities include `SINGLES`, `TIMESTAMPS`, `HIST_HARDWARE`, `HIST_SOFTWARE`, `COINCIDENCE`, `COINCIDENCE_SOFTWARE`, and `THRESHOLD_CONTROL` where the selected mode supports them;
- `resolution_ps` reflects the configured TTTR/T1 resolution.

Connection calls `InitDll`, `InitDev`, and `DevConnected`. Disconnect calls `UnInitDll` and clears the instance state. Repeated connect/disconnect calls are idempotent from the backend user's perspective.

The backend uses 1-based CH numbering, matching the other `qtools.tdc` backends and the user-facing examples. SYNC and M1-M4 are not included in `channel_count`.

## Acquisition flow

### Singles

`get_singles(duration)` configures a short T1/statistics task, starts mode `0x01`, waits until completion, then reads each channel's stop count using `GetSignalStatus`. The returned `SinglesResult` contains CH counts and rates only; SYNC counts are retained in an optional backend diagnostic field.

### TTTR timestamps

`get_timestamps(duration)` uses memory mode:

1. enable TTTR for the selected CH mask;
2. set T2 or T3 mode and end condition;
3. enable `SetMemoryDataMode(True)`;
4. start the task;
5. poll `IsTaskCompleted`, consume every `FtmtRawData` block with `GetMemoryData`, and release it with `ReleaseMemoryData`;
6. parse all 32-bit words and return a `TimestampResult`.

T2 event timestamps are reconstructed from 25-bit time values and overflow words at the configured resolution. T3 timestamps combine the 15-bit SYNC-relative delta and the reconstructed 10-bit SYNC sequence. If `sync_period_ps` is configured, T3 timestamps are absolute relative to the first sync sequence; otherwise the returned values are the per-event delta values and the vendor-specific result records that the timeline is relative.

## Marker representation

`parser.py` decodes the control-bit records defined by the manual:

```text
M1       -> mask 0x1 -> 0x82000000
M2       -> mask 0x2 -> 0x84000000
M3       -> mask 0x4 -> 0x88000000
M4       -> mask 0x8 -> 0x90000000
M1 + M2  -> mask 0x3 -> 0x86000000
```

`MarkerEvent` contains the mask, source mode, raw word, stream index, reconstructed T2 time when available, T3 sync sequence when available, and optional absolute timestamp. A control record with indicator `0x3f` is treated as an overflow record, never as a Marker. Marker records do not enter `TimestampResult.channels` or `TimestampResult.timestamps`.

The backend exposes `get_last_markers()` and `get_tttr_events()` for vendor-specific consumers. `get_tttr_events()` returns channel events, overflow events, and Marker events in original stream order.

## T1, ITTR, and coincidence extensions

The backend adds explicit methods for modes that do not map cleanly to the generic result models:

- `get_t1_histogram(...)` configures `EnableT1`, bin size, resolution, and statistics time, then reads `GetT1Data` into a NumPy histogram;
- `get_ittr(...)` supports `ITTR-T` (internal interval) and `ITTR-M` (M1-delimited windows), returning a structured result with per-window intensity and optional Marker boundaries;
- `get_coincidence(..., method="hardware")` configures DMTCH with a two-or-more-channel strategy and returns the generic `CoincidenceResult`;
- `get_coincidence(..., method="software")` delegates to the base software implementation when timestamps are available.

The ITTR-M configuration uses vendor run mode `0x07`; the existing vendor sample's comments and calls use `0x06` even where it describes `ITTR-M`, so the backend will follow the header constants and document this correction.

## Error handling and cleanup

- Importing `qtools.tdc` must not load the DLL or fail on non-Windows systems.
- Missing DLL, wrong bitness, or missing Windows runtime produces `SiminicsSDKUnavailable` with the expected path and platform guidance.
- Vendor non-zero return codes are converted to `SiminicsError` with operation and code.
- Memory blocks are released in `finally` blocks even when parsing fails.
- A failed acquisition stops the active task and resets memory mode where possible.
- Invalid channels, masks, durations, bin sizes, and incompatible T2/T3 parameters raise `ValueError` before touching the DLL.

## Validation

Add tests that do not require hardware:

- parser tests for T2 events, T2 overflow, T3 events, T3 sync overflow, single and combined Marker masks;
- fake-DLL tests for call order, mode constants, error propagation, and memory block release;
- registry and capability tests for the new backend;
- a package-layout test confirming the three copied Win64 SDK files are present.

Hardware tests remain marked `hardware` and cover connect, singles, T2/T3 capture, Marker events, ITTR-M, T1, and coincidence when a Windows FT10xx is attached.
