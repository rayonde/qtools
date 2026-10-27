#!/usr/bin/env python3
"""
fit.py
------
Maximum Likelihood Estimation (MLE) parameter fitter for polarization systems.
Fits servo calibration parameters (scale, offset, wobble terms), waveplate
retardance, and the input polarization state (alpha, beta) from intensity-vs-angle
sweep data.

Supports three-stage fitting with optional retardance fitting and global
degeneracy breaking (fixing first servo offset to 0).
"""

import numpy as np
from scipy.optimize import minimize
from typing import List, Dict, Any

from .modeling import JonesModel, map_servo_to_plate


# ══════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════

def _build_angles_for_row(
    row: np.ndarray,
    scales: List[float],
    offsets: List[float],
    a_wobbles: List[float],
    b_wobbles: List[float],
    retardances: List[float],
) -> List[tuple]:
    """Build (optical_angle, delta_rad) pairs for one sweep row.

    Each servo j has a SINGLE retardance delta_j shared across all rows.
    The optical fast-axis angle is computed via map_servo_to_plate.
    """
    return [
        (
            map_servo_to_plate(row[j], scales[j], offsets[j],
                               a_wobbles[j], b_wobbles[j]),
            retardances[j],
        )
        for j in range(len(scales))
    ]


# ══════════════════════════════════════════════════════════════
# Main fitter
# ══════════════════════════════════════════════════════════════

