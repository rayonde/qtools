"""Comprehensive unit tests for the unified qtools.tomo.bell module."""

from __future__ import annotations

import unittest

import numpy as np
import qutip as qt

from qtools.tomo.bell import (
    a_state,
    basis_states,
    bell_state,
    calculate,
    chsh_correlation,
    chsh_measurements,
    chsh_scan,
    chsh_value,
    circ_to_lin_matrix,
    concurrence,
    conditional_probability,
    convert_basis,
    d_state,
    density_matrix,
    h_state,
    hwp,
    hwp_analyzer_basis,
    hwp_to_polarization_angle,
    joint_probability,
    l_state,
    lin_to_circ_matrix,
    linear_polarization,
    marginal_probability,
    parametric_bell_state,
    polarization_angle_to_hwp,
    polarization_basis,
    polarization_observable,
    polarizer,
    post_measurement_state,
    projector,
    qwp,
    r_state,
    state_from_amplitudes,
    to_circular_basis,
    to_hv_basis,
    v_state,
    werner_state,
)


def coeff(hh: float = 0, hv: float = 0, vh: float = 0, vv: float = 0) -> dict[str, dict[str, float]]:
    return {
        "HH": {"magnitude": abs(hh), "phase": 0 if hh >= 0 else 180},
        "HV": {"magnitude": abs(hv), "phase": 0 if hv >= 0 else 180},
        "VH": {"magnitude": abs(vh), "phase": 0 if vh >= 0 else 180},
        "VV": {"magnitude": abs(vv), "phase": 0 if vv >= 0 else 180},
    }


def payload(
    amplitudes: dict,
    *,
    state_basis: str = "linear",
    alice_bases: list[str] | None = None,
    phase_target: str = "VV",
    scan: dict | None = None,
) -> dict:
    return {
        "state_basis": state_basis,
        "amplitudes": amplitudes,
        "alice_bases": alice_bases or ["D"],
        "phase_target": phase_target,
        "scan": scan or {"min": -45, "max": 45, "step": 2},
    }


class PolarizationJonesTests(unittest.TestCase):
    def test_single_photon_orthonormality(self) -> None:
        h, v = h_state(), v_state()
        d, a = d_state(), a_state()
        r, l = r_state(), l_state()

        # Normalization
        for st in (h, v, d, a, r, l):
            self.assertAlmostEqual(st.norm(), 1.0, places=10)

        # Orthogonality
        self.assertAlmostEqual(abs(complex(h.dag() * v)), 0.0, places=10)
        self.assertAlmostEqual(abs(complex(d.dag() * a)), 0.0, places=10)
        self.assertAlmostEqual(abs(complex(r.dag() * l)), 0.0, places=10)

    def test_hwp_rotates_polarization_by_twice_angle(self) -> None:
        h = h_state()
        # theta = 0 -> identity on H
        self.assertAlmostEqual(abs(complex(h.dag() * (hwp(0) * h))), 1.0, places=10)
        # theta = 22.5 deg -> polarization rotates by 45 deg to |D>
        d_out = hwp(22.5) * h
        self.assertAlmostEqual(abs(complex(d_state().dag() * d_out)), 1.0, places=10)
        # theta = 45 deg -> polarization rotates by 90 deg to |V>
        v_out = hwp(45) * h
        self.assertAlmostEqual(abs(complex(v_state().dag() * v_out)), 1.0, places=10)

    def test_qwp_creates_circular_polarization(self) -> None:
        h = h_state()
        # QWP at 45 deg maps H to L (up to global phase)
        l_out = qwp(45) * h
        self.assertAlmostEqual(abs(complex(l_state().dag() * l_out)), 1.0, places=10)
        # QWP at -45 deg maps H to R (up to global phase)
        r_out = qwp(-45) * h
        self.assertAlmostEqual(abs(complex(r_state().dag() * r_out)), 1.0, places=10)

    def test_hwp_angle_conversions(self) -> None:
        self.assertEqual(hwp_to_polarization_angle(22.5), 45.0)
        self.assertEqual(polarization_angle_to_hwp(45.0), 22.5)

    def test_polarization_observable_matches_hwp_jones(self) -> None:
        # Observable A(alpha) = J_HWP(alpha/2)^dag * sigma_z * J_HWP(alpha/2)
        for alpha in (0.0, 22.5, 45.0, 67.5, 90.0):
            obs1 = polarization_observable(alpha)
            u = hwp(alpha / 2.0)
            obs2 = u.dag() * qt.sigmaz() * u
            self.assertAlmostEqual((obs1 - obs2).norm(), 0.0, places=10)


