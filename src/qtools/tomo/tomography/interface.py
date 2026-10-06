"""High-level interface for Quantum State Tomography (QST).

Implements the standard workflow outlined in Kwiat Group's Quantum State Tomography
tutorial (refs/tutorial_for_tomography2019.pdf). Provides:
1. Preset dataset loader (1-qubit, 2-qubit Bell, 2N detector, crosstalk)
2. In-memory data & configuration execution for Maximum Likelihood Estimation (MLE)
3. Quantitative state metrics (Fidelity, Purity, Concurrence, Tangles, Entropies)
4. Theoretical state simulation bridging qtools.tomo.bell and tomography
"""

from __future__ import annotations

import json
from math import comb
from pathlib import Path
from typing import Any

import numpy as np

from qtools.tomo.tomography.TomoClass import Tomography
import qtools.tomo.tomography.TomoFunctions as tf
import qtools.tomo.tomography.TomoDisplay as td
import qtools.tomo.tomography.TomoDisplayHelpers as tdh

BASE_DIR = Path(__file__).resolve().parent
EXAMPLE_FILES_DIR = BASE_DIR / "ExampleFiles"

PRESET_METADATA = {
    "1_qubit_example": {
        "title": "1-Qubit Pure State (|R⟩)",
        "description": "Single-qubit tomography using 6 canonical measurements (H, V, D, A, R, L) with 1 detector.",
        "file": "1_qubit_example.json",
        "n_qubits": 1,
        "n_detectors": 1,
        "default_target": "R",
    },
    "bell_state_example": {
        "title": "2-Qubit Bell State (|Φ⁺⟩)",
        "description": "Two-qubit polarization-entangled Bell state tomography using 36 standard canonical projective measurements.",
        "file": "bell_state_example.json",
        "n_qubits": 2,
        "n_detectors": 1,
        "default_target": "Phi+",
    },
    "2n_detector_example": {
        "title": "2-Qubit 4-Detector (2 Detectors / Qubit)",
        "description": "Simultaneous 4-channel measurement setup (HH, HV, VH, VV) requiring only 9 measurement cycles.",
        "file": "2n_detector_example.json",
        "n_qubits": 2,
        "n_detectors": 2,
        "default_target": "Phi+",
    },
    "crosstalk_inefficiency_example": {
        "title": "2-Qubit with Crosstalk & Detector Inefficiency",
        "description": "Real-world scenario with polarizing beam splitter (PBS) crosstalk and detector-pair efficiency calibration.",
        "file": "crosstalk_inefficiency_example.json",
        "n_qubits": 2,
        "n_detectors": 2,
        "default_target": "Phi+",
    },
}


def list_presets() -> list[dict[str, Any]]:
    """List all available built-in tomography presets with description and specs."""
    result = []
    for key, meta in PRESET_METADATA.items():
        result.append({
            "id": key,
            "title": meta["title"],
            "description": meta["description"],
            "n_qubits": meta["n_qubits"],
            "n_detectors": meta["n_detectors"],
            "default_target": meta["default_target"],
        })
    return result


def list_example_files() -> list[str]:
    """List all available raw files in the ExampleFiles directory."""
    if not EXAMPLE_FILES_DIR.exists():
        return []
    return sorted([p.name for p in EXAMPLE_FILES_DIR.iterdir() if p.is_file()])


def load_example_data(identifier: str = "bell_state_example.json") -> dict[str, Any]:
    """Directly load dataset from ExampleFiles by filename or preset key."""
    if identifier in PRESET_METADATA:
        return load_preset(identifier)["data"]

    filepath = EXAMPLE_FILES_DIR / identifier
    if not filepath.exists():
        raise FileNotFoundError(f"Example file '{identifier}' not found in {EXAMPLE_FILES_DIR}")

    if filepath.suffix == ".json":
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    text = filepath.read_text(encoding="utf-8")
    parsed = parse_tomo_file(text, identifier)
    return parsed.get("data", parsed)


