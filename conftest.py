"""Global pytest isolation for tests that use cwd-relative paths.

Production code intentionally resolves user data relative to the process working
directory.  Tests must therefore never run with the repository root as their
working directory, otherwise calibration/configuration helpers can create local
artifact folders directly in the checkout.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Run every test from its own temporary working directory."""

    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    return workdir
