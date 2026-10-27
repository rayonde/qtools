#!/usr/bin/env python3
"""joint_optimize.py -- joint optimisation of the alice + bob fibre paddles.

``--target`` selects the physical polarisation target.  Each target is a list
of measurement planes:

    TARGET -> PLANES -> measurement keys -> counts -> J

Within one plane, bright basis combinations contribute +1 and dark combinations
contribute -1:

    E = (sum(bright counts) - sum(dark counts))
        / (sum(bright counts) + sum(dark counts))

Product targets (HH, VV, HV, VH) use one linear plane.  Entangled targets
(HH+VV, HV+VH) use linear and diagonal planes, combined with equal 0.5/0.5
weights by default.  This keeps the two visibility measurements equally
important even when their raw count rates differ.

Modes:
    python -m qtools.pctrl.joint_optimize --target HH+VV
    python -m qtools.pctrl.joint_optimize --target VV --fast
    python -m qtools.pctrl.joint_optimize --target HH+VV --track
    python -m qtools.pctrl.joint_optimize --apply

Outputs, all inside optimized_paddles/: history_*.csv (angles + J per
evaluation), counts_*.csv (per-basis counts and per-plane correlations),
paddles_*.yaml (--save), *.png (--plot) and _work/ (the config copies a run
uses).  pctrl_config.yaml and polmeas_config.yaml are only read, never written.

Single side only: TARGET_PATHS = ["alice"] (or ["bob"]).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# 1. Parameters -- usually the only section you need to edit
# ---------------------------------------------------------------------------

HERE = Path.cwd()
PCTRL_CONFIG = HERE / "pctrl_config.yaml"       # servos + TDC (read only)
POLMEAS_CONFIG = HERE / "polmeas_config.yaml"   # basis HWP motors (read only)
OUT_DIR = HERE / "optimized_paddles"            # every file this script writes
WORK_DIR = OUT_DIR / "_work"                    # config copies used by a run

TARGET_PATHS = ["alice", "bob"]   # pctrl channel paths to optimise; keep one for one side
BASIS_SIDES = ["alice", "bob"]    # pmeas optical_path, one per measurement column

# Measurement settings (same names as `pctrl optimize` / pmeas scan).
# WS / WE / CH_START / CH_STOP / DELAY must match the running coincidence setup:
# use exactly the values you would pass to `pctrl optimize --ch_start/--ch_stop/
# --delay/--ws/--we`.  Nothing can be inherited from polmeas_config.yaml here --
# its own window is left on auto-detect (window_start: null).
MEAS_TYPE = "pairs"    # "pairs" (two-photon) | "singles" (single photon)
TIME = 2.0             # integration time per measurement, s   [--time]
SAMPLES = 5            # readings averaged per measurement     [--samples]
SINGLES_CH = 1         # singles: TDC channel (1-based)        [--channel]
CH_START = 1           # pairs: start channel (1-based)        [--ch_start]
CH_STOP = 4            # pairs: stop channel (1-based)         [--ch_stop]
DELAY = 100            # pairs: stop-channel delay, bins       [--delay]
WS = 109               # pairs: coincidence window start, bins [--ws]
WE = 110               # pairs: coincidence window stop, bins  [--we]
#   ^ WS / WE above are placeholders: put your real coincidence window here.
THRESHVOLT = 0.6       # pairs: TDC threshold, V               [--threshvolt]

# Physical targets.  All terms within a plane have equal magnitude.  The
# optional "weight" controls how that plane contributes to the final scalar J.
TARGETS = {
    "HH": {
        "planes": [
            {
                "name": "linear",
                "bright": [("H", "H")],
                "dark": [("V", "V"), ("H", "V"), ("V", "H")],
            },
        ],
    },
    "VV": {
        "planes": [
            {
                "name": "linear",
                "bright": [("V", "V")],
                "dark": [("H", "H"), ("H", "V"), ("V", "H")],
            },
        ],
    },
    "HV": {
        "planes": [
            {
                "name": "linear",
                "bright": [("H", "V")],
                "dark": [("V", "H"), ("H", "H"), ("V", "V")],
            },
        ],
    },
    "VH": {
        "planes": [
            {
                "name": "linear",
                "bright": [("V", "H")],
                "dark": [("H", "V"), ("H", "H"), ("V", "V")],
            },
        ],
    },
    "HH+VV": {
        "planes": [
            {
                "name": "linear",
                "weight": 0.5,
                "bright": [("H", "H"), ("V", "V")],
                "dark": [("H", "V"), ("V", "H")],
            },
            {
                "name": "diagonal",
                "weight": 0.5,
                "bright": [("D", "D"), ("A", "A")],
                "dark": [("D", "A"), ("A", "D")],
            },
        ],
    },
    "HV+VH": {
        "planes": [
            {
                "name": "linear",
                "weight": 0.5,
                "bright": [("H", "V"), ("V", "H")],
                "dark": [("H", "H"), ("V", "V")],
            },
            {
                "name": "diagonal",
                "weight": 0.5,
                "bright": [("D", "D"), ("A", "A")],
                "dark": [("D", "A"), ("A", "D")],
            },
        ],
    },
}

ACTIVE_TARGET = ""
ACTIVE_PLANES: list[dict] = []
MEASUREMENT_KEYS: list[tuple[str, str]] = []


def apply_target(target: str) -> None:
    """Set the active target and derive its unique basis measurements."""
    global ACTIVE_TARGET, ACTIVE_PLANES, MEASUREMENT_KEYS
    if target not in TARGETS:
        raise ValueError(
            f"unknown target {target!r}; choose from {', '.join(sorted(TARGETS))}"
        )

    planes = []
    keys: list[tuple[str, str]] = []
    for raw in TARGETS[target]["planes"]:
        bright = [(str(a).upper(), str(b).upper()) for a, b in raw["bright"]]
        dark = [(str(a).upper(), str(b).upper()) for a, b in raw["dark"]]
        overlap = set(bright) & set(dark)
        if overlap:
            pairs = ", ".join(f"{a},{b}" for a, b in sorted(overlap))
            raise ValueError(f"target {target!r} has bright/dark overlap: {pairs}")

        plane = {
            "name": str(raw["name"]),
            "weight": float(raw.get("weight", 1.0)),
            "bright": tuple(bright),
            "dark": tuple(dark),
        }
        if plane["weight"] <= 0.0:
            raise ValueError(f"target {target!r} plane weights must be positive")
        planes.append(plane)
        for key in bright + dark:
            if key not in keys:
                keys.append(key)

    ACTIVE_TARGET = target
    ACTIVE_PLANES = planes
    MEASUREMENT_KEYS = keys


def plane_correlations(counts: dict) -> dict[str, float]:
    """Return one normalized correlation value for each active plane."""
    values = {}
    for plane in ACTIVE_PLANES:
        bright = [float(counts.get(key, 0.0)) for key in plane["bright"]]
        dark = [float(counts.get(key, 0.0)) for key in plane["dark"]]
        denominator = sum(abs(value) for value in bright + dark)
        if denominator <= 1e-12:
            values[plane["name"]] = -1.0
        else:
            values[plane["name"]] = float(
                np.clip((sum(bright) - sum(dark)) / denominator, -1.0, 1.0)
            )
    return values


def figure_of_merit(counts: dict) -> float:
    """Combine per-plane correlations into one scalar J, higher is better."""
    correlations = plane_correlations(counts)
    total_weight = sum(plane["weight"] for plane in ACTIVE_PLANES)
    if total_weight <= 1e-12:
        return -1.0
    value = sum(
        plane["weight"] * correlations[plane["name"]]
        for plane in ACTIVE_PLANES
    ) / total_weight
    return float(np.clip(value, -1.0, 1.0))


# Used by --apply and by direct library imports. New searches require --target.
apply_target("HH+VV")

# Optimizer settings (defaults match `pctrl optimize`).
METHOD = "Nelder-Mead"
MAXITER = 100
TOL = 1.0              # Nelder-Mead angle tolerance, deg     [--tol]
STEP_SIZE_DEG = 15.0   # initial simplex step                 [--step-size]
SPEED_DEG_S = 10.0
SETTLE_TIME = 0.1      # extra wait after the servos stop
BASIS_SETTLE = 0.05    # extra wait after each basis motor move

# Quick preset shared by --fast / --dry-run and used as the base of --track
# (coarser step, shorter integration, like `pctrl calibrate --fast`).
FAST_TIME = 0.2
FAST_SAMPLES = 1
FAST_MAXITER = 15
FAST_STEP_SIZE_DEG = 30.0

APPLY = False          # True -> same as --apply (restore the last saved optimum)
SAVE = True            # True -> same as --save (write the result to OUT_DIR)
SAVE_PROCESS = True    # True -> keep the history / counts CSV in OUT_DIR
PLOT = False           # True -> save the convergence plot in OUT_DIR
TRACK = False          # True -> same as --track (local re-optimisation only)
TRACK_RANGE_DEG = 5.0  # default --rangle: +/- window around the start angles

RANGE_PENALTY = -1.0   # J reported for points outside the tracking window


class CompositeMeasurement:
    """Readout adapter returning the basis-combined figure of merit J.

    ``optimize_channel`` reads every point through ``meas_mgr.measure()``.  This
    adapter sits in that slot: each read rotates the basis HWPs to every basis
    combination listed in MEASUREMENT_KEYS, measures each one through pctrl
    ``MeasManager`` and returns the combined metric, so no extra hardware read is
    spent and the optimizer needs no other hook.

    All measurement arguments arrive from ``optimize_channel`` unchanged, i.e.
    the same ``--measure/--ch_start/--ws/--we`` parameters as `pctrl optimize`.
    """

    def __init__(self, meas_mgr, polmeas_cfg, motor_mgr):
        self.meas_mgr = meas_mgr
        self.polmeas_cfg = polmeas_cfg
        self.motor_mgr = motor_mgr
        self.servo_mgr = None
        self.servo_names: list[str] = []
        self.limits = None             # (angles, half_width_deg) in tracking mode
        self.basis_now: dict = {}      # side -> label, keeps repeated moves out
        self.last_counts: dict = {}
        self.history_rows: list = []   # (evaluation, counts, J) for counts_*.csv
        self.last_elapsed = 0.0

    def set_tracking(self, servo_mgr, servo_names: list[str], start: list[float],
                     half_width_deg: float) -> None:
        """Restrict the readout to a +/- window around *start* (tracking mode).

        optimize_channel only knows the servo limits, so tracking mode adds this
        softer box: a point outside the window is scored as the worst possible J
        and is not measured at all.
        """
        self.servo_mgr = servo_mgr
        self.servo_names = list(servo_names)
        self.limits = (list(start), float(half_width_deg))

    def out_of_range(self) -> bool:
        """True when some servo has drifted outside the tracking window."""
        if self.limits is None:
            return False
        start, half_width = self.limits
        for name, ref in zip(self.servo_names, start):
            angle = self.servo_mgr.get_angle(name) - self.servo_mgr.get_servo_center(name)
            if abs(angle - ref) > half_width:
                return True
        return False

    # -- basis ----------------------------------------------------------
    def _basis_angle(self, side: str, basis) -> float:
        """Resolve a basis label with pmeas' own resolver (same as its CLI)."""
        from qtools.pmeas.entanglement import _get_basis_angle

        return float(_get_basis_angle(self.polmeas_cfg, side, basis))

    def _move_basis(self, side: str, basis) -> None:
        key = str(basis).upper()
        if self.basis_now.get(side) == key:
            return
        stage = self.motor_mgr.get_motor(side)
        stage.move_to(self._basis_angle(side, basis))
        stage.wait_move()
        time.sleep(BASIS_SETTLE)
        self.basis_now[side] = key

    # -- readout --------------------------------------------------------
    def _read(self, duration, samples, channels, measure_type, ch_start,
              ch_stop, delay, window_start, window_stop, threshvolt) -> float:
        if measure_type == "pairs":
            result = self.meas_mgr.measure(
                duration=duration, samples=samples, measure_type="pairs",
                ch_start=ch_start, ch_stop=ch_stop, delay=delay,
                window_start=window_start, window_stop=window_stop,
                threshvolt=threshvolt,
            )
        else:
            result = self.meas_mgr.measure(
                duration=duration, samples=samples, channels=channels,
            )
        return float(result[0][0])

    def measure(self, duration=None, samples=None, channels=None,
                measure_type="singles", ch_start=None, ch_stop=None, delay=None,
                window_start=None, window_stop=None, threshvolt=None) -> list:
        """Measure every basis combination and return ``[(J, 0.0)]``."""
        started = time.time()
        if self.out_of_range():
            self.last_counts = {}
            self.last_elapsed = time.time() - started
            return [(RANGE_PENALTY, 0.0)]
        counts = {}
        for basis_a, basis_b in MEASUREMENT_KEYS:
            self._move_basis(BASIS_SIDES[0], basis_a)
            self._move_basis(BASIS_SIDES[1], basis_b)
            counts[(basis_a, basis_b)] = self._read(
                duration, samples, channels, measure_type, ch_start, ch_stop,
                delay, window_start, window_stop, threshvolt,
            )
        self.last_counts = counts
        self.last_elapsed = time.time() - started
        return [(figure_of_merit(counts), 0.0)]

    def log_evaluation(self, eval_count, angles, value, raw) -> None:
        """optimize_channel callback: print the per-basis counts behind J."""
        self.history_rows.append((eval_count, dict(self.last_counts), float(value)))
        if not self.last_counts:
            print("      outside the tracking window -> worst-case J", flush=True)
            return
        parts = " ".join(f"{a}{b.lower()}={c:9.2f}"
                         for (a, b), c in self.last_counts.items())
        correlations = "  ".join(
            f"E_{name}={value:+.4f}"
            for name, value in plane_correlations(self.last_counts).items()
        )
        print(f"      {parts}   {correlations}   "
              f"({self.last_elapsed:.1f}s)", flush=True)


