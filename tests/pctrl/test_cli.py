import pytest
from unittest.mock import patch, MagicMock
from qtools.pctrl.repl import run_cli_interactive
from qtools.pctrl.backends import COMM_SUCCESS


def test_cli_new_commands(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
  servo_type: scs
channels:
  - path: "alice"
    wavelength: 1550
    servos:
      - name: "alice1550_qwp_1"
        group: "alice"
        servo_id: 1
        waveplate: "QWP"
        order: 1
        zero_position: 512
        deg_per_step: 0.293
        min_angle: -90.0
        max_angle: 90.0
"""
    config_file.write_text(config_content)

    # Mock inputs:
    # 1. reset
    # 2. torque off (which disables torque for ID 1)
    # 3. loops 1550 (which calculates loop counts)
    # 4. exit
    inputs = ["reset", "torque off", "loops 1550", "exit"]

    mock_backend = MagicMock()
    mock_backend.ReadPosSpeed.return_value = (512, 0, COMM_SUCCESS, 0)
    mock_backend.write1ByteTxRx.return_value = COMM_SUCCESS
    mock_backend.port_handler = MagicMock()
    mock_backend.is_open = True
    mock_backend.list_servos.return_value = [1]
    mock_backend.lock.return_value = True
    mock_backend.release.return_value = True
    mock_backend.WritePosEx.return_value = (0, 0)
    mock_backend.move.return_value = (0, 0)

    with patch("builtins.input", side_effect=inputs), \
         patch("qtools.pctrl.servo_manager.ServoBackend", return_value=mock_backend), \
         patch("qtools.pctrl.utils.ServoBackend", return_value=mock_backend):
        run_cli_interactive(str(config_file), mock=True)

        # Reset should write middle position
        assert mock_backend.WritePosEx.called or mock_backend.move.called
        # Torque off should release
        assert mock_backend.release.called


def test_cli_startup(tmp_path):
    config_file = tmp_path / "polarization_config.yaml"
    # Empty channels list to test auto setup-wizard trigger
    config_content = """
connection:
  port: "COM_FAKE"
  baudrate: 1000000
channels: []
"""
    config_file.write_text(config_content)

    inputs = ["exit"]
    with patch("builtins.input", side_effect=inputs), \
         patch("qtools.pctrl.repl.run_setup") as mock_setup, \
         patch("qtools.pctrl.repl.ServoManager") as MockMgr:
        mock_mgr = MagicMock()
        mock_mgr.backend = MagicMock()
        mock_mgr.backend.port_handler = MagicMock()
        mock_mgr.mock_mode = True
        MockMgr.return_value = mock_mgr

        run_cli_interactive(str(config_file), mock=True)

        # Setup should be called because channels list is empty
        assert mock_setup.called
        # Disconnect should be called on exit
        assert mock_mgr.disconnect.called


def test_cli_subcommands_dispatch(tmp_path):
    from qtools.pctrl.cli import main

    config_file = tmp_path / "polarization_config.yaml"
    config_file.write_text("connection:\n  port: COM_FAKE\n  baudrate: 1000000\nchannels: []")

    with patch("sys.argv", ["pctrl", "-c", str(config_file), "status"]), \
         patch("qtools.pctrl.utils.run_status") as mock_status:
        main()
        assert mock_status.called

    with patch("sys.argv", ["pctrl", "-c", str(config_file), "reset", "alice"]), \
         patch("qtools.pctrl.utils.run_reset") as mock_reset:
        main()
        mock_reset.assert_called_once_with(
            config=str(config_file),
            port=None,
            baud=1000000,
            speed_deg_s=None,
            target="alice",
            servo_type=None,
            mock=False,
        )

    with patch("sys.argv", ["pctrl", "-c", str(config_file), "set", "alice_qwp_1", "45.0"]), \
         patch("qtools.pctrl.utils.run_direct_set") as mock_set:
        main()
        mock_set.assert_called_once_with(
            config=str(config_file),
            set_str="alice_qwp_1:45.0",
            speed_deg_s=None,
            port=None,
            baud=1000000,
            servo_type=None,
            mock=False,
            encode=False,
            accurate=False,
        )

    # Test status target positional parameter
    with patch("sys.argv", ["pctrl", "-c", str(config_file), "status", "COM3"]), \
         patch("qtools.pctrl.utils.run_status") as mock_status:
        main()
        mock_status.assert_called_once_with(
            config=str(config_file),
            port=None,
            baud=1000000,
            target="COM3",
            servo_type=None,
            mock=False,
        )

    # Test set multiple targets and angles
    with patch("sys.argv", ["pctrl", "-c", str(config_file), "set", "1,2,3", "45,90,135"]), \
         patch("qtools.pctrl.utils.run_direct_set") as mock_set_multi:
        main()
        mock_set_multi.assert_called_once_with(
            config=str(config_file),
            set_str="1:45,2:90,3:135",
            speed_deg_s=None,
            port=None,
            baud=1000000,
            servo_type=None,
            mock=False,
            encode=False,
            accurate=False,
        )

    # Test set-zero command routing
    with patch("sys.argv", ["pctrl", "-c", str(config_file), "set-zero", "alice"]), \
         patch("qtools.pctrl.utils.run_set_middle") as mock_zero:
        main()
        mock_zero.assert_called_once_with(
            config=str(config_file),
            target="alice",
            port=None,
            baud=1000000,
            servo_type=None,
            mock=False,
        )

    # Test limit command routing
    with patch("sys.argv", ["pctrl", "-c", str(config_file), "limit", "alice", "-45.0", "45.0"]), \
         patch("qtools.pctrl.utils.run_limit") as mock_limit:
        main()
        mock_limit.assert_called_once_with(
            config=str(config_file),
            target="alice",
            min_angle=-45.0,
            max_angle=45.0,
            port=None,
            baud=1000000,
            servo_type=None,
            mock=False,
        )

    # Test device command routing
    with patch("sys.argv", ["pctrl", "-c", str(config_file), "device", "tdc", "COM4"]), \
         patch("qtools.pctrl.utils.run_device_subcommand") as mock_device:
        main()
        mock_device.assert_called_once_with(
            config=str(config_file),
            device_type="tdc",
            device_args=["COM4"],
            mock=False,
        )

    # Test --mock is forwarded
    with patch("sys.argv", ["pctrl", "--mock", "-c", str(config_file), "list"]), \
         patch("qtools.pctrl.utils.run_list") as mock_list:
        main()
        assert mock_list.call_args.kwargs.get("mock") is True
