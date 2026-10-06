"""Run a streamed synchronized timestamps acquisition on multiple channels to merge and save them togather on the fly.

In a regular timestamps acquisition, the Time Controller send the measured timestamps :
    * when internal buffers are full (around 100-300 millions of timestamps)
    * when the acquisition is over

A synchronized timestamps acquisition ensure that the Time Controller sends them at regular interval
by running multiple sub-acquisitions.
Each sub-acquisition must be separated by a dead-time of at least 40 ns.
The sub-acquisition duration is set with:
    * the --sub-duration argument or 
    * the DEFAULT_SUB_ACQUISITION_DURATION constant

This example illustrates this mecanism by merging timestamps acquired from up to 4 channels.
The basic merging algorithm used here require timestamps without any reference signal.
This is acheived by configuring each channel # with the command: RAW#:REF:LINK NONE 
All timestamps are then referenced by the acquisition starting time.
This assumption allows the basic algorithm to simply sort the timestamp to merge them.

The script must be able to handle timestamps as fast as they arrive to prevent timestamps loss.
Process timestamp on-the-fly in the reception process would slow down the timestamp reception.

To prevent such slow down, the reception process (BufferStreamClient) is decoupled from the 
processing process (TimestampsMergerThread):
    * the channel BufferStreamClient only stores the received timestamps in a buffer.
    * the TimestampsMergerThread does the time consuming processing work for merging timestamps.

This way, reception is fast and let the TimestampsMergerThread merge timestamps at it own pace.

WARNING
-------
With a high (or even moderate) rate, timestamps might build up in the script buffers until there's 
no more memory. For high rate on the fly processing, consider another faster language than Python.

While running the script, monitor the buffers size (logged in console output) remain stable or are
constantly rising.
"""

import sys
import time
import array
import logging
import argparse
from pathlib import Path
from threading import Thread
from operator import itemgetter
from argparse import RawTextHelpFormatter

sys.path.append(str(Path(__file__).parent.parent))
from utils.common import connect, dlt_connect, zmq_exec, dlt_exec, DataLinkTargetError
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

# Merged timestamps file path
DEFAULT_OUTPUT_FILE = Path("C:/TEMP/timestamps.txt")

# Default acquisition duration in seconds
DEFAULT_ACQUISITION_DURATION = 3

# Default channels on which timestamps are acquired (possible range: 1-4)
DEFAULT_CHANNELS = [1, 2, 3, 4]

# Default duration of each sub-acquisitions in seconds (must be >= 0.2s)
#
# Note that the StreamClient will receive the timestamps:
#  - after this amount of time
#    OR
#  - after the DataLinkTarget Buffered more than 100M timestamps.
#
# Theirfore, avoid long sub-acquisition time with high stop signal frequency.
# Indeed, more than one message would be received per sub-acquisition period otherwise.
# (e.g. 10 seconds of sub-acquisitions with >10Mev/s on a channel would buffer more than 100M timestamps)
DEFAULT_SUB_ACQUISITION_DURATION = 1

# Dead time after each sub-acquisitions in seconds (must be >= 40ns)
DEAD_TIME = 40e-8

# Generate dummy timestamps on all channels
DEMO_MODE = True

# Default log file path where logging output is stored
DEFAULT_LOG_PATH = None

#################################################################
####################   UTILS FUNCTIONS   ########################
#################################################################


def format_size(size):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1000:
            break
        size /= 1000

    return "{0:.3f}".format(size).rstrip("0").rstrip(".") + " " + unit


class BufferStreamClient(StreamClient):
    def __init__(self, channel):

        self.port = 4241 + channel

        super().__init__(f"tcp://127.0.0.1:{self.port}")

        self.buffer = []
        self.number = channel

        def message_callback(message):
            # Store received timestamps to be processed by the TimestampsMergerThread
            self.buffer += (message,)
            received_timestamps = len(message) // 8

            buffered = sum(len(data) for data in self.buffer if data != None)
            msg_no = len(self.buffer)
            logger.info(
                f"[channel {channel}] buffering {received_timestamps} new timestamps from message #{msg_no} (buffered: {format_size(buffered)})"
            )

        self.message_callback = message_callback


