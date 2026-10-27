"""Path resolution helpers for qtools.pmeas."""

from __future__ import annotations

from pathlib import Path


def get_subdir_path(subdir: str, filename: str) -> str:
    """Return a path inside the output directory."""
    out_dir = Path.cwd() / subdir
    out_dir.mkdir(exist_ok=True)
    return str(out_dir / filename)
