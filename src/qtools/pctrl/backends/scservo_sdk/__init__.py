#!/usr/bin/env python

from .port_handler import *
from .protocol_packet_handler import *
from .group_sync_write import *
from .group_sync_read import *
from .sms_sts import *
from .scscl import *

# Dynamic Mock Mode Proxies
from .port_handler import PortHandler as RealPortHandler
from .sms_sts import sms_sts as realsms_sts

mock_mode = False
_mock_ph = None
_mock_sts = None

class PortHandlerProxy:
    def __new__(cls, *args, **kwargs):
        global mock_mode, _mock_ph
        if mock_mode:
            from qtools.pctrl.backends.mockservo import MockPortHandler
            if _mock_ph is None:
                _mock_ph = MockPortHandler(args[0] if args else "MOCK_PORT")
            return _mock_ph
        return RealPortHandler(*args, **kwargs)

class sms_sts_proxy:
    def __new__(cls, *args, **kwargs):
        global mock_mode, _mock_sts
        if mock_mode:
            from qtools.pctrl.backends.mockservo import MockSmsSts
            if _mock_sts is None:
                _mock_sts = MockSmsSts()
            return _mock_sts
        return realsms_sts(*args, **kwargs)

PortHandler = PortHandlerProxy
sms_sts = sms_sts_proxy
