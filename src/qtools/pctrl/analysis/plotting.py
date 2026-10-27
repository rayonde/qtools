#!/usr/bin/env python3
"""
plotting.py
-----------
Matplotlib figure generation for calibration and optimization results.

Two entry points, both of which save PNG figures to disk and (when a GUI
matplotlib backend is active) pop them up at the end:

  * ``plot_calibration(...)``        — fit curves, verification scatter, and
                                       a Poincaré-sphere trajectory figure.
  * ``plot_optimization_history(...)``— metric + servo-angle convergence trace.

Colors follow the validated categorical slots from the data-viz reference
palette; text stays in neutral ink so series identity is never color-alone.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib
import matplotlib.pyplot as plt

from .modeling import JonesModel, map_servo_to_plate

# ── Palette (validated categorical slots, light mode) ──────────────
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK = "#0b0b0b"            # primary text
INK_SECONDARY = "#52514e"  # labels / legend
MUTED = "#898781"          # axes, ticks
GRID = "#e1e0d9"           # hairline gridlines
SURFACE = "#fcfcfb"        # chart surface


# ══════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════

def _style_axes(ax: plt.Axes) -> None:
    """Apply the muted, recessive look shared by all 2-D figures."""
    ax.set_facecolor(SURFACE)
    for spine in ax.spines.values():
        spine.set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _save_figs(figs: list[plt.Figure], paths: list[Path]) -> None:
    """Save *figs* to *paths*, then pop them up if a GUI backend is active."""
    for fig, path in zip(figs, paths):
        fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
        print(f"Saved plot: {path}")
    if matplotlib.get_backend().lower() != "agg":
        plt.show()
    for fig in figs:
        plt.close(fig)


def _sanitize_filename(name: str) -> str:
    """Replace characters that are illegal in filenames (e.g. ':' on Windows)."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def _stokes_of(E: np.ndarray) -> np.ndarray:
    """Normalised Stokes vector (s1, s2, s3) for a Jones 2-vector *E*."""
    s0 = np.abs(E[0]) ** 2 + np.abs(E[1]) ** 2
    if s0 == 0:
        return np.array([0.0, 0.0, 0.0])
    s1 = np.abs(E[0]) ** 2 - np.abs(E[1]) ** 2
    s2 = 2.0 * np.real(E[0] * np.conj(E[1]))
    s3 = 2.0 * np.imag(E[0] * np.conj(E[1]))
    return np.array([s1 / s0, s2 / s0, s3 / s0])


def _model_states(
    servo_sweeps: np.ndarray,
    fit_res: dict,
) -> np.ndarray:
    """Output Stokes states (N, 3) from the fitted Jones model.

    Each sweep row is propagated through the fitted waveplates, so the
    resulting trajectories trace the output polarization on the Poincaré
    sphere as the plates rotate.
    """
    E_in = np.array([
        np.cos(fit_res["alpha"]),
        np.sin(fit_res["alpha"]) * np.exp(1j * fit_res["beta"]),
    ])
    states = np.empty((len(servo_sweeps), 3))
    for i in range(len(servo_sweeps)):
        pairs = [
            (
                map_servo_to_plate(
                    servo_sweeps[i, j],
                    fit_res["servos"][j]["scale"],
                    fit_res["servos"][j]["offset"],
                    fit_res["servos"][j].get("a_wobble", 0.0),
                    fit_res["servos"][j].get("b_wobble", 0.0),
                ),
                fit_res["servos"][j]["retardance"],
            )
            for j in range(len(fit_res["servos"]))
        ]
        E_out = JonesModel.system_matrix(["RETARDER"] * len(pairs), pairs) @ E_in
        states[i] = _stokes_of(E_out)
    return states


# ══════════════════════════════════════════════════════════════
# Calibration figures
# ══════════════════════════════════════════════════════════════

