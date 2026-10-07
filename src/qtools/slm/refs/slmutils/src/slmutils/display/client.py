#!/usr/bin/env python3
"""Convenience script to connect to a local display server.

Examples:
    $ python -im slmutils.display.client
    >>> display.resolution
    (1920, 1080)
"""

import sys

from ipyutils import Client

from slmutils.display import DisplayInterface


def get_localhost_client(port):
    return Client(DisplayInterface, port=port, secret="slmmer")


if __name__ == "__main__":
    monitor = None
    port = 4444
    if len(sys.argv) > 1:
        try:
            monitor = int(sys.argv[1])
            port = 4444 + monitor
        except TypeError:
            print("usage: python -im slmutils.display.client [MONITOR_NUM]", file=sys.stderr)
            sys.exit(1)

    display = Client(DisplayInterface, port=4444, secret="slmmer")
