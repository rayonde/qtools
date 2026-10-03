"""Bell states, quantum polarization optics, projective measurements, and CHSH tests in QuTiP.

This module unifies:
1. Polarization basis states (|H>, |V>, |D>, |A>, |R>, |L>) and Jones calculus (HWP, QWP, Polarizers).
2. Basis transformations between circular (|R>, |L>) and linear (|H>, |V>) representations.
3. Parametric two-photon entangled states, Bell states, Werner mixed states, and density matrices.
4. Projective measurements: marginal P(A), joint P(A, B), conditional P(B|A), and post-measurement states.
5. CHSH Bell inequality calculations, correlation functions, and angular scans.
6. Web explorer API (calculate, scan_angles, phase_scan) for experimental simulation.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import qutip as qt

LINEAR_LABELS = ("HH", "HV", "VH", "VV")
CIRCULAR_LABELS = ("RR", "RL", "LR", "LL")


# ==============================================================================
# 1. Polarization Basis States & Optical Jones Matrices
# ==============================================================================

def h_state() -> qt.Qobj:
    """Horizontal polarization state |H> = [1, 0]^T."""
    return qt.basis(2, 0)


def v_state() -> qt.Qobj:
    """Vertical polarization state |V> = [0, 1]^T."""
    return qt.basis(2, 1)


def d_state() -> qt.Qobj:
    """Diagonal polarization state |D> = (|H> + |V>) / sqrt(2)."""
    return (h_state() + v_state()).unit()


def a_state() -> qt.Qobj:
    """Anti-diagonal polarization state |A> = (|H> - |V>) / sqrt(2)."""
    return (h_state() - v_state()).unit()


def r_state() -> qt.Qobj:
    """Right-circular polarization state |R> = (|H> + i|V>) / sqrt(2)."""
    return (h_state() + 1j * v_state()).unit()


def l_state() -> qt.Qobj:
    """Left-circular polarization state |L> = (|H> - i|V>) / sqrt(2)."""
    return (h_state() - 1j * v_state()).unit()


def linear_polarization(angle_deg: float) -> qt.Qobj:
    """Linear polarization state at angle alpha (degrees) from horizontal."""
    rad = np.deg2rad(angle_deg)
    return (np.cos(rad) * h_state() + np.sin(rad) * v_state()).unit()


def orthogonal_polarization(angle_deg: float) -> qt.Qobj:
    """Linear polarization state orthogonal to angle alpha: -sin(alpha)|H> + cos(alpha)|V>."""
    rad = np.deg2rad(angle_deg)
    return (-np.sin(rad) * h_state() + np.cos(rad) * v_state()).unit()


def polarization_basis(angle_deg: float) -> tuple[qt.Qobj, qt.Qobj]:
    """Return orthonormal pair of states (|alpha>, |alpha_perp>) at polarization angle alpha."""
    return linear_polarization(angle_deg), orthogonal_polarization(angle_deg)


def basis_states() -> dict[str, qt.Qobj]:
    """Return dictionary of canonical single-photon polarization states {H, V, D, A, R, L}."""
    return {
        "H": h_state(),
        "V": v_state(),
        "D": d_state(),
        "A": a_state(),
        "R": r_state(),
        "L": l_state(),
    }


def rotation_matrix(theta_deg: float) -> qt.Qobj:
    """Spatial coordinate rotation matrix R(theta)."""
    rad = np.deg2rad(theta_deg)
    c, s = np.cos(rad), np.sin(rad)
    return qt.Qobj([[c, -s], [s, c]], dims=[[2], [2]])


def hwp(theta_deg: float) -> qt.Qobj:
    """Half-Wave Plate (HWP) Jones matrix with optical axis at physical angle theta (degrees).

    J_HWP(theta) = R(theta) * diag(1, -1) * R(-theta)
                 = [[ cos(2*theta),  sin(2*theta)],
                    [ sin(2*theta), -cos(2*theta)]]

    Action on |H>: J_HWP(theta) |H> = cos(2*theta)|H> + sin(2*theta)|V> = |2*theta>.
    Rotating the HWP by angle theta rotates the linear polarization by 2*theta.
    """
    rad = 2.0 * np.deg2rad(theta_deg)
    c, s = np.cos(rad), np.sin(rad)
    return qt.Qobj([[c, s], [s, -c]], dims=[[2], [2]])


def qwp(theta_deg: float) -> qt.Qobj:
    """Quarter-Wave Plate (QWP) Jones matrix with optical axis at physical angle theta (degrees).

    J_QWP(theta) = R(theta) * diag(1, i) * R(-theta)
    """
    rad = np.deg2rad(theta_deg)
    c, s = np.cos(rad), np.sin(rad)
    rot = np.array([[c, -s], [s, c]], dtype=complex)
    mat = rot @ np.diag([1.0, 1j]) @ rot.T
    return qt.Qobj(mat, dims=[[2], [2]])


def polarizer(angle_deg: float) -> qt.Qobj:
    """Linear polarizer Jones projection operator at angle alpha (degrees)."""
    return qt.ket2dm(linear_polarization(angle_deg))


def hwp_to_polarization_angle(hwp_angle_deg: float) -> float:
    """Convert HWP physical rotation angle to effective polarization rotation angle: beta = 2 * theta."""
    return 2.0 * float(hwp_angle_deg)


def polarization_angle_to_hwp(polarization_angle_deg: float) -> float:
    """Convert polarization angle to required HWP rotation angle: theta = beta / 2."""
    return float(polarization_angle_deg) / 2.0


def hwp_analyzer_basis(hwp_angle_deg: float) -> tuple[qt.Qobj, qt.Qobj]:
    """Return the analyzer basis states for an HWP followed by a horizontal/vertical PBS.

    Rotating HWP by theta_hwp rotates the analyzed polarization by beta = 2 * theta_hwp.
    Returns (|beta>, |beta_perp>).
    """
    pol_angle = hwp_to_polarization_angle(hwp_angle_deg)
    return polarization_basis(pol_angle)


# ==============================================================================
# 2. Basis Transformations (Circular <-> Linear)
# ==============================================================================

def circ_to_lin_matrix() -> qt.Qobj:
    """Unitary operator converting circular basis {|R>, |L>} coordinates to linear basis {|H>, |V>}.

    Columns are representations of |R> and |L> in {|H>, |V>}:
    |R> = (|H> + i|V>)/sqrt(2), |L> = (|H> - i|V>)/sqrt(2).
    """
    r_col = r_state().full().flatten()
    l_col = l_state().full().flatten()
    return qt.Qobj(np.column_stack([r_col, l_col]), dims=[[2], [2]])


def lin_to_circ_matrix() -> qt.Qobj:
    """Unitary operator converting linear basis {|H>, |V>} coordinates to circular basis {|R>, |L>}."""
    return circ_to_lin_matrix().dag()


def basis_transform_operator(from_basis: str, to_basis: str, n_photons: int = 1) -> qt.Qobj:
    """Return the unitary change-of-basis operator for 1 or 2 photons."""
    f = from_basis.lower().strip()
    t = to_basis.lower().strip()
    if f in ("linear", "hv") and t in ("linear", "hv"):
        u1 = qt.qeye(2)
    elif f in ("circular", "rl") and t in ("circular", "rl"):
        u1 = qt.qeye(2)
    elif f in ("circular", "rl") and t in ("linear", "hv"):
        u1 = circ_to_lin_matrix()
    elif f in ("linear", "hv") and t in ("circular", "rl"):
        u1 = lin_to_circ_matrix()
    else:
        raise ValueError(f"Unsupported basis conversion: {from_basis} -> {to_basis}")

    if n_photons == 1:
        return u1
    if n_photons == 2:
        return qt.tensor(u1, u1)
    raise ValueError(f"Only 1 or 2 photons supported, got {n_photons}")


def convert_basis(
    state_or_dm: qt.Qobj,
    from_basis: str,
    to_basis: str,
) -> qt.Qobj:
    """Transform a quantum state ket or density matrix between 'linear' and 'circular' bases."""
    if not isinstance(state_or_dm, qt.Qobj):
        raise TypeError("state_or_dm must be a qutip.Qobj")

    n_photons = 1 if state_or_dm.dims[0] == [2] else 2 if state_or_dm.dims[0] == [2, 2] else None
    if n_photons is None:
        raise ValueError(f"Expected 1 or 2 qubit dimensions, got {state_or_dm.dims}")

    u = basis_transform_operator(from_basis, to_basis, n_photons=n_photons)
    if state_or_dm.isket:
        return (u * state_or_dm).unit()
    if state_or_dm.isoper:
        return u * state_or_dm * u.dag()
    raise ValueError(f"Expected ket or operator, got {state_or_dm.type}")


def to_hv_basis(state_or_dm: qt.Qobj, from_basis: str = "circular") -> qt.Qobj:
    """Convert a state or density matrix to canonical {|H>, |V>} basis."""
    return convert_basis(state_or_dm, from_basis=from_basis, to_basis="linear")


def to_circular_basis(state_or_dm: qt.Qobj, from_basis: str = "linear") -> qt.Qobj:
    """Convert a state or density matrix to circular {|R>, |L>} basis."""
    return convert_basis(state_or_dm, from_basis=from_basis, to_basis="circular")


# ==============================================================================
# 3. Parametric Entangled States, Bell States, and Density Matrices
# ==============================================================================

def bell_state(name: str = "Phi+") -> qt.Qobj:
    """Return one of the four standard Bell states as a 2-qubit ket in {|H>, |V>} basis:

    - 'Phi+': (|HH> + |VV>) / sqrt(2)
    - 'Phi-': (|HH> - |VV>) / sqrt(2)
    - 'Psi+': (|HV> + |VH>) / sqrt(2)
    - 'Psi-': (|HV> - |VH>) / sqrt(2)
    """
    h, v = h_state(), v_state()
    hh = qt.tensor(h, h)
    hv = qt.tensor(h, v)
    vh = qt.tensor(v, h)
    vv = qt.tensor(v, v)

    key = name.strip().replace(" ", "").capitalize()
    if key in ("Phi+", "Phi_plus", "Phi_p"):
        return (hh + vv).unit()
    if key in ("Phi-", "Phi_minus", "Phi_m"):
        return (hh - vv).unit()
    if key in ("Psi+", "Psi_plus", "Psi_p"):
        return (hv + vh).unit()
    if key in ("Psi-", "Psi_minus", "Psi_m"):
        return (hv - vh).unit()
    raise ValueError(f"Unknown Bell state '{name}'. Allowed: 'Phi+', 'Phi-', 'Psi+', 'Psi-'.")


def bell_states() -> dict[str, qt.Qobj]:
    """Return dictionary of the four canonical Bell states."""
    return {
        "Phi+": bell_state("Phi+"),
        "Phi-": bell_state("Phi-"),
        "Psi+": bell_state("Psi+"),
        "Psi-": bell_state("Psi-"),
    }


def parametric_bell_state(
    theta: float,
    phi: float = 0.0,
    kind: str = "phi",
    degrees: bool = True,
) -> qt.Qobj:
    """Construct a parameterized two-photon entangled pure state.

    For kind='phi':
        |psi(theta, phi)> = cos(theta)|HH> + exp(i*phi)*sin(theta)|VV>
    For kind='psi':
        |psi(theta, phi)> = cos(theta)|HV> + exp(i*phi)*sin(theta)|VH>

    Parameters
    ----------
    theta : float
        Angle parameter controlling amplitude weighting (0 to 90 deg or 0 to pi/2 rad).
        theta=45 deg (pi/4) yields maximally entangled Bell states.
    phi : float
        Relative phase parameter (0 to 360 deg or 0 to 2*pi rad).
    kind : str
        'phi' for |HH>/|VV> superposition, 'psi' for |HV>/|VH> superposition.
    degrees : bool
        Whether theta and phi are in degrees (default: True).
    """
    th = np.deg2rad(theta) if degrees else float(theta)
    ph = np.deg2rad(phi) if degrees else float(phi)

    h, v = h_state(), v_state()
    c = np.cos(th)
    s = np.sin(th) * np.exp(1j * ph)

    kind_clean = kind.lower().strip()
    if kind_clean in ("phi", "phi+", "phi-"):
        hh = qt.tensor(h, h)
        vv = qt.tensor(v, v)
        return (c * hh + s * vv).unit()
    if kind_clean in ("psi", "psi+", "psi-"):
        hv = qt.tensor(h, v)
        vh = qt.tensor(v, h)
        return (c * hv + s * vh).unit()
    raise ValueError(f"kind must be 'phi' or 'psi', got '{kind}'")


def density_matrix(state: qt.Qobj) -> qt.Qobj:
    """Return a normalized density matrix rho from a ket or existing density matrix."""
    if not isinstance(state, qt.Qobj):
        raise TypeError("state must be a qutip.Qobj")
    if state.isket:
        return qt.ket2dm(state.unit())
    if state.isoper:
        tr = state.tr()
        if abs(tr) <= 1e-12:
            raise ValueError("Density matrix trace must be nonzero")
        return state / tr
    raise ValueError(f"Unsupported Qobj type: {state.type}")


def werner_state(p: float, bell_name: str = "Phi+") -> qt.Qobj:
    """Construct a 2-qubit Werner mixed state:

    rho(p) = p * |Bell><Bell| + ((1 - p) / 4) * I_4

    Parameters
    ----------
    p : float
        Purity / visibility parameter in [0, 1].
        p > 1/3 is entangled; p > 1/sqrt(2) violates CHSH inequality.
    bell_name : str
        Component Bell state (default: 'Phi+').
    """
    if not (0.0 <= p <= 1.0):
        raise ValueError(f"Werner state parameter p must be in [0, 1], got {p}")
    rho_bell = density_matrix(bell_state(bell_name))
    i4 = qt.tensor(qt.qeye(2), qt.qeye(2))
    return p * rho_bell + ((1.0 - p) / 4.0) * i4


def state_from_amplitudes(
    amplitudes: dict[str, Any] | list | np.ndarray,
    basis: str = "linear",
) -> qt.Qobj:
    """Build a normalized 2-photon state ket in the canonical {|H>, |V>} basis.

    Parameters
    ----------
    amplitudes : dict or array-like
        If dict: maps basis labels to {'magnitude': float, 'phase': float (deg)},
        or complex amplitudes.
        Linear labels: 'HH', 'HV', 'VH', 'VV'.
        Circular labels: 'RR', 'RL', 'LR', 'LL'.
    basis : str
        'linear' or 'circular'. If 'circular', converts from R/L basis to H/V basis.
    """
    labels = LINEAR_LABELS if basis in ("linear", "hv") else CIRCULAR_LABELS
    if isinstance(amplitudes, dict):
        vec = []
        for key in labels:
            item = amplitudes.get(key, {})
            if isinstance(item, dict):
                mag = float(item.get("magnitude", 0.0))
                phase_deg = float(item.get("phase", 0.0))
                if not np.isfinite(mag) or mag < 0:
                    raise ValueError(f"{key} magnitude must be a finite nonnegative number")
                if not np.isfinite(phase_deg):
                    raise ValueError(f"{key} phase must be finite")
                val = mag * np.exp(1j * np.deg2rad(phase_deg))
            elif isinstance(item, (int, float, complex, np.number)):
                val = complex(item)
            else:
                raise ValueError(f"{key} must contain magnitude and phase")
            vec.append(val)
        arr = np.array(vec, dtype=complex)
    else:
        arr = np.asarray(amplitudes, dtype=complex).flatten()
        if len(arr) != 4:
            raise ValueError(f"Expected 4 amplitudes for 2 qubits, got {len(arr)}")

    norm = np.linalg.norm(arr)
    if norm <= 1e-12:
        raise ValueError("at least one state amplitude must be nonzero")
    arr = arr / norm

    ket_in_basis = qt.Qobj(arr.reshape(4, 1), dims=[[2, 2], [1, 1]])
    if basis in ("circular", "rl"):
        return to_hv_basis(ket_in_basis, from_basis="circular")
    return ket_in_basis


def concurrence(state_or_dm: qt.Qobj) -> float:
    """Compute concurrence for a two-qubit state or density matrix using QuTiP."""
    if not isinstance(state_or_dm, qt.Qobj):
        raise TypeError("state_or_dm must be a qutip.Qobj")
    if state_or_dm.isket:
        # For pure states, use the exact spin-flip formula C = |<psi*|(sigma_y (x) sigma_y)|psi>|
        # to avoid sqrtm numerical errors on rank-1 density matrices
        ket = state_or_dm.unit()
        sy2 = qt.tensor(qt.sigmay(), qt.sigmay())
        ket_star = qt.Qobj(np.conj(ket.full()), dims=ket.dims)
        val = float(abs(complex(ket.dag() * sy2 * ket_star)))
        return float(np.clip(val, 0.0, 1.0))
    rho = density_matrix(state_or_dm)
    return float(np.clip(qt.concurrence(rho), 0.0, 1.0))


# ==============================================================================
# 4. Projective Measurements, Joint, Marginal, and Conditional Probabilities
# ==============================================================================

def projector(state: qt.Qobj) -> qt.Qobj:
    """Return single-qubit projection operator Pi = |psi><psi|."""
    if not isinstance(state, qt.Qobj):
        raise TypeError("state must be a qutip.Qobj")
    if state.isket:
        return qt.ket2dm(state.unit())
    if state.isoper:
        return state
    raise ValueError(f"Expected ket or operator, got {state.type}")


def bipartite_projector(
    alice_state: qt.Qobj | None = None,
    bob_state: qt.Qobj | None = None,
) -> qt.Qobj:
    """Construct 2-qubit measurement projector Pi_A (x) Pi_B."""
    pi_a = projector(alice_state) if alice_state is not None else qt.qeye(2)
    pi_b = projector(bob_state) if bob_state is not None else qt.qeye(2)
    return qt.tensor(pi_a, pi_b)


def marginal_probability(
    state_or_rho: qt.Qobj,
    measurement_state: qt.Qobj,
    qubit: int = 0,
) -> float:
    """Calculate marginal detection probability P(A) or P(B) via projective measurement.

    P(A) = Tr((Pi_A (x) I) rho)   [qubit=0]
    P(B) = Tr((I (x) Pi_B) rho)   [qubit=1]
    """
    rho = density_matrix(state_or_rho)
    if qubit == 0:
        proj = bipartite_projector(alice_state=measurement_state, bob_state=None)
    elif qubit == 1:
        proj = bipartite_projector(alice_state=None, bob_state=measurement_state)
    else:
        raise ValueError(f"qubit must be 0 or 1, got {qubit}")
    prob = float(qt.expect(proj, rho).real)
    return float(np.clip(prob, 0.0, 1.0))


def joint_probability(
    state_or_rho: qt.Qobj,
    alice_state: qt.Qobj,
    bob_state: qt.Qobj,
) -> float:
    """Calculate joint coincidence probability P(A, B) = Tr((Pi_A (x) Pi_B) rho)."""
    rho = density_matrix(state_or_rho)
    proj = bipartite_projector(alice_state=alice_state, bob_state=bob_state)
    prob = float(qt.expect(proj, rho).real)
    return float(np.clip(prob, 0.0, 1.0))


def conditional_probability(
    state_or_rho: qt.Qobj,
    bob_state: qt.Qobj,
    alice_state: qt.Qobj,
    tol: float = 1e-12,
) -> float:
    """Calculate conditional probability P(B|A) = P(A, B) / P(A)."""
    rho = density_matrix(state_or_rho)
    p_a = marginal_probability(rho, alice_state, qubit=0)
    if p_a <= tol:
        return 0.0
    p_ab = joint_probability(rho, alice_state, bob_state)
    return float(np.clip(p_ab / p_a, 0.0, 1.0))


def post_measurement_state(
    state_or_rho: qt.Qobj,
    alice_state: qt.Qobj,
    tol: float = 1e-12,
) -> qt.Qobj:
    """Calculate the collapsed post-measurement density matrix on Bob given Alice's outcome:

    rho' = (Pi_A (x) I) rho (Pi_A (x) I)
    rho_B|A = Tr_A(rho') / Tr(rho')
    """
    rho = density_matrix(state_or_rho)
    pi_a = bipartite_projector(alice_state=alice_state, bob_state=None)
    collapsed = pi_a * rho * pi_a
    p_a = float(collapsed.tr().real)
    if p_a <= tol:
        raise ValueError("Conditioning probability P(A) is effectively zero")
    return (collapsed.ptrace(1) / p_a).unit()


# ==============================================================================
# 5. CHSH Inequality, Correlation Functions, and Angular Scans
# ==============================================================================

def polarization_observable(angle_deg: float) -> qt.Qobj:
    """Return Pauli-type projection observable A(alpha) = |+><+| - |-><-|

    at polarization angle alpha. Equivalently:
    A(alpha) = cos(2*alpha)*sigma_z + sin(2*alpha)*sigma_x
             = J_HWP(alpha/2)^dag * sigma_z * J_HWP(alpha/2)
    """
    plus, minus = polarization_basis(angle_deg)
    return qt.ket2dm(plus) - qt.ket2dm(minus)


def chsh_correlation(rho: qt.Qobj, a_deg: float, b_deg: float) -> float:
    """Compute quantum expectation correlation E(a, b) = <A(a) (x) B(b)> = Tr((A(a) (x) B(b)) * rho)."""
    dm = density_matrix(rho)
    obs_a = polarization_observable(a_deg)
    obs_b = polarization_observable(b_deg)
    corr = qt.expect(qt.tensor(obs_a, obs_b), dm).real
    return float(np.clip(corr, -1.0, 1.0))


def chsh_probabilities(rho: qt.Qobj, a_deg: float, b_deg: float) -> dict[str, float]:
    """Compute the 4 joint detection probabilities {++, +-, -+, --} for analyzer settings (a, b)."""
    dm = density_matrix(rho)
    a_plus, a_minus = polarization_basis(a_deg)
    b_plus, b_minus = polarization_basis(b_deg)
    return {
        "++": joint_probability(dm, a_plus, b_plus),
        "+-": joint_probability(dm, a_plus, b_minus),
        "-+": joint_probability(dm, a_minus, b_plus),
        "--": joint_probability(dm, a_minus, b_minus),
    }


def chsh_value(
    rho: qt.Qobj,
    a_deg: float,
    ap_deg: float,
    b_deg: float,
    bp_deg: float,
) -> float:
    """Compute the CHSH sign convention matched to the standard Bell angles."""
    dm = density_matrix(rho)
    e_ab = chsh_correlation(dm, a_deg, b_deg)
    e_abp = chsh_correlation(dm, a_deg, bp_deg)
    e_apb = chsh_correlation(dm, ap_deg, b_deg)
    e_apbp = chsh_correlation(dm, ap_deg, bp_deg)
    return float(e_ab - e_abp + e_apb + e_apbp)


def chsh_measurements(
    rho: qt.Qobj,
    a_deg: float,
    ap_deg: float,
    b_deg: float,
    bob_offset: float = 45.0,
    total_counts: float = 1000.0,
    counts_override: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Calculate four Wikipedia CHSH subexperiments and their outcome counts."""
    dm = density_matrix(rho)
    bp_deg = b_deg + bob_offset

    probabilities_by_setting = {
        "E(a,b)": chsh_probabilities(dm, a_deg, b_deg),
        "E(a,b')": chsh_probabilities(dm, a_deg, bp_deg),
        "E(a',b)": chsh_probabilities(dm, ap_deg, b_deg),
        "E(a',b')": chsh_probabilities(dm, ap_deg, bp_deg),
    }

    def correlation(p: dict[str, float]) -> float:
        return p["++"] + p["--"] - p["+-"] - p["-+"]

    correlations = {key: correlation(val) for key, val in probabilities_by_setting.items()}
    s_value = (
        correlations["E(a,b)"] - correlations["E(a,b')"]
        + correlations["E(a',b)"] + correlations["E(a',b')"]
    )

    normalized_rates_by_setting = {}
    for setting, probabilities in probabilities_by_setting.items():
        alice_plus_probability = probabilities["++"] + probabilities["+-"]
        alice_minus_probability = probabilities["-+"] + probabilities["--"]
        normalized_rates_by_setting[setting] = {
            "++": probabilities["++"] / alice_plus_probability if alice_plus_probability > 1e-12 else 0.0,
            "+-": probabilities["+-"] / alice_plus_probability if alice_plus_probability > 1e-12 else 0.0,
            "-+": probabilities["-+"] / alice_minus_probability if alice_minus_probability > 1e-12 else 0.0,
            "--": probabilities["--"] / alice_minus_probability if alice_minus_probability > 1e-12 else 0.0,
        }

    theoretical_counts_by_setting = {
        key: {k: total_counts * v for k, v in val.items()}
        for key, val in probabilities_by_setting.items()
    }
    counts_by_setting = {}
    if counts_override is None:
        counts_by_setting = theoretical_counts_by_setting
    else:
        if not isinstance(counts_override, dict):
            raise ValueError("chsh_counts must be an object keyed by CHSH setting")
        for setting, theoretical_counts in theoretical_counts_by_setting.items():
            supplied = counts_override.get(setting, theoretical_counts)
            if not isinstance(supplied, dict):
                raise ValueError(f"counts for {setting} must be an object")
            counts = {}
            for outcome in ("++", "--", "+-", "-+"):
                value = float(supplied.get(outcome, theoretical_counts[outcome]))
                if not np.isfinite(value) or value < 0:
                    raise ValueError(f"count {setting}/{outcome} must be finite and non-negative")
                counts[outcome] = value
            counts_by_setting[setting] = counts

        # Manual counts define the observed probabilities and therefore E/S.
        probabilities_by_setting = {}
        for setting, counts in counts_by_setting.items():
            total = sum(counts.values())
            if total <= 1e-12:
                raise ValueError(f"counts for {setting} must have a positive total")
            probabilities_by_setting[setting] = {
                outcome: value / total for outcome, value in counts.items()
            }

    # Counts are the observed data source. Recompute probabilities, E, and S
    # after applying manual counts so the table and CHSH result stay coupled.
    correlations = {key: correlation(val) for key, val in probabilities_by_setting.items()}
    s_value = (
        correlations["E(a,b)"] - correlations["E(a,b')"]
        + correlations["E(a',b)"] + correlations["E(a',b')"]
    )
    normalized_rates_by_setting = {}
    for setting, probabilities in probabilities_by_setting.items():
        alice_plus_probability = probabilities["++"] + probabilities["+-"]
        alice_minus_probability = probabilities["-+"] + probabilities["--"]
        normalized_rates_by_setting[setting] = {
            "++": probabilities["++"] / alice_plus_probability if alice_plus_probability > 1e-12 else 0.0,
            "+-": probabilities["+-"] / alice_plus_probability if alice_plus_probability > 1e-12 else 0.0,
            "-+": probabilities["-+"] / alice_minus_probability if alice_minus_probability > 1e-12 else 0.0,
            "--": probabilities["--"] / alice_minus_probability if alice_minus_probability > 1e-12 else 0.0,
        }

    alice_plus = {
        "a": probabilities_by_setting["E(a,b)"]["++"] + probabilities_by_setting["E(a,b)"]["+-"],
        "a'": probabilities_by_setting["E(a',b)"]["++"] + probabilities_by_setting["E(a',b)"]["+-"],
    }
    bob_plus = {
        "b": probabilities_by_setting["E(a,b)"]["++"] + probabilities_by_setting["E(a,b)"]["-+"],
        "b'": probabilities_by_setting["E(a,b')"]["++"] + probabilities_by_setting["E(a,b')"]["-+"],
    }

    basis_specs = {
        "E(a,b)": ("a", "b", a_deg, b_deg),
        "E(a,b')": ("a", "b'", a_deg, bp_deg),
        "E(a',b)": ("a'", "b", ap_deg, b_deg),
        "E(a',b')": ("a'", "b'", ap_deg, bp_deg),
    }
    outcome_specs = {
        "++": ("{alice}", "{bob}", "{alice}", "{bob}"),
        "--": ("{alice}−90°", "{bob}−90°", "{alice}−90°", "{bob}−90°"),
        "+-": ("{alice}", "{bob}−90°", "{alice}", "{bob}−90°"),
        "-+": ("{alice}−90°", "{bob}", "{alice}−90°", "{bob}"),
    }
    measurement_rows = {}
    for setting, (alice_label, bob_label, _alice_angle, _bob_angle) in basis_specs.items():
        measurement_rows[setting] = []
        for outcome in ("++", "--", "+-", "-+"):
            dual_alice, dual_bob, single_alice, single_bob = outcome_specs[outcome]
            measurement_rows[setting].append({
                "outcome": outcome,
                "dual_alice_label": dual_alice.format(alice=alice_label),
                "dual_bob_label": dual_bob.format(bob=bob_label),
                "single_alice_label": single_alice.format(alice=alice_label),
                "single_bob_label": single_bob.format(bob=bob_label),
                "probability": probabilities_by_setting[setting][outcome],
                "normalized_rate": normalized_rates_by_setting[setting][outcome],
                "theoretical_probability": chsh_probabilities(
                    dm,
                    _alice_angle if outcome[0] == "+" else _alice_angle + 90.0,
                    _bob_angle if outcome[1] == "+" else _bob_angle + 90.0,
                )[("++")],
                "count": counts_by_setting[setting][outcome],
            })

    return {
        "a": a_deg,
        "ap": ap_deg,
        "b": b_deg,
        "bp": bp_deg,
        "probabilities": probabilities_by_setting,
        "normalized_rates": normalized_rates_by_setting,
        "counts": counts_by_setting,
        "theoretical_probabilities": {
            setting: dict(values)
            for setting, values in (
                {
                    "E(a,b)": chsh_probabilities(dm, a_deg, b_deg),
                    "E(a,b')": chsh_probabilities(dm, a_deg, bp_deg),
                    "E(a',b)": chsh_probabilities(dm, ap_deg, b_deg),
                    "E(a',b')": chsh_probabilities(dm, ap_deg, bp_deg),
                }
            ).items()
        },
        "theoretical_counts": theoretical_counts_by_setting,
        "measurement_rows": measurement_rows,
        "correlations": correlations,
        "s": float(s_value),
        "total_counts": total_counts,
    }


