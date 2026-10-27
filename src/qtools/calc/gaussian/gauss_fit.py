"""Compatibility imports and CLI for the original Gaussian beam script.

Original model: Alessandro Cere (2014); multi-beam extension: Yifan Li (2026).
Use qtools.calc.gaussian.fit for new code.
"""

from qtools.calc.gaussian import Profile, fit, gauss_flat, gaussian2d, plot
from qtools.calc.gaussian.cli import main

__all__ = ["Profile", "fit", "gauss_flat", "gaussian2d", "main", "plot"]

if __name__ == "__main__":
    raise SystemExit(main())
