from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path

import numpy as np

from qtools.pmeas import calibration
from qtools.pmeas.commands import calibrate as calibrate_command
from qtools.pmeas.cli import _add_calibrate_args
from qtools.pmeas.config import ConfigManager


def _write_calibration_csv(path: Path) -> None:
    path.write_text(
        "# Polarization Calibration Data\n"
        "# Wavelength (nm),1550\n"
        "# Device Serial,SN-1550\n"
        "# Data Unit,uW\n\n"
        "angle_deg,signal_rate (uW),error (uW),fit_curve (uW)\n"
        "0,10,0.1,999\n"
        "20,11,nan,999\n"
        "40,12,0.2,999\n"
        "60,13,0.2,999\n",
        encoding="utf-8",
    )


def test_load_calibration_csv_uses_measured_columns(tmp_path: Path) -> None:
    path = tmp_path / "cal.csv"
    _write_calibration_csv(path)

    data = calibration.load_calibration_csv(path)

    np.testing.assert_array_equal(data["angles"], [0, 20, 40, 60])
    np.testing.assert_array_equal(data["values"], [10, 11, 12, 13])
    np.testing.assert_allclose(data["errors"][[0, 2, 3]], [0.1, 0.2, 0.2])
    assert np.isnan(data["errors"][1])
    assert data["unit"] == "uW"
    assert data["wavelength_nm"] == 1550.0
    assert data["device_serial"] == "SN-1550"


def test_save_refit_calibration_config_updates_existing_device(tmp_path: Path) -> None:
    cfg_path = tmp_path / "polmeas_config.yaml"
    cfg = ConfigManager.resolve(cfg_path)
    cfg.register_device(
        serial="SN-1550",
        name="alice_hwp",
        optical_path="alice",
        role="basis",
    )
    cfg.save()

    result = {
        "theta_0": 2.0,
        "fast_axis": 2.0,
        "visibility": 0.8,
        "phi": 3.14159,
        "r_squared": 0.99,
        "target_angles": {"H": 2.0, "V": 47.0},
        "device_serial": "SN-1550",
        "device_name": "alice_hwp",
        "wavelength_nm": 1550.0,
        "cal_file": str(tmp_path / "cal.csv"),
        "plot_file": "",
        "refit_path": str(tmp_path / "cal.csv"),
    }

    device_key = calibration.save_refit_calibration_config(
        result,
        cfg,
        waveplate="hwp",
    )

    assert device_key == "SN-1550"

    reloaded = ConfigManager.resolve(cfg_path)
    cal = reloaded.get_calibration("SN-1550")
    assert cal is not None
    assert cal["theta_0"] == 2.0
    assert cal["bases"]["H"] == 2.0
    dev = reloaded.get_device("alice_hwp")
    assert dev["calibration"]["theta_0"] == 2.0
    assert dev["bases"]["H"] == 2.0


