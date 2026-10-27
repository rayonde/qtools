"""Print inputs status."""

# Check that packages below (zmq, socket) are installed.
# Install the missing packages with the following command in an instance of cmd.exe, opened as admin user.
#   python.exe -m pip install "name of missing package"

import sys
import logging
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from utils.common import connect, zmq_exec

logger = logging.getLogger(__name__)

#################################################################
#################   TO BE FILLED BY USER   ######################
#################################################################

# Time Controller default IP address
DEFAULT_TC_ADDRESS = "169.254.99.1XX"

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None

#################################################################
####################   UTILS FUNCTIONS   ########################
#################################################################


def print_input_status(tc):
    INPUT_STATUS = {
        0: "OK",
        1: "Re-calibration required. Please execute DEVIce:SAMPling:RECAlibrate command.",
        2: "The count rate is above 25 Mhz, Please reduce the rate.",
        3: "Please reduce minimum time between two consecutive events.",
        4: "Please reduce minimum time between two consecutive events.",
        5: "The channel is disabled. Please restart the device.",
        1001: "Reduce signal rate, change the threshold or try to recalibrate (error 1001)",
        1002: "Reduce signal rate, change the threshold or try to recalibrate (error 1002)",
        1003: "Reduce signal rate, change the threshold or try to recalibrate (error 1003)",
    }

    high_resolution = zmq_exec(tc, f"DEVIce:RESolution?") == "HIRES"
    for input_no in range(0, 5):
        if high_resolution:
            block = "STARt" if input_no == 0 else f"INPU{input_no}"
            # Get last error code
            status = int(zmq_exec(tc, f"{block}:HIRES:ERROR?"))
            # Clear error
            zmq_exec(tc, f"{block}:HIRES:ERROR:CLEAR")
        else:
            status = 0  # OK

        input_name = "Start  " if input_no == 0 else f"Input {input_no}"
        status_description = INPUT_STATUS.get(status, f"Unknown error ({status}).")
        print(f"{input_name}: {status_description}")


#################################################################
#######################   MAIN FUNCTION   #######################
#################################################################


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--address",
        type=str,
        help="Time Controller address",
        metavar=("IP"),
        default=DEFAULT_TC_ADDRESS,
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        help="store output in log file",
        metavar=("FULLPATH"),
        default=DEFAULT_LOG_PATH,
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        filename=args.log_path
    )

    try:
        tc = connect(args.address)
        print_input_status(tc)
    except ConnectionError as e:
        logger.exception(e)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
