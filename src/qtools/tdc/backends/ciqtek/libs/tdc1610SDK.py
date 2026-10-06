import os
from ctypes import *
from .errorCode import *
import platform
from array import array
import random
import uuid
import socket
import struct
import _thread
import time
import re
import datetime

TDC_CALLBACK = CFUNCTYPE(None, c_int, c_int, c_void_p)

projectPath = ""
class Tdc1610():
    _instance = None
    def __new__(cls, *args, **kw):
        if cls._instance is None:
            cls._instance = object.__new__(cls, *args, **kw)
        return cls._instance

    def __init__(self):
        global projectPath
        projectPath = os.path.abspath(os.path.dirname(__file__))
        arch = platform.architecture()[0]
        print("wd:",projectPath,"\r\narch: ",arch)

        dll_path = ""

        if arch == '64bit':
            dll_path = os.path.join(projectPath, 'TDC1610DLL_x64.dll')  # ATDC1610DLL_x64.dll
        else:
            print(" 32 bit is not supported ")

        if os.path.isfile(dll_path):
            self.__dll = CDLL(dll_path)
        else:
            raise Exception("can not found dll")

    def showResult(self,errorCode):
        return ErrorCode[errorCode]

        # 异常回调函数类型
        self.__dll.SetErrorCallback.restype = c_int

        # 搜索设备，返回是否成功，参数[ char *local_ip, char *des_ip, char *dst_mac, char *dst_name, int *device_count ]
        self.__dll.FindDevice.restype = c_int
        self.__dll.FindDevice.argtypes = [c_char_p, c_char_p, c_char_p, c_char_p, POINTER(c_int)]

        
        # 搜索设备，返回是否成功，参数[ char *local_ip, char *des_ip, char *dst_mac, char *dst_name, int *device_count ]
        self.__dll.SearchTdc.restype = c_int
        self.__dll.SearchTdc.argtypes = [c_char_p, c_char_p, c_char_p, c_char_p, POINTER(c_int)]

        # 连接，返回是否成功 [char * pLocalip, char *pDestinationIP, char *pDestinationMAC]
        self.__dll.ConnectDevice.restype = c_int
        self.__dll.ConnectDevice.argtypes = [POINTER(c_char), POINTER(c_char), POINTER(c_char)]

        # 断开连接，解除固件的IP锁定
        self.__dll.DisConnectDevice.restype = c_int

        # 开始采集
        self.__dll.StartCollect.restype = c_int

        # 停止采集
        self.__dll.StopCollect.restype = c_int

        # 触发模式
        self.__dll.ConfigTdcTriggerMode.restype = c_int
        self.__dll.ConfigTdcTriggerMode.argtypes = [c_int]

        # start通道开关
        self.__dll.ConfigStartSwitch.restype = c_int
        self.__dll.ConfigStartSwitch.argtypes = [c_int, c_int]

        # start配置
        self.__dll.ConfigStartChannel.restype = c_int
        self.__dll.ConfigStartChannel.argtypes = [c_int, c_int]

        # stop配置
        self.__dll.ConfigStopSwitchSZ.restype = c_int
        self.__dll.ConfigStopSwitchSZ.argtypes = [POINTER(c_int), POINTER(c_int)]

        # mark标记配置
        self.__dll.ConfigMark.restype = c_int
        self.__dll.ConfigMark.argtypes = [c_int, c_int, c_int]

        # 分辨率
        self.__dll.ConfigTimeResolution.restype = c_int
        self.__dll.ConfigTimeResolution.argtypes = [c_int]

        # 动态范围(采集窗口)
        self.__dll.ConfigDynamicRange.restype = c_int
        self.__dll.ConfigDynamicRange.argtypes = [c_int]

        # 绘图窗口
        self.__dll.ConfigDrawWindowRange.restype = c_int
        self.__dll.ConfigDrawWindowRange.argtypes = [c_ulonglong]

        # 时钟配置
        self.__dll.ConfigClock.restype = c_int
        self.__dll.ConfigClock.argtypes = [c_int, c_int, c_int]

        # 内部时钟的触发频率
        self.__dll.ConfigClockPeriod.restype = c_int
        self.__dll.ConfigClockPeriod.argtypes = [c_int]

        # 获取采集的数据 每次一个通道，全部获取
        self.__dll.GetCollectDataByUsed.restype = c_int
        self.__dll.GetCollectDataByUsed.argtypes = [c_int, POINTER(c_int), POINTER(c_ulonglong)]

        # 获取采集的数据 每次一个通道，获取非0数据
        self.__dll.GetCollectDataByUsedEx.restype = c_int
        self.__dll.GetCollectDataByUsedEx.argtypes = [c_int, POINTER(c_int), POINTER(c_ulonglong), POINTER(c_ulonglong),
                                                      POINTER(c_int)]

        # 获取CPS全部获取
        self.__dll.GetCpsByUser.restype = c_int
        self.__dll.GetCpsByUser.argtypes = [POINTER(c_int), POINTER(c_int)]

        # 获取符合计数
        self.__dll.GetAccordWithByUser.restype = c_int
        self.__dll.GetAccordWithByUser.argtypes = [POINTER(c_ulonglong)]

        # 采集时间
        self.__dll.TdcSetCollectTime.restype = c_int
        self.__dll.TdcSetCollectTime.argtypes = [c_int]

        # 刷新时间
        self.__dll.TdcSetFreshTime.restype = c_int
        self.__dll.TdcSetFreshTime.argtypes = [c_int]

        # 码密度校准
        self.__dll.TdcSetCalibration.restype = c_int

        # 获取码密度校准结果
        self.__dll.TdcGetCalibrationResult.restype = c_int

        # 设置算法
        self.__dll.TdcSSetAlgorithm.restype = c_int
        self.__dll.TdcSSetAlgorithm.argtypes = [c_int]

        # 添加算法
        self.__dll.TdcSetAlgorithmType.restype = c_int
        self.__dll.TdcSetAlgorithmType.argtypes = [c_int]

        # 清除算法
        self.__dll.TdcResetAlgorithmType.restype = c_int
        self.__dll.TdcResetAlgorithmType.argtypes = [c_int]

        # 获取随机数最后n位
        self.__dll.TdcGetRandomLastBits.restype = c_int
        self.__dll.TdcGetRandomLastBits.argtypes = [POINTER(c_char), c_int]

        # 配置随机数
        self.__dll.TdcConfigAlgorithmRandom.restype = c_int
        self.__dll.TdcConfigAlgorithmRandom.argtypes = [c_int, c_int, c_ulonglong, c_int]

        # 保存随机数到指定路径
        self.__dll.TdcSaveRandomChar.restype = c_int
        self.__dll.TdcSaveRandomChar.argtypes = [POINTER(c_char)]

        # 配置随机数保存的路径
        self.__dll.TdcConfigRandomPathChar.restype = c_int
        self.__dll.TdcConfigRandomPathChar.argtypes = [POINTER(c_char)]

        # 配置符合计数
        self.__dll.TdcConfigAlgorithmAccord.restype = c_int
        self.__dll.TdcConfigAlgorithmAccord.argtypes = [c_int, c_ulonglong, c_int, c_int, c_int]

        # 配置Mark保存的路径
        self.__dll.ConfigMarkSavePathChar.restype = c_int
        self.__dll.ConfigMarkSavePathChar.argtypes = [POINTER(c_char)]

        # 设置mark最大信号周期
        self.__dll.TdcSetMarkMaxDelay.restype = c_int
        self.__dll.TdcSetMarkMaxDelay.argtypes = [c_int]

        # 配置mark最大周期后的实时状态
        self.__dll.TdcGetMarkDelayStatus.restype = c_int
        self.__dll.TdcGetMarkDelayStatus.argtypes = [POINTER(c_int)]

        # 配置mark最大周期后的实时状态
        self.__dll.TdcSetCalibration.restype = c_int
        
        # 校准码密度 先写后读操作，发出校准指令然后回读结果
        self.__dll.TdcGetCalibrationResult.restype = c_int

        # 校准码密度 先写后读操作，发出校准指令然后回读结果
        self.__dll.TdcGetCalibrationResult.restype = c_int

    # 设置异常回调函数
    def SetErrorCallback(self, callback):
        if type(callback) == TDC_CALLBACK:
            return self.__dll.SetErrorCallback(callback)
        else:
            return False

    # 查找设备，返回[执行结果，设备列表]
    def FindDevice(self):
        local_ip = (c_char * 255)()
        dst_ip = (c_char * 255)()
        dst_mac = (c_char * 255)()
        dst_name = (c_char * 255)()
        device_count = c_int()
        ret = self.__dll.SearchTdc(local_ip, dst_ip, dst_mac, dst_name, byref(device_count))

        retLocal_ip = str(local_ip.value.decode("unicode-escape"))
        ret_ip = str(dst_ip.value.decode("unicode-escape"))
        ret_mac = str(dst_mac.value.decode("unicode-escape"))
        ret_name = str(dst_name.value.decode("unicode-escape"))

        retLocal_ip_list = re.split('[|]', retLocal_ip)
        ret_ip_list = re.split('[|]', ret_ip)
        ret_mac_list = re.split('[|]', ret_mac)
        ret_name_list = re.split('[|]', ret_name)
        ret_dev_count = device_count
        devlist = []
        count = 0
        for i in range(ret_dev_count.value):
            dev = []
            if retLocal_ip_list[i] != '\0':
                dev.append(i)
                dev.append(retLocal_ip_list[i])
                dev.append(ret_ip_list[i])
                dev.append(ret_mac_list[i])
                dev.append(ret_name_list[i])
                devlist.append(dev)
        return ret, devlist

    def ConnectDevice(self, dev):
        if len(dev) < 4:
            exit(" connect info error")
        local_ip = dev[1]
        des_ip = dev[2]
        dst_mac = dev[3]
        print("connct info : ", local_ip, des_ip, dst_mac)
        local_ip = local_ip.encode("unicode-escape")
        des_ip = des_ip.encode("unicode-escape")
        dst_mac = dst_mac.encode("unicode-escape")
        ret = self.__dll.ConnectDevice(local_ip, des_ip, dst_mac)
        return ret

    #断开连接 解除固件的ip锁定
    def DisConnectDevice(self):
        return self.__dll.DisConnectDevice()

    #开始采集
    def StartCollect(self):
        return self.__dll.StartCollect()

    #停止采集
    def StopCollect(self):
        return self.__dll.StopCollect()

    # tdc触发模式0 外触发 1内触发
    def ConfigTdcTriggerMode(self, mode):
        return self.__dll.ConfigTdcTriggerMode(mode)

    # start[通道使能，触发方式] [0禁用，1启用，  0上升沿，1下降沿]
    def ConfigStartSwitch(self, enable, mode):
        return self.__dll.ConfigStartSwitch(enable, mode)

    # 配置start通道的[阈值,延迟] [-5000~5000mv, -200~200ns]
    def ConfigStartChannel(self, range, delay):
        return self.__dll.ConfigStartChannel(range, delay)

    # channelEnable 对应16个stop通道的开关 0关 1开
    # mode 对应16个通道的触发方式 0上升沿 1下降沿
    def ConfigStopSwitchSZ(self, channelEnable, mode):
        channelEnable = (c_int * len(channelEnable))(*channelEnable)
        mode = (c_int * len(mode))(*mode)
        return self.__dll.ConfigStopSwitchSZ(channelEnable, mode)

    # 配置stop通道的[通道，阈值,延迟] [0~16，-5000~5000mv, -200~200ns]    (外触发时，channel = 0 表示start通道)
    def ConfigStopChannel(self, channel, range, delay):
        return self.__dll.ConfigStopChannel(channel, range, delay)

    # mark标记配置  enable：使能[0禁用，1启用]，mode：触发模式[0外部,1内部]，rang触发阈值[-5000,5000]mv
    def ConfigMark(self, enable, mode, range):
        return self.__dll.ConfigMark(enable, mode, range)

    global m_resolution 
    # 时间分辨率8,16,32,64,128,256,1024,ps
    def ConfigTimeResolution(self, resolution):
        global m_resolution
        m_resolution = resolution
        return self.__dll.ConfigTimeResolution(resolution)

    # 采集有效窗口ps [最大可配置 = 分辨率 x (2^32 -1)ps - 4000ps] 切不超过12500000
    def ConfigDynamicRange(self, dynamicRange):
        return self.__dll.ConfigDynamicRange(dynamicRange)

    # 绘图窗口ps 不大于时间分辨率，最大12500000个点，x8=100us
    def ConfigDrawWindowRange(self, range):
        return self.__dll.ConfigDrawWindowRange(range)

    # 时钟配置，输入时钟类型[0内，1外]，输入时钟频率[0:10M,1:100M]，输出时钟频率[0:10M,1:100M], 内时钟只有100M
    def ConfigClock(self, inputType, inputValue, output):
        return self.__dll.ConfigClock(inputType, inputValue, output)

    # 内部时钟的触发频率[100,1000000000]ns
    def ConfigClockPeriod(self, clockPeriod):
        return self.__dll.ConfigClockPeriod(clockPeriod)

    # 获取采集的数据 每次一个通道 暂时未用
    def GetCollectDataByUser(self, channel):
        channel = c_int()
        length = c_int()
        retData = (c_ulonglong * 12500000)()
        return self.__dll.GetCollectDataByUsed(channel, byref(length), retData)

    # 获取非0数据，每次一个通道   返回[通道，横坐标列表，纵坐标列表，是否已刷新数据],  isAlreadyFresh：刷新模式下可用，获取数据时返回此标志
    #接口获取0~16 start+16个stop
    def GetCollectDataByUserEx(self, channel):
        global m_resolution
        channel = c_int(channel)
        length = c_int()
        retData = (c_ulonglong * 12500000)()
        index = (c_ulonglong * 12500000)()
        isAlreadyFresh = c_int()
        ret = self.__dll.GetCollectDataByUsedEx(channel, byref(length), retData, index, byref(isAlreadyFresh))
        indexList = []
        dataList = []
        for i in range(length.value):
            #index[i] = index[i]*m_resolution-4000
            indexList.append(index[i])
            dataList.append(retData[i])
        return channel.value, indexList, dataList, isAlreadyFresh.value

    #获取cps 用户主动调用 返回[调用结果，是否是新数据，cps列表]   cps列表：{0：内部触发频率，1：start通道的计数率，2-17：stop1-stop16的计数率}
    def GetCpsByUser(self):
        isNew = c_int()
        data = (c_int * 20)()
        ret = self.__dll.GetCpsByUser(byref(isNew), data)
        cpsList = []
        for i in range(1, 18):
            cpsList.append(data[i])
        return ret, isNew.value, cpsList

    #获取符合计数 用户主动调用 返回[调用结果，数据列表]   数据列表[符合计数，第一个通道cps，第二个通道cps，第三个通道cps]
    def GetAccordByUser(self):
        data = (c_ulonglong * 4)()
        ret = self.__dll.GetAccordWithByUser(data)
        dataList = []
        for i in range(4):
            dataList.append(data[i])
        return ret, dataList

    #采集(工作)时间 mSec[0,360000000]ms, 0表示不开启此功能
    def TdcSetCollectTime(self, collectTime):
        return self.__dll.TdcSetCollectTime(collectTime)

    #设置刷新模式的清除时间 sec[0,86400]s,0表示不启用此功能
    def TdcSetFreshTime(self, FreshTime):
        return self.__dll.TdcSetFreshTime(FreshTime)

    #校准码密度 先写后读操作，此处写
    def TdcSetCalibration(self):
        return self.__dll.TdcSetCalibration()

    #校准码密度 先写后读操作，此处读
    def TdcGetCalibrationResult(self):
        return self.__dll.TdcGetCalibrationResult()
    
    #设置算法按位设置{0x01,0x02,0x04,0x08} 分别对应 {随机数，二重符合，三重符合，mark}，先清除再设置，可（0x01 | 0x02）形式设置多个
    def TdcSetAlgorithm(self, Algorith):
        return self.__dll.TdcSSetAlgorithm(Algorith)

    #合并算法按位设置{0x01,0x02,0x04,0x08} 分别对应 {随机数，二重符合，三重符合，mark}，先清除再设置，可（0x01 | 0x02）形式设置多个
    def TdcSetAlgorithmType(self, Algorith):
        return self.__dll.TdcSetAlgorithmType(Algorith)

    #清除算法 {0x01,0x02,0x04,0x08} 分别对应 {随机数，二重符合，三重符合，mark}，清除某一位
    def TdcResetAlgorithmType(self, Algorith):
        return self.__dll.TdcResetAlgorithmType(Algorith)
    
    #获取随机数的最后bits位，不足bits位则全部获取， int bits返回读取的实际位数默认40，buf返回读取到的字符串 返回[执行结果，随机数最后n位]  次函数只做查看使用
    def TdcGetRandomLastBits(self, length):
        data = (c_char * 1024)()
        ret = self.__dll.TdcGetRandomLastBits(data, length)
        return ret, data.value

    # channe1：通道1，channel2：通道2，saveCount：保存点数，RandomCodeWith：符合门（RandomCodeWith未启用，调用时不用传参数）
    def TdcConfigAlgorithmRandom(self, channe1, channel2, saveCount, CodeWith=100):
        return self.__dll.TdcConfigAlgorithmRandom(channe1, channel2, saveCount, CodeWith)

    #保存随机数到指定文件内(注意是指定文件的绝对路径:C:\\Abc\\123.txt)，用户可已配置路径，不配置路径则默认路径的默认文件，不指定文件名则根据时间自动创建文件名
    def TdcSaveRandom(self, path: str):#projectPath+
        global projectPath
        if path == "":
            path = projectPath+"\\TDC_Random_"+datetime.datetime.strftime(datetime.datetime.now(),'%Y-%m-%d_%H-%M-%S')+".txt"
        elif path.find(".txt")!=-1:
            None
        else:
            path += "\\TDC_Random_"+datetime.datetime.strftime(datetime.datetime.now(),'%Y-%m-%d_%H-%M-%S')+".txt"
        
        print("Random Path :", path)
        path = c_char_p(path.encode('gbk'))
        return self.__dll.TdcSaveRandomChar(path)

    #配置保存随机数的路径 暂未使用
    def TdcConfigRandomPath(self, path: str):
        global projectPath
        if path == "":
            path = projectPath
        print("Random Path :", path)
        path = c_char_p(path.encode('gbk'))
        return self.__dll.TdcConfigRandomPathChar(path)

    #配置符合计数的参数 CodeWith：符合门宽，channe1：通道1， channel2：通道2， channel3：通道3， 只用1，2通道是2重符合， 1,2,3通道都用是三重符合
    def TdcConfigAlgorithmAccord(self, CodeWith:c_ulonglong, channe1, channel2, channel3 = -1 ):
        return self.__dll.TdcConfigAlgorithmAccord(1,CodeWith, channe1, channel2, channel3)

    #配置mark的缓存路径 在此路径下创建 Markfile文件夹，在Markfile内生成文件
    def ConfigMarkSavePath(self, path: str):
        global projectPath
        if path == "":
            path = projectPath
        print("Mark_File Path :",path)
        path = c_char_p(path.encode('gbk'))
        return self.__dll.ConfigMarkSavePathChar(path)

    #配置mark最大信号周期，当此时间内无mark信号，自动关闭mark功能
    def TdcSetMarkMaxDelay(self, MaxDelay):
        return self.__dll.TdcSetMarkMaxDelay(MaxDelay)

    #获取当前mark的状态，0未开启， 1已开启未收到mark信号， 2已开启mark且已收到信号，
    def TdcGetMarkDelayStatus(self):
        status = c_int()
        ret = self.__dll.TdcGetMarkDelayStatus(byref(status))
        return ret, int(status)


    #获取当前mark的状态，0未开启， 1已开启未收到mark信号， 2已开启mark且已收到信号，
    def TdcSetCalibration(self):
        return self.__dll.TdcSetCalibration()


    #获取当前mark的状态，0未开启， 1已开启未收到mark信号， 2已开启mark且已收到信号，
    def TdcGetCalibrationResult(self):
        return self.__dll.TdcGetCalibrationResult()


