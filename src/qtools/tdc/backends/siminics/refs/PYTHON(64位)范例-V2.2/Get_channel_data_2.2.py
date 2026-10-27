import ctypes
import time
from ctypes import *

# 加载动态链接库
lib = ctypes.cdll.LoadLibrary(r"win64\smncsftmt.dll")

# 初始化 DLL
dll_init = lib.InitDll
dll_init.restype = c_int  # 假设返回 int
print("DLL 初始化：", dll_init())

# 初始化设备
dev_init = lib.InitDev
dev_init.restype = c_int  # 假设返回 int
print("设备初始化：", dev_init())

# 检查设备连接
dll_devconnect = lib.DevConnected
dll_devconnect.argtypes = [c_int]
dll_devconnect.restype = c_int  # 修正为 restype
print("设备连接：", dll_devconnect(0))

# 定义 GetSignalStatus 函数原型
dll_getsignalstatus = lib.GetSignalStatus
dll_getsignalstatus.argtypes = [
    c_int,              # nDevId
    c_int,              # nBoard
    c_int,              # nChannel
    POINTER(c_uint),    # ptrStartCount
    POINTER(c_uint)     # ptrStopCount
]
dll_getsignalstatus.restype = c_int  # 返回值为 int

# 获取通道计数
def get_signal_status(dev_id, board, channel):
    # 创建输出参数
    start_count = c_uint(0)  # unsigned int
    stop_count = c_uint(0)   # unsigned int

    # 调用函数
    result = dll_getsignalstatus(
        dev_id,
        board,
        channel,
        byref(start_count),  # 传递指针
        byref(stop_count)
    )

    # 检查返回值（假设 0 表示成功）
    if result != 0:
        print(f"GetSignalStatus 失败，设备 {dev_id}, 板卡 {board}, 通道 {channel}, 返回码: {result}")
        return None, None

    return start_count.value, stop_count.value

# 循环读取通道计数
number = 0
for i in range(100):  # 可改为 while True 以持续读取
    time.sleep(0.1)
    channel = number % 16  # 假设有 16 个通道
    start_count, stop_count = get_signal_status(0, 0, channel)
    if start_count is not None and stop_count is not None:
        print(f"设备 0, 板卡 0, 通道 {channel + 1}: Start Count = {start_count}, Stop Count = {stop_count}")
    number += 1

# 反初始化 DLL
dll_uninitdll = lib.UnInitDll
dll_uninitdll.restype = c_int  # 假设返回 int
print("DLL 反初始化：", dll_uninitdll())