from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from qtools.camera import CameraDependencyError, FLIR
from qtools.camera.backends import flir as flir_module


def test_finds_bundled_pyspin_wheel() -> None:
    wheel = FLIR.find_pyspin_wheel(python_version=(3, 12))

    assert wheel.is_file()
    assert flir_module._wheel_cp_tag(wheel) == "cp312"
    assert flir_module._wheel_version(wheel) == "4.4.0.246"


def test_defaults_to_python_312() -> None:
    assert FLIR.default_python_version == (3, 12)
    assert flir_module._wheel_cp_tag(FLIR.find_pyspin_wheel()) == "cp312"


def test_finds_no_wheel_for_unsupported_python() -> None:
    with pytest.raises(CameraDependencyError, match="Python 3.14"):
        FLIR.find_pyspin_wheel(python_version=(3, 14))


def test_bridge_python_path() -> None:
    python = FLIR.bridge_python(".venv-camera")

    assert python.name == ("python.exe" if sys.platform == "win32" else "python")
    assert python.parent.name == ("Scripts" if sys.platform == "win32" else "bin")


def test_rejects_wrong_base_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flir_module, "_probe_python", lambda executable: (3, 14, 64))

    with pytest.raises(CameraDependencyError, match="requires Python 3.12"):
        flir_module._resolve_python((3, 12), sys.executable)


def test_auto_installs_missing_python(monkeypatch: pytest.MonkeyPatch) -> None:
    discovered = [None, Path(sys.executable)]
    installs: list[tuple[int, int]] = []
    monkeypatch.setattr(flir_module, "_find_python", lambda *args: discovered.pop(0))
    monkeypatch.setattr(
        flir_module,
        "_install_python_with_winget",
        lambda version: installs.append(version) or True,
    )

    result = flir_module._resolve_python((3, 12), None)

    assert result == Path(sys.executable)
    assert installs == [(3, 12)]

def test_incompatible_venv_is_recreated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    venv_path = tmp_path / ".venv-camera"
    venv_path.mkdir()
    fake_python = venv_path / "python.exe"
    fake_python.touch()
    identities = iter([(3, 12, 64), (3, 10, 64), (3, 12, 64)])
    commands: list[list[str]] = []

    monkeypatch.setattr(FLIR, "bridge_python", staticmethod(lambda _: fake_python))
    monkeypatch.setattr(flir_module, "_resolve_python", lambda *args, **kwargs: Path(sys.executable))
    monkeypatch.setattr(flir_module, "_probe_python", lambda executable: next(identities))
    monkeypatch.setattr(
        flir_module, "_pyspin_ready", lambda executable, expected_version=None: True
    )
    monkeypatch.setattr(flir_module, "_run_checked", lambda command, description: commands.append(command))

    result = FLIR.create_bridge_venv(
        venv_path,
        wheel=FLIR.find_pyspin_wheel(),
        auto_install_python=False,
    )

    assert result == venv_path
    assert commands == [[str(sys.executable), "-m", "venv", "--clear", str(venv_path)]]

def test_pyspin_ready_requires_matching_installed_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = types.SimpleNamespace(returncode=0, stdout="4.3.0.1\n", stderr="")
    monkeypatch.setattr(flir_module.subprocess, "run", lambda *args, **kwargs: completed)

    assert not flir_module._pyspin_ready(Path(sys.executable), "4.4.0.246")

