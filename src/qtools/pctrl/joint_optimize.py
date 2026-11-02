"""Compatibility helpers for the former joint optimizer.

The optimization loop now lives in :mod:`qtools.pctrl.optimize`.  This module
keeps the old correlation helpers and ``CompositeMeasurement`` import working
for existing scripts while new code should use ``BasisMeasurement`` directly.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from qtools.pctrl.optimize import BasisMeasurement


# Backward-compatible name used by older notebooks and scripts.
CompositeMeasurement = BasisMeasurement

TARGETS = {
    "HH": {"planes": [{"name": "linear", "bright": [("H", "H")], "dark": [("V", "V"), ("H", "V"), ("V", "H")]}]},
    "VV": {"planes": [{"name": "linear", "bright": [("V", "V")], "dark": [("H", "H"), ("H", "V"), ("V", "H")]}]},
    "HV": {"planes": [{"name": "linear", "bright": [("H", "V")], "dark": [("V", "H"), ("H", "H"), ("V", "V")]}]},
    "VH": {"planes": [{"name": "linear", "bright": [("V", "H")], "dark": [("H", "V"), ("H", "H"), ("V", "V")]}]},
    "HH+VV": {"planes": [
        {"name": "linear", "weight": 0.5, "bright": [("H", "H"), ("V", "V")], "dark": [("H", "V"), ("V", "H")]},
        {"name": "diagonal", "weight": 0.5, "bright": [("D", "D"), ("A", "A")], "dark": [("D", "A"), ("A", "D")]},
    ]},
    "HV+VH": {"planes": [
        {"name": "linear", "weight": 0.5, "bright": [("H", "V"), ("V", "H")], "dark": [("H", "H"), ("V", "V")]},
        {"name": "diagonal", "weight": 0.5, "bright": [("D", "D"), ("A", "A")], "dark": [("D", "A"), ("A", "D")]},
    ]},
}

ACTIVE_TARGET = ""
ACTIVE_PLANES: list[dict] = []
MEASUREMENT_KEYS: list[tuple[str, str]] = []


def apply_target(target: str) -> None:
    """Select the legacy visibility target and derive its measurement keys."""
    global ACTIVE_TARGET, ACTIVE_PLANES, MEASUREMENT_KEYS
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}; choose from {', '.join(sorted(TARGETS))}")
    planes = []
    keys = []
    for raw in TARGETS[target]["planes"]:
        bright = tuple((str(a).upper(), str(b).upper()) for a, b in raw["bright"])
        dark = tuple((str(a).upper(), str(b).upper()) for a, b in raw["dark"])
        overlap = set(bright) & set(dark)
        if overlap:
            raise ValueError(f"target {target!r} has bright/dark overlap: {sorted(overlap)!r}")
        plane = {
            "name": str(raw["name"]),
            "weight": float(raw.get("weight", 1.0)),
            "bright": bright,
            "dark": dark,
        }
        planes.append(plane)
        for key in bright + dark:
            if key not in keys:
                keys.append(key)
    ACTIVE_TARGET, ACTIVE_PLANES, MEASUREMENT_KEYS = target, planes, keys


def plane_correlations(counts: dict) -> dict[str, float]:
    values = {}
    for plane in ACTIVE_PLANES:
        bright = [float(counts.get(key, 0.0)) for key in plane["bright"]]
        dark = [float(counts.get(key, 0.0)) for key in plane["dark"]]
        denominator = sum(abs(value) for value in bright + dark)
        values[plane["name"]] = -1.0 if denominator <= 1e-12 else float(
            np.clip((sum(bright) - sum(dark)) / denominator, -1.0, 1.0)
        )
    return values


def figure_of_merit(counts: dict) -> float:
    """Legacy visibility metric; higher is better."""
    correlations = plane_correlations(counts)
    total_weight = sum(plane["weight"] for plane in ACTIVE_PLANES)
    if total_weight <= 1e-12:
        return -1.0
    return float(np.clip(
        sum(plane["weight"] * correlations[plane["name"]] for plane in ACTIVE_PLANES)
        / total_weight,
        -1.0,
        1.0,
    ))


def save_counts(path: str | Path, rows: list[tuple]) -> None:
    """Save legacy per-basis visibility history."""
    path = Path(path)
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


apply_target("HH+VV")


if __name__ == "__main__":
    raise SystemExit(
        "joint_optimize was merged into qtools.pctrl.optimize; "
        "use PolarizationController.optimize with BasisMeasurement."
    )
