"""Run a streamed timestamps acquisition and saves the timestamps."""

# This example is a good start to implement on-the-fly timestamps processing.

import sys
import argparse
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from utils.common import connect, zmq_exec, dlt_connect, DataLinkTargetError, dlt_exec
from utils.acquisitions import (
    close_active_acquisitions,
    wait_end_of_timestamps_acquisition,
    close_timestamps_acquisition,
    StreamClient,
)

logger = logging.getLogger(__name__)

#################################################################
#################   TO BE FILLED BY USER   ######################
#################################################################

# Folder of the "DataLinkTargetService.exe" executable on your computer.
# Once the GUI installed, you should find it there:
DLT_PATH = Path("C:/Program Files/IDQ/Time Controller/packages/ScpiClient")

# Default Time Controller IP address
DEFAULT_TC_ADDRESS = "169.254.99.1XX"

# Default acquisition duration in seconds
DEFAULT_ACQUISITION_DURATION = 1

# Default location where timestamps files are saved
DEFAULT_OUTPUT_PATH = Path("C:/Temp")

# Default channels on which timestamps are acquired (possible range: 1-4)
DEFAULT_CHANNELS = [1, 2, 3, 4]

# Include reference index
DEFAULT_WITH_REF_INDEX = True

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None

#################################################################
####################   UTILS FUNCTIONS   ########################
#################################################################


class WritterStreamClient(StreamClient):
    def __init__(self, addr, filename):
        super().__init__(addr)

        self.file = open(filename, "wb+")
        self.message_callback = lambda binary_ts: self.file.write(binary_ts)

    def run(self):
        super().run()
        self.file.close()


def open_timestamps_stream(tc, dlt, tc_address, channels, output_dir, with_ref_index):
    acquisitions_id = {}
    clients = {}

    for channel in channels:
        # Reset error counter
        zmq_exec(tc, f"RAW{channel}:ERRORS:CLEAR")

        filename = output_dir / f"timestamps_C{channel}.bin"

        # start a stream client for each channel)
        recv_port = 4241 + channel
        clients[channel] = WritterStreamClient(f"tcp://localhost:{recv_port}", filename)
        clients[channel].start()

        # Tell the DataLink to start listening and store the timestamps in text format.
        # Command: start-stream --address <time controller ip> --channel <channel> --stream-port <port>
        #    channel: choose on between 1 to 4
        #    port:    port on which timestamps are streamed
        command = f"start-stream --channel {channel} --address {tc_address} --stream-port {recv_port}"
        if with_ref_index:
            command += " --with-ref-index"
        answer = dlt_exec(dlt, command)

        acquisitions_id[channel] = answer["id"]

        # Start transfer of timestamps
        zmq_exec(tc, f"RAW{channel}:SEND ON")

    return acquisitions_id, clients


def acquire_streamed_timestamps(
    tc, dlt, tc_address, duration, channels, output_dir, with_ref_index
):
    ### Configure the acquisition timer

    # Trigger RECord signal manually (PLAY command)
    zmq_exec(tc, "REC:TRIG:ARM:MODE MANUal")
    # Enable the RECord generator
    zmq_exec(tc, "REC:ENABle ON")
    # STOP any already ongoing acquisition
    zmq_exec(tc, "REC:STOP")
    # Record a single acquisition
    zmq_exec(tc, "REC:NUM 1")
    # Record for the request duration (in ps)
    zmq_exec(tc, f"REC:DURation {duration * 1e12}")

    clients = []
    try:
        acquisitions_id, clients = open_timestamps_stream(
            tc, dlt, tc_address, channels, output_dir, with_ref_index
        )

        zmq_exec(tc, "REC:PLAY")  # Start the acquisition

        wait_end_of_timestamps_acquisition(tc, dlt, acquisitions_id)

        success = close_timestamps_acquisition(tc, dlt, acquisitions_id)

    finally:
        # wait for the streaming threads to finish
        for client in clients.values():
            client.join()

    return success


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
        "--channels",
        type=int,
        nargs="+",
        choices=(1, 2, 3, 4),
        help="hitograms to plot/save",
        metavar="NUM",
        default=DEFAULT_CHANNELS,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="timestamps output directory",
        metavar=("FULLPATH"),
        default=DEFAULT_OUTPUT_PATH,
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
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        filename=args.log_path
    )

    try:
        tc = connect(args.address)
        dlt = dlt_connect(args.output_dir)

        # Close any ongoing acquisition on the DataLinkTarget
        close_active_acquisitions(dlt)

        success = acquire_streamed_timestamps(
            tc,
            dlt,
            args.address,
            args.duration,
            args.channels,
            args.output_dir,
            args.with_ref_index,
        )

    except (DataLinkTargetError, ConnectionError, NotADirectoryError) as e:
        logger.exception(e)
        success = False

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