def test_refit_uses_current_fit_function_and_skips_export_by_default(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "cal.csv"
    _write_calibration_csv(path)
    calls: dict[str, object] = {}

    def fake_fit(
        angles,
        values,
        input_pol="H",
        basis="H",
        background=20.0,
        estimated_theta_0=0.0,
        segment=True,
        retardance_deg=180.0,
    ):
        calls["angles"] = np.asarray(angles)
        calls["values"] = np.asarray(values)
        calls["input_pol"] = input_pol
        calls["basis"] = basis
        calls["background"] = background
        calls["estimated_theta_0"] = estimated_theta_0
        return {
            "theta_0": 2.0,
            "visibility": 0.8,
            "phi": np.pi,
            "r_squared": 0.99,
            "model_func": lambda x: np.asarray(x, dtype=float) * 0 + 7.0,
        }

    monkeypatch.setattr(calibration, "fit_calibration_curve", fake_fit)
    result = calibration.refit_calibration(
        path,
        plot=False,
        estimated_theta_0=-12.5,
        background=20.0,
    )

    np.testing.assert_array_equal(calls["angles"], [0, 20, 40, 60])
    np.testing.assert_array_equal(calls["values"], [10, 11, 12, 13])
    assert result["theta_0"] == 2.0
    assert result["cal_file"] == ""
    assert result["fitted_values"].tolist() == [7.0] * len(result["fitted_values"])
    assert calls["background"] == 20.0
    assert calls["estimated_theta_0"] == -12.5


def test_fit_calibration_data_keeps_segmented_primary_and_global_result(
    monkeypatch,
) -> None:
    def fake_fit(
        angles,
        values,
        input_pol="H",
        basis="H",
        background=20.0,
        estimated_theta_0=0.0,
        segment=True,
        retardance_deg=180.0,
    ):
        theta_0 = 2.34 if segment else 2.345678
        return {
            "theta_0": theta_0,
            "visibility": 0.9,
            "phi": np.pi,
            "r_squared": 0.99,
            "fit_method": "segmented" if segment else "global",
            "model_func": lambda x: np.asarray(x, dtype=float) * 0 + 1.0,
        }

    monkeypatch.setattr(calibration, "fit_calibration_curve", fake_fit)

    result = calibration._fit_calibration_data(
        np.array([0.0, 20.0, 40.0, 60.0]),
        np.array([10.0, 11.0, 12.0, 13.0]),
        np.array([0.1, 0.1, 0.1, 0.1]),
        waveplate="hwp",
        basis="H",
        input_pol="H",
    )

    assert result["theta_0"] == 2.34
    assert result["fit_result"]["fit_method"] == "segmented"
    assert result["global_fit_result"]["theta_0"] == 2.345678
    assert result["global_fit_result"]["fit_method"] == "global"


def test_refit_cli_option_is_parsed() -> None:
    parser = ArgumentParser()
    parser.add_argument("cal_mode", choices=["hwp", "qwp"])
    _add_calibrate_args(parser)

    args = parser.parse_args([
        "hwp",
        "--refit",
        "stored.csv",
        "--estimated_theta_0",
        "-12.5",
        "--background",
        "20",
    ])

    assert args.cal_mode == "hwp"
    assert args.refit == "stored.csv"
    assert args.estimated_theta_0 == -12.5
    assert args.background == 20.0


def test_refit_save_config_option_is_parsed() -> None:
    parser = ArgumentParser()
    parser.add_argument("cal_mode", choices=["hwp", "qwp"])
    _add_calibrate_args(parser)

    args = parser.parse_args([
        "hwp",
        "--refit",
        "stored.csv",
        "--save_config",
    ])

    assert args.save_config is True


def test_cmd_calibrate_refit_does_not_initialize_controller(monkeypatch) -> None:
    called: dict[str, object] = {}

    class NoControllerAllowed:
        def __init__(self, *args, **kwargs):
            raise AssertionError("refit must not initialize MeasController")

    def fake_refit(path, **kwargs):
        called["path"] = path
        called["kwargs"] = kwargs
        return {"theta_0": 1.25}

    monkeypatch.setattr(calibrate_command, "MeasController", NoControllerAllowed)
    monkeypatch.setattr(calibrate_command, "refit_calibration", fake_refit)

    args = Namespace(
        cal_mode="hwp",
        refit="stored.csv",
        basis=None,
        input="H",
        wavelength=None,
        unit=None,
        export=None,
        no_export=False,
        plot=True,
        device=None,
        estimated_theta_0=-12.5,
        background=20.0,
        config=None,
    )
    calibrate_command.cmd_calibrate(args)

    assert called["path"] == "stored.csv"
    assert called["kwargs"]["waveplate"] == "hwp"
    assert called["kwargs"]["export"] is False
    assert called["kwargs"]["estimated_theta_0"] == -12.5
    assert called["kwargs"]["background"] == 20.0


def test_cmd_calibrate_refit_updates_config_when_save_config_present(
    tmp_path: Path,
    monkeypatch,
) -> None:
    called: dict[str, object] = {}

    def fake_refit(path, **kwargs):
        return {"theta_0": 1.25}

    def fake_save(result, cfg, **kwargs):
        called["result"] = result
        called["config_path"] = str(cfg.config_path)
        called["kwargs"] = kwargs
        return "SN-1550"

    monkeypatch.setattr(calibrate_command, "refit_calibration", fake_refit)
    monkeypatch.setattr(
        calibrate_command,
        "save_refit_calibration_config",
        fake_save,
    )

    config_path = tmp_path / "polmeas_config.yaml"
    args = Namespace(
        cal_mode="hwp",
        refit="stored.csv",
        basis=None,
        input="H",
        wavelength=None,
        unit=None,
        export=None,
        no_export=False,
        plot=True,
        device=None,
        estimated_theta_0=0.0,
        background=20.0,
        config=str(config_path),
        save_config=True,
    )

    calibrate_command.cmd_calibrate(args)

    assert called["config_path"] == str(config_path)
    assert called["kwargs"]["waveplate"] == "hwp"
    assert called["kwargs"]["detector"] == "stored-data"


def test_cmd_calibrate_refit_does_not_save_without_save_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_refit(path, **kwargs):
        return {"theta_0": 1.25}

    def fake_save(*args, **kwargs):
        raise AssertionError("save_config must be required for config updates")

    monkeypatch.setattr(calibrate_command, "refit_calibration", fake_refit)
    monkeypatch.setattr(
        calibrate_command,
        "save_refit_calibration_config",
        fake_save,
    )

    args = Namespace(
        cal_mode="hwp",
        refit="stored.csv",
        basis=None,
        input="H",
        wavelength=None,
        unit=None,
        export=None,
        no_export=False,
        plot=True,
        device=None,
        estimated_theta_0=0.0,
        background=20.0,
        config=str(tmp_path / "polmeas_config.yaml"),
        save_config=False,
    )

    calibrate_command.cmd_calibrate(args)


def test_plot_marks_h_basis_with_dashed_line(tmp_path: Path, monkeypatch) -> None:
    matplotlib = __import__("matplotlib")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.axes import Axes

    axvline_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    original_axvline = Axes.axvline

    def capture_axvline(self, *args, **kwargs):
        axvline_calls.append((args, kwargs))
        return original_axvline(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "axvline", capture_axvline)

    fit_result = {
        "theta_0": 10.0,
        "visibility": 0.8,
        "phi": np.pi,
        "r_squared": 0.99,
        "model_func": lambda x: np.asarray(x, dtype=float) * 0 + 1.0,
    }
    output = tmp_path / "plot.png"
    result = calibration._plot_calibration(
        np.array([0.0, 20.0, 40.0]),
        np.array([1.0, 2.0, 1.0]),
        np.array([0.1, np.nan, 0.1]),
        fit_result,
        "hwp",
        "stored-data",
        wavelength_nm=1550.0,
        unit="uW",
        output_path=output,
        waveplate="hwp",
    )

    assert result == str(output)
    assert output.exists()
    assert axvline_calls
    assert axvline_calls[0][0][0] == 10.0
    assert axvline_calls[0][1]["linestyle"] == "--"
    fig = plt.figure()
    plt.close(fig)


def test_default_calibration_plot_directory_is_cal_output(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_get_subdir_path(subdir: str, filename: str) -> str:
        captured["subdir"] = subdir
        return str(tmp_path / filename)

    monkeypatch.setattr(calibration, "get_subdir_path", fake_get_subdir_path)
    fit_result = {
        "theta_0": 0.0,
        "visibility": 0.8,
        "phi": np.pi,
        "r_squared": 0.99,
        "model_func": lambda x: np.asarray(x, dtype=float) * 0 + 1.0,
    }

    output = calibration._plot_calibration(
        np.array([0.0, 20.0, 40.0]),
        np.array([1.0, 2.0, 1.0]),
        np.array([0.1, 0.1, 0.1]),
        fit_result,
        "hwp",
        "stored-data",
        output_path=None,
    )

    assert captured["subdir"] == "cal_output"
    assert Path(output).exists()


def test_default_calibration_plot_name_avoids_collisions(tmp_path: Path, monkeypatch) -> None:
    created = {tmp_path / "calibration_hwp_bob_1560nm_20260803_000000.png"}

    def fake_get_subdir_path(subdir: str, filename: str) -> str:
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    for path in created:
        path.touch()
    monkeypatch.setattr(calibration, "get_subdir_path", fake_get_subdir_path)
    fit_result = {
        "theta_0": 0.0,
        "visibility": 0.8,
        "phi": np.pi,
        "r_squared": 0.99,
        "model_func": lambda x: np.asarray(x, dtype=float) * 0 + 1.0,
    }

    # Freeze the timestamp so the collision path is deterministic.
    class FrozenDatetime:
        @classmethod
        def now(cls):
            class Stamp:
                def strftime(self, fmt):
                    return "20260803_000000"

            return Stamp()

    monkeypatch.setattr(calibration, "_dt", FrozenDatetime)
    output = calibration._plot_calibration(
        np.array([0.0, 20.0, 40.0]),
        np.array([1.0, 2.0, 1.0]),
        np.array([0.1, 0.1, 0.1]),
        fit_result,
        "hwp",
        "stored-data",
        wavelength_nm=1560.0,
        unit="uW",
        device_name="bob",
        output_path=None,
    )

    assert Path(output).name == "calibration_hwp_bob_1560nm_20260803_000000_1.png"


def test_plot_shows_global_fit_params(tmp_path: Path, monkeypatch) -> None:
    matplotlib = __import__("matplotlib")
    matplotlib.use("Agg")
    from matplotlib.axes import Axes

    plot_labels: list[str] = []
    original_plot = Axes.plot

    def capture_plot(self, *args, **kwargs):
        label = kwargs.get("label")
        if label:
            plot_labels.append(label)
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "plot", capture_plot)

    fit_result = {
        "theta_0": 2.0,
        "visibility": 0.8,
        "phi": np.pi,
        "r_squared": 0.99,
        "model_func": lambda x: np.asarray(x, dtype=float) * 0 + 1.0,
    }
    global_fit_result = {
        "theta_0": 2.345678,
        "visibility": 0.9,
        "phi": np.pi,
        "r_squared": 0.999,
        "model_func": lambda x: np.asarray(x, dtype=float) * 0 + 1.1,
    }
    output = tmp_path / "plot.png"

    calibration._plot_calibration(
        np.array([0.0, 20.0, 40.0]),
        np.array([1.0, 2.0, 1.0]),
        np.array([0.1, 0.1, 0.1]),
        fit_result,
        "hwp",
        "stored-data",
        wavelength_nm=1550.0,
        unit="uW",
        output_path=output,
        waveplate="hwp",
        global_fit_result=global_fit_result,
    )

    assert output.exists()
    assert any(label.startswith("Global fit") for label in plot_labels)


def test_refit_uses_one_timestamp_for_csv_and_plot(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "cal.csv"
    _write_calibration_csv(path)
    timestamps: list[str | None] = []

    def fake_export(*args, timestamp=None, **kwargs):
        timestamps.append(timestamp)
        return str(tmp_path / f"calibration_{timestamp}.csv")

    def fake_plot(*args, timestamp=None, **kwargs):
        timestamps.append(timestamp)
        return str(tmp_path / f"calibration_{timestamp}.png")

    monkeypatch.setattr(calibration, "export_calibration_csv", fake_export)
    monkeypatch.setattr(calibration, "_plot_calibration", fake_plot)

    result = calibration.refit_calibration(path, export=True, plot=True)

    assert result["cal_file"].endswith(".csv")
    assert result["plot_file"].endswith(".png")
    assert len(timestamps) == 2
    assert timestamps[0] == timestamps[1]
    assert timestamps[0] is not None


def test_live_calibration_uses_one_timestamp_for_csv_and_plot(monkeypatch) -> None:
    fit_calls: dict[str, object] = {}
    timestamps: list[str | None] = []

    def fake_fit_data(angles, values, errors, **kwargs):
        fit_calls.update(kwargs)
        fit_result = {
            "theta_0": 1.0,
            "visibility": 0.8,
            "phi": np.pi,
            "r_squared": 0.99,
            "model_func": lambda x: np.asarray(x, dtype=float) * 0 + 1.0,
        }
        return {
            "theta_0": 1.0,
            "fast_axis": 1.0,
            "visibility": 0.8,
            "phi": np.pi,
            "r_squared": 0.99,
            "target_angles": {"H": 1.0},
            "fit_result": fit_result,
            "angles": np.asarray(angles),
            "values": np.asarray(values),
            "fitted_angles": np.asarray(angles),
            "fitted_values": np.asarray(values),
            "errors": np.asarray(errors),
        }

    def fake_export(*args, timestamp=None, **kwargs):
        timestamps.append(timestamp)
        return "cal.csv"

    def fake_plot(*args, timestamp=None, **kwargs):
        timestamps.append(timestamp)
        return "cal.png"

    class Measurement:
        value = 100.0
        error = 1.0
        unit = "uW"

    class MeasurementManager:
        def measure(self, **kwargs):
            return Measurement()

    class MotorManager:
        cfg = None

        def get_motor(self, target):
            return None

    monkeypatch.setattr(calibration, "_fit_calibration_data", fake_fit_data)
    monkeypatch.setattr(calibration, "export_calibration_csv", fake_export)
    monkeypatch.setattr(calibration, "_plot_calibration", fake_plot)

    result = calibration.run_calibration(
        "bob",
        motor_mgr=MotorManager(),
        meas_mgr=MeasurementManager(),
        start_angle=0.0,
        end_angle=5.0,
        step_angle=5.0,
        export=True,
        plot=True,
        estimated_theta_0=-10.0,
        background=20.0,
    )

    assert result["cal_file"] == "cal.csv"
    assert result["plot_file"] == "cal.png"
    assert len(timestamps) == 2
    assert timestamps[0] == timestamps[1]
    assert fit_calls["estimated_theta_0"] == -10.0
    assert fit_calls["background"] == 20.0