class TimestampsMergerThread(Thread):
    """Merge togather referenceless timestamps bufferd by many streams."""

    def __init__(self, streams, timestamps_file, sub_acquisition_pper):
        Thread.__init__(self)
        self._streams = streams
        self._next_merge_message_idx = 0
        self._expect_more_timestamps = True
        self._file = open(timestamps_file, "w")
        self._total_timestamps = 0
        self._sub_acquisition_pper = sub_acquisition_pper

    def _total_buffered_bytes(self):
        return sum(
            len(data)
            for stream in self._streams
            for data in stream.buffer
            if data != None
        )

    def _merge_timestamps(self):
        timestamps_to_merge = []

        streams_with_buffer_ready = (
            stream
            for stream in self._streams
            if len(stream.buffer) > self._next_merge_message_idx
            and stream.buffer[self._next_merge_message_idx]
        )

        for stream in streams_with_buffer_ready:

            # Unpack timestamps
            timestamps = array.array("Q")
            timestamps.frombytes(stream.buffer[self._next_merge_message_idx])

            # Adjust timestamps value (which are reset at each start of sub-acquisition)
            timestamps = [
                int(
                    timestamp
                    + self._sub_acquisition_pper * self._next_merge_message_idx
                )
                for timestamp in timestamps
            ]

            timestamps_to_merge += ((stream.number, timestamps),)

            # Remove timestamps from stream buffer
            stream.buffer[self._next_merge_message_idx] = None

        # Merge timestamps of the same message index together
        merged_timestamps = (
            (channel, timestamp)
            for channel, channel_timestamps in timestamps_to_merge
            for timestamp in channel_timestamps
        )

        # Append merged timestamps to the file
        for channel, timestamp in sorted(merged_timestamps, key=itemgetter(1)):
            print(f"{channel};{timestamp}", file=self._file)
            self._total_timestamps += 1

        self._next_merge_message_idx += 1

        buffers_bytes = format_size(self._total_buffered_bytes())
        logger.info(
            f"Merged timestamps from message #{self._next_merge_message_idx} (total timestamps: {self._total_timestamps}, total buffered: {buffers_bytes})."
        )

    def _all_channels_buffer_ready(self):
        return all(
            self._next_merge_message_idx < len(stream.buffer)
            for stream in self._streams
        )

    def run(self):
        while self._expect_more_timestamps:

            logger.info("Wait for more timestamps to merge...")
            time.sleep(1)

            # Merge while there's timestamps available for merging
            while self._all_channels_buffer_ready():
                self._merge_timestamps()

        # If for some reason, a channel become unresponsive, merge other channels received
        # timestamps before leaving.
        while self._total_buffered_bytes() > 0:
            self._merge_timestamps()

    def join(self):
        self._expect_more_timestamps = False
        super().join()
        self._file.close()


def configure_dummy_timestamps(tc):

    zmq_exec(tc, "GEN1:ENAB ON;PPER 10000000;PWID 20000;PNUM INF;PLAY;TRIG:LINK NONE")
    zmq_exec(tc, "GEN2:ENAB ON;PPER 10000000;PWID 20000;PNUM INF;PLAY;TRIG:LINK NONE")
    zmq_exec(tc, "GEN3:ENAB ON;PPER 10000000;PWID 20000;PNUM INF;PLAY;TRIG:LINK NONE")
    zmq_exec(tc, "GEN4:ENAB ON;PPER 10000000;PWID 20000;PNUM INF;PLAY;TRIG:LINK NONE")

    zmq_exec(tc, "TSCO1:FIR:LINK GEN1")
    zmq_exec(tc, "TSCO1:OPIN ONLYFIR;OPOU ONLYFIR;WIND:ENAB OFF")
    zmq_exec(tc, "TSCO1:WIND:BEGI:LINK NONE;:TSCO1:WIND:END:LINK NONE")

    zmq_exec(tc, "TSCO2:FIR:LINK GEN2")
    zmq_exec(tc, "TSCO2:OPIN ONLYFIR;OPOU ONLYFIR;WIND:ENAB OFF")
    zmq_exec(tc, "TSCO2:WIND:BEGI:LINK NONE;:TSCO2:WIND:END:LINK NONE")

    zmq_exec(tc, "TSCO3:FIR:LINK GEN3")
    zmq_exec(tc, "TSCO3:OPIN ONLYFIR;OPOU ONLYFIR;WIND:ENAB OFF")
    zmq_exec(tc, "TSCO3:WIND:BEGI:LINK NONE;:TSCO3:WIND:END:LINK NONE")

    zmq_exec(tc, "TSCO4:FIR:LINK GEN4")
    zmq_exec(tc, "TSCO4:OPIN ONLYFIR;OPOU ONLYFIR;WIND:ENAB OFF")
    zmq_exec(tc, "TSCO4:WIND:BEGI:LINK NONE;:TSCO4:WIND:END:LINK NONE")

    zmq_exec(tc, "RAW1:STOP:LINK TSCO1;:RAW1:REF:LINK NONE")
    zmq_exec(tc, "RAW2:STOP:LINK TSCO2;:RAW2:REF:LINK NONE")
    zmq_exec(tc, "RAW3:STOP:LINK TSCO3;:RAW3:REF:LINK NONE")
    zmq_exec(tc, "RAW4:STOP:LINK TSCO4;:RAW4:REF:LINK NONE")


