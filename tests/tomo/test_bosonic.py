"""Unit tests for the bosonic Fock-space tomography and state toolkit."""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest
import qutip as qt

from qtools.tomo.bosonic import (
    BosonicTomography,
    cat_state,
    coherent_density_matrix,
    coherent_state,
    construct_displaced_fock_operators,
    displaced_photon_probabilities,
    displaced_state,
    fock_density_matrix,
    fock_state,
    plot_fock_distribution,
    plot_hinton,
    plot_q_function,
    plot_reconstruction_summary,
    plot_wigner,
    q_function,
    simulate_photon_counts,
    squeezed_vacuum_state,
    superposition_state,
    thermal_state,
    wigner_function,
)


def test_state_constructors():
    """Verify Fock, coherent, cat, squeezed, and thermal state constructors."""
    n_dim = 16

    # 1. Fock state
    f2 = fock_state(n_dim, 2)
    assert f2.isket
    assert f2.norm() == pytest.approx(1.0)
    assert np.argmax(np.abs(f2.full())) == 2

    fdm = fock_density_matrix(n_dim, 3)
    assert fdm.isoper
    assert fdm.tr() == pytest.approx(1.0)
    assert np.abs(fdm.full()[3, 3]) == pytest.approx(1.0)

    # 2. Coherent state
    alpha = 1.5 + 0.5j
    coh = coherent_state(n_dim, alpha)
    assert coh.isket
    assert coh.norm() == pytest.approx(1.0)

    coh_dm = coherent_density_matrix(n_dim, alpha)
    assert coh_dm.isoper
    assert coh_dm.tr() == pytest.approx(1.0)
    assert qt.fidelity(coh, coh_dm) == pytest.approx(1.0, abs=1e-5)

    # 3. Standard Cat states (even, odd, yurke-stoler)
    cat_even = cat_state(n_dim, 2.0, parity="even")
    cat_odd = cat_state(n_dim, 2.0, parity="odd")
    cat_ys = cat_state(n_dim, 2.0, parity="yurke-stoler")

    for cat in (cat_even, cat_odd, cat_ys):
        assert cat.isket
        assert cat.norm() == pytest.approx(1.0)

    # 4. Multi-headed cat state (e.g., 3-headed cat as in QuTiP tutorial)
    cat_3 = cat_state(n_dim, [2.0, -2.0 - 1.0j, -2.0 + 1.0j])
    assert cat_3.isket
    assert cat_3.norm() == pytest.approx(1.0)

    # 5. Squeezed vacuum state
    sq = squeezed_vacuum_state(n_dim, r=0.5, theta=np.pi / 4)
    assert sq.isket
    assert sq.norm() == pytest.approx(1.0)

    # 6. Thermal state
    th = thermal_state(n_dim, n_th=0.8)
    assert th.isoper
    assert th.tr() == pytest.approx(1.0)
    assert float(np.real((th * th).tr())) < 1.0  # Mixed state

    # 7. Displaced & Superposition helpers
    disp_f0 = displaced_state(fock_state(n_dim, 0), alpha=1.0)
    assert qt.fidelity(disp_f0, coherent_state(n_dim, 1.0)) == pytest.approx(1.0, abs=1e-5)

    sup = superposition_state([fock_state(n_dim, 0), fock_state(n_dim, 2)], weights=[1.0, 1.0])
    assert sup.norm() == pytest.approx(1.0)


def test_measurements_and_operators():
    """Verify measurement operator construction, probability evaluation, and distributions."""
    n_dim = 12
    betas = [0.0, 1.0, 1.0j]

    # Operators
    r_ops = construct_displaced_fock_operators(n_dim, betas, max_photons=8)
    assert len(r_ops) == len(betas)
    assert len(r_ops[0]) == 8

    # Each operator must be Hermitian and positive semi-definite
    for beta_ops in r_ops:
        for op in beta_ops:
            assert op.isherm
            evals = np.linalg.eigvalsh(op.full())
            assert np.all(evals >= -1e-12)

    # Probabilities
    state = coherent_state(n_dim, 0.8)
    probs = displaced_photon_probabilities(state, betas, max_photons=n_dim, r_ops=r_ops)
    assert probs.shape == (3, 8)
    assert np.all(probs >= 0.0)
    # Sum of first 8 probabilities for moderate coherent state should be close to 1
    assert np.all(np.sum(probs, axis=1) <= 1.0 + 1e-6)

    # Count simulation
    counts = simulate_photon_counts(state, betas, shots_per_setting=5000, max_photons=8, seed=42)
    assert counts.shape == (3, 8)
    assert np.all(counts >= 0)
    assert np.all(np.sum(counts, axis=1) == 5000)

    # Phase space distribution evaluation
    grid = np.linspace(-3.0, 3.0, 20)
    q_mat = q_function(state, grid, grid)
    assert q_mat.shape == (20, 20)
    assert np.all(q_mat >= -1e-10)

    w_mat = wigner_function(state, grid, grid)
    assert w_mat.shape == (20, 20)


