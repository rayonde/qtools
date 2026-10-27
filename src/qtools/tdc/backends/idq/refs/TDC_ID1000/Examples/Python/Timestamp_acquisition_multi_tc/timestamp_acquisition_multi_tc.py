# Run an acquisition and saves the timestamps.

# Check that packages below (zmq, subprocess, psutil) are installed.
# Install the missing packages with the following command in an instance of cmd.exe, opened as admin user.
#   python.exe -m pip install "name of missing package"

import os
import sys
import logging
import argparse
from pathlib import Path

import multi_tc_acquisition
from multi_tc_acquisition import MY_DOCUMENTS, AcquisitionError

SCRIPT_DIR = Path(os.path.realpath(__file__)).parent

DEFAULT_CONF_FILENAME = "config.json"
DEFAULT_CONF_FILEPATH = str(SCRIPT_DIR / DEFAULT_CONF_FILENAME)
DEFAULT_OUTPUT_DIR = MY_DOCUMENTS
DEFAULT_ACQUISITION_TIME = 5
DEFAULT_DATALINK_DIR = Path(r"C:\Program Files\IDQ\Time Controller\packages\ScpiClient")
DEFAULT_LOG_FILENAME = f"{Path(__file__).stem}.log"
DEFAULT_LOG_FILEPATH = SCRIPT_DIR / DEFAULT_LOG_FILENAME


def dir_path(path):
    if not os.path.exists(path):
        os.makedirs(path)
    elif not os.path.isdir(path):
        raise NotADirectoryError(
            f"Unable to create directory, a file with the same name exist: {path}"
        )

    return Path(path)


def setup_logging(level):
    class NoExceptionFormatter(logging.Formatter):
        """
        Keep exception stack trace out of logs.
        Credits: https://stackoverflow.com/questions/6177520/python-logging-exc-info-only-for-file-handler 
        """

        def format(self, record):
            record.exc_text = ""  # ensure formatException gets called
            return super(NoExceptionFormatter, self).format(record)

        def formatException(self, record):
            return ""

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        NoExceptionFormatter(fmt="%(levelname)s: %(message)s", datefmt=None)
    )
    console_handler.setLevel(level)

    file_handler = logging.FileHandler(args.log)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(levelname)s: %(message)s", "%Y-%m-%d %H:%M:%S"
        )
    )
    file_handler.setLevel(logging.DEBUG)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--conf",
        metavar="file",
        type=argparse.FileType("r"),
        default=DEFAULT_CONF_FILEPATH,
        help=f"acquisition description file (default: {DEFAULT_CONF_FILENAME})",
    )
    parser.add_argument(
        "--datalink-dir",
        metavar="path",
        type=dir_path,
        default=DEFAULT_DATALINK_DIR,
        help=f"DataLinkTargetService.exe folder",
    )
    parser.add_argument(
        "--output-dir",
        metavar="path",
        type=dir_path,
        default=MY_DOCUMENTS,
        help=f"output folder",
    )
    parser.add_argument(
        "--duration",
        metavar="seconds",
        type=float,
        default=DEFAULT_ACQUISITION_TIME,
        help=f"acquisition duration (default: {DEFAULT_ACQUISITION_TIME})",
    )
    parser.add_argument(
        "--log",
        metavar="path",
        type=str,
        default=DEFAULT_LOG_FILEPATH,
        help=f"log file (default: {DEFAULT_LOG_FILENAME})",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    parser.add_argument(
        "-n",
        "--repeat",
        metavar="N",
        type=int,
        default=None,
        help=f"repeat measurments N times",
    )

    config = None
    output_dir = None
    try:
        args = parser.parse_args()
        setup_logging(logging.DEBUG if args.verbose else logging.INFO)

        config = multi_tc_acquisition.setup(args.conf, args.datalink_dir)

        if args.repeat:
            for i in range(1, args.repeat + 1):
                output_dir = args.output_dir / f"{i}"
                multi_tc_acquisition.run(config, output_dir, args.duration)
        else:
            output_dir = args.output_dir
            multi_tc_acquisition.run(config, output_dir, args.duration)

    except KeyboardInterrupt:
        multi_tc_acquisition.stop(config, output_dir)

    except AcquisitionError as e:
        multi_tc_acquisition.stop(config, output_dir)
        logging.exception(e)

    except Exception as e:
        multi_tc_acquisition.stop(config, output_dir)
        logging.exception(e)
        raise e from None
