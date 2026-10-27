"""Correlation analysis utilities for coincidence measurements."""

from __future__ import annotations

import numpy as np


# ═══════════════════════════════════════════════════════════════════════════
# Correlation coefficient
# ═══════════════════════════════════════════════════════════════════════════


def get_correlation(
    c00: float,
    c11: float,
    c01: float,
    c10: float,
    e00: float = 0.0,
    e11: float = 0.0,
    e01: float = 0.0,
    e10: float = 0.0,
) -> tuple[float, float]:
    """Compute the correlation coefficient *E* and its propagated error.

    .. math::
        E = (C_{00} + C_{11} - C_{01} - C_{10}) /
            (C_{00} + C_{11} + C_{01} + C_{10})

    Parameters
    ----------
    c00, c11, c01, c10 : float
        Coincidence counts or rates for the four outcome combinations.
    e00, e11, e01, e10 : float, optional
        Standard uncertainties for the corresponding counts or rates.

    Returns
    -------
    tuple[float, float]
        The correlation coefficient ``E`` and its propagated standard
        uncertainty.  ``(0.0, 0.0)`` is returned when the total count is
        zero.
    """
    num = c00 + c11 - c01 - c10
    den = c00 + c11 + c01 + c10
    if den == 0:
        return 0.0, 0.0

    correlation = num / den

    # Error propagation for E = (same - opposite) / (same + opposite).
    term_same = 2.0 * (c01 + c10) / (den**2)
    term_opposite = -2.0 * (c00 + c11) / (den**2)
    error = np.sqrt(
        (term_same * e00) ** 2
        + (term_same * e11) ** 2
        + (term_opposite * e01) ** 2
        + (term_opposite * e10) ** 2
    )
    return float(correlation), float(error)
