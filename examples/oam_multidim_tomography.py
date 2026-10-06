"""Finite-dimensional OAM tomography examples.

Run from the repository root with:

    PYTHONPATH=src python examples/oam_multidim_tomography.py
"""

from __future__ import annotations

import numpy as np

from qtools.tomo.oam import (
    oam_mub_projectors,
    oam_projectors,
    polarization_oam_skyrmion_density_matrix,
    polarization_projectors,
    product_povm,
    simulate_counts,
    skyrmion_topological_charge,
    two_oam_entangled_state,
)
from qtools.tomo.oam import Tomography, negativity


def polarization_oam_example(seed=1):
    l_values = (-2, -1, 0, 1, 2)
    rho = polarization_oam_skyrmion_density_matrix(l_values=l_values)
    oam_bases = [oam_projectors(l_values)] + [
        oam_mub_projectors(l_values, basis_index=k) for k in range(len(l_values))
    ]
    settings = [(pol, oam) for pol in polarization_projectors().values() for oam in oam_bases]
    effects = product_povm(settings)
    counts = simulate_counts(rho, effects, shots=20_000, rng=seed)
    tomo = Tomography(dims=[2, len(l_values)], maxfev=50_000)
    fitted, intensity, fval = tomo.StateTomography_POVM(effects, counts, method="MLE")
    charge = skyrmion_topological_charge(rho, radial_points=48, angular_points=96)
    return fitted, intensity, fval, charge


def two_oam_example(seed=2):
    l_values = (-2, -1, 0, 1, 2)
    ket = two_oam_entangled_state(l_values=l_values, l_pair=1)
    rho = np.outer(ket, ket.conj())
    oam_bases = [oam_projectors(l_values)] + [
        oam_mub_projectors(l_values, basis_index=k) for k in range(len(l_values))
    ]
    settings = [(left, right) for left in oam_bases for right in oam_bases]
    effects = product_povm(settings)
    counts = simulate_counts(rho, effects, shots=5_000, rng=seed)
    fitted, intensity, fval = Tomography(dims=[5, 5], maxfev=50_000).StateTomography_POVM(
        effects, counts, method="MLE", rho_start=rho
    )
    return fitted, intensity, fval, negativity(fitted, dims=[5, 5], subsystem=0)


if __name__ == "__main__":
    rho, intensity, fval, charge = polarization_oam_example()
    print("[2,5] trace =", np.trace(rho))
    print("[2,5] intensity =", intensity, "fval =", fval)
    print("Skyrmion topological charge =", charge)