def _merged_channel(cfg) -> dict:
    """Build one channel dict holding every servo of TARGET_PATHS.

    optimize_channel optimises ``channel["servos"]`` in a single Nelder-Mead run;
    merging alice and bob into one channel is what makes the optimisation joint
    instead of one side after the other.
    """
    wanted = [p.lower() for p in TARGET_PATHS]
    channels = [c for c in cfg.channels if str(c.get("path", "")).lower() in wanted]
    if not channels:
        sys.exit(f"channels {TARGET_PATHS} not found in {PCTRL_CONFIG.name}")
    servos = []
    for channel in channels:
        servos.extend(sorted(channel["servos"], key=lambda s: s["order"]))
    return {
        "path": "+".join(str(c["path"]) for c in channels),
        "wavelength": channels[0].get("wavelength", 1560),
        "servos": servos,
    }


def measurement_kwargs() -> dict:
    """Measurement settings handed to the readout.

    optimize_channel forwards them to ``meas_mgr.measure`` unchanged, i.e. the
    same flags as `pctrl optimize`.
    """
    return {
        "measure_type": MEAS_TYPE,
        "channels": None if MEAS_TYPE == "pairs" else [SINGLES_CH],
        "ch_start": CH_START,
        "ch_stop": CH_STOP,
        "delay": DELAY,
        "window_start": WS,
        "window_stop": WE,
        "threshvolt": THRESHVOLT,
    }


