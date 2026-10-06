"""Enumerations and constants for TEC devices."""

from __future__ import annotations

from enum import IntEnum


class TECMode(IntEnum):
    """Heating / cooling operating modes for TEC."""

    BOTH = 0     # Bipolar (both heat and cool)
    COOL = 1     # Cool only
    HEAT = 2     # Heat only
    VOLTAGE = 3  # Voltage / PWM duty control mode


class TECPolarity(IntEnum):
    """Output polarity for TEC controller."""

    NORMAL = 0
    REVERSED = 1


class SensorModel(IntEnum):
    """Temperature sensor solution models (spec section 3.2.3)."""

    B_VALUE = 0         # NTC with B-value & R0, polynomial correction enabled
    PT_MODEL = 1        # PT platinum resistance model (PT1000)
    STEINHART_HART = 2  # Steinhart-Hart (S-H) model
    MF501 = 3           # MF501 thermistor model


class PowerMode(IntEnum):
    """Power-on output modes (spec section 3.2.20)."""

    FOLLOW_LAST = 0  # Follow last output state before power off
    POWER_ON = 1     # Automatically enable output on boot
    POWER_OFF = 2    # Default to disabled output on boot


# 16-bit status register bit definitions (spec section 3.5.8)
ERROR_BIT_MAP: dict[int, str] = {
    0: "Interior high temperature alarm (power reduced)",
    1: "Interior over-temperature alarm (output stopped)",
    2: "Under-voltage alarm (< 7V)",
    3: "Over-voltage alarm (> 30V)",
    5: "Channel 1 sensor temperature out of threshold",
    6: "Channel 1 current limited at maximum",
    9: "Channel 2 sensor temperature out of threshold",
    10: "Channel 2 current limited at maximum",
}


# Models defined in section 3.5.1 of official protocol
TEC_MODEL_MAP: dict[int, str] = {
    1: "103",
    2: "207L",
    3: "207",
    4: "215L",
    5: "215",
    6: "215Pro",
    7: "107L",
    8: "107",
    9: "115L",
    10: "115",
    11: "115Pro",
    12: "100L",
    13: "100",
    14: "100Pro",
    15: "403L",
    16: "403",
    17: "403Pro",
    18: "415L",
    19: "415",
    20: "603L",
    21: "603",
    22: "615L",
    23: "615",
    24: "615Pro",
    25: "803L",
    26: "803",
    27: "815L",
    28: "815",
    29: "815Pro",
    30: "203L",
    31: "203",
}



