from .utils import scpi_exec_device
from .config import load_config
from .connect import connect_devices
from .const import (
    NUMERATOR_HR,
    NUMERATOR_HS,
    HIST_NONE_REF_TSCO,
    ACQU_SIGNAL_DELA,
    ACQU_SIGNAL_GEN,
    ACQU_SIGNAL_TSCO,
)


def get_input_tsco(channel):
    return f"TSCO{int(channel) + 4}"


def setup_device_inputs(device, resolution):
    for channel, channel_config in device.get("inputs").items():
        tsco = get_input_tsco(channel)
        dela = f"DELA{channel}"
        inpu = f"INPU{channel}"
        threshold = channel_config.get("threshold")
        delay_ps = channel_config.get("delay")
        edge = channel_config.get("edge")
        select = channel_config.get("select")
        scpi_exec_device(
            device,
            f"{inpu}:ENAB ON;COUP DC;EDGE {edge};THRE {threshold};SELE {select};RESY AUTO",
        )
        scpi_exec_device(device, f"{dela}:VALU {delay_ps};LINK {inpu}")
        scpi_exec_device(
            device,
            f"{tsco}:FIR:LINK {dela};:{tsco}:OPIN ONLYFIR;OPOUt ONLYFIR;WIND:ENAB OFF",
        )
    scpi_exec_device(device, f"DEVIce:RESolution {resolution}")


def setup_device_acquisitions(device, high_resolution):
    resolution, numerator = (
        ("HIRES", NUMERATOR_HR) if high_resolution else ("LOWRES", NUMERATOR_HS)
    )

    setup_device_inputs(device, resolution)

    if any(
        channel_ref == 0
        for channel_ref, _ in device.get("histograms", {}).get("acquisitions", [])
    ):
        scpi_exec_device(
            device,
            f"{HIST_NONE_REF_TSCO}:FIR:LINK REC;:{HIST_NONE_REF_TSCO}:OPIN ONLYFIR;OPOUt ONLYFIR;WIND:ENAB OFF",
        )

    # Setup histogram acquisitions
    for i, (channel_ref, channel_stop) in enumerate(
        device.get("histograms", {}).get("acquisitions", []), 1
    ):
        bwid = device.get("histograms", {}).get("bin_width")
        tsco_ref = (
            HIST_NONE_REF_TSCO if channel_ref == 0 else get_input_tsco(channel_ref)
        )
        tsco_stop = get_input_tsco(channel_stop)
        scpi_exec_device(
            device,
            f"HIST{i}:MIN 0;BWID {bwid};BCOUnt 16384;REF:LINK {tsco_ref};:HIST{i}:STOP:LINK {tsco_stop}",
        )

    # Setup timestamps acquisitions
    for i, (channel_ref, channel_stop) in enumerate(
        device.get("timestamps", {}).get("acquisitions", []), 1
    ):
        tsco_ref = "NONE" if channel_ref == 0 else get_input_tsco(channel_ref)
        tsco_stop = get_input_tsco(channel_stop)
        scpi_exec_device(
            device,
            f"RAW{i}:SEND OFF;NUMErator {numerator};DENOminator 1;REF:LINK {tsco_ref};:RAW{i}:STOP:LINK {tsco_stop}",
        )


def setup_device_custom_config(device):
    for config in device.get("config", []):
        scpi_exec_device(device, config)


def setup_devices_layout(layout, devices, high_resolution, level=0):
    device_name = layout.get("device")
    device = devices.get(device_name)

    # Setup STARt -> DELA8 -> REC trigger
    delay = device["trigger_delay"]
    scpi_exec_device(
        device, "STARt:ENAB ON;COUP DC;EDGE FALLing;THRE -0.400V;SELE UNSHaped"
    )
    scpi_exec_device(device, f"{ACQU_SIGNAL_DELA}:VALU 0;LINK STAR")
    scpi_exec_device(
        device,
        f"REC:ENAB OFF;TRIG:DELA {delay};LINK {ACQU_SIGNAL_DELA};ARM:MODE MANU;:REC:ENABle ON;NUM 1",
    )

    agents = layout.get("agents", {})
    agent_channels = list(agents.keys())
    if level == 0:
        # Setup acquisition signal trigger on master:
        #   ACQU_SIGNAL_GEN -> ACQU_SIGNAL_TSCO -> (OUTP1, OUTP#)
        # with # being the slaves output channels
        scpi_exec_device(
            device, f"{ACQU_SIGNAL_GEN}:TRIG:LINK NONE;DELA 0;ARM:MODE MANU"
        )
        scpi_exec_device(
            device, f"{ACQU_SIGNAL_GEN}:ENABle ON;STOP;PWID 1000000;PPER 1004000;PNUM 1"
        )
        scpi_exec_device(device, f"{ACQU_SIGNAL_TSCO}:FIR:LINK {ACQU_SIGNAL_GEN}")
        for channel in agent_channels + [1]:
            scpi_exec_device(device, f"OUTP{channel}:ENAB ON;LINK {ACQU_SIGNAL_TSCO}")
            scpi_exec_device(device, f"OUTP{channel}:PULS OFF")
        # Master Time Controller's clock is the reference for all other TC
        scpi_exec_device(device, f"DEVIce:SYNC INT")
    else:
        # Setup acquisition signal forwarng on agent:
        #  ACQU_SIGNAL_DELA -> TSCO# -> OUTP#
        # with # being the agent's agents output channels
        for channel in agent_channels:
            tsco = f"TSCO{channel}"
            scpi_exec_device(
                device,
                f"{tsco}:FIR:LINK {ACQU_SIGNAL_DELA};:{tsco}:OPIN ONLYFIR;OPOUt ONLYFIR;WIND:ENAB OFF",
            )
            scpi_exec_device(device, f"OUTP{channel}:ENAB ON;LINK {tsco}")
            scpi_exec_device(device, f"OUTP{channel}:PULS ON;PULS:WIDT 1000000")

        # Device clock is SYNC to another Time Controller (and ultimately to the master TC)
        scpi_exec_device(device, f"DEVIce:SYNC EXT")

    for agent_layout in agents.values():
        setup_devices_layout(agent_layout, devices, high_resolution, level + 1)

    setup_device_acquisitions(device, high_resolution)
    setup_device_custom_config(device)


def setup(config_file, datalink_dir):
    devices, layout, high_resolution = config = load_config(config_file)
    connect_devices(devices, datalink_dir)
    setup_devices_layout(layout, devices, high_resolution)

    return config
