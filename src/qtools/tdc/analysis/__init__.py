"""Analysis engines for TDC data processing."""

from qtools.tdc.analysis.g2 import (
    compute_g2,
    compute_triplet_g2,
    compute_gate_coincidence,
    compute_gate_photons,
    measure_multiple_g2,
)
from qtools.tdc.analysis.efficiency import compute_pairs, compute_accidentals, compute_coincidence
from qtools.tdc.data import DataWriter, read_log

__all__ = [
    "compute_g2",
    "compute_triplet_g2",
    "compute_gate_coincidence",
    "compute_gate_photons",
    "measure_multiple_g2",
    "compute_pairs",
    "compute_accidentals",
    "compute_coincidence",
    "DataWriter",
    "read_log",
]