def load_preset(preset_id: str) -> dict[str, Any]:
    """Load configuration and measurement dataset directly from ExampleFiles."""
    meta = PRESET_METADATA.get(preset_id, PRESET_METADATA["bell_state_example"])
    filepath = EXAMPLE_FILES_DIR / meta["file"]

    if not filepath.exists():
        raise FileNotFoundError(f"Preset file '{meta['file']}' not found in {EXAMPLE_FILES_DIR}")

    if filepath.suffix == ".json":
        with open(filepath, "r", encoding="utf-8") as f:
            data_dict = json.load(f)
    else:
        text = filepath.read_text(encoding="utf-8")
        parsed = parse_tomo_file(text, meta["file"])
        data_dict = parsed.get("data", parsed)

    # Standard default configuration with drift and accidental corrections enabled
    conf_dict = {
        "get_bell_settings": (meta["n_qubits"] == 2),
        "do_drift_correction": True,
        "do_accidental_correction": (meta["n_qubits"] == 2),
        "method": "MLE",
    }

    # Load default conf.toml from ExampleFiles if available
    conf_toml_path = EXAMPLE_FILES_DIR / "conf.toml"
    if conf_toml_path.exists():
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            with open(conf_toml_path, "rb") as cf:
                toml_conf = tomllib.load(cf)
                conf_dict.update(toml_conf)
        except Exception:
            pass

    if "coincidence_window" in data_dict:
        conf_dict["window"] = data_dict["coincidence_window"]

    return {
        "preset_id": preset_id,
        "config": conf_dict,
        "data": data_dict,
        "default_target": meta["default_target"],
    }


def get_target_density_matrix(target_spec: Any, n_qubits: int) -> np.ndarray:
    """Resolve a target state specification into a normalized 2^n x 2^n density matrix."""
    if isinstance(target_spec, dict):
        if "vector" in target_spec:
            target_spec = target_spec["vector"]
        elif "amplitudes" in target_spec:
            target_spec = target_spec["amplitudes"]
        elif "matrix" in target_spec:
            target_spec = target_spec["matrix"]

    if isinstance(target_spec, (list, np.ndarray)):
        elements = []
        for x in target_spec:
            if isinstance(x, dict):
                elements.append(complex(float(x.get("re", 0.0)), float(x.get("im", 0.0))))
            elif isinstance(x, (list, tuple)) and len(x) == 2 and isinstance(x[0], (int, float)):
                elements.append(complex(float(x[0]), float(x[1])))
            else:
                elements.append(complex(x))
        arr = np.array(elements, dtype=complex)
        if arr.ndim == 1:
            norm = np.linalg.norm(arr)
            if norm > 1e-12:
                arr = arr / norm
            return np.outer(arr, arr.conj())
        elif arr.ndim == 2:
            tr = np.trace(arr)
            if abs(tr) > 1e-12:
                arr = arr / tr
            return arr
        raise ValueError(f"Invalid target array shape: {arr.shape}")

    name = str(target_spec).strip()
    # 1-qubit single photon states
    if n_qubits == 1:
        single_kets = {
            "H": np.array([1.0, 0.0], dtype=complex),
            "V": np.array([0.0, 1.0], dtype=complex),
            "D": np.array([1.0, 1.0], dtype=complex) / np.sqrt(2),
            "A": np.array([1.0, -1.0], dtype=complex) / np.sqrt(2),
            "R": np.array([1.0, 1.0j], dtype=complex) / np.sqrt(2),
            "L": np.array([1.0, -1.0j], dtype=complex) / np.sqrt(2),
        }
        if name in single_kets:
            psi = single_kets[name]
            return np.outer(psi, psi.conj())

    # 2-qubit Bell states
    if n_qubits == 2:
        inv_sqrt2 = 1.0 / np.sqrt(2)
        bell_kets = {
            "Phi+": np.array([inv_sqrt2, 0.0, 0.0, inv_sqrt2], dtype=complex),
            "Phi-": np.array([inv_sqrt2, 0.0, 0.0, -inv_sqrt2], dtype=complex),
            "Psi+": np.array([0.0, inv_sqrt2, inv_sqrt2, 0.0], dtype=complex),
            "Psi-": np.array([0.0, inv_sqrt2, -inv_sqrt2, 0.0], dtype=complex),
        }
        cleaned = name.replace(" ", "").replace("|", "").replace("⟩", "").replace(">", "")
        if cleaned in bell_kets:
            psi = bell_kets[cleaned]
            return np.outer(psi, psi.conj())

    raise ValueError(f"Unsupported target state '{target_spec}' for {n_qubits}-qubit system.")


