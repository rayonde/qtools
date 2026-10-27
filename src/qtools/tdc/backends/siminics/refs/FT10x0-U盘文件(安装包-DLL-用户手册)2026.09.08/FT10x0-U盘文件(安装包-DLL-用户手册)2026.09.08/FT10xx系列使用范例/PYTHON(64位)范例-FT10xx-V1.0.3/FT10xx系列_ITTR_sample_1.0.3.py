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

# 设置数据采集时间
dll_setstatisticstime = lib.SetStatisticsTime
dll_setstatisticstime.argtypes = [c_int, c_float]
dll_setstatisticstime.restypes = c_int
# 6：ITTR-T    7:ITTR-M
# 数据采集时间单位秒
print("设置数据采集时间：", dll_setstatisticstime(6, 3.0))

# 设置文件保存方式
dll_setfilemode = lib.SetFileMode
dll_setfilemode.argtypes = [c_int, c_int, c_int]
dll_setfilemode.restypes = c_int
# 6：ITTR-T    7:ITTR-M
# 0：不保存 1：保存二进制
# nFm:默认0
print("设置文件保存方式：", dll_setfilemode(6, 1, 0))

# 使能ITTR模式
dll_enableittr = lib.EnableITTR
dll_enableittr.argtypes = [c_int, c_int, c_int]
# ndv:设备编号
# nbrd:板卡号
# umask:使能的通道编号，例如1代表 0000 0001，即1通道
print("使能ITTR模式:", dll_enableittr(0, 0, 255))

# 设置统计周期
dll_setittrinterval = lib.SetITTRInterval
dll_setittrinterval.argtypes = [c_int, c_int, c_int]
# nlntvl：统计周期，单位微秒
print("设置统计周期:", dll_setittrinterval(0, 0, 1000))

# 设置采集数据文件保存路径
dll_setfilepath = lib.SetFilePath
dll_setfilepath.argtypes = [c_int, c_int, POINTER(c_char)]
dll_setfilepath.restypes = c_int
path_char = (c_char*64)(*bytes(r"D:\Siminics", "utf-8"))
# 6：ITTR-T    7:ITTR-M
print("设置采集数据文件保存路径:", dll_setfilepath(0, 6, path_char))

#设置停止方式
dll_setittrendmode = lib.SetITTREndMode
dll_setittrendmode.argtypes = [c_int, c_int]
# 0:时间停止
# uEvents64：默认0
print("设置停止方式:", dll_setittrendmode(0, 0))

# 开始任务
dll_starttask = lib.StartTask
dll_starttask.argtypes = [c_int]
dll_starttask.restypes = c_int
# 6：ITTR-T    7:ITTR-M
print("开始任务:", dll_starttask(6))

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

