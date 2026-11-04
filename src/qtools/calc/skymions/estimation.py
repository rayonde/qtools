#!/usr/bin/env python3
# State reconstruction and entanglement monotones
# Justin, 2026-10-23
#
# Note that in the context of QKD, the interferometric visibilities in the MUBs
# are sufficient to derive a QBER. These visibilities provide a lower bound to
# the concurrence of the shared entangled state, using entanglement witness
# W = I - ZZ - XX for local uncertainty relations, i.e. C >= -<W>

import itertools
import numpy as np
from scipy.optimize import minimize


H = np.array([1, 0], dtype=complex)
V = np.array([0, 1], dtype=complex)
D = (H + V) / np.sqrt(2)
A = (H - V) / np.sqrt(2)
R = (H + 1j * V) / np.sqrt(2)
L = (H - 1j * V) / np.sqrt(2)

pures = [H, V, D, A, R, L]  # 1-qubit pure states
B = np.zeros((36, 16), dtype=complex)  # measurement matrix (density matrix -> projected state)
Ps = []
for i, (s1, s2) in enumerate(itertools.product(pures, pures)):
    pure2 = np.kron(s1, s2)  # 2-qubit pure states
    P = np.outer(pure2, pure2.conj())
    Ps.append(P)
    B[i] = P.flatten()

def measure(rho):
    return np.real(np.array([np.trace(P @ rho) for P in Ps]))

def fidelity(rho, target):
    # How close a state is to the target state
    return np.real(np.trace(rho @ target))

def purity(rho):
    # How close the state is to a pure state
    return np.real(np.trace(rho @ rho))

def concurrence(rho):
    # One-to-one map to entanglement of formation
    # Wootters, William K. “Entanglement of Formation of an Arbitrary State of Two Qubits.”
    # Physical Review Letters 80, no. 10 (1998): 2245–48. https://doi.org/10.1103/PhysRevLett.80.2245.
    Y = np.array([[0, -1j], [1j, 0]])
    YY = np.kron(Y, Y)
    rho_tilde = YY @ np.conj(rho) @ YY
    R = rho @ rho_tilde

    # Get eigenvalues (guaranteed to non-negative real)
    eigenvalues = np.linalg.eigvals(R)
    lambdas = np.sqrt(np.maximum(np.real(eigenvalues), 0))
    lambdas = np.sort(lambdas)[::-1]  # descending order

    C = np.clip(lambdas[0] - np.sum(lambdas[1:]), 0, 1)
    return C

def entanglement_of_formation(rho):
    # Average entanglement required to locally prepare state 'rho'
    # Bennett, Charles H., David P. DiVincenzo, John A. Smolin, and William K. Wootters. “Mixed-State Entanglement and Quantum Error Correction.”
    # Physical Review A 54, no. 5 (1996): 3824–51. https://doi.org/10.1103/PhysRevA.54.3824.
    C = concurrence(rho)
    if C == 0:
        return 0
    if C == 1:
        return 1

    x = 0.5 * (1 + np.sqrt(1 - C**2))
    eof = -x * np.log2(x) - (1 - x) * np.log2(1 - x)
    return eof

def entanglement_entropy(rho):
    # von-Neumann entropy of a general mixed state
    # Bennett, Charles H., Herbert J. Bernstein, Sandu Popescu, and Benjamin Schumacher. “Concentrating Partial Entanglement by Local Operations.”
    # Physical Review A 53, no. 4 (1996): 2046–52. https://doi.org/10.1103/PhysRevA.53.2046.
    eigenvalues = np.linalg.eigvalsh(rho)  # for Hermitian
    valid_eigenvalues = eigenvalues[eigenvalues > 1e-10]
    entropy = -np.sum(valid_eigenvalues * np.log2(valid_eigenvalues))
    return entropy

def report_state(description, rho, target):
    print("\n" + description)
    print(np.round(rho, 3))
    trace = round(np.real(np.trace(rho)), 3)
    print("- Trace:", trace)
    if trace == 1:
        print("- Fidelity:", round(fidelity(rho, target), 3))
        print("- Purity:", round(purity(rho), 3))
        print("- Entropy:", round(entanglement_entropy(rho), 3))
        print("- Concurrence:", round(concurrence(rho), 3))
        print("- Entanglement of formation:", round(entanglement_of_formation(rho), 3))


# State preparation
phase = 0
phi_plus = 1/2**0.5 * (np.kron(H, H) + np.exp(1j * phase) * np.kron(V, V))
psi_plus = 1/2**0.5 * (np.kron(H, V) + np.kron(V, H))  # triplet state

state = psi_plus
rho = np.outer(state, state.conj())
measured = measure(rho)
measured_noisy = np.clip(measured + np.random.normal(0, 0.1, 36), 0, None)  # add noise


##########################################################
# Least-squares reconstruction
B_inv = np.linalg.pinv(B)  # pseudoinverse
"""
B = [
    P_HH, P_HV, P_HD, P_HA, P_HR, P_HL,
    P_VH, P_VV, ...,
    ...,
    ..., P_LA, P_LR, P_LL
]
"""
rho_lsq = (B_inv @ measured).reshape((4, 4))
report_state("Expected:", rho_lsq, rho)
# rho_lsq = (B_inv @ measured_noisy).reshape((4, 4))
# report_state("Least-squares:", rho_lsq, rho)


##########################################################
# Maximum-likelihood estimation
# We use Cholesky decomposition of the (positive semi-definite Hermitian)
# density matrix, i.e. rho = LL*
# Eqn S.24 and S.25 from [doi:10.1038/s41467-026-68751-3]
def L_from_params(x):
    """
    Maps flattened free-parameters of 4x4 lower triangular matrix L
    with real diagonal entries.
    """
    # Note diagonals are real and positive for
    # fmt: off
    return np.array([
        [x[0],          0,              0,              0    ],
        [x[1]+1j*x[2],  x[3],           0,              0    ],
        [x[4]+1j*x[5],  x[6]+1j*x[7],   x[8],           0    ],
        [x[9]+1j*x[10], x[11]+1j*x[12], x[13]+1j*x[14], x[15]],
    ], dtype=complex)
    # fmt: on

def rho_from_params(x):
    L = L_from_params(x)
    R = L @ L.conj().T  # Cholesky decomposition
    return R / np.real(np.trace(R))  # normalize to trace 1

def loss(x, measured):
    rho_guess = rho_from_params(x)
    estimated = measure(rho_guess)
    return np.sum((estimated - measured)**2)  # L2-norm

# White noise initial guess (identity matrix)
x0 = np.zeros(16)
x0[0] = x0[3] = x0[8] = x0[15] = 1
result = minimize(loss, x0, (measured_noisy,))

rho_mle = rho_from_params(result.x)
report_state("Maximum-likelihood:", rho_mle, rho)

# np.save("state.cache.npy", [rho_mle, rho])
