"""Path resolution helpers for qtools.motor."""

from __future__ import annotations

import os
from pathlib import Path


def get_config_path() -> Path:
    """Absolute path to the config file.

    Respects the ``MOTOR_CONFIG`` environment variable (set by
    ``qtools.pmeas`` when stepper is embedded).  Defaults to
    ``motor_config.yaml`` in the **current working directory**.
    """
    env = os.environ.get("MOTOR_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd() / "motor_config.yaml"


def get_subdir_path(subdir: str, filename: str) -> str:
    """Return a path inside the given subdirectory."""
    out_dir = Path.cwd() / subdir
    out_dir.mkdir(exist_ok=True)
    return str(out_dir / filename)


