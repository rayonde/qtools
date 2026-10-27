import ctypes
from ctypes import *


lib = ctypes.cdll.LoadLibrary(r"win64\smncsftmt.dll")

# dll初始化
dll_init = lib.InitDll
dll_init()

# dev初始化
dev_init = lib.InitDev
dev_init()

get_dll = lib.GetDllVersion
# 设置参数
get_dll.argtypes = [POINTER(c_char)]

# 设备连接？
dll_devconnect = lib.DevConnected
dll_devconnect.argtypes = [c_int]
dll_devconnect.restypes = c_int
print("设备连接：", dll_devconnect(0))

# 使能T1模式
dll_enablet1 = lib.EnableT1
dll_enablet1.argtypes = [c_int, c_int, c_int]
# ndv:设备编号
# nbrd:板卡号
# umask:使能的通道编号，例如1代表0000 0000 0000 0001，即1通道
print("使能T1模式:", dll_enablet1(0, 0, 255))


# 设置单次采集时间
dll_sett1interval = lib.SetT1Interval
dll_sett1interval.argtypes = [c_float]
dll_sett1interval.restypes = c_int
# 设置内部刷新间隔100ms，该配置不建议更改
print("设置单次采集时间:", dll_sett1interval(0.1))

# 设置最大计数
dll_setmaxbarvalue = lib.SetMaxBarValue
dll_setmaxbarvalue.argtypes = [c_int]
dll_setmaxbarvalue.restypes = c_int
print("设置最大计数:", dll_setmaxbarvalue(100000))

# 设置数据采集时间
dll_setstatisticstime = lib.SetStatisticsTime
dll_setstatisticstime.argtypes = [c_int, c_float]
dll_setstatisticstime.restypes = c_int
# 设置停止条件：统计时间
# rMode：模式配置，T1模式配1
# sTime：统计时间配置，默认1s
print("设置数据采集时间：", dll_setstatisticstime(1, 1))

# 设置时间分辨率
dll_settimewindowres = lib.SetTimeWindowRes
dll_settimewindowres.argtypes = [c_int, c_int]
dll_settimewindowres.restypes = c_int
'''
设置时间分辨率：
0: 1ps
1: 2ps
2: 4ps
3: 8ps
4: 16ps
5: 32ps
6 : 64ps
7 : 128ps
8 : 256ps
9 : 512ps
....
以此类推，最大可配到
33554432ps
'''
print("设置时间分辨率：", dll_settimewindowres(0, 2))


# 设置bin总数
dll_setbinsize = lib.SetBinSize
dll_setbinsize.argtypes = [c_int, c_int]
dll_setbinsize.restypes = c_int
# 范围 65536~1048576
print("设置bin总数：", dll_setbinsize(0, 655360))

# 设置采集数据文件保存路径
dll_setfilepath = lib.SetFilePath
dll_setfilepath.argtypes = [c_int, c_int, POINTER(c_char)]
dll_setfilepath.restypes = c_int
path_char = (c_char*64)(*bytes(r"D:\Siminics", "utf-8"))
# rMode：T1模式下设为1；
print("设置采集数据文件保存路径:", dll_setfilepath(0, 1, path_char))

# 设置文件保存方式
dll_setfilemode = lib.SetFileMode
dll_setfilemode.argtypes = [c_int, c_int, c_int]
dll_setfilemode.restypes = c_int
'''
rMode：T1模式下设为1；
sMode：定义保存文件的格式；
0：不保存；
2：保存为解析后的文本；
fMode（建议设置为1）：
0：保存直方图的每次更新；
1：保存直方图的最后一次更新；
'''
print("设置文件保存方式：", dll_setfilemode(1, 2, 1))

# 开始任务
dll_starttask = lib.StartTask
dll_starttask.argtypes = [c_int]
dll_starttask.restypes = c_int
# 开始直方图T1模式采集
print("开始任务:", dll_starttask(1))

# # 判断任务是否执行完成
dll_istaskcompleted = lib.IsTaskCompleted
dll_istaskcompleted.restypes = c_int
while True:
    # 获取T1数据
    dll_gett1data = lib.GetT1Data
    # 设置参数
    dll_gett1data.argtypes = [c_int, c_int, POINTER(c_ulonglong)]
    # 创建数组
    # int_array = c_uint * 655360
    # # 指针类型
    int_p = POINTER(c_ulonglong)
    # 实例化
    int_obj = (c_ulonglong*655360)(0, 0)
    int_p_obj = int_p(int_obj)

    print("获取T1数据:", dll_gett1data(0, 0, int_p_obj))
    if dll_istaskcompleted() == 0:
        break

# 反初始化
dll_uninitdll = lib.UnInitDll
# dll_uninitdll()
print("反初始化:", dll_uninitdll())

