import os
import time
import logging
import matplotlib.pyplot as plt

from .utils import dlt_exec_device, scpi_exec_device, remove_suffix
from .const import (
    RAW_FORMATS,
    HISTO_FORMATS,
    HISTO_FORMAT_CSV,
    HISTO_FORMAT_PDF,
    ACQU_SIGNAL_GEN,
    INACTIVITY_TIMEOUT,
)
from .exceptions import AcquisitionError

logger = logging.getLogger(__package__)
logging.getLogger("matplotlib").setLevel(logging.ERROR)


def begin_acquisition_histo(devices):
    for device in devices.values():
        for i, _ in enumerate(device.get("histograms", {}).get("acquisitions", []), 1):
            scpi_exec_device(device, f"HIST{i}:FLUSh")


def get_filename_raw(device_name, input_pair, ext):
    ref, stop = input_pair
    return f"timestamps_{device_name}_{ref}-{stop}.{ext}"


def get_filename_histo(device_name, input_pair, ext):
    ref, stop = input_pair
    return f"histogram_{device_name}_{ref}-{stop}.{ext}"


def get_inputs(input_pairs):
    return {i for input_pairs in input_pairs for i in input_pairs if i != 0}


def clear_hires_errors(device):
    timestamps = device.get("timestamps", {}).get("acquisitions", [])
    histograms = device.get("histograms", {}).get("acquisitions", [])
    for i in get_inputs(timestamps + histograms):
        scpi_exec_device(device, f"INPUt{i}:HIREs:ERROr:CLEAr")


def get_hires_error(device, input_no):
    command = f"INPUt{input_no}:HIREs:ERROr?"
    error_code = int(scpi_exec_device(device, command))
    return f"{command} reports errors (code {error_code})." if error_code else None


def get_hires_errors(device, input_pair):
    errors = []
    if device.get("high_resolution"):
        inputs = (i for i in input_pair if i != 0)
        errors = (get_hires_error(device, i) for i in inputs)
    return [error for error in errors if error]


def get_raw_errors(device, raw_idx):
    """ Check if data was lost while transmitting the timestamps. """

    command = f"RAW{raw_idx}:ERRORS?"
    raw_errors = int(scpi_exec_device(device, command))
    if raw_errors:
        return [f"{command} reports {raw_errors} errors."]
    return []


def begin_acquisition_raw(devices, output_dir):
    for device_name, device in devices.items():
        for i, input_pair in enumerate(
            device.get("timestamps", {}).get("acquisitions", []), 1
        ):
            # Reset error counter
            scpi_exec_device(device, f"RAW{i}:ERRORS:CLEAR")

            # Tell the DataLink to start listening and store the timestamps in text format.
            # Command start-save arguments:
            #    address: Time Controller IP address
            #    channel: 1 <-> RAW1
            #             2 <-> RAW2
            #             3 <-> RAW3
            #             4 <-> RAW4
            #    filename: Timestamps file full or relative path.
            #    format:   "acsii" or "bin"
            ip = device.get("ip")
            fmt = device.get("timestamps").get("format")
            with_ref_idx = device.get("timestamps").get("with_ref_index")
            filename = get_filename_raw(device_name, input_pair, RAW_FORMATS[fmt])
            filepath = f"{output_dir / filename}"
            filepath_escaped = filepath.replace("\\", "\\\\")

            command = f'start-save --address {ip} --channel {i} --filename "{filepath_escaped}" --format {fmt}'
            if with_ref_idx:
                command += " --with-ref-index"
            answer = dlt_exec_device(device, command)

            device["acquisitions_id"] = device.get("acquisitions_id", {})
            device["acquisitions_id"][i] = answer["id"]

            # Start transfer of timestamps
            scpi_exec_device(device, f"RAW{i}:SEND ON")

            ref, stop = input_pair
            logger.info(
                f'Record timestamps {ref}-{stop} of {device_name} in "{filepath}"'
            )


def save_histogram_plot(filepath, histogram, bin_min, bin_width):
    # Compute bins time and filter empty bins to speedup plot rendering
    bins = {
        bin_min + i * bin_width: histo_bin
        for i, histo_bin in enumerate(histogram)
        if histo_bin != 0
    }
    bins = bins if bins else {bin_min: 0, bin_min + len(histogram) - 1: 0}
    xlim = bin_min + len(histogram) * bin_width
    ylim = max(bins.values())

    # Plot bins
    fig, _ = plt.subplots(1)
    fig.canvas.set_window_title("Histogram")
    plt.xlabel("ps")
    plt.xlim(0, max(1, xlim))
    plt.ylim(0, max(1, ylim))
    plt.stem(list(bins.keys()), list(bins.values()), markerfmt=" ", basefmt=" ")
    plt.savefig(filepath)


def save_histogram_csv(filepath, histogram):
    with open(filepath, "w") as file:
        file.write(";".join(str(i) for i in histogram))


def stop_datalink_acquisition(device, acqu_id):
    stop_answer = dlt_exec_device(device, f"stop {acqu_id}")
    status = stop_answer.get("status")
    return [
        f'DataLinkTarget error: {error.get("description")}'
        for error in status.get("errors")
    ]