class BasisTransformTests(unittest.TestCase):
    def test_circ_lin_unitarity(self) -> None:
        u = circ_to_lin_matrix()
        i2 = qt.qeye(2)
        self.assertAlmostEqual((u * u.dag() - i2).norm(), 0.0, places=10)
        self.assertAlmostEqual((u.dag() * u - i2).norm(), 0.0, places=10)

    def test_bell_state_in_circular_basis(self) -> None:
        # Phi+ = (|HH> + |VV>)/sqrt(2) = (|RL> + |LR>)/sqrt(2)
        phi_plus = bell_state("Phi+")
        circ_phi = to_circular_basis(phi_plus)
        arr = circ_phi.full().flatten()
        # Order: RR, RL, LR, LL
        self.assertAlmostEqual(abs(arr[0]), 0.0, places=10)
        self.assertAlmostEqual(abs(arr[1]), 1.0 / np.sqrt(2), places=10)
        self.assertAlmostEqual(abs(arr[2]), 1.0 / np.sqrt(2), places=10)
        self.assertAlmostEqual(abs(arr[3]), 0.0, places=10)

        # Back to linear
        recovered = to_hv_basis(circ_phi)
        self.assertAlmostEqual((recovered - phi_plus).norm(), 0.0, places=10)


class EntangledStatesTests(unittest.TestCase):
    def test_all_four_bell_states_unit_concurrence(self) -> None:
        for name in ("Phi+", "Phi-", "Psi+", "Psi-"):
            psi = bell_state(name)
            self.assertAlmostEqual(concurrence(psi), 1.0, places=10)

    def test_parametric_bell_state_interpolates_entanglement(self) -> None:
        # Product state at theta=0 (|HH>)
        prod_state = parametric_bell_state(0.0, 0.0, kind="phi")
        self.assertAlmostEqual(concurrence(prod_state), 0.0, places=10)

        # Maximally entangled at theta=45 deg
        max_entangled = parametric_bell_state(45.0, 0.0, kind="phi")
        self.assertAlmostEqual(concurrence(max_entangled), 1.0, places=10)

    def test_werner_state_concurrence(self) -> None:
        # P = 1 -> pure Bell state (C = 1)
        self.assertAlmostEqual(concurrence(werner_state(1.0)), 1.0, places=10)
        # P = 0 -> maximally mixed state (C = 0)
        self.assertAlmostEqual(concurrence(werner_state(0.0)), 0.0, places=10)


class ProjectiveMeasurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.phi_plus = bell_state("Phi+")

    def test_marginal_probabilities(self) -> None:
        h, v = h_state(), v_state()
        d = d_state()
        self.assertAlmostEqual(marginal_probability(self.phi_plus, h, qubit=0), 0.5, places=10)
        self.assertAlmostEqual(marginal_probability(self.phi_plus, v, qubit=0), 0.5, places=10)
        self.assertAlmostEqual(marginal_probability(self.phi_plus, d, qubit=0), 0.5, places=10)

    def test_joint_probabilities(self) -> None:
        h, v = h_state(), v_state()
        d, a = d_state(), a_state()
        self.assertAlmostEqual(joint_probability(self.phi_plus, h, h), 0.5, places=10)
        self.assertAlmostEqual(joint_probability(self.phi_plus, h, v), 0.0, places=10)
        self.assertAlmostEqual(joint_probability(self.phi_plus, d, d), 0.5, places=10)
        self.assertAlmostEqual(joint_probability(self.phi_plus, d, a), 0.0, places=10)

    def test_conditional_probabilities(self) -> None:
        h, v = h_state(), v_state()
        d, a = d_state(), a_state()
        # For Phi+, if Alice gets H, Bob is definitely H
        self.assertAlmostEqual(conditional_probability(self.phi_plus, h, h), 1.0, places=10)
        self.assertAlmostEqual(conditional_probability(self.phi_plus, v, h), 0.0, places=10)
        # If Alice gets D, Bob is definitely D
        self.assertAlmostEqual(conditional_probability(self.phi_plus, d, d), 1.0, places=10)
        self.assertAlmostEqual(conditional_probability(self.phi_plus, a, d), 0.0, places=10)

    def test_post_measurement_state(self) -> None:
        d = d_state()
        bob_dm = post_measurement_state(self.phi_plus, d)
        expected_dm = qt.ket2dm(d)
        self.assertAlmostEqual((bob_dm - expected_dm).norm(), 0.0, places=10)


