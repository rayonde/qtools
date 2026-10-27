"""Run an acquisition and then display and save the histograms."""

# Check that packages below (zmq, subprocess, psutil, ...) are installed.
# Install the missing packages with the following command in an instance of cmd.exe, opened as admin user.
#   python.exe -m pip install "name of missing package"

import sys
import argparse
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from utils.common import connect, adjust_bin_width
from utils.acquisitions import acquire_histograms, save_histograms
from utils.plot import plot_histograms

logger = logging.getLogger(__name__)

#################################################################
#################   TO BE FILLED BY USER   ######################
#################################################################

# Default Time Controller IP address
DEFAULT_TC_ADDRESS = "169.254.99.1XX"

# Default acquisition duration in seconds
DEFAULT_ACQUISITION_DURATION = 1

# Default histogram bin count
DEFAULT_BIN_COUNT = 10

# Default histogram bin width (None = automatically set the lowest possible bin width)
DEFAULT_BIN_WIDTH = None

# Default file path where histograms are saved in CSV format (None = do not save)
DEFAULT_HISTOGRAMS_FILEPATH = None

# Default list of histograms to acquire
DEFAULT_HISTOGRAMS = [1, 2, 3, 4]

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None

#################################################################
#######################   MAIN FUNCTION   #######################
#################################################################


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration",
        type=float,
        help="acquisition duration",
        metavar=("SECONDS"),
        default=DEFAULT_ACQUISITION_DURATION,
    )
    parser.add_argument(
        "--address",
        type=str,
        help="Time Controller address",
        metavar=("IP"),
        default=DEFAULT_TC_ADDRESS,
    )
    parser.add_argument(
        "--bin-width",
        type=int,
        help="histograms bin width",
        metavar=("PS"),
        default=DEFAULT_BIN_WIDTH,
    )
    parser.add_argument(
        "--bin-count",
        type=int,
        help="histograms bin count",
        metavar=("PS"),
        default=DEFAULT_BIN_COUNT,
    )
    parser.add_argument(
        "--histograms",
        type=int,
        nargs="+",
        choices=(1, 2, 3, 4),
        help="hitograms to plot/save",
        metavar="NUM",
        default=DEFAULT_HISTOGRAMS,
    )
    parser.add_argument(
        "--save",
        type=str,
        help="save histograms in a csv file",
        metavar="FILEPATH",
        dest="histogram_filepath",
        default=DEFAULT_HISTOGRAMS_FILEPATH,
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

        bin_width = adjust_bin_width(tc, args.bin_width)

        histograms = acquire_histograms(
            tc, args.duration, bin_width, args.bin_count, args.histograms
        )

        if args.histogram_filepath:
            save_histograms(histograms, bin_width, args.histogram_filepath)

        plot_histograms(histograms, bin_width)

    except ConnectionError as e:
        logger.exception(e)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
