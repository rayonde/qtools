from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from qtools.pmeas.config import ConfigManager
from qtools.pmeas.entanglement import (
    _basis_arm_angles,
    _resolve_basis_arm,
    run_bell_scan,
)


class FakeStage:
    def __init__(self, name: str) -> None:
        self.name = name
        self.is_connected = False
        self.positions: list[float] = []
        self.home_count = 0

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.is_connected = False

    def home(self) -> None:
        self.home_count += 1

    def move_to(self, angle: float) -> None:
        self.positions.append(float(angle))

    def wait_move(self) -> None:
        pass


class FakeMotorManager:
    def __init__(self, stages: dict[str, FakeStage]) -> None:
        self.stages = stages

    def get_motor(self, target: str) -> FakeStage:
        return self.stages[target]


class FakeMeasManager:
    def __init__(self) -> None:
        self.calls = 0

    def measure(self, **kwargs):
        self.calls += 1
        rate = 100.0 + self.calls
        return SimpleNamespace(
            value=rate,
            error=1.0,
            metrics={
                "raw_pair_rate": rate,
                "raw_pair_rate_std": 1.0,
            },
        )


def _config(tmp_path: Path) -> ConfigManager:
    cfg = ConfigManager.resolve(tmp_path / "polmeas_config.yaml")
    cfg.upsert_device(
        key="alice_qwp",
        name="alice_qwp",
        optical_path="alice",
        waveplate="qwp",
        serial="AQ",
        bases={"H": 10.0, "V": 10.0, "D": 55.0, "A": 55.0},
        calibration={"theta_0": 10.0},
    )
    cfg.upsert_device(
        key="alice_hwp",
        name="alice_hwp",
        optical_path="alice",
        waveplate="hwp",
        serial="AH",
        bases={"H": 40.0, "V": 85.0, "D": 62.5, "A": 107.5},
        calibration={"theta_0": 40.0},
    )
    cfg.upsert_device(
        key="bob_hwp",
        name="bob_hwp",
        optical_path="bob",
        waveplate="hwp",
        serial="BH",
        bases={"H": 20.0, "V": 65.0, "D": 42.5, "A": 87.5},
        calibration={"theta_0": 20.0},
    )
    return cfg


def test_bell_arm_inference_and_qwp_hwp_angle_mapping(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    stages = {
        "alice_qwp": FakeStage("alice_qwp"),
        "alice_hwp": FakeStage("alice_hwp"),
        "bob_hwp": FakeStage("bob_hwp"),
    }
    arms = {
        side: _resolve_basis_arm(cfg, FakeMotorManager(stages), side)
        for side in ("alice", "bob")
    }

    assert arms["alice"]["waveplates"] == ["qwp", "hwp"]
    assert arms["bob"]["waveplates"] == ["hwp"]

    angles = _basis_arm_angles(arms["alice"], "D")
    assert [round(angle, 6) for _stage, angle in angles] == [55.0, 62.5]


def test_bell_scan_moves_both_alice_waveplates(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    stages = {
        "alice_qwp": FakeStage("alice_qwp"),
        "alice_hwp": FakeStage("alice_hwp"),
        "bob_hwp": FakeStage("bob_hwp"),
    }

    run_bell_scan(
        motor_mgr=FakeMotorManager(stages),
        meas_mgr=FakeMeasManager(),
        cfg=cfg,
        start_offset=0.0,
        end_offset=0.0,
        step_offset=1.0,
        duration=0.01,
        repetitions=1,
        subtract_accidentals=False,
        save_raw=False,
        save_plot=False,
    )

    assert stages["alice_qwp"].positions == [10.0, 10.0, 55.0, 55.0]
    assert stages["alice_hwp"].positions == [40.0, 85.0, 62.5, 107.5]
    assert stages["bob_hwp"].positions[:4] == [20.0, 65.0, 42.5, 87.5]
    assert all(stage.home_count == 1 for stage in stages.values())