def chsh_scan(
    rho: qt.Qobj,
    b_angles: np.ndarray,
    a: float,
    ap: float,
    b_custom: float | None = None,
    bp_custom: float | None = None,
    counts_override: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Scan S as a function of ``b-a`` at a fixed ``bp-b`` offset.

    The curve and the highlighted current point must use the same Bob pair of
    settings. When the caller supplies ``b_custom`` and ``bp_custom`` their
    difference is therefore the curve offset; otherwise the analytically
    selected offset is used.
    """
    dm = density_matrix(rho)
    # Bell-test geometry uses b' = b + 45 degrees. Keep the opposite
    # orientation available for the scan, but prefer the standard +45 degree
    # branch when selecting the theoretical maximum.
    offsets = (45.0, -45.0)

    if len(b_angles):
        sample = np.array([0.0, 45.0, 90.0])
        candidates_by_offset = {}
        for offset in offsets:
            sample_values = np.array([chsh_measurements(dm, a, ap, float(ang), offset)["s"] for ang in sample])
            constant = 0.5 * (sample_values[0] + sample_values[2])
            cosine = sample_values[0] - constant
            sine = sample_values[1] - constant
            phase = np.rad2deg(np.arctan2(sine, cosine)) / 2.0
            candidates_by_offset[offset] = [phase + 90.0 * index for index in range(-4, 5)]

        selected_offset, selected_b = max(
            ((offset, angle) for offset in offsets for angle in candidates_by_offset[offset]),
            key=lambda item: chsh_measurements(dm, a, ap, item[1], item[0])["s"],
        )
        selected_b = ((selected_b + 90.0) % 180.0) - 90.0
        maximum = float(chsh_measurements(dm, a, ap, selected_b, selected_offset)["s"])
    else:
        selected_offset = 45.0
        selected_b = 0.0
        maximum = 0.0

    current_b = selected_b if b_custom is None else float(b_custom)
    if bp_custom is not None:
        current_offset = float(bp_custom) - current_b
    else:
        current_offset = selected_offset

    # If the user supplied b/b', the visible S curve follows that exact
    # difference. The automatic curve is only the default when no pair was
    # supplied.
    curve_offset = current_offset
    settings_at_smax = chsh_measurements(dm, a, ap, selected_b, selected_offset)
    settings_current = chsh_measurements(
        dm, a, ap, current_b, current_offset, counts_override=counts_override
    )
    curve_angles = np.asarray(b_angles, dtype=float)
    if not np.any(np.isclose(curve_angles, current_b, atol=1e-10)):
        curve_angles = np.sort(np.append(curve_angles, current_b))
    values = [
        chsh_measurements(dm, a, ap, float(angle), curve_offset)["s"]
        for angle in curve_angles
    ]
    b_relative = curve_angles - a
    settings_curve = [
        chsh_measurements(dm, a, ap, float(angle), curve_offset)
        for angle in curve_angles
    ]
    curve_max_index = int(np.argmax(values)) if values else 0

    return {
        "b_angles": curve_angles.tolist(),
        "b_relative": b_relative.tolist(),
        "values": values,
        "curve_settings": settings_curve,
        "curve_smax": float(values[curve_max_index]) if values else 0.0,
        "curve_smax_b": float(curve_angles[curve_max_index]) if values else 0.0,
        "scan_smax": maximum,
        "scan_smax_b": float(selected_b),
        "scan_smax_relative": float(selected_b - a),
        "bob_offset": selected_offset,
        "a": a,
        "ap": ap,
        "settings_at_smax": settings_at_smax,
        "settings_current": settings_current,
        "current_b": current_b,
        "current_bp": current_b + current_offset,
        "current_s": settings_current["s"],
        "curve_offset": float(curve_offset),
        "curve_bp_minus_b": float(curve_offset),
        "classical_bound": 2.0,
    }


# ==============================================================================
# 6. High-level Simulation & Web Explorer Engine
# ==============================================================================

def scan_angles(scan: dict[str, Any]) -> np.ndarray:
    """Validate and generate Bob HWP physical scan angles."""
    if not isinstance(scan, dict):
        raise ValueError("scan must be a Bob HWP angle-range object")
    start = float(scan.get("min", -45))
    stop = float(scan.get("max", 45))
    step = float(scan.get("step", 1))
    if not all(np.isfinite(value) for value in (start, stop, step)):
        raise ValueError("Bob HWP angles must be finite")
    if stop < start:
        raise ValueError("scan max theta_b must be greater than or equal to min theta_b")
    if step <= 0 or step > 10:
        raise ValueError("scan step must be greater than 0 and no greater than 10 degrees")
    count = int(np.floor((stop - start) / step)) + 1
    if count > 5001:
        raise ValueError("too many scan points; increase the step")
    angles = start + np.arange(count, dtype=float) * step
    if stop - angles[-1] > 1e-8:
        angles = np.append(angles, stop)
    return angles


def format_state_amplitudes(state: qt.Qobj, basis: str = "linear") -> list[dict[str, Any]]:
    """Format 2-photon state amplitudes into list of dicts with label, magnitude, and phase (deg)."""
    labels = LINEAR_LABELS if basis in ("linear", "hv") else CIRCULAR_LABELS
    state_in_basis = state if basis in ("linear", "hv") else to_circular_basis(state)
    vec = state_in_basis.full().flatten()

    items = []
    for key, value in zip(labels, vec):
        magnitude = float(abs(value))
        phase = float(np.rad2deg(np.angle(value))) if magnitude > 1e-12 else 0.0
        items.append({"label": key, "magnitude": magnitude, "phase": phase})
    return items


def phase_scan(state: qt.Qobj, state_basis: str, phase_target: str) -> dict[str, Any]:
    """Scan the relative phase of one target basis amplitude from -180 to +180 deg."""
    labels = LINEAR_LABELS if state_basis in ("linear", "hv") else CIRCULAR_LABELS
    if phase_target not in labels:
        raise ValueError(f"phase_target must be one of {labels}")

    target_idx = labels.index(phase_target)
    state_in_basis = state if state_basis in ("linear", "hv") else to_circular_basis(state)
    base_components = state_in_basis.full().flatten()
    original_magnitude = abs(base_components[target_idx])

    phases = np.arange(-180.0, 181.0, 2.0)
    curves = []

    alice_d = d_state()
    alice_a = a_state()
    bob_plus_d, _ = hwp_analyzer_basis(22.5)
    bob_plus_a, _ = hwp_analyzer_basis(-22.5)

    for alice_label, alice_state in (("D", alice_d), ("A", alice_a)):
        for bob_label, bob_state in (("D", bob_plus_d), ("A", bob_plus_a)):
            values = []
            for ph in phases:
                mod_vec = base_components.copy()
                mod_vec[target_idx] = original_magnitude * np.exp(1j * np.deg2rad(ph))
                norm = np.linalg.norm(mod_vec)
                if norm > 1e-12:
                    mod_vec /= norm
                phased_ket = qt.Qobj(mod_vec.reshape(4, 1), dims=[[2, 2], [1, 1]])
                if state_basis in ("circular", "rl"):
                    phased_ket = to_hv_basis(phased_ket, from_basis="circular")
                values.append(joint_probability(phased_ket, alice_state, bob_state))
            curves.append({"alice": alice_label, "bob": bob_label, "joint": values})

    return {
        "phases": phases.tolist(),
        "current_phase": 0.0,
        "target": phase_target,
        "curves": curves,
        "target_magnitude": float(original_magnitude),
    }


def calculate(payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate measurements from one explicit state-basis request using QuTiP."""
    if not isinstance(payload, dict):
        raise ValueError("request payload must be a JSON object")

    state_basis = payload.get("state_basis")
    if state_basis not in ("linear", "circular"):
        raise ValueError("state_basis must be linear or circular")

    # Build 2-photon pure state ket and density matrix in canonical H/V basis
    state = state_from_amplitudes(payload.get("amplitudes", {}), basis=state_basis)
    rho = density_matrix(state)

    # Alice measurement bases
    alice_basis_dict = basis_states()
    alice_bases = payload.get("alice_bases")
    allowed_alice = tuple(alice_basis_dict)
    if not isinstance(alice_bases, list) or not alice_bases:
        raise ValueError("alice_bases must contain at least one measurement basis")
    if any(not isinstance(item, str) or item not in allowed_alice for item in alice_bases):
        raise ValueError(f"alice_bases must contain only {', '.join(allowed_alice)}")
    alice_bases = list(dict.fromkeys(alice_bases))

    # Phase target
    labels = LINEAR_LABELS if state_basis == "linear" else CIRCULAR_LABELS
    phase_target = payload.get("phase_target")
    if phase_target not in labels:
        raise ValueError(f"phase_target must be one of {labels}")

    # Bob scan angles (physical HWP angles)
    angles = scan_angles(payload.get("scan", {}))
    b_angles = 2.0 * angles

    # CHSH calculation
    chsh_payload = payload.get("chsh", {})
    if not isinstance(chsh_payload, dict):
        raise ValueError("chsh must be an angle settings object")
    a = float(chsh_payload.get("a", 0.0))
    ap = float(chsh_payload.get("ap", 45.0))
    b_val = chsh_payload.get("b")
    bp_val = chsh_payload.get("bp")
    b_custom = float(b_val) if b_val is not None and np.isfinite(float(b_val)) else None
    bp_custom = float(bp_val) if bp_val is not None and np.isfinite(float(bp_val)) else None
    chsh_counts = payload.get("chsh_counts")
    if chsh_counts is not None and not isinstance(chsh_counts, dict):
        raise ValueError("chsh_counts must be an object")
    if not np.isfinite(a) or not np.isfinite(ap):
        raise ValueError("CHSH Alice polarization angles must be finite")

    chsh = chsh_scan(rho, b_angles, a, ap, b_custom, bp_custom, chsh_counts)

    # Curves for requested Alice bases
    curves = []
    for alice in alice_bases:
        alice_ket = alice_basis_dict[alice]
        joint_values = []
        conditional_values = []
        for angle in angles:
            bob_plus, _ = hwp_analyzer_basis(float(angle))
            joint = joint_probability(rho, alice_ket, bob_plus)
            cond = conditional_probability(rho, bob_plus, alice_ket)
            joint_values.append(joint)
            conditional_values.append(cond)
        curves.append({"alice": alice, "joint": joint_values, "conditional": conditional_values})

    # Concurrence
    concurrence_val = concurrence(state)

    # Key measurements table for the first selected Alice basis
    selected_alice = alice_bases[0]
    alice_ket_0 = alice_basis_dict[selected_alice]
    selected_alice_prob = marginal_probability(rho, alice_ket_0, qubit=0)

    key_measurements = []
    for basis_label, theta_b in (("H", 0.0), ("D", 22.5), ("A", -22.5), ("V", 45.0)):
        bob_plus, bob_minus = hwp_analyzer_basis(theta_b)
        plus_cond = conditional_probability(rho, bob_plus, alice_ket_0)
        minus_cond = conditional_probability(rho, bob_minus, alice_ket_0)
        key_measurements.append({
            "basis": basis_label,
            "theta_b": theta_b,
            "b": 2.0 * theta_b,
            "plus": plus_cond,
            "minus": minus_cond,
            "total": selected_alice_prob,
        })

    # State representations
    normalized_state = format_state_amplitudes(state, state_basis)
    states_by_basis = {
        "linear": format_state_amplitudes(state, "linear"),
        "circular": format_state_amplitudes(state, "circular"),
    }

    # Phase scan
    pscan = phase_scan(state, state_basis, phase_target)
    selected_amplitude = payload.get("amplitudes", {}).get(phase_target, {})
    pscan["current_phase"] = float(selected_amplitude.get("phase", 0.0))

    return {
        "angles": angles.tolist(),
        "b_angles": b_angles.tolist(),
        "curves": curves,
        "chsh": chsh,
        "phase_scan": pscan,
        "concurrence": concurrence_val,
        "state_basis": state_basis,
        "basis_labels": ["H", "V"] if state_basis == "linear" else ["R", "L"],
        "alice_bases": alice_bases,
        "measurement_bases": list(allowed_alice),
        "smax": chsh["scan_smax"],
        "normalized_state": normalized_state,
        "states_by_basis": states_by_basis,
        "key_measurements": key_measurements,
    }
