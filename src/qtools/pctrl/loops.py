"""
loops.py
--------
Logic to calculate required fiber loops for HWP/QWP retardations.
"""

from __future__ import annotations
import numpy as np


def map_cladding_to_d(cladding_um: float) -> float:
    """Map cladding or jacket diameter (in um) to the glass cladding diameter (in meters)."""
    if cladding_um in (125.0, 900.0, 250.0):
        return 125e-6
    elif cladding_um == 80.0:
        return 80e-6
    else:
        if cladding_um > 150.0:
            return 125e-6
        else:
            return cladding_um * 1e-6


def retardation(wl: float, N, D: float, d: float) -> float:
    """Estimates retardation (in waves) from looping fiber.

    Args:
        wl: Wavelength, in nm.
        N: Number of loops (integer or numpy array).
        D: Diameter of loops, in mm.
        d: Cladding diameter, in meters.
    """
    a = 0.133  # constant for Silica fiber
    wl_m = wl * 1e-9
    D_m = D * 1e-3
    return np.pi * a * N * (d**2) / wl_m / D_m


def select_candidates(rs, loops):
    """Select loop count that is closest to QWP and HWP retardations."""
    # Halfwave, close to 0.5 + k
    hw_distances = np.abs((rs % 1) - 0.5)
    hw_errors = hw_distances / 0.5
    hw_loop = loops[np.argmin(hw_errors)]
    hw_error = np.min(hw_errors)

    # Quarter wave, close to 0.25 + 0.5k
    qw_distances = np.abs((rs % 0.5) - 0.25)
    qw_errors = qw_distances / 0.25
    qw_loop = loops[np.argmin(qw_errors)]
    qw_error = np.min(qw_errors)
    return int(qw_loop), float(qw_error * 100), int(hw_loop), float(hw_error * 100)


def run_loops(args) -> None:
    """Calculate required loops for QWP and HWP retardations."""
    wl = args.wavelength
    D = args.diameter
    cladding_um = args.cladding

    d = map_cladding_to_d(cladding_um)
    
    # Search up to 6 loops by default
    loop_counts = np.arange(1, 7)
    rs = retardation(wl, loop_counts, D, d)
    qw_loop, qw_err, hw_loop, hw_err = select_candidates(rs, loop_counts)

    print(f"Wavelength: {wl:.1f} nm")
    print(f"Loop Diameter: {D:.1f} mm")
    print(f"Fiber cladding option: {cladding_um:.1f} um (effective glass cladding: {d*1e6:.1f} um)")
    print("-" * 50)
    print(f"Calculated results (from physicsutils stress-induced birefringence):")
    print(f"  QWP (λ/4): {qw_loop} loop(s) (error: {qw_err:.1f}%)")
    print(f"  HWP (λ/2): {hw_loop} loop(s) (error: {hw_err:.1f}%)")

    # Thorlabs recommended tables
    THORLABS_QWP = {
        480: {18: 3, 27: None, 56: 3},
        630: {18: 3, 27: 2, 56: 4},
        780: {18: 4, 27: 1, 56: 2},
        850: {18: 3, 27: 1, 56: 2},
        980: {18: 2, 27: 3, 56: 2},
        1060: {18: 2, 27: 3, 56: 2},
        1310: {18: 1, 27: 4, 56: 3},
        1550: {18: 1, 27: 2, 56: 3},
    }

    THORLABS_HWP = {
        480: {18: 2, 27: 3, 56: 2},
        630: {18: 1, 27: 4, 56: 3},
        780: {18: 1, 27: 2, 56: 4},
        850: {18: 1, 27: 2, 56: 4},
        980: {18: 4, 27: 2, 56: 4},
        1060: {18: 4, 27: 2, 56: 4},
        1310: {18: 2, 27: 3, 56: 6},
        1550: {18: 2, 27: 3, 56: 6},
    }

    std_wls = [480, 630, 780, 850, 980, 1060, 1310, 1550]
    std_ds = [18, 27, 56]

    closest_wl = min(std_wls, key=lambda w: abs(w - wl))
    closest_d = min(std_ds, key=lambda d_val: abs(d_val - D))

    if abs(closest_wl - wl) <= 10 and abs(closest_d - D) <= 2:
        rec_q = THORLABS_QWP[closest_wl][closest_d]
        rec_h = THORLABS_HWP[closest_wl][closest_d]
        q_str = f"{rec_q} loop(s)" if rec_q is not None else "N/A"
        h_str = f"{rec_h} loop(s)" if rec_h is not None else "N/A"
        print(f"\nThorlabs Reference (for ~{closest_wl} nm, Ø{closest_d} mm):")
        print(f"  QWP (λ/4): {q_str}")
        print(f"  HWP (λ/2): {h_str}")
