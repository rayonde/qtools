from pathlib import Path
import sys


from qtools.pctrl.backends.scservo_sdk import protocol_packet_handler, COMM_SUCCESS


class FakePortHandler:
    def __init__(self):
        self.is_using = False
        self.cleared = 0
        self.writes = []
        self.reads = []
        self.packet_timeout = 0.0

    def clearPort(self):
        self.cleared += 1

    def writePort(self, packet):
        self.writes.append(packet)
        return len(packet)

    def readPort(self, length):
        if self.reads:
            return self.reads.pop(0)
        return []

    def setPacketTimeout(self, packet_length):
        self.packet_timeout = packet_length

    def isPacketTimeout(self):
        return len(self.reads) == 0

    def getCurrentTime(self):
        return 0.0

    def getTimeSinceStart(self):
        return 0.0


class FakeHandler(protocol_packet_handler):
    def __init__(self):
        super().__init__(FakePortHandler(), 0)


def test_ping_does_not_get_stuck_after_first_response():
    handler = FakeHandler()
    port = handler.portHandler

    def make_packet(sid: int):
        packet = [0xFF, 0xFF, sid, 2, 0, 0]
        checksum = (~sum(packet[2:-1]) & 0xFF)
        packet[-1] = checksum
        return packet

    def make_read_packet(sid: int, data: list[int]):
        length = len(data) + 2
        packet = [0xFF, 0xFF, sid, length, 0] + data + [0]
        checksum = (~sum(packet[2:-1]) & 0xFF)
        packet[-1] = checksum
        return packet

    # First ping should complete and release the busy flag.
    port.reads.append(make_packet(1))
    port.reads.append(make_read_packet(1, [3, 0]))
    _, result, _ = handler.ping(1)
    assert result == COMM_SUCCESS
    assert port.is_using is False

    # A second ping should not see a stale busy flag.
    port.reads.append(make_packet(1))
    port.reads.append(make_read_packet(1, [3, 0]))
    _, result2, _ = handler.ping(1)
    assert result2 == COMM_SUCCESS
    assert port.is_using is False