def fit_polarization_system(
    servo_sweeps: np.ndarray,           # (N, M) — servo physical angles
    intensities: np.ndarray,            # (N,) — measured intensities / rates
    waveplate_types: List[str],         # ["RETARDER"] * M (or ["QWP","HWP","QWP"])
    analyzer_deg: float = 0.0,
    retardance_guesses: List[float] | None = None,  # per-servo delta (rad)
    fit_retardance: bool = True,
    fix_first_offset: bool = True,      # break global alpha/offset degeneracy
) -> Dict[str, Any]:
    """Fit polarization system parameters from sweep data.

    Parameters
    ----------
    servo_sweeps : (N, M) array
        Physical servo angles for each of N measurements and M servos.
    intensities : (N,) array
        Measured intensity / count rate at each measurement point.
    waveplate_types : list of str
        Waveplate type per servo.  When ``fit_retardance=True`` the fitter
        treats every element as ``"RETARDER"``, using *retardance_guesses*
        (or inferred values) as the per-servo retardance.
    analyzer_deg : float
        Linear analyzer orientation in degrees.
    retardance_guesses : list of float, optional
        Per-servo initial retardance in radians.  Required when
        ``fit_retardance=True``.  A typical value for a QWP is ``0.25*pi``.
    fit_retardance : bool
        Whether to fit retardance as a free parameter (bounded around guess).
    fix_first_offset : bool
        If True, fix servo 0 offset to 0.  This breaks the global degeneracy
        between alpha and a uniform rotation of all offsets.

    Returns
    -------
    dict
        ``alpha``, ``beta`` — input polarization state (radians).
        ``gain``, ``bg_offset`` — intensity rescaling (original units).
        ``servos`` — list of per-servo dicts with keys:
            ``scale``, ``offset``, ``a_wobble``, ``b_wobble``, ``retardance``.
        ``r_squared`` — coefficient of determination.
        ``predictions`` — model intensities in original units (N,).
    """
    n_servos = len(waveplate_types)
    n_points = len(intensities)

    # ── Normalise intensities ────────────────────────────────────
    int_min, int_max = np.min(intensities), np.max(intensities)
    int_range = int_max - int_min if int_max > int_min else 1.0
    y_norm = (intensities - int_min) / int_range

    # ── Retardance initialisation ─────────────────────────────────
    if retardance_guesses is None:
        retardance_guesses = []
        for wp in waveplate_types:
            w = wp.upper()
            if w == "QWP":
                retardance_guesses.append(np.pi / 2)
            elif w == "HWP":
                retardance_guesses.append(np.pi)
            else:
                retardance_guesses.append(np.pi / 2)  # fallback
    retardance_guesses = [float(r) for r in retardance_guesses]

    # Force RETARDER type when fitting retardance
    wp_types = (["RETARDER"] * n_servos) if fit_retardance else waveplate_types

    # ── Shared loss builder ───────────────────────────────────────
    def _loss(params, n_off, n_scale, n_ret, n_wob):
        """Build residual sum of squares for given parameter layout.

        Parameter layout (per servo):
          offset_j   (skip j=0 if fix_first_offset)
          scale_j
          retardance_j
          a_wobble_j, b_wobble_j   (zeroed when n_wob == 0)
        """
        alpha, beta, gain, bg = params[:4]
        cursor = 4

        offsets = [0.0] * n_servos if fix_first_offset else [0.0] * n_servos
        start_j = 1 if fix_first_offset else 0
        for j in range(start_j, n_servos):
            offsets[j] = params[cursor]
            cursor += 1

        scales = []
        for j in range(n_servos):
            scales.append(params[cursor])
            cursor += 1

        rets = []
        for j in range(n_servos):
            rets.append(params[cursor])
            cursor += 1

        a_wobs = [0.0] * n_servos
        b_wobs = [0.0] * n_servos
        if n_wob:
            for j in range(n_servos):
                a_wobs[j] = params[cursor]
                cursor += 1
                b_wobs[j] = params[cursor]
                cursor += 1

        sse = 0.0
        for i in range(n_points):
            angs = _build_angles_for_row(
                servo_sweeps[i], scales, offsets, a_wobs, b_wobs, rets
            )
            theory = JonesModel.intensity(
                wp_types, angs, alpha, beta, analyzer_deg=analyzer_deg
            )
            pred = gain * theory + bg
            sse += (y_norm[i] - pred) ** 2
        return sse

    # ═══════════════════════════════════════════════════════════
    # Stage 1 — linear params + retardance (no wobble)
    # ═══════════════════════════════════════════════════════════
    p0 = [np.pi / 4, 0.0, 1.0, 0.0]  # alpha, beta, gain, bg
    bounds = [
        (0.0, np.pi / 2), (0.0, 2 * np.pi), (0.01, 10.0), (-0.5, 0.5),
    ]

    n_off_s1 = n_servos - (1 if fix_first_offset else 0)
    for _ in range(n_off_s1):
        p0.append(0.0)
        bounds.append((-180.0, 180.0))

    for _ in range(n_servos):
        p0.append(1.0)
        bounds.append((0.8, 1.25))

    for j in range(n_servos):
        rg = retardance_guesses[j]
        p0.append(rg)
        bounds.append((rg * 0.95, rg * 1.05) if fit_retardance else (rg, rg))

    res1 = minimize(_loss, p0, args=(n_off_s1, n_servos, n_servos, 0),
                    bounds=bounds, method="L-BFGS-B")

    # ═══════════════════════════════════════════════════════════
    # Stage 2 — add wobble terms
    # ═══════════════════════════════════════════════════════════
    p2 = list(res1.x)
    bounds2 = list(bounds)
    for j in range(n_servos):
        p2.extend([0.0, 0.0])
        bounds2.extend([(-15.0, 15.0), (-15.0, 15.0)])

    n_wob = n_servos  # signal that wobble terms are present
    res2 = minimize(_loss, p2, args=(n_off_s1, n_servos, n_servos, n_wob),
                    bounds=bounds2, method="L-BFGS-B")

    # ═══════════════════════════════════════════════════════════
    # Stage 3 — joint refinement of all params
    # ═══════════════════════════════════════════════════════════
    res3 = minimize(_loss, res2.x, args=(n_off_s1, n_servos, n_servos, n_wob),
                    bounds=bounds2, method="L-BFGS-B", options={"maxiter": 500})

    # ═══════════════════════════════════════════════════════════
    # Extract results
    # ═══════════════════════════════════════════════════════════
    best = res3.x
    alpha_fit, beta_fit, gain_f, bg_f = best[:4]
    cursor = 4

    offsets = [0.0] * n_servos
    start_j = 1 if fix_first_offset else 0
    for j in range(start_j, n_servos):
        offsets[j] = float(best[cursor])
        cursor += 1

    scales = []
    for j in range(n_servos):
        scales.append(float(best[cursor]))
        cursor += 1

    rets = []
    for j in range(n_servos):
        rets.append(float(best[cursor]))
        cursor += 1

    a_wobs = [0.0] * n_servos
    b_wobs = [0.0] * n_servos
    for j in range(n_servos):
        a_wobs[j] = float(best[cursor])
        cursor += 1
        b_wobs[j] = float(best[cursor])
        cursor += 1

    fitted_gain = gain_f * int_range
    fitted_bg = bg_f * int_range + int_min

    # Predictions
    y_pred = np.zeros(n_points)
    for i in range(n_points):
        angs = _build_angles_for_row(
            servo_sweeps[i], scales, offsets, a_wobs, b_wobs, rets
        )
        y_pred[i] = fitted_gain * JonesModel.intensity(
            wp_types, angs, alpha_fit, beta_fit, analyzer_deg=analyzer_deg
        ) + fitted_bg

    ss_res = np.sum((intensities - y_pred) ** 2)
    ss_tot = np.sum((intensities - np.mean(intensities)) ** 2)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    servos_fit = []
    for j in range(n_servos):
        servos_fit.append({
            "scale": scales[j],
            "offset": offsets[j],
            "a_wobble": a_wobs[j],
            "b_wobble": b_wobs[j],
            "retardance": rets[j],
        })

    return {
        "alpha": float(alpha_fit),
        "beta": float(beta_fit),
        "gain": float(fitted_gain),
        "bg_offset": float(fitted_bg),
        "servos": servos_fit,
        "r_squared": float(r_squared),
        "predictions": y_pred,
    }