def write_angles(ctrl, servo_names: list[str], angles: list[float]) -> None:
    """Push physical angles to the servos through pctrl's own set path.

    ctrl.set_angles() is the route `pctrl set` uses (utils.run_direct_set), so
    the angle-to-servo mapping stays identical to the CLI; the caller only has
    to keep *angles* in *servo_names* order.
    """
    wanted = [p.lower() for p in TARGET_PATHS]
    for src in ctrl.cfg.channels:
        if str(src.get("path", "")).lower() not in wanted:
            continue
        names = [s["name"] for s in sorted(src["servos"], key=lambda s: s["order"])]
        ctrl.set_angles(src["path"], [angles[servo_names.index(n)] for n in names])


def last_optimum(servo_names: list[str]) -> tuple[list[float], str] | None:
    """Recover the angles of the most recent saved optimisation in OUT_DIR.

    Prefers the newest saved result (paddles_*.yaml, written by --save), then the
    newest history CSV that every run writes (this script maximises J, so the
    best row is the one with the largest `val`).  ``None`` when neither source
    holds an angle for every servo.
    """
    import csv
    import yaml

    for path in sorted(OUT_DIR.glob("paddles_*.yaml"), reverse=True):
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        servos = data.get("servos") or {}
        if all(name in servos for name in servo_names):
            angles = [float(servos[name]) for name in servo_names]
            return angles, (f"{path.name} "
                            f"(J={float(data.get('optimal_value', 0.0)):+.4f})")

    for path in sorted(OUT_DIR.glob("history_*.csv"), reverse=True):
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or len(rows[0]) - 3 != len(servo_names):
            continue        # saved for a different servo set, not usable
        best = max(rows, key=lambda row: float(row["val"]))
        angles = [float(best[f"angle_{i + 1}"]) for i in range(len(servo_names))]
        return angles, (f"{path.name}, evaluation {best['evaluation']} "
                        f"(J={float(best['val']):+.4f})")

    return None