def _vector_to_basis_name(c0: complex, c1: complex) -> str:
    """Identify nearest standard polarization basis label for a state vector."""
    norm = np.hypot(abs(c0), abs(c1))
    if norm < 1e-9:
        return "H"
    c0, c1 = c0 / norm, c1 / norm
    if abs(c0 - 1.0) < 0.15 and abs(c1) < 0.15:
        return "H"
    if abs(c0) < 0.15 and abs(c1 - 1.0) < 0.15:
        return "V"
    if abs(c0 - 1.0 / np.sqrt(2)) < 0.2:
        if abs(c1 - 1.0 / np.sqrt(2)) < 0.2:
            return "D"
        if abs(c1 + 1.0 / np.sqrt(2)) < 0.2:
            return "A"
        if abs(c1 - 1j / np.sqrt(2)) < 0.2:
            return "R"
        if abs(c1 + 1j / np.sqrt(2)) < 0.2:
            return "L"
    return "H"


def parse_tomo_file(content: str, filename: str = "") -> dict[str, Any]:
    """Parse uploaded tomography file (.json, .toml, or .txt) into standardized dataset.

    Returns dictionary containing:
    - status: 'success'
    - data: standard dataset dictionary
    - config: configuration dictionary (if present)
    - filename: original file name
    """
    import re
    from qtools.tomo.tomography.Utilities import parse_np_array

    text = content.strip()

    # 1. JSON format (.json)
    if text.startswith("{") or filename.lower().endswith(".json"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "data" in parsed:
                win = parsed.get("coincidence_window") or parsed.get("window")
                if win is None and isinstance(parsed.get("config"), dict):
                    win = parsed["config"].get("window") or parsed["config"].get("coincidence_window")
                if win is not None:
                    if not isinstance(win, list):
                        win = [win]
                    parsed["coincidence_window"] = win
                    parsed.setdefault("config", {})["window"] = win
                return {
                    "status": "success",
                    "format": "json",
                    "filename": filename,
                    "data": parsed,
                    "config": parsed.get("config", {}),
                }
        except Exception:
            pass

    # 2. TOML configuration (.toml)
    if filename.lower().endswith(".toml") or (not text.startswith("tomo_input") and "=" in text and "[" in text and "]" in text):
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib
            conf = tomllib.loads(text)
            if isinstance(conf, dict) and len(conf) > 0:
                win = conf.get("window") or conf.get("coincidence_window")
                if win is None and "tomography" in conf and isinstance(conf["tomography"], dict):
                    win = conf["tomography"].get("window") or conf["tomography"].get("coincidence_window")
                if win is not None:
                    if not isinstance(win, list):
                        win = [win]
                    conf["window"] = win
                return {
                    "status": "success",
                    "format": "toml",
                    "filename": filename,
                    "config": conf,
                }
        except Exception:
            pass

    # 3. Classic Kwiat Lab MATLAB / text eval format (.txt)
    # Lines like: tomo_input = [...] or tomo_input=np.array(...)
    if "tomo_input" in text:
        tomo_input_str = ""
        win_val = None
        for line in text.splitlines():
            line_str = line.strip()
            if line_str.startswith("tomo_input"):
                parts = line_str.split("=", 1)
                val_str = parts[1].strip().rstrip(";")
                if val_str.startswith("np.array("):
                    val_str = val_str[len("np.array("):].rstrip(")")
                tomo_input_str = val_str
            elif "=" in line_str:
                parts = [p.strip() for p in line_str.split("=", 1)]
                if parts[0].lower() in ("window", "coincidence_window", "conf['window']", 'conf["window"]', "conf.window"):
                    right_val = parts[1].rstrip(";").strip()
                    try:
                        if right_val.startswith("[") and right_val.endswith("]"):
                            win_val = [float(x.strip()) for x in right_val[1:-1].split(",") if x.strip()]
                        else:
                            win_val = [float(right_val)]
                    except Exception:
                        pass

        if tomo_input_str:
            arr = parse_np_array(tomo_input_str)
            n_rows, n_cols = arr.shape

            # Detect geometry from columns
            if n_cols == 13:
                # 2 qubits, 2 detectors per qubit (4 detectors total)
                n_qubits = 2
                n_detectors = 2
                data_rows = []
                for row in arr:
                    time = float(row[0].real) if abs(row[0].real) > 1e-9 else 1.0
                    singles = [int(round(float(s.real))) for s in row[1:5]]
                    coincs = [int(round(float(c.real))) for c in row[5:9]]
                    bA = _vector_to_basis_name(row[9], row[10])
                    bB = _vector_to_basis_name(row[11], row[12])
                    data_rows.append({
                        "basis": [bA, bB],
                        "integration_time": time,
                        "counts": singles + coincs,
                    })
            elif n_cols == 8:
                # 2 qubits, 1 detector per qubit
                n_qubits = 2
                n_detectors = 1
                data_rows = []
                for row in arr:
                    time = float(row[0].real) if abs(row[0].real) > 1e-9 else 1.0
                    sA = int(round(float(row[1].real)))
                    sB = int(round(float(row[2].real)))
                    coinc = int(round(float(row[3].real)))
                    bA = _vector_to_basis_name(row[4], row[5])
                    bB = _vector_to_basis_name(row[6], row[7])
                    data_rows.append({
                        "basis": [bA, bB],
                        "integration_time": time,
                        "counts": [sA, sB, coinc],
                    })
            elif n_cols in (4, 5):
                # 1 qubit, 1 detector
                n_qubits = 1
                n_detectors = 1
                data_rows = []
                for row in arr:
                    time = float(row[0].real) if abs(row[0].real) > 1e-9 else 1.0
                    if n_cols == 5:
                        c_val = int(round(float(row[2].real)))
                        bA = _vector_to_basis_name(row[3], row[4])
                    else:
                        c_val = int(round(float(row[1].real)))
                        bA = _vector_to_basis_name(row[2], row[3])
                    data_rows.append({
                        "basis": [bA],
                        "integration_time": time,
                        "counts": [c_val],
                    })
            else:
                raise ValueError(f"Unrecognized tomo_input array dimensions: {arr.shape}")

            dataset = {
                "n_qubits": n_qubits,
                "n_detectors_per_qubit": n_detectors,
                "coincidence_window": win_val if win_val is not None else ([0] if n_detectors == 1 else [0, 0, 0, 0]),
                "n_measurements_per_qubit": len(data_rows),
                "measurement_states": {
                    "H": [1, 0],
                    "V": [0, 1],
                    "D": [1, 1],
                    "A": [1, -1],
                    "R": [1, "1j"],
                    "L": [1, "-1j"],
                },
                "data": data_rows,
            }

            return {
                "status": "success",
                "format": "txt_tomo_input",
                "filename": filename,
                "data": dataset,
                "config": {
                    "do_drift_correction": False,
                    "do_accidental_correction": bool(win_val is not None and win_val[0] > 0),
                    "window": win_val if win_val is not None else ([0] if n_detectors == 1 else [0, 0, 0, 0]),
                    "get_bell_settings": (n_qubits == 2),
                    "method": "MLE",
                },
            }

    raise ValueError(f"Could not parse file '{filename}'. Supported formats: .json, .toml, or .txt with tomo_input.")


def run_tomography(
    config: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    target_state: str | list | None = None,
    preset_id: str | None = None,
) -> dict[str, Any]:
    """Execute quantum state tomography on provided data and configuration.

    Parameters
    ----------
    config : dict, optional
        Configuration parameters (method, do_drift_correction, get_bell_settings, etc.)
    data : dict, optional
        Standard Tomography JSON data dictionary containing measurement_states and data points.
    target_state : str or list, optional
        Target pure state or density matrix to evaluate state reconstruction fidelity.
    preset_id : str, optional
        Optional preset to load if config/data are omitted.

    Returns
    -------
    dict
        Structured tomography analysis results including density matrix, properties, and tables.
    """
    if preset_id and (data is None or config is None):
        loaded = load_preset(preset_id)
        config = config or loaded["config"]
        data = data or loaded["data"]
        target_state = target_state or loaded["default_target"]

    if data is None:
        # Load default bell_state_example directly from ExampleFiles
        loaded = load_preset("bell_state_example")
        data = loaded["data"]
        config = config or loaded["config"]
        target_state = target_state or loaded["default_target"]

    if config is None:
        config = {}

    n_qubits = int(data.get("n_qubits", 1))

    # Initialize Tomography object
    t = Tomography(n_qubits)

    # Load configuration and measurement data into Tomography
    t._import_conf(config)
    t._import_data(data)

    # Check the counts actually used by tomography.  Summing all detector
    # channels would treat nonzero singles in an otherwise empty template as
    # observed coincidence data and produce a misleading reconstructed state.
    coincidence_index = max(
        0,
        sum(comb(n_qubits, i) for i in range(n_qubits)) - 1,
    )
    total_counts = 0.0
    for row in data.get("data", []):
        counts = row.get("counts", [])
        if counts and len(counts) > coincidence_index:
            value = counts[coincidence_index]
        elif counts:
            value = counts[-1]
        else:
            value = 0.0
        try:
            total_counts += max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    if total_counts <= 0:
        dim = 2**n_qubits
        rho = np.eye(dim, dtype=complex) / dim
        intens = 0.0
        fval = 0.0
    else:
        # Perform Maximum Likelihood Estimation (MLE) state reconstruction
        rho, intens, fval = t.run_tomography()

    # Calculate key physical state properties defined in Kwiat Group's manual
    purity = float(np.real(tf.purity(rho)))
    lin_entropy = float(np.real(tf.linear_entropy(rho)))
    von_neumann_entropy = float(np.real(tf.entropy(rho)))

    concurrence: float | None = None
    tangle: float | None = None
    bell_settings: list[dict[str, Any]] = []

    if n_qubits == 2:
        try:
            concurrence = float(np.real(tf.concurrence(rho)))
            tangle = float(np.real(tf.tangle(rho)))
        except Exception:
            concurrence = None
            tangle = None

        if config.get("get_bell_settings") or config.get("Bellstate"):
            try:
                raw_bs = t.getBellSettings(rho)
                # Format bell inequality settings
                for row in raw_bs:
                    angle_deg = float(row[1])
                    err_deg = float(row[2]) if len(row) > 2 and not np.isnan(row[2]) else None
                    bell_settings.append({
                        "property": str(row[0]),
                        "angle_deg": round(angle_deg, 3),
                        "error_deg": round(err_deg, 3) if err_deg is not None else None,
                    })
            except Exception:
                bell_settings = []

    # Fidelity calculation
    fidelity_val: float | None = None
    target_rho: np.ndarray | None = None
    if target_state is not None:
        try:
            target_rho = get_target_density_matrix(target_state, n_qubits)
            fidelity_val = float(np.real(tf.fidelity(rho, target_rho)))
        except Exception:
            fidelity_val = None

    # Uncertainty calculation based on measurement stds / Poisson fallback and asymmetric credible intervals
    try:
        from qtools.tomo.tomography.TomoUncertainties import compute_state_uncertainties
        unc = compute_state_uncertainties(
            data_rows=data.get("data", []),
            rho=rho,
            target_state=target_rho,
            point_estimates={
                "fidelity": fidelity_val,
                "purity": purity,
                "concurrence": concurrence,
                "entropy": von_neumann_entropy,
            },
            n_samples=80,
            intensity=float(intens) if intens is not None else None,
            n_qubits=n_qubits,
            measurement_states=data.get("measurement_states"),
        )
    except Exception:
        unc = {
            "fidelity_std": None,
            "fidelity_ci": None,
            "fidelity_err_minus": None,
            "fidelity_err_plus": None,
            "purity_std": None,
            "purity_ci": None,
            "purity_err_minus": None,
            "purity_err_plus": None,
            "concurrence_std": None,
            "concurrence_ci": None,
            "concurrence_err_minus": None,
            "concurrence_err_plus": None,
            "entropy_std": None,
            "entropy_ci": None,
            "entropy_err_minus": None,
            "entropy_err_plus": None,
        }

    # Labels for basis representation
    if n_qubits == 1:
        labels = ["|H⟩", "|V⟩"]
    elif n_qubits == 2:
        labels = ["|HH⟩", "|HV⟩", "|VH⟩", "|VV⟩"]
    else:
        labels = [f"|{bin(i)[2:].zfill(n_qubits)}⟩" for i in range(2**n_qubits)]

    dim = 2**n_qubits
    re_matrix = [[round(float(rho[r, c].real), 5) for c in range(dim)] for r in range(dim)]
    im_matrix = [[round(float(rho[r, c].imag), 5) for c in range(dim)] for r in range(dim)]

    curves: list[dict[str, Any]] = []
    curves_qwp: list[dict[str, Any]] = []
    curves_qwp_scan: list[dict[str, Any]] = []
    target_curves: list[dict[str, Any]] = []
    target_curves_qwp: list[dict[str, Any]] = []
    target_curves_qwp_scan: list[dict[str, Any]] = []
    angles: list[float] = []
    if n_qubits == 2:
        try:
            import qutip as qt
            from qtools.tomo import bell

            rho_qobj = qt.Qobj(rho, dims=[[2, 2], [2, 2]])
            target_qobj = qt.Qobj(target_rho, dims=[[2, 2], [2, 2]]) if target_rho is not None else None
            angles = np.linspace(-45.0, 45.0, 91).tolist()
            qwp_45_dag = bell.qwp(45.0).dag()
            h_ket = bell.h_state()

            alice_kets = {
                "H": bell.h_state(),
                "V": bell.v_state(),
                "D": bell.d_state(),
                "A": bell.a_state(),
                "R": bell.r_state(),
                "L": bell.l_state(),
            }

            present_alice = []
            for row in data.get("data", []):
                b = row.get("basis", [])
                if len(b) > 0 and b[0] not in present_alice:
                    present_alice.append(b[0])

            alice_order = ["H", "V", "D", "A", "R", "L"]
            target_alice = [b for b in alice_order if b in present_alice]
            if not target_alice:
                target_alice = ["H", "V", "D", "A"]

            for a_name in target_alice:
                if a_name not in alice_kets:
                    continue
                a_ket = alice_kets[a_name]
                joint_vals, cond_vals, counts_vals = [], [], []
                joint_qwp, cond_qwp, counts_qwp = [], [], []
                joint_scan, cond_scan, counts_scan = [], [], []

                t_joint, t_cond, t_counts = [], [], []
                t_joint_q, t_cond_q, t_counts_q = [], [], []
                t_joint_scan, t_cond_scan, t_counts_scan = [], [], []

                for ang in angles:
                    # 1. Linear analyzer (Chart 1: Bob QWP fixed at phi_b = 0 deg, HWP theta_b scan)
                    bob_plus, _ = bell.hwp_analyzer_basis(float(ang))
                    j = bell.joint_probability(rho_qobj, a_ket, bob_plus)
                    c = bell.conditional_probability(rho_qobj, bob_plus, a_ket)
                    joint_vals.append(round(j, 6))
                    cond_vals.append(round(c, 6))
                    counts_vals.append(round(j * float(intens), 3))

                    # 2. Circular analyzer (Bob QWP at phi_b = 45 deg, HWP scan)
                    bob_qwp_hwp = qwp_45_dag * bell.hwp(float(ang)).dag() * h_ket
                    jq = bell.joint_probability(rho_qobj, a_ket, bob_qwp_hwp)
                    cq = bell.conditional_probability(rho_qobj, bob_qwp_hwp, a_ket)
                    joint_qwp.append(round(jq, 6))
                    cond_qwp.append(round(cq, 6))
                    counts_qwp.append(round(jq * float(intens), 3))

                    # 3. QWP angle scan (Chart 2: Bob HWP fixed at theta_b = 0 deg, QWP phi_b scan)
                    bob_qwp_s = bell.qwp(float(ang)).dag() * h_ket
                    js = bell.joint_probability(rho_qobj, a_ket, bob_qwp_s)
                    cs = bell.conditional_probability(rho_qobj, bob_qwp_s, a_ket)
                    joint_scan.append(round(js, 6))
                    cond_scan.append(round(cs, 6))
                    counts_scan.append(round(js * float(intens), 3))

                    # Target state curves if available
                    if target_qobj is not None:
                        tj = bell.joint_probability(target_qobj, a_ket, bob_plus)
                        tc = bell.conditional_probability(target_qobj, bob_plus, a_ket)
                        t_joint.append(round(tj, 6))
                        t_cond.append(round(tc, 6))
                        t_counts.append(round(tj * float(intens), 3))

                        tjq = bell.joint_probability(target_qobj, a_ket, bob_qwp_hwp)
                        tcq = bell.conditional_probability(target_qobj, bob_qwp_hwp, a_ket)
                        t_joint_q.append(round(tjq, 6))
                        t_cond_q.append(round(tcq, 6))
                        t_counts_q.append(round(tjq * float(intens), 3))

                        tjs = bell.joint_probability(target_qobj, a_ket, bob_qwp_s)
                        tcs = bell.conditional_probability(target_qobj, bob_qwp_s, a_ket)
                        t_joint_scan.append(round(tjs, 6))
                        t_cond_scan.append(round(tcs, 6))
                        t_counts_scan.append(round(tjs * float(intens), 3))

                curves.append({
                    "alice": a_name,
                    "joint": joint_vals,
                    "conditional": cond_vals,
                    "counts": counts_vals,
                })
                curves_qwp.append({
                    "alice": a_name,
                    "joint": joint_qwp,
                    "conditional": cond_qwp,
                    "counts": counts_qwp,
                })
                curves_qwp_scan.append({
                    "alice": a_name,
                    "joint": joint_scan,
                    "conditional": cond_scan,
                    "counts": counts_scan,
                })

                if target_qobj is not None:
                    target_curves.append({
                        "alice": a_name,
                        "joint": t_joint,
                        "conditional": t_cond,
                        "counts": t_counts,
                    })
                    target_curves_qwp.append({
                        "alice": a_name,
                        "joint": t_joint_q,
                        "conditional": t_cond_q,
                        "counts": t_counts_q,
                    })
                    target_curves_qwp_scan.append({
                        "alice": a_name,
                        "joint": t_joint_scan,
                        "conditional": t_cond_scan,
                        "counts": t_counts_scan,
                    })
        except Exception:
            curves = []
            curves_qwp = []
            curves_qwp_scan = []
            target_curves = []
            target_curves_qwp = []
            target_curves_qwp_scan = []
            angles = []

    return {
        "status": "success",
        "n_qubits": n_qubits,
        "n_measurements": len(data.get("data", [])),
        "fval": round(float(fval), 5),
        "intensity": round(float(intens), 3),
        "purity": round(purity, 5),
        "purity_std": unc.get("purity_std"),
        "purity_ci": unc.get("purity_ci"),
        "purity_err_minus": unc.get("purity_err_minus"),
        "purity_err_plus": unc.get("purity_err_plus"),
        "linear_entropy": round(lin_entropy, 5),
        "entropy": round(von_neumann_entropy, 5),
        "entropy_std": unc.get("entropy_std"),
        "entropy_ci": unc.get("entropy_ci"),
        "entropy_err_minus": unc.get("entropy_err_minus"),
        "entropy_err_plus": unc.get("entropy_err_plus"),
        "concurrence": round(concurrence, 5) if concurrence is not None else None,
        "concurrence_std": unc.get("concurrence_std"),
        "concurrence_ci": unc.get("concurrence_ci"),
        "concurrence_err_minus": unc.get("concurrence_err_minus"),
        "concurrence_err_plus": unc.get("concurrence_err_plus"),
        "tangle": round(tangle, 5) if tangle is not None else None,
        "fidelity": round(fidelity_val, 5) if fidelity_val is not None else None,
        "fidelity_std": unc.get("fidelity_std"),
        "fidelity_ci": unc.get("fidelity_ci"),
        "fidelity_err_minus": unc.get("fidelity_err_minus"),
        "fidelity_err_plus": unc.get("fidelity_err_plus"),
        "target_state": str(target_state) if target_state else None,
        "density_matrix": {
            "dim": dim,
            "labels": labels,
            "real": re_matrix,
            "imag": im_matrix,
        },
        "bell_settings": bell_settings,
        "curves": curves,
        "curves_qwp": curves_qwp,
        "curves_qwp_scan": curves_qwp_scan,
        "target_curves": target_curves,
        "target_curves_qwp": target_curves_qwp,
        "target_curves_qwp_scan": target_curves_qwp_scan,
        "angles": angles,
        "html": {
            "matrix_html": td.matrixToHTML(rho),
        },
    }


def get_template(
    n_qubits: int = 2,
    template_type: str = "canonical_36",
    n_detectors: int = 1,
) -> dict[str, Any]:
    """Generate empty measurement template with standard basis settings.

    Supported template types:
    - 2-Qubits: 'canonical_36' ({H,V,D,A,R,L}²), 'minimal_16' ({H,V,D,R}²), 'canonical_9' ({H,D,R}² for 2 det)
    - 1-Qubit: 'single_6' ({H,V,D,A,R,L}), 'minimal_4' ({H,V,D,R})
    """
    single_bases = ["H", "V", "D", "A", "R", "L"]
    minimal_bases = ["H", "V", "D", "R"]
    two_det_bases = ["H", "D", "R"]

    if n_qubits == 1:
        chosen_bases = minimal_bases if ("minimal" in template_type or "4" in template_type) else single_bases
        rows = [{"basis": [b], "integration_time": 1, "counts": [0]} for b in chosen_bases]
    else:
        if n_detectors == 2 or "9" in template_type:
            chosen_a, chosen_b = two_det_bases, two_det_bases
            count_len = 8  # [s1, s2, s3, s4, c12, c14, c32, c34]
        elif "16" in template_type or "minimal" in template_type:
            chosen_a, chosen_b = minimal_bases, minimal_bases
            count_len = 3  # [singles_A, singles_B, coincidences]
        else:  # 36 canonical
            chosen_a, chosen_b = single_bases, single_bases
            count_len = 3

        rows = []
        for a in chosen_a:
            for b in chosen_b:
                rows.append({
                    "basis": [a, b],
                    "integration_time": 1,
                    "counts": [0] * count_len,
                })

    return {
        "n_qubits": n_qubits,
        "n_detectors_per_qubit": n_detectors,
        "coincidence_window": [0] if n_detectors == 1 else [0, 0, 0, 0],
        "n_measurements_per_qubit": len(rows),
        "measurement_states": {
            "H": [1, 0],
            "V": [0, 1],
            "D": [1, 1],
            "A": [1, -1],
            "R": [1, "1j"],
            "L": [1, "-1j"],
        },
        "data": rows,
    }
