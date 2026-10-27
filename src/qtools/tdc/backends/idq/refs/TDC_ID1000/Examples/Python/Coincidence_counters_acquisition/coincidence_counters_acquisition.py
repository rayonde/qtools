"""Save input and coincidence counters values in a file each second."""

# Check that packages below are installed.
# Install the missing packages with the following command in an instance of cmd.exe, opened as admin user.
#   python.exe -m pip install "name of missing package"

# Python modules needed
import itertools
import os
import sys
import time
import logging
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from utils.acquisitions import coincidences
from utils.common import connect


logger = logging.getLogger(__name__)

#################################################################
#################   TO BE FILLED BY USER   ######################
#################################################################

# Time Controller default IP address
DEFAULT_TC_ADDRESS = "169.254.99.1XX"

# Default interval between counters acquisitions in seconds
DEFAULT_ACQUISITION_INTERVAL = 1

# Default acquisition total duration in seconds (0 or None = infinite)
DEFAULT_ACQUISITION_DURATION = None

# File path where histogram is saved in CSV format
DEFAULT_COUNTERS_FILEPATH = "counters.csv"

# Default coincidence window in ps
DEFAULT_COINCIDENCE_WINDOW = 10000

# Default coincidence window in ns (0 or None = endless accumulation of counts)
DEFAULT_COUNTERS_INTEGRATION_TIME = 1000

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None

#################################################################
####################   UTILS FUNCTIONS   ########################
#################################################################


def acquire_coincidence_counters(tc, filepath, interval, duration=None):

    with open(filepath, "w") as file:

        # Write counter names as first line of the file

        start_time = time.time()
        for i in itertools.count():

            # Acquire counters for the given duration or forever if no duration is provided
            if duration and (time.time() - start_time) >= duration:
                break

            # Gather counters
            counters_gathering_time = time.time()
            counters = coincidences.read_counts(tc)

            if i == 0:
                # write header on first iteration
                file.write(f"time;{';'.join(counters)}\n")


            counts_string = [
                str(counts) for counts in counters.values()
            ]

            # Save counters
            time_since_start = counters_gathering_time - start_time
            file.write(f"{time_since_start:.2f};{';'.join(counts_string)}\n")
            file.flush()

            # Wait for the given interval (minus the time it took to gather and save counters)
            wait_time = interval - (time.time() - counters_gathering_time)
            if wait_time > 0:
                time.sleep(wait_time)


#################################################################
#######################   MAIN FUNCTION   #######################
#################################################################


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval",
        type=float,
        help="interval between counters acquisitions",
        metavar=("SECONDS"),
        default=DEFAULT_ACQUISITION_INTERVAL,
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="acquisition total duration",
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
        "--file",
        type=str,
        help="save histograms in a csv file",
        metavar="FILEPATH",
        dest="counters_filepath",
        default=DEFAULT_COUNTERS_FILEPATH,
    )
    parser.add_argument(
        "--window",
        type=int,
        help="coincidence window in ps",
        metavar="PS",
        dest="coincidence_window",
        default=DEFAULT_COINCIDENCE_WINDOW,
    )
    parser.add_argument(
        "--integration",
        type=int,
        help="counter integration time in ns",
        metavar="NS",
        default=DEFAULT_COUNTERS_INTEGRATION_TIME,
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

        coincidences.configure(tc, args.coincidence_window, args.integration)

        # let counter gather some count after the TC has been configured
        if args.integration:
            integration_in_seconds = args.integration / 1000
            time.sleep(integration_in_seconds)
            if integration_in_seconds > args.interval:
                logger.warning(
                    "counter intergation time > counters acquisition interval. Script will record duplicated counter values."
                )

        message = f"recording counters into {os.path.realpath(args.counters_filepath)} every {args.interval} seconds"

        if args.duration:
            logger.info(f"{message} for {args.duration} seconds...\n")
        else:
            logger.info(f"{message} (press CTRL + C to stop)...\n")

        acquire_coincidence_counters(
            tc, args.counters_filepath, args.interval, args.duration
        )

    except KeyboardInterrupt:
        logger.info("Stop recording counters.")

    except ConnectionError as e:
        logger.exception(e)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
