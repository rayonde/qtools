"""Acquire up 1 input counts over time."""

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
    save_counts_over_time,
    COUNT_OVER_TIME_INPUTS,
)

from utils.plot import plot_histograms
from utils.consts import HIST_BWID_RANGE

logger = logging.getLogger(__name__)

import math
from typing import Dict, Any, Tuple, Iterable
from utils.common import zmq_exec, adjust_bin_width
from utils.acquisitions.counts_over_time import INPUT_TO_HIST_CHANNEL_BLOCK_MAP
from utils.acquisitions.histograms import acquire_histograms

#################################################################
#################   TO BE FILLED BY USER   ######################
#################################################################

# Default Time Controller IP address
DEFAULT_TC_ADDRESS = "169.254.99.1XX"

# Default acquisition time in ps
DEFAULT_ACQUISITION_TIME = 10000000000000

# Default file path where counts are saved in CSV format (None = do not save)
DEFAULT_COUNTS_FILEPATH = "input_counts.csv"

# Default counter integration time ps
DEFAULT_COUNTERS_INTEGRATION_TIME = 1000000000000

# Default input counts to acquire
DEFAULT_COUNTER = "1"

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None



#################################################################
#######################   MAIN FUNCTION   #######################
#################################################################

MAX_DELAY = 3600000000000
MAX_BIN_COUNT = 16384

REC_TO_HIST_REF = {
    1: ("GEN1", "TSCO9"),
    2: ("GEN2", "TSCO10"),
    3: ("GEN3", "TSCO11"),
    4: ("GEN4", "TSCO12"),
}


def setup_counts_over_long_time_acquisition(
    tc,
    integration_time: int,
    acquisition_time: int,
    counter_hist_stop_block: str,
) -> Tuple[Dict[int, Any], int]:

    hist_channel_timespan = integration_time * MAX_BIN_COUNT
    max_acquisition_time = hist_channel_timespan * len(REC_TO_HIST_REF)

    assert acquisition_time <= max_acquisition_time, f"acquisition time too long (max: {max_acquisition_time}): reduce it or increase integration time"

    hist_channels = []
    delay = 0
    for hist_channel in sorted(REC_TO_HIST_REF):
        gen, tsco = REC_TO_HIST_REF[hist_channel]

        assert delay < MAX_DELAY, "delay too long: reduce integration or acquisition time"
        if delay >= acquisition_time:
            break # no need for more histograms 

        zmq_exec(tc, f"{gen}:ENAB ON;PNUM 1;PPER 80000;PWID 40000;TRIG:DELA {delay};LINK REC;ARM:MODE AUTO")

        # Link RECord generator to its TSCO 
        zmq_exec(tc, f"{tsco}:FIR:LINK {gen}")
        # Set RECord TSCO to just forward the signal
        zmq_exec(tc, f"{tsco}:OPIN ONLYFIR;OPOUt ONLYFIR;WIND:ENAB OFF")

        # Link histogram REF to the REC TSCO configured above
        zmq_exec(tc, f"HIST{hist_channel}:REF:LINK {tsco}")

        if counter_hist_stop_block.startswith("TSCO"):
            zmq_exec(tc, f"{counter_hist_stop_block}:OPIN ONLYFIR;OPOUt ONLYFIR;WIND:ENAB OFF")

        # Link histogram STOP to the input channel TSCO
        zmq_exec(tc, f"HIST{hist_channel}:STOP:LINK {counter_hist_stop_block}")

        delay += (integration_time * MAX_BIN_COUNT)
        hist_channels.append(hist_channel)

    actual_integration_time = adjust_bin_width(tc, integration_time)
    
    return hist_channels, actual_integration_time



def setup_input_counts_over_long_time_acquisition(
    tc,
    integration_time: int,
    acquisition_time: int,
    counter: Any
):
    zmq_exec(tc, f"DEVIce:CONF:LOAD HISTO")

    return setup_counts_over_long_time_acquisition(
        tc,
        integration_time,
        acquisition_time,
        INPUT_TO_HIST_CHANNEL_BLOCK_MAP[counter],
    )

def acquire_counts_over_long_time(tc, integration_time: int, duration: int, hist_channels: Iterable[int]):
    histograms = acquire_histograms(
        tc, duration / 1e12, integration_time, MAX_BIN_COUNT, hist_channels
    )

    total_bins = math.ceil(duration / integration_time)

    counts = []
    for hist_channel in sorted(histograms):
        nb_bins = min(total_bins, MAX_BIN_COUNT)

        channel_counts = histograms[hist_channel]
        counts.extend(channel_counts[:nb_bins])

        total_bins -= nb_bins 

    counts_over_time = {"counts": counts}

    return counts_over_time


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--acquisition-time",
        type=int,
        help="total acquisition time",
        metavar=("PS"),
        default=DEFAULT_ACQUISITION_TIME,
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
        "--counter",
        type=str,
        choices=COUNT_OVER_TIME_INPUTS,
        help=f"input counts to acquire (choices {COUNT_OVER_TIME_INPUTS})",
        metavar="INPUT",
        default=DEFAULT_COUNTER,
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
        assert_arg_range("--integration", args.integration, HIST_BWID_RANGE)

        tc = connect(args.address)

        hist_channels, actual_integration_time = setup_input_counts_over_long_time_acquisition(
            tc, args.integration, args.acquisition_time, args.counter
        )

        if actual_integration_time != args.integration:
            logger.warning(
                f"counters integration time adjusted to {actual_integration_time}ps to work with the current resolution"
            )

        logger.info(
            f"acquire counts over {args.acquisition_time} ps"
        )

        counts = acquire_counts_over_long_time(
            tc,
            actual_integration_time,
            args.acquisition_time,
            hist_channels,
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
