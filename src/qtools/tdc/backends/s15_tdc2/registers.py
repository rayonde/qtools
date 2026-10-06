"""FPGA configuration registers mapped from configtmst.h.

Definitions used for configuring the TDC2 FPGA.
"""

CollectLED = 0x01
CollectEN = 0x02
CounterReset = 0x04
FIFOreset = 0x08

LongFormat = 0x00
ShortFormat = 0x10

DummyInject = 0x20
NoDummyInject = 0x00

NIMOUTenable = 0x40
ParameterSelect = 0x80
LookuptabSelect = 0x00

SampleDelayShift = 10

TimestampDebug = 0x100
ADC_SPI_Select = 0x200
PositiveInputPolarity = 0x8000
NegativeInputPolarity = 0

# NIM divider options
NIMdivider256 = 0x00
NIMdivider1024 = 0x01
NIMdivider16k = 0x02
NIMdivider64k = 0x03

# ADC preprocessing
ADC_HiresRouting = 0x8000
