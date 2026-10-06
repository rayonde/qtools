"""TDC Backend implementations.

Each backend is auto-registered when imported.
"""

import logging

logger = logging.getLogger(__name__)

_BACKEND_MODULES = [
    "qtools.tdc.backends.s15_tdc1",
    "qtools.tdc.backends.s15_tdc2",
    "qtools.tdc.backends.ciqtek",
    "qtools.tdc.backends.idq",
]

for _mod in _BACKEND_MODULES:
    try:
        __import__(_mod)
    except ImportError as e:
        logger.debug("Backend module '%s' not available: %s", _mod, e)
    except Exception as e:
        logger.warning("Unexpected error importing backend '%s': %s", _mod, e)
