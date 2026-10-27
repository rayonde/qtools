import ctypes
from ctypes import *


lib = ctypes.cdll.LoadLibrary(r"win64\smncsftmt.dll")

# dll初始化
dll_init = lib.InitDll
dll_init()

# dev初始化
dev_init = lib.InitDev
dev_init()

# 设备连接？
dll_devconnect = lib.DevConnected
dll_devconnect.argtypes = [c_int]
dll_devconnect.restypes = c_int
print("设备连接：", dll_devconnect(0))

# 使能T2/T3模式
dll_enabletttr = lib.EnableTTTR
dll_enabletttr.argtypes = [c_int, c_int, c_int]
# ndv:设备编号
# nbrd:板卡号
# umask:使能的通道编号，例如1代表0000 0000 0000 0001，即1通道
print("使能TTTR模式:", dll_enabletttr(0, 0, 255))

# 设置采集数据文件保存路径
dll_setfilepath = lib.SetFilePath
dll_setfilepath.argtypes = [c_int, c_int, POINTER(c_char)]
dll_setfilepath.restypes = c_int
path_char = (c_char*64)(*bytes(r"D:\Siminics", "utf-8"))
# 2：T2    3:T3
print("设置采集数据文件保存路径:", dll_setfilepath(0, 2, path_char))

# 设置数据采集时间
dll_setstatisticstime = lib.SetStatisticsTime
dll_setstatisticstime.argtypes = [c_int, c_float]
dll_setstatisticstime.restypes = c_int
# 2：T2    3:T3
# 数据采集时间单位秒
print("设置数据采集时间：", dll_setstatisticstime(2, 1))

#设置停止方式
dll_settttrendmode = lib.SetTTTREndMode
dll_settttrendmode.argtypes = [c_int, c_int]
# eMode：停止条件设定
# 0 : 时间停止
print("设置停止方式:", dll_settttrendmode(0, 1))

# 设置文件保存方式
dll_setfilemode = lib.SetFileMode
dll_setfilemode.argtypes = [c_int, c_int, c_int]
dll_setfilemode.restypes = c_int
# 2：T2    3:T3
# 0：不保存 1：保存二进制
# nFm:默认0
print("设置文件保存方式：", dll_setfilemode(2, 1, 0))

# 开始任务
dll_starttask = lib.StartTask
dll_starttask.argtypes = [c_int]
dll_starttask.restypes = c_int
# 2：T2    3:T3
print("开始任务:", dll_starttask(2))

# # 判断任务是否执行完成
dll_istaskcompleted = lib.IsTaskCompleted
dll_istaskcompleted.restypes = c_int
while True:
    if dll_istaskcompleted() == 0:
        break

# 反初始化
dll_uninitdll = lib.UnInitDll
# dll_uninitdll()
print("反初始化:", dll_uninitdll())

