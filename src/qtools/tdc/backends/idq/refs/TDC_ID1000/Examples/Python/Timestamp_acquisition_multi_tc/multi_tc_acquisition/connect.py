import os
import zmq
import socket
import logging
import subprocess
from pathlib import Path

from .exceptions import DataLinkConnexionError, ScpiConnexionError
from .const import MY_DOCUMENTS

SCPI_PORT = 5555
DLT_PORT = 6060

logger = logging.getLogger(__package__)


def check_host(address, port):
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((address, port))
        s.settimeout(None)
        return True
    except socket.error:
        return False


def connect_dlt(context, ip, device_name, datalink_dir):

    if not check_host(ip, DLT_PORT):
        if ip != "127.0.0.1" and ip != "localhost":
            raise DataLinkConnexionError(
                f"Unable to connect to remote DataLinkTarget service of device {device_name} (ip: {ip}, port: {DLT_PORT})."
            )
        else:
            logger.info("Starting DataLinkTarget service on local computer.")

            # Check that the executables folder exists
            if not os.path.isdir(datalink_dir):
                raise DataLinkConnexionError(
                    f'Path to the executables folder "{datalink_dir}" does not exist.'
                )

            # Build Datalink log configuration file
            script_path = Path(os.path.realpath(__file__)).parent
            log_conf_template = (
                datalink_dir / "config" / "DataLinkTargetService.log.conf"
            )
            log_conf = script_path / "DataLinkTargetService.log.conf"
            with open(log_conf, "w") as f:
                for line in open(log_conf_template, "r"):
                    f.write(
                        line.replace(
                            "log4cplus.appender.AppenderFile.File=",
                            f"log4cplus.appender.AppenderFile.File={script_path}{os.sep}",
                        )
                    )

            # Launch partner executables
            dlt_command = [str(datalink_dir / "DataLinkTargetService.exe")]
            dlt_command += ["-f", str(MY_DOCUMENTS)]
            dlt_command += ["--logconf", str(log_conf)]
            subprocess.Popen(dlt_command)

    # Create zmq socket and connect to the DataLink
    dlt_socket = context.socket(zmq.REQ)
    dlt_socket.connect(f"tcp://{ip}:{DLT_PORT}")

    return dlt_socket


def connect_scpi(context, ip, device_name):

    if not check_host(ip, SCPI_PORT):
        raise ScpiConnexionError(
            f"Unable to connect to device {device_name} (ip: {ip}, port: {SCPI_PORT})."
        )

    scpi_socket = context.socket(zmq.REQ)
    scpi_socket.connect(f"tcp://{ip}:{SCPI_PORT}")

    return scpi_socket


def connect_devices(devices, datalink_dir):

    context = zmq.Context()

    for device_name, device in devices.items():
        dlt_host = device.get("timestamps", {}).get("dlt_host")
        device["dlt_socket"] = connect_dlt(context, dlt_host, device_name, datalink_dir)

        ip = device.get("ip")
        device["scpi_socket"] = connect_scpi(context, ip, device_name)
