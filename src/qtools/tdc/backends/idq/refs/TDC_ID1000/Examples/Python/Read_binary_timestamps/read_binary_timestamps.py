"""Read a binary timestamps file, convert it into an ascii file and print the N first timestamps. """

# If the numpy library is missing, install it with th following command.
#   python.exe -m pip install numpy
import argparse
import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

#################################################################
#################   TO BE FILLED BY USER   ######################
#################################################################

# Path to the binary timestamps file to read
DEFAULT_BINARY_FILEPATH = "timestamps.bin"

# Convert binary timestamps file into this ascii file
DEFAULT_CONVERT_FILEPATH = "timestamps.txt"

# Print this number of timestamps
DEFAULT_NB_TIMESTAMPS_TO_PRINT = 10

# Tell whether or not the timestamp file contains reference indexes
DEFAULT_WITH_REF_INDEX = True

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None

#################################################################
####################   UTILS FUNCTIONS   ########################
#################################################################


def get_dtype(with_ref_index: bool):
    if with_ref_index:
        return np.dtype([("timestamp", np.uint64), ("refIndex", np.uint64)])
    else:
        return np.uint64


def read_binary_timestamps(filepath: str, with_ref_index: bool):
    dtype = get_dtype(with_ref_index)
    return np.fromfile(filepath, dtype=dtype)


def head(timestamps, n: int, with_ref_index: bool):
    for i, data in enumerate(timestamps, 1):
        if i > n:
            break

        if with_ref_index:
            timestamp, ref_index = data
            print(f"{i}) {timestamp} (ref: {ref_index})")
        else:
            timestamp = data
            print(f"{i}) {timestamp}")


def convert(timestamps, filepath, with_ref_index: bool):
    dtype = get_dtype(with_ref_index)
    fmt = "%s;%s" if with_ref_index else "%s"
    np.savetxt(filepath, timestamps.view(dtype), fmt=fmt)


#################################################################
#######################   MAIN FUNCTION   #######################
#################################################################


def main():

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=str,
        help="binary timestamps file",
        metavar="FILEPATH",
        dest="binary_filepath",
        default=DEFAULT_BINARY_FILEPATH,
    )
    parser.add_argument(
        "--convert",
        type=str,
        help="convert to ascii file",
        metavar="FILEPATH",
        dest="ascii_filepath",
        default=DEFAULT_CONVERT_FILEPATH,
    )
    parser.add_argument(
        "--head",
        type=int,
        help="print first N timestamps",
        metavar=("N"),
        default=DEFAULT_NB_TIMESTAMPS_TO_PRINT,
    )
    parser.add_argument(
        "--without-ref-index" if DEFAULT_WITH_REF_INDEX else "--with-ref-index",
        action="store_false" if DEFAULT_WITH_REF_INDEX else "store_true",
        dest="with_ref_index",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        help="store output in log file",
        metavar=("FULLPATH"),
        default=DEFAULT_LOG_PATH,
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        filename=args.log_path
    )

    timestamps = read_binary_timestamps(args.binary_filepath, args.with_ref_index)

    count = len(timestamps)

    logger.info(f"Read a total of {count} timestamp(s)")

    if args.head:
        logger.info(f"Print first {min(args.head, count)} timestamps")
        head(timestamps, args.head, args.with_ref_index)

    if args.ascii_filepath:
        convert(timestamps, args.ascii_filepath, args.with_ref_index)


if __name__ == "__main__":
    main()
