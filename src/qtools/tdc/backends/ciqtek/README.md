# CIQTEK (国仪量子) TDC1610 Backend

This backend integrates the **CIQTEK TDC1610** time-to-digital converter into
the `tdc` framework.

- Backend name (registry / CLI): `tdc1610`
- Class: `TDC1610Backend` (`tdc.backends.ciqtek.backend`)
- Registered capabilities: `SINGLES | THRESHOLD_CONTROL`

## Hardware / Platform

- The TDC1610 is an **Ethernet-connected** instrument with **1 start input
  and 16 stop inputs** (17 inputs total).
- The vendor SDK loads `TDC1610DLL_x64.dll`, a **Windows x64** shared
  library. Real hardware access therefore requires **Windows**. On other
  platforms the module imports fine, but `connect()` raises `ImportError`.
- The vendor SDK files (`tdc1610SDK.py`, `errorCode.py`, `tdc1610example.py`,
  DLLs) are kept **unmodified** under `libs/` as reference material.

## Connection Flow

1. `FindDevice()` — UDP-broadcast network search; each device is described by
   `[index, local_ip, des_ip, dst_mac, dst_name]`.
2. `ConnectDevice(local_ip, des_ip, dst_mac)` — establish the Ethernet link.
3. Code-density calibration is run automatically if the device reports it is
   required (`calibrate=True` by default).
4. Configuration: trigger mode, clock, per-channel enable/mode/threshold(mV)/
   delay(ps), time resolution, dynamic range, draw window.
5. Acquisition loop: `StartCollect()` → read data → `StopCollect()`.
6. `DisConnectDevice()` — release the firmware's IP lock.

## Channel Mapping

The unified 1-based channel model maps onto the SDK channels as:

| Physical channel | SDK channel | Meaning   |
|------------------|-------------|-----------|
| 1                | 0           | start (trigger) |
| 2 … 17           | 1 … 16      | stop1 … stop16 |

Units follow the vendor SDK: thresholds are in **millivolts (mV)**
(`-5000..5000`) and delays in **picoseconds (ps)** (`-200000..200000`).

## Data Formats

| Method | Result type | Status | Content | Vendor SDK source |
|---|---|---|---|---|
| `get_singles()` | `SinglesResult` | supported | `counts` (17, uint64), `count_rates` (cps), `integration_time` | `GetCpsByUser()` → rates `[start, stop1..16]`; counts = `rate × duration` |
| `get_timestamps()` | `TimestampResult` | **unsupported** | — | SDK has no raw timestamp stream |
| `compute_g2()` | `G2Result` | **unsupported** | — | software g² needs raw timestamps |

## Raw Timestamps vs. Histogram (important)

- The vendor SDK does **not** expose a raw per-event timestamp stream like
  S15 / IDQ drivers do. The TDC1610 is a time-interval analyzer: for each
  channel it accumulates a **histogram (time spectrum)** of events inside the
  configured dynamic-range window.
- `GetCollectDataByUserEx(channel)` returns
  `(channel, index_list, data_list, is_new)`, where `index_list` are the
  non-zero bin positions and `data_list` the event counts in those bins.
- The backend therefore **does not fabricate timestamps**: `get_timestamps()`
  and `compute_g2()` raise `NotImplementedError`. Use `get_singles()` for
  count rates and `get_accord_counts()` for hardware coincidence counts.

### Histogram reference channel

- In **external-trigger mode** (`trigger_mode=0`), the start channel (SDK
  channel 0 / physical channel 1) is the trigger source: every stop channel's
  histogram measures the time of its events **relative to the start
  (trigger) event**, i.e. x = `t_stop − t_start`.
- In **internal-trigger mode** (`trigger_mode=1`), the reference is the
  **internal clock trigger** (`ConfigClockPeriod`), and each channel
  (including the start channel) accumulates its histogram relative to those
  triggers.
- The reference channel is **not selectable through the SDK** — it is implied
  by the trigger configuration. (Inferred from the vendor example; verify on
  hardware if in doubt.)
- The **external-trigger source is fixed to the start input** (SDK channel 0 /
  physical channel 1); the SDK has no API to route the trigger from a stop
  channel. To use a different input as the trigger, rewire that signal to the
  start input at the hardware level. Coincidence channels
  (`configure_accord()`, physical channels 1–17) are configurable
  independently of the trigger.

## Hardware Coincidence (Example: Channels 3 & 4)

The TDC1610 can count hardware coincidences between any enabled channels:
two channels = 2-fold coincidence, three channels = 3-fold coincidence.

```python
import time

backend.set_algorithm(0x02)   # enable the 2-fold coincidence algorithm
backend.configure_accord(     # physical channels (1-based)
    code_width_ps=352,        # gate width in ps; multiple of resolution (8 ps)
    channel1=3,
    channel2=4,
)
backend.start_collect()
time.sleep(1.0)
backend.stop_collect()

accord = backend.get_accord_counts()
# -> [coincidence_count, ch3_cps, ch4_cps, 0]  (4th slot unused for 2-fold)
```

