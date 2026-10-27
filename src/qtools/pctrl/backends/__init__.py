#!/usr/bin/env python3
"""
backends — unified servo backends for qtools.pctrl.

Provides
6: --------
7: ServoBackend   — auto-detecting, protocol-agnostic servo interface
8: COMM_SUCCESS   — communication result constant (re-exported for convenience)
9: """

from .servo import ServoBackend
from .scservo import COMM_SUCCESS

__all__ = ["ServoBackend", "COMM_SUCCESS"]
