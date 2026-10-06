"""Run an histogram acquisition and filter stop event within in window after the start.

For a demonstration, run with DEMO_MODE = True. Dummy signals are then generated
on input 1, 2 and 3 (no wire required).

For a real measurement, set DEMO_MODE = False and connect the following inputs:
  - INPUT1 (start)
  - INPUT2 (stop)
  - INPUT3 (trigger)
"""

import sys
import logging
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from utils.common import connect, zmq_exec, adjust_bin_width
from utils.acquisitions import acquire_histograms, save_histograms
from utils.plot import plot_histograms

logger = logging.getLogger(__name__)

#################################################################
#################   TO BE FILLED BY USER   ######################
#################################################################

# Default Time Controller IP address
DEFAULT_TC_ADDRESS = "169.254.99.1XX"

# Default acquisition duration in seconds
DEFAULT_ACQUISITION_DURATION = 3

# Default delay (in ps) to open the window after the tigger
DEFAULT_WINDOW_DELAY = 100000

# Default duration (in ps) of the opened window
DEFAULT_WINDOW_DURATION = 500000

# Default bin_width (None = automatically set the lowest possible bin width)
DEFAULT_BIN_WIDTH = None

# Generate dummy signals on all inputs (no wire required)
DEMO_MODE = True

# Default file path where histograms are saved in CSV format (None = do not save)
DEFAULT_HISTOGRAMS_FILEPATH = None

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None

#################################################################
####################   UTILS FUNCTIONS   ########################
#################################################################


def configure_filtering(tc, window_delay, window_duration):
    # Configure input1 -> delay1 -> tsco5 (no filtering)
    zmq_exec(tc, "INPU1:ENAB ON;THRE -0.4V;COUP DC;EDGE FALLING;SELE UNSHAPED")
    zmq_exec(tc, "DELA1:VALUe 0;LINK INPU1")
    zmq_exec(tc, "TSCO5:WIND:ENAB OFF;:TSCO5:FIR:LINK DELA1;:TSCO5:OPOUt ONLYFIR")

    # Configure input2 -> delay2 -> tsco6 (without filtering)
    #                            -> tsco7 (with filtering)
    #           input3 -> delay3 -> tsco7 (as filter trigger)

    # input1 -> delay2
    zmq_exec(tc, "INPU2:ENAB ON;THRE -0.4V;COUP DC;EDGE FALLING;SELE UNSHAPED")
    zmq_exec(tc, "DELA2:VALUe 0;LINK INPU2")

    # input3 -> delay3
    zmq_exec(tc, "INPU3:ENAB ON;THRE -0.4V;COUP DC;EDGE FALLING;SELE UNSHAPED")
    zmq_exec(tc, "DELA3:VALUe 0;LINK INPU3")

    # delay2 -> tsco6 (no filtering)
    zmq_exec(tc, "TSCO6:WIND:ENAB OFF;:TSCO6:FIR:LINK DELA2;:TSCO6:OPOUt ONLYFIR")

    # delay2 -> tsco7 (with filtering)
    zmq_exec(tc, "TSCO7:WIND:ENAB ON;:TSCO7:FIR:LINK DELA2")
    # Setup when the window starts ('window_delay' ps after a rising edge event on INPU3)
    zmq_exec(tc, f"TSCO7:WIND:BEGI:LINK DELA3;DELAY {window_delay};EDGE RISING")
    # Setup when the window ends ('window_duration' ps after a rising edge event on INPU3)
    end_delay = window_delay + window_duration
    zmq_exec(tc, f"TSCO7:WIND:END:LINK DELA3;DELAY {end_delay};EDGE RISING")
    # Setup what the window does (let the signal from INPU2 through only inside the window)
    zmq_exec(tc, "TSCO7:OPIN ONLYFIR;:TSCO7:OPOUt MUTE")

    # histogram1: input1 as start (tsco5) and unfiltered input2 as stop (tsco6)
    zmq_exec(tc, "HIST1:REF:LINK TSCO5;:HIST1:STOP:LINK TSCO6")

    # histogram2: input1 as start (tsco5) and filtered input2 as stop (tsco7)
    zmq_exec(tc, "HIST2:REF:LINK TSCO5;:HIST2:STOP:LINK TSCO7")


def configure_dummy_signals(tc):
    ## Configure start signal (trigger) and link it to both output 1 and 3
    zmq_exec(tc, "GEN1:ENAB OFF")
    zmq_exec(tc, "GEN1:PPER 4000000;PWID 4000;PNUM INF;TRIG:ARM:MODE MANUal")
    zmq_exec(tc, "GEN1:ENAB ON;PLAY")

    zmq_exec(tc, "TSCO1:WIND:ENAB OFF;:TSCO1:FIR:LINK GEN1;:TSCO1:OPOUt ONLYFIR")
    zmq_exec(tc, "OUTP1:ENAB ON;MODE NIM;LINK TSCO1")

    ## Configure stop signal and link it to output 2
    zmq_exec(tc, "GEN2:ENAB OFF")
    zmq_exec(tc, "GEN2:PPER 4000100;PWID 4000;PNUM INF;TRIG:ARM:MODE MANUal")
    zmq_exec(tc, "GEN2:ENAB ON;PLAY")
    zmq_exec(tc, "TSCO2:WIND:ENAB OFF;:TSCO2:FIR:LINK GEN2;:TSCO2:OPOUt ONLYFIR")
    zmq_exec(tc, "OUTP2:ENAB ON;MODE NIM;LINK TSCO2")

    zmq_exec(tc, "OUTP3:ENAB ON;MODE NIM;LINK TSCO1")  # output start as trigger signal

    zmq_exec(tc, "INPU1:SELE OUTP")
    zmq_exec(tc, "INPU2:SELE OUTP")
    zmq_exec(tc, "INPU3:SELE OUTP")


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
        "--window-delay",
        type=int,
        help="delay before the window is opened after a trigger event",
        metavar=("PS"),
        default=DEFAULT_WINDOW_DELAY,
    )
    parser.add_argument(
        "--window-duration",
        type=int,
        help="duration of the window",
        metavar=("PS"),
        default=DEFAULT_WINDOW_DURATION,
    )
    parser.add_argument(
        "--bin-width",
        type=int,
        help="histograms bin width",
        metavar=("PS"),
        default=DEFAULT_BIN_WIDTH,
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

        configure_filtering(tc, args.window_delay, args.window_duration)

        if DEMO_MODE:
            configure_dummy_signals(tc)

        bin_width = adjust_bin_width(tc, args.bin_width)

        histograms = acquire_histograms(tc, args.duration, bin_width, 16384, [1, 2])

        if args.histogram_filepath:
            save_histograms(histograms, bin_width, args.histogram_filepath)

        plot_histograms(histograms, bin_width)

    except ConnectionError as e:
        logger.exception(e)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
