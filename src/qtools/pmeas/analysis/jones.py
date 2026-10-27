"""Jones calculus for waveplate modelling.

References the same mathematical model used in ``qtools.pctrl``.
"""

from __future__ import annotations

import numpy as np


def jones_retarder(theta_deg: float, delta_deg: float) -> np.ndarray:
    """Jones matrix of a linear retarder.

    Parameters
    ----------
    theta_deg : float
        Fast-axis angle in degrees.
    delta_deg : float
        Retardance in degrees.  ``180`` gives an ideal HWP and ``90``
        gives an ideal QWP.

    Notes
    -----
    The convention is chosen so that ``jones_retarder(theta, 180)`` equals
    :func:`jones_hwp` and ``jones_retarder(theta, 90)`` equals
    :func:`jones_qwp`.
    """
    t = np.radians(theta_deg)
    delta = np.radians(delta_deg)
    c = np.cos(t)
    s = np.sin(t)
    phase = np.exp(1j * delta)

    return np.array([
        [c**2 + phase * s**2, (1.0 - phase) * s * c],
        [(1.0 - phase) * s * c, s**2 + phase * c**2],
    ], dtype=complex)


def jones_hwp(theta_deg: float) -> np.ndarray:
    """Jones matrix of an ideal half-wave plate (HWP)."""
    return jones_retarder(theta_deg, 180.0)


def jones_qwp(theta_deg: float) -> np.ndarray:
    """Jones matrix of an ideal quarter-wave plate (QWP)."""
    return jones_retarder(theta_deg, 90.0)


def transmission_retarder_pbs(
    theta_deg: float,
    delta_deg: float,
    input_jones: np.ndarray = None,
) -> float:
    """Power transmitted through a retarder followed by a horizontal PBS.

    The PBS transmits horizontal polarization, i.e. it projects the output
    Jones vector onto ``[1, 0]``.

    Parameters
    ----------
    theta_deg : float
        Retarder fast-axis angle in degrees.
    delta_deg : float
        Retardance in degrees.  ``180`` corresponds to an ideal HWP and
        ``90`` corresponds to an ideal QWP.
    input_jones : np.ndarray, optional
        Input Jones vector (default: horizontal ``[1, 0]``).

    Returns
    -------
    float
        Normalised transmitted intensity in ``[0, 1]`` for a normalised
        input Jones vector.
    """
    if input_jones is None:
        input_jones = np.array([1.0, 0.0], dtype=complex)
    input_jones = np.asarray(input_jones, dtype=complex)
    if input_jones.shape != (2,):
        raise ValueError("input_jones must be a length-2 Jones vector")

    # Keep this expression vectorized in theta_deg so calibration fitting can
    # evaluate a whole scan without calling the scalar Jones matrix once per
    # point.  For a scalar angle the return type remains float.
    theta = np.radians(np.asarray(theta_deg, dtype=float))
    delta = np.radians(delta_deg)
    c = np.cos(theta)
    s = np.sin(theta)
    phase = np.exp(1j * delta)
    out_h = (
        (c**2 + phase * s**2) * input_jones[0]
        + (1.0 - phase) * s * c * input_jones[1]
    )
    transmitted = np.asarray(np.abs(out_h) ** 2, dtype=float)
    # PBS transmits H -> project onto [1, 0].
    return float(transmitted) if transmitted.ndim == 0 else transmitted


def transmission_hwp_pbs(
    theta_deg: float,
    input_jones: np.ndarray = None,
) -> float:
    """Power transmitted through an ideal HWP followed by a horizontal PBS.

    This is a convenience wrapper around :func:`transmission_retarder_pbs`
    with ``delta_deg=180``.
    """
    return transmission_retarder_pbs(theta_deg, 180.0, input_jones)


def _normalize_basis_angle(angle_deg: float) -> float:
    """Preserve negative basis angles; wrap non-negative angles as before."""
    if angle_deg < 0.0:
        return float(angle_deg)
    return float(angle_deg % 180.0)


def compute_target_angles(theta_0: float, waveplate: str = "hwp") -> dict[str, float]:
    """Compute the stage angles for standard polarization bases.

    For a HWP followed by a PBS, rotating the HWP by Δθ rotates the
    output linear polarization by 2·Δθ.

    Parameters
    ----------
    theta_0 : float
        Calibrated fast-axis offset (degrees).
    waveplate : str
        ``"hwp"`` or ``"qwp"``.

    Returns
    -------
    dict[str, float]
        Mapping from basis label to target motor angle.
    """
    if waveplate == "hwp":
        return {
            "H": _normalize_basis_angle(theta_0),
            "D": _normalize_basis_angle(theta_0 + 22.5),
            "V": _normalize_basis_angle(theta_0 + 45.0),
            "A": _normalize_basis_angle(theta_0 + 67.5),
        }
    else:  # qwp
        return {
            "R": _normalize_basis_angle(theta_0 - 45.0),
            "L": _normalize_basis_angle(theta_0 + 45.0),
        }
