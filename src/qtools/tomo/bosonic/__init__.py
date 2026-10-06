"""qtools.tomo.bosonic - Bosonic/Continuous-Variable Quantum State Tomography.

Provides a clean, modular wrapper around QuTiP for state reconstruction in Fock space
using displaced photon counting statistics and Iterative Maximum Likelihood Estimation (iMLE).
"""

from __future__ import annotations

from .measurements import (
    construct_displaced_fock_operators,
    displaced_photon_probabilities,
    q_function,
    simulate_photon_counts,
    wigner_function,
)
from .states import (
    cat_state,
    coherent_density_matrix,
    coherent_state,
    displaced_state,
    fock_density_matrix,
    fock_state,
    squeezed_vacuum_state,
    superposition_state,
    thermal_state,
)
from .tomography import BosonicTomography, BosonicTomographyResult
from .visualization import (
    plot_fock_distribution,
    plot_hinton,
    plot_q_function,
    plot_reconstruction_summary,
    plot_wigner,
)

__all__ = [
    # Core Solver & Result
    "BosonicTomography",
    "BosonicTomographyResult",
    # State Constructors
    "fock_state",
    "fock_density_matrix",
    "coherent_state",
    "coherent_density_matrix",
    "cat_state",
    "squeezed_vacuum_state",
    "thermal_state",
    "displaced_state",
    "superposition_state",
    # Measurement & Operators
    "construct_displaced_fock_operators",
    "displaced_photon_probabilities",
    "simulate_photon_counts",
    "q_function",
    "wigner_function",
    # Visualizations
    "plot_q_function",
    "plot_wigner",
    "plot_fock_distribution",
    "plot_hinton",
    "plot_reconstruction_summary",
]
