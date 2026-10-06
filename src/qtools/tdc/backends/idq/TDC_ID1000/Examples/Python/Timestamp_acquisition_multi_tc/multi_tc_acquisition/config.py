from pathlib import Path
import json
import logging
import jsonschema

from .const import LATENCY_HS, GEN_DELAY_MIN, GEN_DELAY_MAX
from .exceptions import ConfigurationError, ConfigurationPropertyError

logger = logging.getLogger(__package__)


def get_layout_devices(layout):
    devices_names = [layout.get("device")]

    for agent_layout in layout.get("agents", {}).values():
        devices_names += get_layout_devices(agent_layout)

    return devices_names


def check_acquisitions_inputs(devices, device_name, acquisition_type):
    device = devices.get(device_name, {})
    device_inputs = device.get("inputs")
    acquisitions_inputs = device.get(acquisition_type, {}).get("acquisitions", [])
    for input_no in (
        input_no for start_stop in acquisitions_inputs for input_no in start_stop
    ):
        if input_no != 0 and str(input_no) not in device_inputs:
            property_inputs = ["devices", device_name, "inputs"]
            property_acquisitions = [
                "devices",
                device_name,
                acquisition_type,
                "acquisitions",
            ]
            properites = (property_inputs, property_acquisitions)
            raise ConfigurationPropertyError(
                f"Device {device_name} use unconfigured input {input_no} for its {acquisition_type} acquisition.",
                properites,
            )


def check_device_acquisitions(devices, device_name):
    timestamps = devices.get(device_name, {}).get("timestamps", {})
    histograms = devices.get(device_name, {}).get("histograms", {})

    if not (timestamps or histograms):
        logger.warning(
            f"No acquisition defined (timestamps nor histograms) for device {device_name}."
        )
    else:
        check_acquisitions_inputs(devices, device_name, "timestamps")
        check_acquisitions_inputs(devices, device_name, "histograms")


def check_devices_duplicated(devices):
    devices_names = list(devices.keys())
    for device_name_1, device in devices.items():
        devices_names.remove(device_name_1)
        for device_name_2 in devices_names:
            if device.get("ip") == devices[device_name_2].get("ip"):
                property1_path = ["devices", device_name_1, "ip"]
                property2_path = ["devices", device_name_2, "ip"]
                properties_path = (property1_path, property2_path)
                raise ConfigurationPropertyError(
                    f'Device "{device_name_1}" and "{device_name_2}" share the same IP address.',
                    properties_path,
                )


def check_devices(devices):
    for device_name in devices.keys():
        check_device_acquisitions(devices, device_name)
    check_devices_duplicated(devices)


def check_layout(layout, devices, is_master=True, layout_path=["layout"]):
    name = layout.get("device")

    if name not in devices.keys():
        property_path = layout_path + ["device"]
        raise ConfigurationPropertyError(
            f"Device {name} from layout is undefined in devices list.", property_path
        )

    agents = layout.get("agents", {})

    for channel, agent_layout in agents.items():
        if is_master and channel == "1":
            property_path = layout_path + ["agents", channel]
            raise ConfigurationPropertyError(
                f"Device {name} is master and its output channel 1 cannot connect any agent but must be connected to its own START input.",
                property_path,
            )
        else:
            check_layout(agent_layout, devices, False, layout_path + [channel])


def compute_propagation_time(layout, devices, level=0, propagation_time=None):
    """
    Compute the acquisition trigger signal propagation_time of each device and 
    return the max propagation_time of the whole layout.
    """

    device_name = layout.get("device")
    device = devices.get(device_name)

    # Compute the device propagation time
    wire_latency = layout.get("wire_latency")
    if level < 2:
        propagation_time = wire_latency
    else:
        propagation_time += (
            wire_latency + LATENCY_HS
        )  # Start input is always in HS mode

    # Save the device propagation time and initialize p_max
    p_max = device["propagation_time"] = propagation_time

    # Compute agents propagation time and the while layout max propagation time
    for agent_layout in layout.get("agents", {}).values():
        p = compute_propagation_time(agent_layout, devices, level + 1, propagation_time)
        p_max = max(p_max, p)

    return p_max


def compute_devices_trigger_delay(layout, devices):
    p_max = compute_propagation_time(layout, devices)

    # Compute device trigger delay
    for device in devices.values():
        device["trigger_delay"] = p_max - device["propagation_time"]

    # It's impossible to apply a trigger delay strictly between 0 and GEN_DELAY_MIN
    if any(0 < device["trigger_delay"] < GEN_DELAY_MIN for device in devices.values()):
        # Adjust the trigger delay to fit the mentioned delay limitation
        for device in devices.values():
            device["trigger_delay"] += GEN_DELAY_MIN


def check_devices_trigger_delay(devices):
    """Check if layout total latency fit within trigger maximum applicable delay"""
    layout_total_latency = max(device["trigger_delay"] for device in devices.values())
    if layout_total_latency > GEN_DELAY_MAX:
        raise ConfigurationError(
            f"The total layout latency ({layout_total_latency}) is too big (max: {GEN_DELAY_MAX}). Reduce layout tree depth or wires length."
        )


def extend_with_default(validator_class):
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):
        for property, subschema in properties.items():
            if "default" in subschema:
                instance.setdefault(property, subschema["default"])

        for error in validate_properties(validator, properties, instance, schema):
            yield error

    return jsonschema.validators.extend(validator_class, {"properties": set_defaults})


def load_config(file):
    with open(Path(__file__).parent / "config_schema.json") as schema_file:
        schema = json.load(schema_file)

    try:
        config = json.load(file)

        Validator = extend_with_default(jsonschema.Draft7Validator)
        Validator(schema).validate(config)
    except jsonschema.ValidationError as e:
        raise ConfigurationPropertyError(e.message, e.absolute_path) from None
    except json.decoder.JSONDecodeError as e:
        raise ConfigurationError(
            f"{e.msg} (configuration file line: {e.lineno}, column: {e.colno})"
        ) from None

    high_resolution = config.get("high_resolution")
    devices = config.get("devices")
    layout = config.get("layout")

    check_devices(devices)
    check_layout(layout, devices)

    # filter out devices which are not in the layout
    devices_in_layout = get_layout_devices(layout)
    devices = {
        name: device for name, device in devices.items() if name in devices_in_layout
    }

    compute_devices_trigger_delay(layout, devices)

    check_devices_trigger_delay(devices)

    return devices, layout, high_resolution
