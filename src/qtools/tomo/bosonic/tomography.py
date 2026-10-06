"""Bosonic Quantum State Tomography using Iterative Maximum Likelihood Estimation (iMLE).

Implements fast vectorized iMLE state reconstruction for continuous-variable/optical
cavity states in truncated Fock spaces based on QuTiP primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence
import numpy as np
import qutip as qt

from .measurements import (
    construct_displaced_fock_operators,
    displaced_photon_probabilities,
    simulate_photon_counts,
    q_function,
    wigner_function,
)


@dataclass
class BosonicTomographyResult:
    """Encapsulates the output of a bosonic state reconstruction."""

    rho: qt.Qobj
    iterations: int
    converged: bool
    final_delta: float
    fidelities: list[float] | None
    deltas: list[float]
    log_likelihoods: list[float]
    final_fidelity: float | None
    hilbert_size: int
    betas: list[complex]
    data: np.ndarray

    def to_numpy(self) -> np.ndarray:
        """Return the density matrix as a NumPy complex array."""
        return self.rho.full()

    def purity(self) -> float:
        """Calculate the state purity Tr(rho^2)."""
        return float(np.real((self.rho * self.rho).tr()))

    def fidelity_with(self, target: qt.Qobj | np.ndarray) -> float:
        """Compute fidelity with an arbitrary reference state."""
        target_qobj = qt.Qobj(target) if isinstance(target, np.ndarray) else target
        return float(qt.fidelity(self.rho, target_qobj))

    def fock_distribution(self, max_n: int | None = None) -> np.ndarray:
        """Return the photon number population P(n) = ⟨n|rho|n⟩."""
        n_max = self.hilbert_size if max_n is None else min(max_n, self.hilbert_size)
        diag = np.real(np.diag(self.rho.full()))
        return diag[:n_max]

    def q_func(self, xvec: np.ndarray, yvec: np.ndarray) -> np.ndarray:
        """Evaluate the Husimi Q-function of the reconstructed state."""
        return q_function(self.rho, xvec, yvec)

    def wigner(self, xvec: np.ndarray, yvec: np.ndarray) -> np.ndarray:
        """Evaluate the Wigner function of the reconstructed state."""
        return wigner_function(self.rho, xvec, yvec)

    def summary(self) -> str:
        """Return a formatted text summary of the reconstruction."""
        lines = [
            "===================================================",
            "        Bosonic Tomography (iMLE) Result           ",
            "===================================================",
            f"Hilbert size (cutoff N) : {self.hilbert_size}",
            f"Number of beta settings : {len(self.betas)}",
            f"Total iterations run    : {self.iterations}",
            f"Converged               : {self.converged}",
            f"Final step delta (||Δρ||): {self.final_delta:.4e}",
            f"Purity Tr(ρ²)           : {self.purity():.6f}",
        ]
        if self.final_fidelity is not None:
            lines.append(f"Target state fidelity   : {self.final_fidelity:.6f}")
        if len(self.log_likelihoods) > 0:
            lines.append(f"Final log-likelihood    : {self.log_likelihoods[-1]:.4e}")
        lines.append("===================================================")
        return "\n".join(lines)


class BosonicTomography:
    """Iterative Maximum Likelihood Estimation (iMLE) for Bosonic / Cavity States.

    Reconstructs the density matrix of a bosonic mode from displaced photon
    counting statistics P(n | beta).

    References
    ----------
    [1] Shen et al., 'Optimized tomography of continuous variable systems using
        excitation counting', Phys. Rev. A 94, 052327 (2016).
    [2] Řeháček, Hradil, Ježek, 'Iterative algorithm for reconstruction of
        entangled states', Phys. Rev. A 63, 040303 (2001).
    """

    DEFAULT_BETAS: list[complex] = [0.0, 2.0, -2.0, 2.0j, -2.0j]

    def __init__(
        self,
        hilbert_size: int = 32,
        betas: Sequence[complex | float] | None = None,
        max_photons: int | None = None,
    ) -> None:
        """Initialize the BosonicTomography solver.

        Parameters
        ----------
        hilbert_size : int, optional
            Dimension of the truncated Hilbert space. Default is 32.
        betas : Sequence[complex | float] | None, optional
            List of displacement amplitudes beta. If None, uses the 5 canonical
            phase space sample points [0, 2, -2, 2j, -2j].
        max_photons : int | None, optional
            Maximum photon number counted (0 <= n < max_photons).
            Defaults to hilbert_size.
        """
        if hilbert_size < 2:
            raise ValueError("hilbert_size must be at least 2")

        self.hilbert_size = hilbert_size
        self.betas = [complex(b) for b in (betas if betas is not None else self.DEFAULT_BETAS)]
        self.max_photons = hilbert_size if max_photons is None else max_photons

        if self.max_photons <= 0 or self.max_photons > hilbert_size:
            raise ValueError(
                f"max_photons must satisfy 1 <= max_photons <= hilbert_size={hilbert_size}"
            )

        # Precompute and cache measurement POVM operators for performance
        self._r_ops = construct_displaced_fock_operators(
            self.hilbert_size, self.betas, max_photons=self.max_photons
        )

        # Flatten into a 3D NumPy array of shape (K, N, N) for vectorized einsum execution
        flat_ops = []
        for beta_ops in self._r_ops:
            for op in beta_ops:
                flat_ops.append(op.full())
        self._ops_mats = np.array(flat_ops, dtype=complex)
        self._num_measurements = len(flat_ops)

    @property
    def num_measurements(self) -> int:
        """Total number of measurement outcomes (len(betas) * max_photons)."""
        return self._num_measurements

    def simulate_data(
        self,
        target_state: qt.Qobj,
        shots: int | None = None,
        noise_std: float | None = None,
        seed: int | None = None,
    ) -> np.ndarray:
        """Generate simulated measurement data from a true quantum state.

        Parameters
        ----------
        target_state : qt.Qobj
            True state (ket or density matrix).
        shots : int | None, optional
            If specified, returns simulated counts using multinomial sampling.
            If None, returns exact theoretical probabilities.
        noise_std : float | None, optional
            Standard deviation of additive Gaussian noise.
        seed : int | None, optional
            Random seed.

        Returns
        -------
        np.ndarray
            2D array of shape (len(betas), max_photons).
        """
        if shots is not None and shots > 0:
            return simulate_photon_counts(
                target_state,
                self.betas,
                shots_per_setting=shots,
                max_photons=self.max_photons,
                noise_std=noise_std,
                seed=seed,
                r_ops=self._r_ops,
            )
        else:
            probs = displaced_photon_probabilities(
                target_state, self.betas, max_photons=self.max_photons, r_ops=self._r_ops
            )
            if noise_std is not None and noise_std > 0:
                rng = np.random.default_rng(seed)
                probs += rng.normal(0.0, noise_std, size=probs.shape)
                probs = np.maximum(probs, 0.0)
            return probs

    def reconstruct(
        self,
        data: np.ndarray | Sequence,
        target_state: qt.Qobj | None = None,
        max_iter: int = 200,
        tol: float = 1e-6,
        rho_init: qt.Qobj | None = None,
        dilution: float = 1.0,
        eps: float = 1e-20,
        callback: Callable[[int, qt.Qobj, float], None] | None = None,
    ) -> BosonicTomographyResult:
        """Reconstruct the density matrix from measurement data using iMLE.

        The iterative update rule is:
            R = sum_k ( d_k / Tr[ M_k rho ] ) * M_k
            rho_{k+1} = R rho_k R / Tr[ R rho_k R ]

        Parameters
        ----------
        data : np.ndarray | Sequence
            2D array of shape (len(betas), max_photons) containing frequencies or counts.
        target_state : qt.Qobj | None, optional
            Optional true reference state used to track fidelity convergence per iteration.
        max_iter : int, optional
            Maximum number of iMLE iterations. Default is 200.
        tol : float, optional
            Convergence threshold on the Frobenius norm of delta_rho. Default is 1e-6.
        rho_init : qt.Qobj | None, optional
            Initial density matrix estimate. Defaults to maximally mixed state I / N.
        dilution : float, optional
            Dilution parameter in (0, 1] for diluted iMLE (Řeháček et al. 2007).
            When dilution=1.0, standard iMLE is used. Values < 1.0 stabilize noisy data.
        eps : float, optional
            Small regularizer added to denominator to avoid division by zero. Default: 1e-20.
        callback : Callable | None, optional
            Function called each iteration with signature callback(iteration, current_rho, current_delta).

        Returns
        -------
        BosonicTomographyResult
            Dataclass containing reconstructed rho, convergence metrics, and history.
        """
        arr_data = np.asarray(data, dtype=float)
        if arr_data.shape != (len(self.betas), self.max_photons):
            # Attempt to reshape if flat
            if arr_data.size == self._num_measurements:
                arr_data = arr_data.reshape((len(self.betas), self.max_photons))
            else:
                raise ValueError(
                    f"Data shape {arr_data.shape} does not match expected "
                    f"({len(self.betas)}, {self.max_photons})"
                )

        data_flat = arr_data.flatten()
        n_dim = self.hilbert_size
        identity = np.eye(n_dim, dtype=complex)

        # Initial density matrix
        if rho_init is not None:
            rho_mat = np.asarray(rho_init.full(), dtype=complex)
            rho_mat = (rho_mat + rho_mat.conj().T) / 2.0
            rho_mat /= np.trace(rho_mat).real
        else:
            rho_mat = identity / float(n_dim)

        fidelities: list[float] | None = [] if target_state is not None else None
        deltas: list[float] = []
        log_likelihoods: list[float] = []
        converged = False
        final_delta = 0.0

        for it in range(max_iter):
            # 1. Vectorized computation of probabilities: p_k = Tr(M_k rho)
            probs = np.einsum("kij,ji->k", self._ops_mats, rho_mat).real
            probs = np.maximum(probs, 0.0)

            # 2. Log-likelihood computation: sum d_k ln(p_k)
            denom = probs + eps
            ll = float(np.sum(data_flat * np.log(denom)))
            log_likelihoods.append(ll)

            # 3. Compute R operator: R = sum_k (d_k / p_k) * M_k
            weights = data_flat / denom
            r_mat = np.einsum("k,kij->ij", weights, self._ops_mats)

            # Apply dilution if requested: R_diluted = (1 - dilution) * I + dilution * R
            if dilution < 1.0:
                dilution_clamped = max(0.01, min(1.0, dilution))
                r_mat = (1.0 - dilution_clamped) * identity + dilution_clamped * r_mat

            # 4. State update: rho_{k+1} = R rho R / Tr(R rho R)
            rho_next = r_mat @ rho_mat @ r_mat
            trace_val = np.trace(rho_next).real
            if trace_val <= 0:
                # Numerical safeguard
                rho_next = (rho_next + rho_next.conj().T) / 2.0
                trace_val = max(np.trace(rho_next).real, 1e-12)
            rho_next /= trace_val

            # Hermitize to eliminate numerical float asymmetry
            rho_next = (rho_next + rho_next.conj().T) / 2.0

            # 5. Convergence check
            delta = float(np.linalg.norm(rho_next - rho_mat, ord="fro"))
            deltas.append(delta)
            final_delta = delta

            # Track fidelity if target is provided
            if target_state is not None:
                current_qobj = qt.Qobj(rho_next)
                fid = float(qt.fidelity(current_qobj, target_state))
                assert fidelities is not None
                fidelities.append(fid)

            if callback is not None:
                callback(it + 1, qt.Qobj(rho_next), delta)

            rho_mat = rho_next

            if delta < tol and it > 5:
                converged = True
                break

        final_qobj = qt.Qobj(rho_mat)
        final_fid = (
            float(qt.fidelity(final_qobj, target_state)) if target_state is not None else None
        )

        return BosonicTomographyResult(
            rho=final_qobj,
            iterations=len(deltas),
            converged=converged,
            final_delta=final_delta,
            fidelities=fidelities,
            deltas=deltas,
            log_likelihoods=log_likelihoods,
            final_fidelity=final_fid,
            hilbert_size=self.hilbert_size,
            betas=self.betas,
            data=arr_data,
        )

    def fit(self, data: np.ndarray | Sequence, **kwargs) -> BosonicTomographyResult:
        """Alias for reconstruct."""
        return self.reconstruct(data, **kwargs)