class ConfigurationError(Exception):
    pass


def configure_timestamps_references(tc, channels):
    """This example basic merging solution require timestamps to have no reference."""

    for ch in channels:
        zmq_exec(tc, f"RAW{ch}:REF:LINK NONE")


def open_timestamps_sync_stream(
    tc, dlt, tc_address, channels, output_file, sub_acquisition_pper
):
    acquisitions_id = {}
    clients = {}

    for channel in channels:
        # Reset error counter
        zmq_exec(tc, f"RAW{channel}:ERRORS:CLEAR")

        # start a stream client for each channel)
        clients[channel] = BufferStreamClient(channel)
        clients[channel].start()

        # Tell the DataLink to start listening for timestamps and stream them with ZMQ.
        # Command: start-stream --address <time controller ip> --channel <channel> --stream-port <port>
        #    channel: choose on between 1 to 4
        #    port:    port on which timestamps are streamed
        answer = dlt_exec(
            dlt,
            f"start-stream --address {tc_address} --channel {channel} --stream-port {clients[channel].port}",
        )
        acquisitions_id[channel] = answer.get("id")

        # Start transfer of timestamps
        zmq_exec(tc, f"RAW{channel}:SEND ON")

    # Start merging incoming timestamps
    merging_thread = TimestampsMergerThread(
        clients.values(), output_file, sub_acquisition_pper
    )
    merging_thread.start()

    return acquisitions_id, clients, merging_thread


def acquire_sync_streamed_timestamps(
    tc, dlt, tc_address, duration, sub_duration, channels, output_file
):
    success = False

    # Sub acquisition duration is the record pulse width
    pwid = int(1e12 * sub_duration)
    # Leave a required dead-time between sub-acquisitions
    pper = int(1e12 * (sub_duration + DEAD_TIME))

    ### Configure the acquisition timer

    # Trigger RECord signal manually (PLAY command)
    zmq_exec(tc, "REC:TRIG:ARM:MODE MANUal")
    # Enable the RECord generator
    zmq_exec(tc, "REC:ENABle ON")
    # STOP any already ongoing acquisition
    zmq_exec(tc, "REC:STOP")
    # Record an infinite number of sub-acquisition
    zmq_exec(tc, "REC:NUM INF")

    zmq_exec(tc, f"REC:PWID {pwid};PPER {pper}")

    merging_thread = None
    clients = []
    try:
        acquisitions_id, clients, merging_thread = open_timestamps_sync_stream(
            tc, dlt, tc_address, channels, output_file, pper
        )

        zmq_exec(tc, "REC:PLAY")  # Start the acquisition

        time.sleep(duration)

        zmq_exec(tc, "REC:STOP")  # Stop the acquisition

        wait_end_of_timestamps_acquisition(tc, dlt, acquisitions_id)

        success = close_timestamps_acquisition(tc, dlt, acquisitions_id)

    finally:
        # Wait for the streaming thread to finish
        for client in clients.values():
            client.join()

        # Wait for timestamps to be merged
        if merging_thread:
            merging_thread.join()

    return success


#################################################################
#######################   MAIN FUNCTION   #######################
#################################################################


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=RawTextHelpFormatter
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="acquisition total duration",
        metavar=("SECONDS"),
        default=DEFAULT_ACQUISITION_DURATION,
    )
    parser.add_argument(
        "--sub-duration",
        type=float,
        help="sub-acquisitions duration",
        metavar=("SECONDS"),
        default=DEFAULT_SUB_ACQUISITION_DURATION,
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
        "--output-file",
        type=Path,
        help="timestamps output file",
        metavar=("PATH"),
        default=DEFAULT_OUTPUT_FILE,
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
        dlt = dlt_connect(args.output_file.parent)

        close_active_acquisitions(dlt)

        if DEMO_MODE:
            configure_dummy_timestamps(tc)

        configure_timestamps_references(tc, args.channels)

        success = acquire_sync_streamed_timestamps(
            tc,
            dlt,
            args.address,
            args.duration,
            args.sub_duration,
            args.channels,
            args.output_file,
        )

    except (
        DataLinkTargetError,
        ConfigurationError,
        ConnectionError,
        NotADirectoryError,
    ) as e:
        logger.exception(e)
        success = False

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