Notes:

- The gate width (`code_width_ps`) must be an integer multiple of the
  configured time resolution, otherwise the SDK returns error 16385.
- Only enabled channels participate (all 17 are enabled by default).
- The coincidence count accumulates while collecting, so use
  `start_collect()` → wait → `stop_collect()` → `get_accord_counts()`.
- The SDK returns the **total coincidence count only** — there is no
  delay-resolved g² histogram (that would require raw timestamps, which the
  SDK does not provide).
- The coincidence gate is anchored to the **start (trigger) event**: the SDK
  only accepts a gate **width**, there is no gate-position/offset parameter.
  The effective window position can only be shifted via the per-channel
  delay (`set_channel_config(..., delay=...)`, ±200 ns; vendor comments are
  inconsistent on ns vs. ps units — verify on hardware).

## Usage

```python
from tdc.connection import get_backend

backend_cls = get_backend("tdc1610")
backend = backend_cls()

devices = backend.discover_devices()
backend.connect()  # or backend.connect(devices[0].device_path)

# Singles (count rates) — supported:
singles = backend.get_singles(integration_time=1.0)

# Raw timestamps / software g2 — NOT supported (raise NotImplementedError):
# ts = backend.get_timestamps(duration=1.0)
# g2 = backend.get_g2(...)

# Hardware coincidence counts — supported (enable the accord algorithm first):
backend.set_algorithm(0x02)
backend.start_collect()
time.sleep(1.0)
backend.stop_collect()
accord = backend.get_accord_counts()

backend.disconnect()
```

`connect()` accepts the following optional kwargs:

- `dev_info`: a full vendor device entry `[index, local_ip, des_ip, dst_mac, dst_name]`.
- `calibrate=True` (default): run code-density calibration when required.
- `trigger_mode`, `clock_period_ns`, `resolution_ps` (8/16/32/64/128/256/1024),
  `dynamic_range_ps`, `draw_window_ps`, `clock_input_type`,
  `clock_input_value`, `clock_output`, `collect_time_ms`, `fresh_time_s`,
  `error_callback`: initial configuration applied after connecting.

## SDK Extensions (not part of `TDCBackend`)

The following vendor-specific methods are provided at the end of
`TDC1610Backend` and are **not** part of the common `TDCBackend` interface:

| Group | Methods | Description |
|---|---|---|
| Collection control | `start_collect()`, `stop_collect()` | Explicit start/stop of acquisition |
| Configuration | `set_trigger_mode()`, `set_clock_period()`, `set_time_resolution()`, `set_dynamic_range()`, `set_draw_window()`, `set_clock()`, `set_collect_time()`, `set_fresh_time()`, `set_channel_config()`, `set_error_callback()` | Trigger, clock, window and per-channel enable/mode/threshold/delay |
| Calibration | `calibrate()`, `get_calibration_result()` | Code-density calibration |
| Coincidence counting | `set_algorithm()`, `reset_algorithm()`, `configure_accord()`, `get_accord_counts()` | Hardware 2-fold / 3-fold coincidence |
| QRNG | `configure_random()`, `get_random_bits()`, `save_random()` | Quantum random-number generation |
| Mark trigger | `configure_mark()`, `set_mark_max_delay()`, `set_mark_save_path()`, `get_mark_status()` | External mark-signal trigger |

## Candidates for Promotion to `TDCBackend`

These TDC1610 features are good candidates for the common `TDCBackend`
interface, so that other backends (e.g. IDQ, S-Fifteen) implement them too:

1. **Hardware coincidence counting** — `get_coincidence_counts()`: maps to
   `GetAccordByUser()`; IDQ's driver already has an equivalent
   (`wait_to_get_coinc_counters_for`). High value for fast pairs measurement.
2. **Explicit acquisition start/stop** — `start_acquisition()` /
   `stop_acquisition()`: useful for long continuous runs and multi-device
   synchronization; maps directly to `start_collect()` / `stop_collect()`.
3. **Live count rates** — `get_cps()`: handy for optical alignment and
   monitoring; a base implementation could derive it from `get_singles()`.
4. **Calibration** — `calibrate()`: generic device hygiene operation.

`TDCBackend.get_g2(method="software")` provides the generic
"`get_timestamps()` + `tdc.analysis.g2.compute_g2`" implementation for
backends that provide raw timestamps. A backend may override the same method
to support `method="hardware"`; this does **not** apply to the TDC1610.

Keep as TDC1610-specific: QRNG, mark trigger, dynamic range / draw window,
trigger mode / clock configuration, and the low-level error callback.

## Notes

- `get_singles()` uses `GetCpsByUser()` (counts/s reported by the device);
  counts are reconstructed as `rate × integration_time`.
- `get_timestamps()` / `compute_g2()` are intentionally unsupported: the SDK
  only returns per-channel histograms — see "Raw Timestamps vs. Histogram"
  above.
- The vendor SDK prints some startup text to stdout when loading the DLL and
  caches a singleton instance; this is upstream SDK behavior.
