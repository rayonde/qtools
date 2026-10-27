import ctypes
import time
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
# umask:使能的通道编号，例如1代表 0000 0001，即1通道
print("使能TTTR模式:", dll_enabletttr(0, 0, 255))

# 设置采集数据文件保存路径
dll_setfilepath = lib.SetFilePath
dll_setfilepath.argtypes = [c_int, c_int, POINTER(c_char)]
dll_setfilepath.restypes = c_int
path_char = (c_char*64)(*bytes(r"E:\Siminics", "utf-8"))
# 2：T2    3:T3
print("设置采集数据文件保存路径:", dll_setfilepath(0, 3, path_char))

# 设置数据采集时间
dll_setstatisticstime = lib.SetStatisticsTime
dll_setstatisticstime.argtypes = [c_int, c_float]
dll_setstatisticstime.restypes = c_int
# 2：T2    3:T3
# 数据采集时间单位秒
print("设置数据采集时间：", dll_setstatisticstime(3, 1))

#设置停止方式
dll_settttrendmode = lib.SetTTTREndMode
dll_settttrendmode.argtypes = [c_int, c_int]
# eMode：停止条件设定
# 0 : 时间停止
print("设置停止方式:", dll_settttrendmode(0, 10000000))

# 设置文件保存方式
dll_setfilemode = lib.SetFileMode
dll_setfilemode.argtypes = [c_int, c_int, c_int]
dll_setfilemode.restypes = c_int
# 2：T2    3:T3
# 0：不保存 1：保存二进制
# nFm:默认0
print("设置文件保存方式：", dll_setfilemode(3, 0, 0))


dll_setmemorydatamode = lib.SetMemoryDataMode
dll_setmemorydatamode.argtypes = [c_bool]
dll_setmemorydatamode.restypes = c_int
print("设置数据内存模式:", dll_setmemorydatamode(True))

#设置内存模式
dll_memorydatamodeenabled = lib.MemoryDataModeEnabled

dll_memorydatamodeenabled.restype = c_bool
print("数据内存模式使能:", dll_memorydatamodeenabled())




# 开始任务
dll_starttask = lib.StartTask
dll_starttask.argtypes = [c_int]
dll_starttask.restypes = c_int
# 2：T2    3:T3
print("开始任务:", dll_starttask(3))

class FtmtRawData(Structure):
    _fields_ = [("nType", c_int), ("lLength", c_long), ("ptrData", POINTER(c_ubyte))]


# # 判断任务是否执行完成
dll_istaskcompleted = lib.IsTaskCompleted
dll_istaskcompleted.restypes = c_int

while True:
    time.sleep(0.01)
    if dll_istaskcompleted() == 0:
        break
    dll_dmtchgetmemorydata = lib.GetMemoryData
    # struct_ptr = lib.GetMemoryData(0)
    dll_dmtchgetmemorydata.argtypes = [c_int]
    dll_dmtchgetmemorydata.restype = POINTER(FtmtRawData)
    struct_ptr = dll_dmtchgetmemorydata(0)

    # print(struct_ptr)
    # print(struct_ptr.contents)
    #
    if struct_ptr:
        print(f"nType: {struct_ptr.contents.nType}, ILength: {struct_ptr.contents.lLength}, ptrData: {struct_ptr.contents.ptrData}")

        bytes_data = ctypes.string_at(struct_ptr.contents.ptrData, struct_ptr.contents.lLength)
        # Print the binary data in hex format
        print("Binary data in hex format:")
        a = ' '.join(f'{b:02X}' for b in bytes_data)
        print(a)


        # with open(r'D:\siminics\a.txt', 'a') as file:
        #     file.write(a)  # 将追加的内容写入文件
        #     file.write("\n")


    # else:
    #     # print("Received NULL pointer")


    lib.ReleaseMemoryData(struct_ptr)
    #dll_dmtchreleasememorydata = lib.ReleaseMemoryData
    #dll_dmtchreleasememorydata.argtypes = [POINTER(FtmtRawData)]
    # dll_dmtchreleasememorydata.restypes = [c_int]
    # struct_instance = FtmtRawData()
    # struct_instance = FtmtRawData(nType = struct_ptr.contents.nType, lLength = struct_ptr.contents.lLength, ptrData = struct_ptr.contents.ptrData)
    # print("dmtch release memory count：", dll_dmtchreleasememorydata.fill_struct(byref(struct_instance)))
    # print("dmtch release memory count：", dll_dmtchreleasememorydata.process_struct(byref(struct_instance)))
    #print("dmtch release memory count：", dll_dmtchreleasememorydata(struct_ptr))
    # print(struct_instance.nType)





# 反初始化
dll_uninitdll = lib.UnInitDll
# dll_uninitdll()
print("反初始化:", dll_uninitdll())

