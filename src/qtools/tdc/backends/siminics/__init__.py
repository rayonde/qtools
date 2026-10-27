"""Siminics FT10xx TDC backend."""

from .backend import SiminicsBackend
from .errors import SiminicsError, SiminicsSDKError, SiminicsSDKUnavailable
from .models import ITTRResult, MarkerEvent, ParsedTTTR, T1HistogramResult, TTTREvent
from .parser import parse_blocks, parse_bytes, parse_file, parse_words
from .sdk import FtmtRawData, SiminicsSDK

__all__ = [
    "FtmtRawData",
    "ITTRResult",
    "MarkerEvent",
    "ParsedTTTR",
    "SiminicsBackend",
    "SiminicsError",
    "SiminicsSDK",
    "SiminicsSDKError",
    "SiminicsSDKUnavailable",
    "T1HistogramResult",
    "TTTREvent",
    "parse_blocks",
    "parse_bytes",
    "parse_file",
    "parse_words",
]
