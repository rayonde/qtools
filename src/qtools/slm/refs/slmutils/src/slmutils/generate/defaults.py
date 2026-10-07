from slmutils.generate.slm import HoloeyeLETO

SLM_532 = HoloeyeLETO(wl=532e-9)
PHASEMASK_532 = SLM_532.to_phase()
DISPLAYMASK_532 = PHASEMASK_532.to_display()