def working_configs() -> tuple[Path, Path]:
    """Copy both configs into OUT_DIR/_work and return the copies.

    pctrl's ServoManager rewrites its config file every time it connects (port /
    ID refresh, timestamps), so the run is handed copies: the configs in the
    experiment folder are only read and stay exactly as the user left them.
    """
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    copies = []
    for src in (PCTRL_CONFIG, POLMEAS_CONFIG):
        dst = WORK_DIR / src.name
        shutil.copy2(src, dst)
        copies.append(dst)
    return copies[0], copies[1]


def save_result(channel: dict, servo_names: list[str], result) -> Path:
    """Write one run's optimum to OUT_DIR as YAML (--save)."""
    import yaml

    path = OUT_DIR / time.strftime("paddles_%Y%m%d_%H%M%S.yaml")
    data = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "channel": channel["path"],
        "wavelength": channel.get("wavelength", 1560),
        "metric": "J = weighted mean of per-plane correlations, higher is better",
        "optimal_value": float(result.optimal_value),
        "n_evaluations": int(result.n_evaluations),
        "measure_type": MEAS_TYPE,
        "target": ACTIVE_TARGET,
        "planes": [
            {
                "name": plane["name"],
                "weight": plane["weight"],
                "bright": [list(key) for key in plane["bright"]],
                "dark": [list(key) for key in plane["dark"]],
            }
            for plane in ACTIVE_PLANES
        ],
        "servos": {name: float(angle) for name, angle
                   in zip(servo_names, result.optimal_angles)},
    }
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    return path


