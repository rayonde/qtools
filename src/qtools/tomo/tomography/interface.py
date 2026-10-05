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


DEFAULT_BELL_DATA = {
    "n_qubits": 2,
    "n_detectors_per_qubit": 1,
    "coincidence_window": [10],
    "n_measurements_per_qubit": 6,
    "measurement_states": {
        "H": [1, 0],
        "V": [0, 1],
        "D": [1, 1],
        "A": [1, -1],
        "R": [1, "1j"],
        "L": [1, "-1j"]
    },
    "data": [
        {"basis": ["H", "H"], "integration_time": 1, "counts": [1200, 1200, 100]},
        {"basis": ["H", "V"], "integration_time": 1, "counts": [1200, 1200, 0]},
        {"basis": ["H", "D"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["H", "A"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["H", "R"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["H", "L"], "integration_time": 1, "counts": [1200, 1200, 50]},

        {"basis": ["V", "H"], "integration_time": 1, "counts": [1200, 1200, 0]},
        {"basis": ["V", "V"], "integration_time": 1, "counts": [1200, 1200, 100]},
        {"basis": ["V", "D"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["V", "A"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["V", "R"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["V", "L"], "integration_time": 1, "counts": [1200, 1200, 50]},

        {"basis": ["D", "H"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["D", "V"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["D", "D"], "integration_time": 1, "counts": [1200, 1200, 100]},
        {"basis": ["D", "A"], "integration_time": 1, "counts": [1200, 1200, 0]},
        {"basis": ["D", "R"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["D", "L"], "integration_time": 1, "counts": [1200, 1200, 50]},

        {"basis": ["A", "H"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["A", "V"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["A", "D"], "integration_time": 1, "counts": [1200, 1200, 0]},
        {"basis": ["A", "A"], "integration_time": 1, "counts": [1200, 1200, 100]},
        {"basis": ["A", "R"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["A", "L"], "integration_time": 1, "counts": [1200, 1200, 50]},

        {"basis": ["R", "H"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["R", "V"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["R", "D"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["R", "A"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["R", "R"], "integration_time": 1, "counts": [1200, 1200, 0]},
        {"basis": ["R", "L"], "integration_time": 1, "counts": [1200, 1200, 100]},

        {"basis": ["L", "H"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["L", "V"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["L", "D"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["L", "A"], "integration_time": 1, "counts": [1200, 1200, 50]},
        {"basis": ["L", "R"], "integration_time": 1, "counts": [1200, 1200, 100]},
        {"basis": ["L", "L"], "integration_time": 1, "counts": [1200, 1200, 0]}
    ]
}

DEFAULT_1_QUBIT_DATA = {
    "n_qubits": 1,
    "n_detectors_per_qubit": 1,
    "coincidence_window": [0],
    "n_measurements_per_qubit": 6,
    "measurement_states": {
        "H": [1, 0],
        "V": [0, 1],
        "D": [1, 1],
        "A": [1, -1],
        "R": [1, "1j"],
        "L": [1, "-1j"]
    },
    "data": [
        {"basis": ["H"], "integration_time": 1, "counts": [50]},
        {"basis": ["V"], "integration_time": 1, "counts": [50]},
        {"basis": ["D"], "integration_time": 1, "counts": [50]},
        {"basis": ["A"], "integration_time": 1, "counts": [50]},
        {"basis": ["R"], "integration_time": 1, "counts": [100]},
        {"basis": ["L"], "integration_time": 1, "counts": [0]}
    ]
}


def load_preset(preset_id: str) -> dict[str, Any]:
    """Load configuration and measurement dataset for a given preset ID."""
    meta = PRESET_METADATA.get(preset_id, PRESET_METADATA["bell_state_example"])
    filepath = EXAMPLE_FILES_DIR / meta["file"]

    data_dict = None
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data_dict = json.load(f)
        except Exception:
            data_dict = None

    if data_dict is None:
        if meta["n_qubits"] == 1:
            data_dict = json.loads(json.dumps(DEFAULT_1_QUBIT_DATA))
        else:
            data_dict = json.loads(json.dumps(DEFAULT_BELL_DATA))

    # Standard default configuration with drift and accidental corrections enabled
    conf_dict = {
        "get_bell_settings": (meta["n_qubits"] == 2),
        "do_drift_correction": True,
        "do_accidental_correction": (meta["n_qubits"] == 2),
        "method": "MLE",
    }

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
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("tomo_input"):
                parts = line.split("=", 1)
                val_str = parts[1].strip().rstrip(";")
                if val_str.startswith("np.array("):
                    val_str = val_str[len("np.array("):].rstrip(")")
                tomo_input_str = val_str
                break

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
                "coincidence_window": [0] if n_detectors == 1 else [0, 0, 0, 0],
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
                    "do_accidental_correction": False,
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
        raise ValueError("Tomography data must be provided either directly or via preset_id.")
    if config is None:
        config = {}

    n_qubits = int(data.get("n_qubits", 1))

    # Initialize Tomography object
    t = Tomography(n_qubits)

    # Load configuration and measurement data into Tomography
    t._import_conf(config)
    t._import_data(data)

    # Check if total counts are zero (e.g. empty template or zeroed counts)
    total_counts = sum(sum(row.get("counts", [])) for row in data.get("data", []))
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
    if target_state is not None:
        try:
            target_rho = get_target_density_matrix(target_state, n_qubits)
            fidelity_val = float(np.real(tf.fidelity(rho, target_rho)))
        except Exception:
            fidelity_val = None

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
    angles: list[float] = []
    if n_qubits == 2:
        try:
            import qutip as qt
            from qtools.tomo import bell

            rho_qobj = qt.Qobj(rho, dims=[[2, 2], [2, 2]])
            angles = np.linspace(-45.0, 45.0, 91).tolist()

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
                joint_vals = []
                cond_vals = []
                counts_vals = []
                for ang in angles:
                    bob_plus, _ = bell.hwp_analyzer_basis(float(ang))
                    j = bell.joint_probability(rho_qobj, a_ket, bob_plus)
                    c = bell.conditional_probability(rho_qobj, bob_plus, a_ket)
                    joint_vals.append(round(j, 6))
                    cond_vals.append(round(c, 6))
                    counts_vals.append(round(j * float(intens), 3))
                curves.append({
                    "alice": a_name,
                    "joint": joint_vals,
                    "conditional": cond_vals,
                    "counts": counts_vals,
                })
        except Exception:
            curves = []
            angles = []

    return {
        "status": "success",
        "n_qubits": n_qubits,
        "n_measurements": len(data.get("data", [])),
        "fval": round(float(fval), 5),
        "intensity": round(float(intens), 3),
        "purity": round(purity, 5),
        "linear_entropy": round(lin_entropy, 5),
        "entropy": round(von_neumann_entropy, 5),
        "concurrence": round(concurrence, 5) if concurrence is not None else None,
        "tangle": round(tangle, 5) if tangle is not None else None,
        "fidelity": round(fidelity_val, 5) if fidelity_val is not None else None,
        "target_state": str(target_state) if target_state else None,
        "density_matrix": {
            "dim": dim,
            "labels": labels,
            "real": re_matrix,
            "imag": im_matrix,
        },
        "bell_settings": bell_settings,
        "curves": curves,
        "angles": angles,
        "html": {
            "matrix_html": td.matrixToHTML(rho),
        },
    }


def simulate_counts_from_bell_state(
    amplitudes: dict[str, dict[str, float]],
    state_basis: str = "linear",
    basis_count: int = 36,
) -> dict[str, Any]:
    """Generate a standard Kwiat QST dataset from a theoretical Bell state.

    Supports 16 minimal basis settings or 36 canonical basis settings.
    """
    from qtools.tomo import bell

    # Reconstruct state vector in HV basis
    phi = bell.state_from_amplitudes(amplitudes, basis=state_basis)
    rho_ideal = bell.density_matrix(phi).full()

    single_projectors = {
        "H": np.array([1.0, 0.0], dtype=complex),
        "V": np.array([0.0, 1.0], dtype=complex),
        "D": np.array([1.0, 1.0], dtype=complex) / np.sqrt(2),
        "A": np.array([1.0, -1.0], dtype=complex) / np.sqrt(2),
        "R": np.array([1.0, 1.0j], dtype=complex) / np.sqrt(2),
        "L": np.array([1.0, -1.0j], dtype=complex) / np.sqrt(2),
    }

    if basis_count == 16:
        basis_keys = ["H", "V", "D", "R"]
    else:
        basis_keys = ["H", "V", "D", "A", "R", "L"]
    data_rows = []

    for a in basis_keys:
        for b in basis_keys:
            proj_a = single_projectors[a]
            proj_b = single_projectors[b]
            proj_2q = np.kron(proj_a, proj_b)
            # Probability P = ⟨proj|rho|proj⟩
            prob = float(np.real(np.vdot(proj_2q, rho_ideal @ proj_2q)))
            expected_counts = prob * (total_pairs / 4.0)

            if noise_ratio > 0:
                noise = np.random.normal(0, np.sqrt(expected_counts + 1) * noise_ratio)
                counts = max(0, int(round(expected_counts + noise)))
            else:
                counts = int(round(expected_counts))

            # [singles_A, singles_B, coincidences] for 1-detector model
            data_rows.append({
                "basis": [a, b],
                "integration_time": 1,
                "counts": [0, 0, counts],
            })

    dataset = {
        "n_qubits": 2,
        "n_detectors_per_qubit": 1,
        "coincidence_window": [0],
        "n_measurements_per_qubit": 6,
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

    return dataset


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
