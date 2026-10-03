"""Quantum State Tomography subpackage for qtools.

Powered by UIUC KwiatLab's Quantum-Tomography framework.
Provides comprehensive quantum state and process tomography, maximum likelihood
estimation (MLE), error estimation, state properties (fidelity, purity, concurrence),
and publication-ready 2D/3D density matrix visualization.
"""

from __future__ import annotations

from .TomoClass import Tomography
from .TomoDisplay import (
    floatToString,
    makeRhoImages,
    matrixToHTML,
    printLastOutput,
    propertiesToHTML,
    saveRhoImages,
    stateToString,
)
from .TomoDisplayHelpers import *
from .TomoFunctions import (
    concurrence,
    density2t,
    density2tm,
    densityOperation,
    entropy,
    fidelity,
    generalized_pauli_basis,
    get_stokes_parameters,
    getWavePlateBasis,
    halfWavePlate,
    ketOperation,
    linear_entropy,
    log_likelyhood,
    make_positive,
    negativity,
    partial_transpose,
    performOperation,
    psd_cholesky,
    purity,
    quarterWavePlate,
    random_bell_state,
    random_density_state,
    random_pure_state,
    removeGlobalPhase,
    t_matrix,
    t_to_density,
    tangle,
    toDensity,
)
from .Utilities import (
    ConfDict,
    cast_to_numpy,
    parse_np_array,
)

__all__ = [
    # Core Class
    "Tomography",
    # Tomography Functions
    "fidelity",
    "purity",
    "concurrence",
    "tangle",
    "entropy",
    "linear_entropy",
    "negativity",
    "t_to_density",
    "density2t",
    "density2tm",
    "t_matrix",
    "toDensity",
    "log_likelyhood",
    "psd_cholesky",
    "make_positive",
    "partial_transpose",
    "removeGlobalPhase",
    "generalized_pauli_basis",
    "get_stokes_parameters",
    "performOperation",
    "densityOperation",
    "ketOperation",
    "quarterWavePlate",
    "halfWavePlate",
    "getWavePlateBasis",
    "random_pure_state",
    "random_density_state",
    "random_bell_state",
    # Visualization & Display
    "makeRhoImages",
    "saveRhoImages",
    "matrixToHTML",
    "propertiesToHTML",
    "printLastOutput",
    "stateToString",
    "floatToString",
    # Utilities
    "ConfDict",
    "cast_to_numpy",
    "parse_np_array",
]
