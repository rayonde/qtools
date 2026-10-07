#!/usr/bin/env python3
"""Convenience script to create a local display server.

Examples:
    $ python -m slmutils.display.server
"""

import sys

from ipyutils import Server

from slmutils.display.display import Display

monitors = [(None, 4444)]
if len(sys.argv) > 1:
    try:
        monitors = [(int(arg), 4444 + int(arg)) for arg in sys.argv[1:]]
    except TypeError:
        print("usage: python -m slmutils.display.server [MONITOR_NUM]...", file=sys.stderr)
        sys.exit(1)

threadeds = [True] * (len(monitors) - 1) + [False]
for (monitor, port), threaded in zip(monitors, threadeds):
    device = Display(monitor)
    server = Server(device, port=port, secret="slmmer")
    server.run(threaded=threaded)
