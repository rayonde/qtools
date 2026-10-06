import numpy as np
import pytest

from qtools.tomo.oam import (
    Tomography,
    negativity,
    partial_transpose,
    polarization_oam_skyrmion,
    polarization_oam_stokes_texture,
    projector,
    simulate_counts,
    skyrmion_topological_charge,
    two_oam_entangled_state,
)
from qtools.tomo.tomography import Tomography as LegacyTomography


def test_tomography_accepts_arbitrary_subsystem_dimensions():
    assert Tomography(dims=[2, 5]).getDimension() == 10
    assert Tomography(dims=[5, 5]).getDimension() == 25
    assert Tomography(dims=[2, 4, 2]).getDimension() == 16
    with pytest.raises(ValueError):
        Tomography(dims=[2, 0])


def test_oam_tomography_is_separate_from_legacy_qubit_tomography():
    assert Tomography.__module__ == "qtools.tomo.oam.tomography"
    assert LegacyTomography.__module__ == "qtools.tomo.tomography.TomoClass"
    assert not hasattr(LegacyTomography(), "dims")


def test_oam_label_order_is_preserved():
    state = two_oam_entangled_state(l_values=(0, -2, 2), l_pair=2)
    assert np.isclose(np.linalg.norm(state), 1.0)
    assert np.argmax(np.abs(state)) in (1 * 3 + 1, 2 * 3 + 2)
    with pytest.raises(ValueError):
        two_oam_entangled_state(l_values=(-1, 0, 1), l_pair=0)


def test_two_oam_metrics_use_explicit_partition():
    ket = two_oam_entangled_state(l_values=(-2, -1, 0, 1, 2), l_pair=1)
    rho = np.outer(ket, ket.conj())
    transposed = partial_transpose(rho, dims=[5, 5], subsystem=0)
    assert transposed.shape == (25, 25)
    assert np.isclose(negativity(rho, dims=[5, 5]), 0.5)


def test_explicit_povm_mle_returns_valid_density_matrix():
    rng = np.random.default_rng(42)
    dimension = 4
    vectors = rng.normal(size=(dimension**2, dimension)) + 1j * rng.normal(size=(dimension**2, dimension))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    effects = np.array([[projector(vector)] for vector in vectors])
    ket = rng.normal(size=dimension) + 1j * rng.normal(size=dimension)
    ket /= np.linalg.norm(ket)
    rho = np.outer(ket, ket.conj())
    counts = simulate_counts(rho, effects, shots=1000, rng=7)

    tomo = Tomography(dims=[2, 2])
    tomo.maxfev = 20_000
    fitted, _, _ = tomo.StateTomography_POVM(effects, counts)
    assert fitted.shape == (dimension, dimension)
    assert np.allclose(fitted, fitted.conj().T)
    assert np.isclose(np.trace(fitted), 1.0)
    assert np.min(np.linalg.eigvalsh(fitted)) >= -1e-9


def test_explicit_povm_rejects_underdetermined_or_negative_counts():
    effect = np.eye(4, dtype=complex)[None, None, :, :] / 4.0
    with pytest.raises(ValueError, match="underdetermined"):
        Tomography(dims=[2, 2]).StateTomography_POVM(effect, np.array([[1]]))

    effects = np.repeat(effect, 16, axis=0)
    with pytest.raises(ValueError, match="non-negative"):
        Tomography(dims=[2, 2]).StateTomography_POVM(effects, -np.ones((16, 1)))


def test_explicit_povm_supports_accidentals_intensities_and_hmle():
    dimension = 2
    effects = np.array(
        [
            [projector([1, 0]), projector([0, 1])],
            [projector([1, 1]), projector([1, -1])],
            [projector([1, 1j]), projector([1, -1j])],
        ],
        dtype=complex,
    ) / 2.0
    rho = np.diag([0.7, 0.3]).astype(complex)
    counts = simulate_counts(rho, effects, shots=200, rng=3)
    fit = Tomography([2], beta=0.01, maxfev=5000).fit_povm(
        effects, counts, accidentals=np.zeros_like(counts), intensities=np.ones(3), method="HMLE"
    )
    assert np.isclose(np.trace(fit.rho), 1.0)
    assert np.all(np.isfinite(fit.rho))


def test_skyrmion_texture_is_finite_and_uses_polarization_oam_shape():
    rho = polarization_oam_skyrmion(as_density_matrix=True)
    radii, phis, stokes, intensity = polarization_oam_stokes_texture(
        rho, radial_points=10, angular_points=20
    )
    assert stokes.shape == (10, 20, 3)
    assert intensity.shape == (10, 20)
    assert np.all(np.isfinite(stokes))
    charge = skyrmion_topological_charge(rho, radial_points=10, angular_points=20)
    assert np.isfinite(charge)
