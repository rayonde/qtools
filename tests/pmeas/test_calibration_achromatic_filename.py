from unittest.mock import MagicMock, patch

from qtools.pmeas.calibration import _scan_single_wavelength


def test_achromatic_csv_filename_includes_motor_name(tmp_path) -> None:
    result = {
        "phi": 0.1,
        "theta_0": 1.0,
        "visibility": 0.9,
        "angles": [],
        "values": [],
        "errors": [],
        "fit_result": {},
        "unit": "cps",
        "device_name": "alice_hwp",
    }

    with patch("qtools.pmeas.calibration.run_calibration", return_value=result):
        with patch("qtools.pmeas.calibration.export_calibration_csv") as export_csv:
            entry = _scan_single_wavelength(
                target="alice",
                wl=1550.0,
                role="hwp",
                controller=MagicMock(),
                channel=0,
                meas_type="singles",
                duration=1.0,
                repetitions=1,
                start_angle=0.0,
                end_angle=180.0,
                step_angle=30.0,
                detector_type="tdc",
                basis="H",
                input_pol="H",
                export=True,
                export_path=None,
                plot=False,
                unit=None,
                out_dir=tmp_path,
            )

    assert "alice_hwp" in entry["csv_file"]
    export_csv.assert_called_once()