class ChshTests(unittest.TestCase):
    def test_tsirelson_bound_reached_for_bell_state(self) -> None:
        phi_plus = bell_state("Phi+")
        # Wikipedia Bell-test angles: a=0, ap=45, b=22.5, bp=67.5
        s = chsh_value(phi_plus, 0.0, 45.0, 22.5, 67.5)
        self.assertAlmostEqual(s, 2.0 * np.sqrt(2.0), places=10)

    def test_chsh_correlations(self) -> None:
        phi_plus = bell_state("Phi+")
        self.assertAlmostEqual(chsh_correlation(phi_plus, 0.0, 22.5), 1.0 / np.sqrt(2.0), places=10)
        self.assertAlmostEqual(chsh_correlation(phi_plus, 0.0, -22.5), 1.0 / np.sqrt(2.0), places=10)
        self.assertAlmostEqual(chsh_correlation(phi_plus, 45.0, 22.5), 1.0 / np.sqrt(2.0), places=10)
        self.assertAlmostEqual(chsh_correlation(phi_plus, 45.0, -22.5), -1.0 / np.sqrt(2.0), places=10)

    def test_chsh_scan_uses_current_b_prime_minus_b(self) -> None:
        phi_plus = bell_state("Phi+")
        angles = np.array([-45.0, -22.5, 0.0, 22.5, 45.0])
        first = chsh_scan(phi_plus, angles, 0.0, 45.0, b_custom=20.0, bp_custom=-10.0)
        second = chsh_scan(phi_plus, angles, 0.0, 45.0, b_custom=20.0, bp_custom=20.0)
        self.assertAlmostEqual(first["curve_bp_minus_b"], -30.0, places=10)
        self.assertAlmostEqual(second["curve_bp_minus_b"], 0.0, places=10)
        self.assertFalse(np.allclose(first["values"], second["values"]))
        current_index = int(np.argmin(np.abs(np.asarray(first["b_angles"]) - 20.0)))
        self.assertAlmostEqual(first["current_s"], first["values"][current_index], places=10)

    def test_standard_bell_test_angles_reach_tsirelson_bound(self) -> None:
        value = chsh_value(bell_state("Phi+"), 0.0, 45.0, 22.5, 67.5)
        self.assertAlmostEqual(value, 2.0 * np.sqrt(2.0), places=10)



class CalculateEngineTests(unittest.TestCase):
    def test_calculate_phi_plus(self) -> None:
        result = calculate(payload(coeff(1, vv=1), scan={"min": 22.5, "max": 22.5, "step": 1}))
        self.assertAlmostEqual(result["concurrence"], 1.0, places=10)
        rows = {row["basis"]: row for row in result["key_measurements"]}
        self.assertAlmostEqual(rows["D"]["plus"], 1.0, places=10)
        self.assertAlmostEqual(result["smax"], 2.0 * np.sqrt(2.0), places=10)

    def test_circular_and_linear_payload_equivalence(self) -> None:
        linear = coeff(1, vv=1)
        circular = {
            "RR": {"magnitude": 0, "phase": 0},
            "RL": {"magnitude": 1 / np.sqrt(2), "phase": 0},
            "LR": {"magnitude": 1 / np.sqrt(2), "phase": 0},
            "LL": {"magnitude": 0, "phase": 0},
        }
        res_lin = calculate(payload(linear, alice_bases=["H"], phase_target="VV"))
        res_circ = calculate(payload(circular, state_basis="circular", alice_bases=["H"], phase_target="LL"))
        self.assertAlmostEqual(res_lin["concurrence"], res_circ["concurrence"], places=10)
        np.testing.assert_allclose(res_lin["curves"][0]["joint"], res_circ["curves"][0]["joint"], atol=1e-10)

    def test_circular_basis_product_state_changes_linear_analyzer_curves(self) -> None:
        circular = {
            "RR": {"magnitude": 1, "phase": 0},
            "RL": {"magnitude": 0, "phase": 0},
            "LR": {"magnitude": 0, "phase": 0},
            "LL": {"magnitude": 0, "phase": 0},
        }
        result = calculate(payload(
            circular,
            state_basis="circular",
            alice_bases=["H", "V", "D", "A"],
            phase_target="RR",
            scan={"min": -45, "max": 45, "step": 5},
        ))

        curves = {curve["alice"]: curve["joint"] for curve in result["curves"]}
        # |RR> = (|HH> + i|HV> + i|VH> - |VV>)/2 in the linear basis.
        # With Alice H, Bob's HWP scan gives 1/4 at theta=0 and theta=+/-45.
        self.assertAlmostEqual(curves["H"][9], 0.25, places=10)
        self.assertAlmostEqual(curves["H"][0], 0.25, places=10)
        self.assertAlmostEqual(curves["H"][9], curves["V"][9], places=10)

    def test_alice_all_six_bases(self) -> None:
        result = calculate(payload(coeff(1, vv=1), alice_bases=["H", "V", "D", "A", "R", "L"]))
        self.assertEqual([c["alice"] for c in result["curves"]], ["H", "V", "D", "A", "R", "L"])
        circ_labels = {item["label"]: item["magnitude"] for item in result["states_by_basis"]["circular"]}
        self.assertAlmostEqual(circ_labels["RL"], 1 / np.sqrt(2), places=5)
        self.assertAlmostEqual(circ_labels["LR"], 1 / np.sqrt(2), places=5)


if __name__ == "__main__":
    unittest.main()