def end_acquisition_histo(devices, output_dir):
    for device_name, device in devices.items():
        histograms = device.get("histograms", {})
        for i, input_pair in enumerate(histograms.get("acquisitions", []), 1):
            histogram = eval(scpi_exec_device(device, f"HIST{i}:DATA?", anslen=80))
            bin_min = eval(
                remove_suffix(scpi_exec_device(device, f"HIST{i}:MIN?"), "TB")
            )
            bin_width = eval(
                remove_suffix(scpi_exec_device(device, f"HIST{i}:BWID?"), "TB")
            )

            fmt = histograms.get("format")
            filename = get_filename_histo(device_name, input_pair, HISTO_FORMATS[fmt])
            filepath = output_dir / filename

            ref, stop = input_pair
            logger.info(f'Save histogram {ref}-{stop} of {device_name} in "{filepath}"')
            if fmt == HISTO_FORMAT_PDF:
                save_histogram_plot(filepath, histogram, bin_min, bin_width)
            elif fmt == HISTO_FORMAT_CSV:
                save_histogram_csv(filepath, histogram)

            # Check for hires errors
            errors = get_hires_errors(device, input_pair)
            if errors:
                logger.warning(
                    f"A data loss for {filename} occured with the following errors: \n  *"
                    + "\n  * ".join(errors)
                )


def end_acquisition_raw(devices):
    for device in devices.values():
        scpi_exec_device(device, f"REC:STOP")
        for i, _ in enumerate(device.get("timestamps", {}).get("acquisitions", []), 1):
            # Stop timestampes transfer
            scpi_exec_device(device, f"RAW{i}:SEND OFF")

    # Wait a while to let the DataLink receive the remaining timestamps
    time.sleep(1)

    for device_name, device in devices.items():
        timestamps = device.get("timestamps", {})
        acquisitions_id = device.get("acquisitions_id")

        if not acquisitions_id:
            continue

        for i, input_pair in enumerate(timestamps.get("acquisitions", []), 1):
            acqu_id = acquisitions_id[i]

            errors = stop_datalink_acquisition(device, acqu_id)
            errors += get_hires_errors(device, input_pair)
            errors += get_raw_errors(device, i)

            if errors:
                fmt = timestamps.get("format")
                filename = get_filename_raw(device_name, input_pair, RAW_FORMATS[fmt])
                logger.warning(
                    f"A data loss for {filename} occured with the following errors: \n  *"
                    + "\n  * ".join(errors)
                )


def begin_acquisition(devices, master, output_dir, duration):
    for device in devices.values():
        clear_hires_errors(device)

        # Arm the RECord generator and set the acquisition duration
        scpi_exec_device(device, f"REC:DUR {duration * 1e12};TRIG:ARM")

    begin_acquisition_histo(devices)
    begin_acquisition_raw(devices, output_dir)
    logger.info("Start of acquisition")

    # Send the acquisition trigger signal to start the acquisition
    scpi_exec_device(master, f"{ACQU_SIGNAL_GEN}:PLAY")


def end_acquisition(devices, output_dir):
    end_acquisition_raw(devices)
    if output_dir:
        end_acquisition_histo(devices, output_dir)
    logger.info("End of acquisition")


def wait_end_of_acquisition(devices, duration):
    acquisitions = (
        (device, acqu_id)
        for device in devices.values()
        for acqu_id in device.get("acquisitions_id", {}).values()
    )

    time.sleep(duration + 0.1)

    while True:
        for device, acqu_id in acquisitions:
            status = dlt_exec_device(device, f"status {acqu_id}")

            if status["acquisitions_count"] <= 0:
                break  # the acquisition is not over yet

            if (
                status.get("inactivity", status.get("seconds_since_last_activity"))
                < INACTIVITY_TIMEOUT
            ):
                break  # there's no inactivity timeout yet

            if not status["errors"]:
                break  # no error stopped the acquisition prematurely

        else:
            break  # all acquisitions are done

        time.sleep(1)


def cleanup_active_acquisitions(devices):

    for device in (device for device in devices.values() if device.get("dlt_socket")):
        try:
            acquisitions = dlt_exec_device(device, f"list")
            for acqu_id in acquisitions:
                dlt_exec_device(device, f"stop {acqu_id}")
        except:
            pass


def get_master_device(layout, devices):
    return devices.get(layout.get("device"))


def run(config, output_dir, duration):
    """ Run the multi-tc acquisition. """

    # Check that the target folder exists
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)

    devices, layout, _ = config
    master = get_master_device(layout, devices)

    try:
        begin_acquisition(devices, master, output_dir, duration)

        wait_end_of_acquisition(devices, duration)

        end_acquisition(devices, output_dir)

    except AcquisitionError as e:
        cleanup_active_acquisitions(devices)
        raise e from None


def stop(config, output_dir):
    """ Stop running acquisition. """
    if not config:
        return

    devices, _, _ = config
    try:
        end_acquisition(devices, output_dir)
    except AcquisitionError as e:
        cleanup_active_acquisitions(devices)
        raise e from None
