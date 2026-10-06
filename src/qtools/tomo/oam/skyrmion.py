"""Polarization-OAM skyrmion texture and topological-charge utilities."""

from __future__ import annotations

import numpy as np
from scipy.special import eval_genlaguerre, factorial
from scipy.integrate import trapezoid

from .states import validate_l_values


def laguerre_gaussian_mode(ell, r, phi, waist=1.0, radial_index=0):
    """Evaluate a dimensionless p=0 Laguerre-Gaussian mode."""
    if waist <= 0:
        raise ValueError("waist must be positive")
    abs_l = abs(int(ell))
    scaled = np.sqrt(2.0) * np.asarray(r) / float(waist)
    radial = scaled**abs_l * eval_genlaguerre(int(radial_index), abs_l, scaled**2) * np.exp(-scaled**2 / 2.0)
    radial /= np.sqrt(factorial(abs_l + int(radial_index)) / factorial(int(radial_index)))
    return radial * np.exp(1j * int(ell) * np.asarray(phi))


def polarization_oam_stokes_texture(rho, l_values=(-2, -1, 0, 1, 2), radial_points=96, angular_points=192, r_max=4.0, waist=1.0):
    """Return radius, azimuth, normalized Stokes texture and intensity."""
    labels = validate_l_values(l_values)
    d = len(labels)
    rho = np.asarray(rho, dtype=complex)
    if rho.shape != (2 * d, 2 * d):
        raise ValueError("rho must have shape (2*len(l_values), 2*len(l_values))")
    if not np.allclose(rho, rho.conj().T, atol=1e-8):
        raise ValueError("rho must be Hermitian")
    radii = np.linspace(0.0, float(r_max), int(radial_points))
    phis = np.linspace(0.0, 2.0 * np.pi, int(angular_points), endpoint=False)
    stokes = np.zeros((len(radii), len(phis), 3), dtype=float)
    intensity = np.zeros((len(radii), len(phis)), dtype=float)
    for ri, radius in enumerate(radii):
        modes = np.array([laguerre_gaussian_mode(label, radius, phis, waist=waist) for label in labels])
        for pi in range(len(phis)):
            mode = modes[:, pi]
            coherency = np.empty((2, 2), dtype=complex)
            for a in range(2):
                for b in range(2):
                    block = rho[a * d:(a + 1) * d, b * d:(b + 1) * d]
                    coherency[a, b] = mode @ block @ mode.conj()
            total = max(float(np.real(np.trace(coherency))), 0.0)
            intensity[ri, pi] = total
            if total > 1e-14:
                stokes[ri, pi] = np.array(
                    [
                        2.0 * np.real(coherency[0, 1]),
                        2.0 * np.imag(coherency[0, 1]),
                        np.real(coherency[0, 0] - coherency[1, 1]),
                    ],
                    dtype=float,
                ) / total
    return radii, phis, stokes, intensity


def skyrmion_topological_charge(rho, l_values=(-2, -1, 0, 1, 2), radial_points=96, angular_points=192, r_max=4.0, waist=1.0, return_diagnostics=False):
    """Compute normalized polarization-texture topological charge."""
    radii, phis, stokes, intensity = polarization_oam_stokes_texture(rho, l_values, radial_points, angular_points, r_max, waist)
    if len(radii) < 3 or len(phis) < 3:
        raise ValueError("radial_points and angular_points must both be at least 3")
    dr = np.gradient(stokes, radii, axis=0, edge_order=1)
    dphi = phis[1] - phis[0]
    dp = (np.roll(stokes, -1, axis=1) - np.roll(stokes, 1, axis=1)) / (2.0 * dphi)
    density = np.einsum("...i,...i->...", stokes, np.cross(dr, dp))
    valid = intensity > 1e-14
    density = np.where(valid, density, 0.0)
    charge = float(trapezoid(trapezoid(density, phis, axis=1), radii, axis=0) / (4.0 * np.pi))
    if return_diagnostics:
        return charge, {"radial_points": len(radii), "angular_points": len(phis), "r_max": float(r_max), "waist": float(waist), "valid_fraction": float(np.mean(valid))}
    return charge
