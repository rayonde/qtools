import json
import logging

from .exceptions import DataLinkCommandError, ScpiCommandError

logger = logging.getLogger(__package__)


def zmq_exec(socket, cmd, target, anslen=None) -> str:
    anslog = lambda x: logger.debug(
        f"{x[:max(0,anslen-3)]}..." if anslen != None and len(x) > anslen else x
    )
    logger.debug(f"[{target}] {cmd}")
    socket.send_string(cmd)
    ans = socket.recv().decode("utf-8")
    if ans:
        anslog(ans)
    return ans


def scpi_exec_device(device, cmd, anslen=None):
    ip = device.get("ip")
    socket = device.get("scpi_socket")
    answer = zmq_exec(socket, cmd, f"SCPI@{ip}", anslen)

    if "SCPI_ERR_" in answer:
        raise ScpiCommandError(ip, answer)

    return answer


def dlt_exec_device(device, cmd):
    ip = device.get("ip")
    socket = device.get("dlt_socket")
    answer = zmq_exec(socket, cmd, f"DLT@{ip}")
    answer = json.loads(answer) if answer.strip() else None

    if isinstance(answer, dict) and answer.get("error"):
        error = answer.get("error").get("description")
        raise DataLinkCommandError(ip, error)

    return answer


def remove_suffix(text, suffix):
    if text.endswith(suffix):
        return text[: -len(suffix)]
    return text
