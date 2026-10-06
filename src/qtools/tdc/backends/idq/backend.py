"""IDQ (ID Quantique) TDC Backend implementations.

This module provides backend wrappers for ID Quantique devices:
- ID801: 8-channel USB TDC (Harvey Mudd College / IDQ C-library driver).
- ID1000: 5-channel Gigabit Ethernet Time Controller (ZeroMQ / SCPI protocol).
"""

from __future__ import annotations

from qtools.tdc.backends.idq.backend_id801 import ID801Backend
from qtools.tdc.backends.idq.backend_id1000 import ID1000Backend

# Backwards compatibility alias: IDQBackend historically pointed to ID801
IDQBackend = ID801Backend

__all__ = [
    "ID801Backend",
    "ID1000Backend",
    "IDQBackend",
]
