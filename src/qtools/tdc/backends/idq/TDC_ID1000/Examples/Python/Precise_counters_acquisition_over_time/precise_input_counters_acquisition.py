"""Acquire up to 4 input counts over time."""

# Check that packages below (zmq, subprocess, psutil, ...) are installed.
# Install the missing packages with the following command in an instance of cmd.exe, opened as admin user.
#   python.exe -m pip install "name of missing package"

import sys
import argparse
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from utils.common import connect, assert_arg_range
from utils.acquisitions import (
    setup_input_counts_over_time_acquisition,
    acquire_counts_over_time,
    save_counts_over_time,
    COUNT_OVER_TIME_INPUTS,
)
from utils.plot import plot_histograms
from utils.consts import HIST_BCOU_RANGE, HIST_BWID_RANGE

logger = logging.getLogger(__name__)

#################################################################
#################   TO BE FILLED BY USER   ######################
#################################################################

# Default Time Controller IP address
DEFAULT_TC_ADDRESS = "169.254.99.1XX"

# Default number of counter acquisitions
DEFAULT_NUMBER_OF_ACQUISITIONS = 10

# Default file path where counts are saved in CSV format (None = do not save)
DEFAULT_COUNTS_FILEPATH = "input_counts.csv"

# Default counter integration time ps
DEFAULT_COUNTERS_INTEGRATION_TIME = 1000000000000

# Default list of input counts to acquire
DEFAULT_COUNTERS = ["1", "2", "3", "4"]

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None


#################################################################
#######################   MAIN FUNCTION   #######################
#################################################################


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acquisitions",
        type=int,
        help="number of counter acquisitions",
        metavar=("N"),
        default=DEFAULT_NUMBER_OF_ACQUISITIONS,
    )
    parser.add_argument(
        "--address",
        type=str,
        help="Time Controller address",
        metavar=("IP"),
        default=DEFAULT_TC_ADDRESS,
    )
    parser.add_argument(
        "--integration",
        type=int,
        help="counter integration time in ps",
        metavar="PS",
        default=DEFAULT_COUNTERS_INTEGRATION_TIME,
    )
    parser.add_argument(
        "--counters",
        type=str,
        nargs="+",
        choices=COUNT_OVER_TIME_INPUTS,
        help=f"input counts to acquire (choices {COUNT_OVER_TIME_INPUTS})",
        metavar="INPUT",
        default=DEFAULT_COUNTERS,
    )
    parser.add_argument(
        "--save",
        type=str,
        help="save counter trace in a csv file",
        metavar="FILEPATH",
        dest="counts_filepath",
        default=DEFAULT_COUNTS_FILEPATH,
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
        assert len(args.counters) <= 4, "Select at most 4 input channels to acquire"
        assert_arg_range("--acquisitions", args.acquisitions, HIST_BCOU_RANGE)
        assert_arg_range("--integration", args.integration, HIST_BWID_RANGE)

        tc = connect(args.address)

        hist_to_counter_map, actual_integration_time = setup_input_counts_over_time_acquisition(
            tc, args.integration, args.counters
        )

        if actual_integration_time != args.integration:
            logger.warning(
                f"counters integration time adjusted to {actual_integration_time}ps to work with the current resolution"
            )

        logger.info(
            f"acquire {args.acquisitions} individual counts over {args.acquisitions * actual_integration_time} ps"
        )

        counts = acquire_counts_over_time(
            tc,
            actual_integration_time,
            args.acquisitions,
            hist_to_counter_map,
        )
        
        if args.counts_filepath:
            save_counts_over_time(
                counts,
                actual_integration_time,
                args.counts_filepath,
            )

        plot_histograms(
            counts,
            actual_integration_time,
            title="Input counts over time",
        )
        
    except AssertionError as e:
        logger.error(e)
        sys.exit(1)

    except ConnectionError as e:
        logger.exception(e)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
