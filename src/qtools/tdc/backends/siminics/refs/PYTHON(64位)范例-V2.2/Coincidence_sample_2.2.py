import ctypes
from ctypes import *
import time

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

# dmtch initialize
dll_dmtchinitalize = lib.DmtchInitialize
dll_dmtchinitalize.argtypes = [c_int, c_int]
# ndv:设备编号
# nbrd:板卡号
print("dmtch initialize:", dll_dmtchinitalize(0, 0))

# DmtchModeSelection
dll_dmtchmodeselection = lib.DmtchModeSelection
dll_dmtchmodeselection.argtypes = [c_int, c_int]
# ndv:设备编号
# nbrd:板卡号
print("dmtch modeselection:", dll_dmtchinitalize(0, 0))


# dmtch add strategy
dll_dmtchaddstrategy = lib.DmtchAddStrategy
arr_type = c_int*2
dll_dmtchaddstrategy.argtypes = [c_int, arr_type, c_int, c_int, c_float, c_int, c_float, c_int]
# 1，2为符合的两个通道
int_array = (c_int * 2)(0, 1)

# 窗口宽度设置1000，单位ns
winlen = 1000
'''
添加数据符合策略
Idx:定义的策略编号
str[]：所要添加策略的通道
号组合。
num：该策略的通道号数量 
winLen：符合运算时的窗口宽度，即 bin的个数。  
times:与统计时间值保持一致
'''
print("dmtch add strategy:", dll_dmtchaddstrategy(1, int_array, 2, winlen, 1, 0, 0, 0))

# 设置文件保存方式
dll_setfilemode = lib.SetFileMode
dll_setfilemode.argtypes = [c_int, c_int, c_int]
dll_setfilemode.restypes = c_int
'''
设置保存模式
rMode：符合模式下设为4；
sMode：定义保存文件的格式；
0：不保存；
1：保存为二进制；
fMode：
0：保存直方图的每次更新；
'''
print("设置文件保存方式：", dll_setfilemode(4, 1, 0))

# 设置采集数据文件保存路径
dll_setfilepath = lib.SetFilePath
dll_setfilepath.argtypes = [c_int, c_int, POINTER(c_char)]
dll_setfilepath.restypes = c_int
path_char = (c_char*64)(*bytes(r"D:\Siminics", "utf-8"))
# rMode：符合模式设置为4
print("设置采集数据文件保存路径:", dll_setfilepath(0, 4, path_char))

# 设置数据采集时间
dll_setstatisticstime = lib.SetStatisticsTime
dll_setstatisticstime.argtypes = [c_int, c_float]
dll_setstatisticstime.restypes = c_int
# rMode：符合模式设置为4
# times:采集时间，单位秒
print("设置数据采集时间：", dll_setstatisticstime(4, 1))

# 开始任务
dll_starttask = lib.StartTask
dll_starttask.argtypes = [c_int]
dll_starttask.restypes = c_int
# 符合模式设置为4
print("开始任务:", dll_starttask(4))

# # 判断任务是否执行完成
dll_istaskcompleted = lib.IsTaskCompleted
dll_istaskcompleted.restypes = c_int
while True:
    time.sleep(0.01)
    if dll_istaskcompleted() == 0:
        break
    # dmtch get stratgy count
    dll_dmtchgetstratgycount = lib.DmtchGetStratgyCount
    dll_dmtchgetstratgycount.argtypes = [c_int]
    dll_dmtchgetstratgycount.restypes = c_int
    # 据符合策略所记录的符合数据数目
    print("dmtch get stratgy count：", dll_dmtchgetstratgycount(1))

    # dmtch get ch1 count
    # 获取数据
    dll_dmtchgetchlcount = lib.DmtchGetChlCount
    # 设置参数
    dll_dmtchgetchlcount.argtypes = [POINTER(c_ulonglong)]
    # 创建数组
    int_p = POINTER(c_ulonglong)
    # 实例化
    int_obj = (c_ulonglong * 64)(0, 0)
    int_p_obj = int_p(int_obj)
    print("dmtch get chl count：", dll_dmtchgetchlcount(int_p_obj))
    print("通道计数：", int_p_obj[0], int_p_obj[1])



# 反初始化
dll_uninitdll = lib.UnInitDll
print("反初始化:", dll_uninitdll())

