# Used for console script discovery
help = """
Available scripts (run with 'python -m ...'), and with '-i' flag for interactive control:

    slmutils.display.display [interactive: 'display']
        Opens a full-screen display on secondary monitor.

    slmutils.display.server
        Opens full-screen displays as well as RPC ports for remote updating.

    slmutils.display.client [interactive: 'display']
        Connects to a full-screen display for remote updating. Client counterpart
        to 'slmutils.display.server'.

    slmutils.camera.flir [interactive: 'camera']:
        Opens a connected FLIR camera.
"""

print(help.strip() + "\n")