def plot_calibration(
    *,
    group_name: str,
    basis: str,
    servos: list[dict],
    servo_sweeps: np.ndarray,       # (N, M) physical servo angles
    measured_means: np.ndarray,     # (N, C) measured channel means
    sweep_ids: np.ndarray,          # (N,) 1-based sweep config id
    fit_res: dict,
    test_angles: np.ndarray,        # (K, M) verification physical angles
    test_measured: np.ndarray,      # (K,)
    test_pred: np.ndarray,          # (K,)
    configs: list,                  # (hold_angs, sweep_idx) per config
    analyzer_deg: float,
    wavelength: float,
    fidelity: float,
    out_dir: str = "pctrl_calibration_data",
) -> list[Path]:
    """Plot calibration results and save them under *out_dir*.

    Produces three figures:

    1. **Fit** — one subplot per sweep config: measured intensity points vs
       the swept plate's fitted optical angle, with the model prediction line.
    2. **Verification** — measured vs predicted intensity for the random test
       points, with a ``y = x`` reference line.
    3. **Poincaré sphere** — the fitted output polarization trajectory for
       each sweep, colour-coded by sweep config.

    Returns the list of saved figure paths.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"cal_{_sanitize_filename(group_name)}_{basis}_{timestamp}"
    intensities = measured_means[:, 0]  # fit used first channel

    figs: list[plt.Figure] = []
    paths: list[Path] = []

    # ── 1. Fit curves ─────────────────────────────────────────────
    unique_ids = np.unique(sweep_ids)
    n_sweeps = len(unique_ids)
    ncols = 2 if n_sweeps > 2 else 1
    nrows = int(np.ceil(n_sweeps / ncols))
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(6.4 * ncols, 4.2 * nrows), squeeze=False,
    )
    for idx, k in enumerate(unique_ids):
        ax = axes.flat[idx]
        rows = np.where(sweep_ids == k)[0]
        hold_angs, sweep_idx = configs[k - 1]
        s_fit = fit_res["servos"][sweep_idx]
        x = np.array([
            map_servo_to_plate(
                servo_sweeps[r, sweep_idx],
                s_fit["scale"], s_fit["offset"],
                s_fit.get("a_wobble", 0.0), s_fit.get("b_wobble", 0.0),
            )
            for r in rows
        ])
        order = np.argsort(x)
        ax.scatter(x, intensities[rows], s=24, color=SERIES[0],
                   label="measured", zorder=3)
        ax.plot(x[order], fit_res["predictions"][rows][order],
                color=SERIES[1], linewidth=2, label="fit")
        ax.set_title(
            f"Sweep {servos[sweep_idx]['name']}   hold={hold_angs}",
            fontsize=10,
        )
        ax.set_xlabel("optical angle (deg)", fontsize=9)
        ax.set_ylabel("intensity", fontsize=9)
        ax.legend(fontsize=8, frameon=False)
        _style_axes(ax)
    for idx in range(n_sweeps, nrows * ncols):
        axes.flat[idx].set_axis_off()
    fig.suptitle(
        f"Calibration fit — {group_name} ({wavelength} nm), "
        f"basis {basis}, analyzer {analyzer_deg}°",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    figs.append(fig)
    paths.append(out / f"{prefix}_fit.png")

    # ── 2. Verification ───────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    lo = min(float(test_measured.min()), float(test_pred.min()))
    hi = max(float(test_measured.max()), float(test_pred.max()))
    ax.plot([lo, hi], [lo, hi], color=MUTED, linewidth=1.2,
            linestyle="--", label="y = x")
    ax.scatter(test_pred, test_measured, s=28, color=SERIES[0],
               label="test points", zorder=3)
    ax.set_xlabel("predicted intensity", fontsize=10)
    ax.set_ylabel("measured intensity", fontsize=10)
    ax.set_title(
        f"Verification — fidelity = {fidelity:.4f} "
        f"({len(test_measured)} random points)",
        fontsize=11,
    )
    ax.legend(fontsize=9, frameon=False)
    _style_axes(ax)
    fig.tight_layout()
    figs.append(fig)
    paths.append(out / f"{prefix}_verification.png")

    # ── 3. Poincaré sphere ───────────────────────────────────────
    states = _model_states(servo_sweeps, fit_res)
    fig = plt.figure(figsize=(7.0, 6.4))
    ax = fig.add_subplot(111, projection="3d")

    u = np.linspace(0, 2 * np.pi, 24)
    v = np.linspace(0, np.pi, 12)
    xs = np.outer(np.cos(u), np.sin(v))
    ys = np.outer(np.sin(u), np.sin(v))
    zs = np.outer(np.ones_like(u), np.cos(v))
    ax.plot_wireframe(xs, ys, zs, color=GRID, linewidth=0.5, alpha=0.6)

    for idx, k in enumerate(unique_ids):
        rows = np.where(sweep_ids == k)[0]
        pts = states[rows]
        color = SERIES[idx % len(SERIES)]
        ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], color=color,
                linewidth=2, alpha=0.85, label=f"sweep {int(k)}")
        ax.scatter(pts[:, 0], pts[:, 1], pts[:, 2], s=14,
                   color=color, depthshade=False)

    E_in = np.array([
        np.cos(fit_res["alpha"]),
        np.sin(fit_res["alpha"]) * np.exp(1j * fit_res["beta"]),
    ])
    s_in = _stokes_of(E_in)
    ax.scatter([s_in[0]], [s_in[1]], [s_in[2]], s=140, marker="*",
               color=INK, label="input state", depthshade=False)

    ax.set_xlabel("S₁", fontsize=10)
    ax.set_ylabel("S₂", fontsize=10)
    ax.set_zlabel("S₃", fontsize=10)
    ax.set_title("Output polarization on the Poincaré sphere", fontsize=11)
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0),
              fontsize=8, frameon=False)
    fig.tight_layout()
    figs.append(fig)
    paths.append(out / f"{prefix}_poincare.png")

    _save_figs(figs, paths)
    return paths


# ══════════════════════════════════════════════════════════════
# Optimization figures
# ══════════════════════════════════════════════════════════════

def plot_optimization_history(
    *,
    title: str,
    servo_names: list[str],
    history: list[dict],
    success: bool,
    optimal_value: float,
    out_dir: str = "pctrl_optimize_data",
) -> Path:
    """Plot the per-evaluation metric and servo-angle convergence trace.

    *history* is the list of ``{"angles": [...], "value": float,
    "std": float, "evaluation": int}`` records collected during
    ``optimize_channel``.

    Returns the saved figure path.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    evals = [h["evaluation"] for h in history]
    vals = [h["value"] for h in history]
    stds = [float(h.get("std", 0.0) or 0.0) for h in history]

    fig, (ax_metric, ax_angle) = plt.subplots(
        2, 1, figsize=(7.2, 7.6), sharex=True,
    )

    ax_metric.errorbar(
        evals,
        vals,
        yerr=stds,
        color=SERIES[0],
        linewidth=2,
        marker="o",
        markersize=3,
        capsize=2,
    )
    ax_metric.set_ylabel("metric value", fontsize=10)
    ax_metric.set_title(
        f"Optimization — {title}"
        f"{'  (converged)' if success else '  (no convergence)'} "
        f"— optimal value = {optimal_value:.4e}",
        fontsize=11,
    )
    _style_axes(ax_metric)

    for i, name in enumerate(servo_names):
        angs = [h["angles"][i] for h in history]
        ax_angle.plot(evals, angs, color=SERIES[i % len(SERIES)],
                      linewidth=1.6, marker="o", markersize=3, label=name)
    ax_angle.set_xlabel("evaluation", fontsize=10)
    ax_angle.set_ylabel("angle (deg)", fontsize=10)
    ax_angle.legend(fontsize=8, frameon=False)
    _style_axes(ax_angle)

    fig.tight_layout()
    path = out / f"opt_{_sanitize_filename(title)}_{timestamp}_history.png"
    _save_figs([fig], [path])
    return path