def plot_history(channel: dict, servo_names: list[str], result) -> Path:
    """Save the convergence figure into OUT_DIR using pctrl's own plotter."""
    from qtools.pctrl.analysis.plotting import plot_optimization_history

    return Path(plot_optimization_history(
        title=f"{channel['path']} @ {channel.get('wavelength', 1560)} nm",
        servo_names=servo_names,
        history=result.history,
        success=bool(result.success),
        optimal_value=float(result.optimal_value),
        out_dir=str(OUT_DIR),
    ))


def save_counts(path: Path, rows: list[tuple]) -> None:
    """Write per-basis counts and per-plane correlations for each evaluation."""
    import csv

    plane_names = [plane["name"] for plane in ACTIVE_PLANES]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["evaluation", "J"]
            + [f"E_{name}" for name in plane_names]
            + [f"{a},{b}" for a, b in MEASUREMENT_KEYS]
        )
        for evaluation, counts, value in rows:
            correlations = plane_correlations(counts)
            writer.writerow(
                [evaluation, value]
                + [correlations.get(name, "") for name in plane_names]
                + [counts.get(key, "") for key in MEASUREMENT_KEYS]
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", dest="target", type=str.upper,
                        choices=sorted(TARGETS), default=None,
                        help="physical target (" + ", ".join(sorted(TARGETS))
                             + "); required unless --apply is used")
    parser.add_argument("--fast", "--dry-run", dest="fast", action="store_true",
                        help="quick optimisation pass: coarse step, short integration")
    parser.add_argument("--track", action="store_true",
                        help="tracking mode: search only within +/- --rangle of the "
                             "last saved optimum (thermal drift)")
    parser.add_argument("--rangle", type=float, default=TRACK_RANGE_DEG,
                        help="tracking half-width, deg "
                             f"(default {TRACK_RANGE_DEG})")
    parser.add_argument("--maxiter", type=int, default=None)
    parser.add_argument("--time", type=float, default=None, help="integration time, s")
    parser.add_argument("--samples", type=int, default=None)
    parser.add_argument("--tol", type=float, default=TOL, help="angle tolerance, deg")
    parser.add_argument("--step-size", type=float, default=None)
    parser.add_argument("--apply", action="store_true",
                        help="apply the last saved optimum to the servos and exit "
                             "(newest paddles_*.yaml, else newest history_*.csv)")
    parser.add_argument("--save", action="store_true",
                        help=f"save the optimum to {OUT_DIR.name}/paddles_<time>.yaml")
    parser.add_argument("--plot", action="store_true",
                        help=f"save the convergence figure in {OUT_DIR.name}/")
    args = parser.parse_args()
    if args.target is None and not args.apply:
        parser.error("--target is required for a new optimisation")
    apply_target(args.target or "HH+VV")

    if MEAS_TYPE == "pairs" and (WS is None or WE is None):
        sys.exit("MEAS_TYPE='pairs' requires WS / WE, same as `pctrl optimize --ws/--we`")

    # --fast / --dry-run is one switch: one preset, one code path.
    # An explicitly given value always wins over the preset.
    track = args.track or TRACK
    fast = args.fast or track        # tracking is a quick pass by definition
    maxiter = args.maxiter if args.maxiter is not None else (
        FAST_MAXITER if fast else MAXITER)
    seconds = args.time if args.time is not None else (
        FAST_TIME if fast else TIME)
    samples = args.samples if args.samples is not None else (
        FAST_SAMPLES if fast else SAMPLES)
    if args.step_size is not None:
        step_size = args.step_size
    elif track:
        step_size = args.rangle / 2.0   # keep the simplex inside the window
    else:
        step_size = FAST_STEP_SIZE_DEG if fast else STEP_SIZE_DEG

    from qtools.pctrl.api import PolarizationController
    from qtools.pctrl.optimize import optimize_channel

    # Work on copies so that pctrl's own config refresh never touches the files
    # in the experiment folder.
    pctrl_config, polmeas_config = working_configs()

    # --apply is a restore-only mode: it pushes the previous optimum (not the
    # result of a new search) to the servos and stops there.  The saved values
    # are read from OUT_DIR, so nothing is connected until there really is
    # something to move to.
    if args.apply:
        from qtools.pctrl.config import ConfigManager

        cfg = ConfigManager.resolve(str(pctrl_config))
        servo_names = [s["name"] for s in _merged_channel(cfg)["servos"]]
        found = last_optimum(servo_names)
        if found is None:
            sys.exit(f"--apply: nothing saved in {OUT_DIR.name}/ yet -- run the "
                     f"optimisation (with --save) before applying")
        angles, source = found
        print(f"[apply] previous optimum from {source}")
        ctrl = PolarizationController(config_path=str(pctrl_config))
        write_angles(ctrl, servo_names, angles)
        for name, angle in zip(servo_names, angles):
            print(f"      {name:<20s} {angle:8.3f} deg")
        ctrl.close()
        return

    ctrl = PolarizationController(config_path=str(pctrl_config))
    channel = _merged_channel(ctrl.cfg)
    servo_names = [s["name"] for s in channel["servos"]]

    from qtools.pmeas.meas_manager import TaskController

    pmeas = TaskController(str(polmeas_config))
    motor_mgr, polmeas_cfg = pmeas.motor_mgr, pmeas.cfg

    composite = CompositeMeasurement(
        meas_mgr=ctrl.meas_mgr, polmeas_cfg=polmeas_cfg, motor_mgr=motor_mgr,
    )

    # Tracking mode: start from the last saved optimum and only accept points
    # inside +/- --rangle, so only a local refinement is done.
    if track:
        found = last_optimum(servo_names)
        if found is None:
            start = [ctrl.get_angles(name)[name] for name in servo_names]
            source = "the current servo angles (nothing saved yet)"
        else:
            start, source = found
            write_angles(ctrl, servo_names, start)
        composite.set_tracking(ctrl.servo_mgr, servo_names, start, args.rangle)
        print(f"[track] start from {source}")
        print(f"[track] accepting only +/-{args.rangle} deg around that point")

    print(f"[target] {ACTIVE_TARGET}: " + "  ".join(
        f"E_{plane['name']} w={plane['weight']:.2f}" for plane in ACTIVE_PLANES
    ))
    est = len(MEASUREMENT_KEYS) * (seconds * samples + 3.0) + SETTLE_TIME
    print(f"[cfg] {MEAS_TYPE}, {len(MEASUREMENT_KEYS)} measurements, "
          f"{seconds}s x {samples} samples, ~{est:.0f}s / evaluation"
          f"{'   [tracking]' if track else '   [fast mode]' if fast else ''}")
    print(f"[cfg] servos ({len(servo_names)}): {', '.join(servo_names)}")
    print(f"[cfg] results -> {OUT_DIR}")
    print(f"[cfg] config copies in {WORK_DIR.name}/, the originals are untouched")

    OUT_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    save_process = (str(OUT_DIR / f"history_{stamp}.csv")
                    if SAVE_PROCESS else None)

    result = optimize_channel(
        cfg=ctrl.cfg,
        channel=channel,
        servo_mgr=ctrl.servo_mgr,
        meas_mgr=composite,
        callback=composite.log_evaluation,
        minimize_metric=False,
        method=METHOD,
        maxiter=maxiter,
        tol=args.tol,
        step_size_deg=step_size,
        speed_deg_s=SPEED_DEG_S,
        settle_time=SETTLE_TIME,
        duration=seconds,
        samples=samples,
        **measurement_kwargs(),
        verbose=True,
        save_process=save_process,
    )

    print(f"\n[opt] {result.message}")
    print(f"[opt] best J = {result.optimal_value:+.4f}  "
          f"({result.n_evaluations} evaluations, {result.n_iterations} iterations)")
    for name, angle in zip(servo_names, result.optimal_angles):
        print(f"      {name:<20s} {angle:8.3f} deg")

    if SAVE_PROCESS:
        counts_path = OUT_DIR / f"counts_{stamp}.csv"
        save_counts(counts_path, composite.history_rows)
        print(f"[log] {counts_path}")
    if args.save or SAVE or track:
        print(f"[save] {save_result(channel, servo_names, result)}")
    if args.plot or PLOT:
        print(f"[plot] {plot_history(channel, servo_names, result)}")

    pmeas.close()
    ctrl.close()


if __name__ == "__main__":
    main()