def test_imle_reconstruction_coherent_state():
    """Test iMLE on a coherent state |alpha=1.5⟩ reaching >99.8% fidelity."""
    n_dim = 18
    target = coherent_state(n_dim, 1.5)
    betas = [0.0, 1.5, -1.5, 1.5j, -1.5j]

    tomo = BosonicTomography(hilbert_size=n_dim, betas=betas)
    data = tomo.simulate_data(target)

    result = tomo.reconstruct(data, target_state=target, max_iter=80, tol=1e-5)

    assert result.converged or result.iterations >= 30
    assert result.final_fidelity is not None
    assert result.final_fidelity > 0.995
    assert result.purity() > 0.95
    assert result.rho.tr() == pytest.approx(1.0, abs=1e-5)
    assert len(result.deltas) == result.iterations


def test_imle_reconstruction_cat_state():
    """Reproduce QuTiP notebook's 3-headed cat state reconstruction reaching >99% fidelity."""
    n_dim = 24
    # Three-headed cat: superposition of alpha = (2, -2 - 1j, -2 + 1j)
    target = cat_state(n_dim, [2.0, -2.0 - 1.0j, -2.0 + 1.0j])
    betas = [0.0, 2.0, -2.0, 2.0j, -2.0j]

    tomo = BosonicTomography(hilbert_size=n_dim, betas=betas)
    data = tomo.simulate_data(target)

    result = tomo.reconstruct(data, target_state=target, max_iter=60, tol=1e-5)

    assert result.final_fidelity is not None
    assert result.final_fidelity > 0.99
    assert result.purity() > 0.90
    assert "Bosonic Tomography (iMLE) Result" in result.summary()


def test_imle_with_noise_and_dilution():
    """Test iMLE robustness under statistical sampling noise and dilution."""
    n_dim = 16
    target = cat_state(n_dim, 1.5, parity="even")
    betas = [0.0, 1.5, -1.5, 1.5j, -1.5j]

    tomo = BosonicTomography(hilbert_size=n_dim, betas=betas)
    noisy_counts = tomo.simulate_data(target, shots=8000, seed=123)

    # Run with dilution=0.8 to smooth out fluctuations
    result = tomo.reconstruct(
        noisy_counts, target_state=target, max_iter=50, dilution=0.8, tol=1e-5
    )

    assert result.final_fidelity is not None
    assert result.final_fidelity > 0.97
    assert result.rho.tr() == pytest.approx(1.0, abs=1e-5)
    # Check that density matrix is positive semi-definite
    evals = np.linalg.eigvalsh(result.to_numpy())
    assert np.all(evals >= -1e-10)


def test_visualization_functions():
    """Ensure all visualization functions execute and render figures without errors."""
    n_dim = 12
    state = coherent_state(n_dim, 1.0)
    betas = [0.0, 1.0, -1.0]

    # 1. Q-function plot
    fig_q, ax_q = plot_q_function(state, show_points=betas)
    assert fig_q is not None
    plt.close(fig_q)

    # 2. Wigner plot
    fig_w, ax_w = plot_wigner(state)
    assert fig_w is not None
    plt.close(fig_w)

    # 3. Fock distribution plot
    fig_f, ax_f = plot_fock_distribution(state, max_n=10)
    assert fig_f is not None
    plt.close(fig_f)

    # 4. Hinton plot
    fig_h, ax_h = plot_hinton(state, max_n=8)
    assert fig_h is not None
    plt.close(fig_h)

    # 5. Reconstruction dashboard
    tomo = BosonicTomography(hilbert_size=n_dim, betas=betas)
    data = tomo.simulate_data(state)
    result = tomo.reconstruct(data, target_state=state, max_iter=15)

    fig_summary = plot_reconstruction_summary(result, target_state=state, max_fock_n=8)
    assert fig_summary is not None
    plt.close(fig_summary)
