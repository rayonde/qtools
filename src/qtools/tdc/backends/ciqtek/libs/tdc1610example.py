
import ctypes
from tdc1610SDK import *
from ctypes import *
import threading
import time
import copy




# 全局参数
isExist = 0  # 线程生存标志
isStart = 0
algorithmType = 0
#以下是start+stop 通道的全部全局配置   第一位是start 后16位表示stop1-stop16的配置
channelEnable = [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0]  # 对应17个通道的开关 0关 1开
channelMode =   [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]  # 对应17个通道的触发方式 0上升沿 1下降沿
channelRange =  [500, 500, 500, 500, 500, 500, 500, 500, 500, 2500, 2500, 2500, 2500, 2500, 2500, 2500, 2500]# 配置通道的[通道，阈值] [0~16，-5000~5000mv]
channelDelay =  [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]# 配置通道的延迟 [0~16，-200000~200000ps]
triggerMode = 0 #触发模式 0 外触发  1內触发
inputID = 0
devCount = 0
errorCode= 0

@CFUNCTYPE(None, c_int, c_int, c_void_p)
def error_callback(type, length, data):
    print("****************error_callback****************\r\ntype: ",type," length: ",length)
    if type == 0:#停止指令
        stop()
        if length == 1:
            print("溢出")
        exit_Ex(1)
    elif type ==1:
        print("mark长时间位采集到信号，已关闭")
        closeMark()
    elif type == 2:#第一个符合
        cdata = c_char_p(data)
        s = cdata.value
        stop()
        print(" first accord stop info ：",s)
    
    return

# 实例化tdc对象
tdc = Tdc1610()

# 设置异常回调函数
errorCode = tdc.SetErrorCallback(error_callback)
print("SetErrorCallback : ", errorCode)

# 查找结果
devlist = tdc.FindDevice()

# 查找结果
print("FindDevice : ", devlist[0])

# FindDevice 设备列表
print("Device list : ")
for dev in devlist[1]:
    print("  ", dev)

#搜索到多个TDC设备时 输入要连接的设备编号
if len(devlist[1]) >1:
    inputID = input("input dev id:")
    inputID = int(inputID)
elif len(devlist[1]) == 0:
    exit("no device")

# FindDevice 结果
if (inputID>len(devlist[1])-1):
    exit("设备连接信息异常")

errorCode = tdc.ConnectDevice(devlist[1][inputID])
print("ConnectDevice : ", errorCode)
if errorCode==0:
    isExist = 1
else:
    exit("连接失败")

calibrationResult =  tdc.TdcGetCalibrationResult()#获取校准
if calibrationResult != 0:
    tdc.TdcSetCalibration()#配置校准
    print("校准中...\n")
    for loop in range(30):
        time.sleep(1)
        print ("\r Loading... "+str(int(100*(loop+1)/30))+"%", end="")
    print("\n")
    calibrationResult =  tdc.TdcGetCalibrationResult()
    if calibrationResult != 0:
        print("校准失败",calibrationResult)
elif calibrationResult !=0:
    print("错误:",calibrationResult)


def configGlobal():
    #声明全局配置
    global channelEnable
    global channelMode 
    global channelRange
    global channelDelay 
    global triggerMode 

    # tdc触发模式0 外触发 1内触发
    print("ConfigTdcTriggerMode : ",  tdc.ConfigTdcTriggerMode(triggerMode))

    # 内部时钟的触发频率[100,1000000000]ns 4的整数倍
    print("ConfigClockPeriod : ", tdc.ConfigClockPeriod(100000000))

    # start[通道使能，触发方式] 
    startEnable = channelEnable[0]
    startMode = channelMode[0]
    print("ConfigStartSwitch : ", tdc.ConfigStartSwitch(startEnable, startMode))

    # 配置start通道的[阈值,延迟] 
    startRange = channelRange[0]
    startDelay = channelDelay[0]
    print("ConfigStartChannel : ", tdc.ConfigStartChannel(startRange, startDelay))


    stopEnable = copy.deepcopy(channelEnable)
    del stopEnable[0]
    stopMode = copy.deepcopy(channelMode)
    del stopMode[0]
    print("ConfigStopSwitchSZ : ", tdc.ConfigStopSwitchSZ(stopEnable, stopMode))

    # 配置stop通道的[通道，阈值,延迟] [0~16，-5000~5000mv, -200~200ns]    (外触发时，channel = 0 表示start通道,循环可以从0开始)
    for i in range(1, len(channelRange)):
        print("ConfigStopChannel ", i ," : ", tdc.ConfigStopChannel(i, channelRange[i], channelDelay[i]))

    #时间分辨率8,16,32,64,128,256,1024,ps
    print("ConfigTimeResolution : ", tdc.ConfigTimeResolution(8))

    #动态采集范围ps 单位4ns
    print("ConfigDynamicRange : ", tdc.ConfigDynamicRange(100000))

    # 绘图窗口ps 不大于 动态采集范围，且最大12500000
    print("ConfigDrawWindowRange : ", tdc.ConfigDrawWindowRange(4000000))
    
    #时钟配置，输入时钟类型[0内，1外]，输入时钟频率[0:10M,1:100M]，输出时钟频率[0:10M,1:100M], 内时钟只有100M
    print("ConfigClock : ", tdc.ConfigClock(0,1,0))

    #采集时间
    print("TdcSetCollectTime : ", tdc.TdcSetCollectTime(0))

    #刷新时间
    print("TdcSetFreshTime : ", tdc.TdcSetFreshTime(0))


# 设置算法按位设置{0x01,0x02,0x04,0x08} 分别对应 {随机数，二重符合，三重符合，mark}，先清除再设置
def openMark():
    global algorithmType
    #mark标记配置  enable：使能[0禁用，1启用]，mode：触发模式[0外部,1内部]，rang触发阈值[-5000,5000]mv
    print("ConfigMark : ", tdc.ConfigMark(1, 0, 0))

    #最大mark周期 辅助作用 kaiqimark后 长时间（下面配置的时间，0为无限大）未收到mark信号 会主动关闭mark功能
    print("TdcSetMarkMaxDelay : ", tdc.TdcSetMarkMaxDelay(0))
    
    print("ConfigMarkSavePath : ", tdc.ConfigMarkSavePath(""))
    
    algorithmType |= 0x08


def closeMark():
    global algorithmType
    # 关闭mark功能 清楚0x08
    print("TdcResetAlgorithmType : ", tdc.TdcResetAlgorithmType(0x08))
    algorithmType &= (~0x08)
    return


def openAccord():
    global algorithmType
    # #符合门100000ps , 通道1 = 1， 通道2 = 2 通道3 = 未配置
    print("TdcConfigAlgorithmAccord : ", tdc.TdcConfigAlgorithmAccord(c_ulonglong(352),4,3))
    algorithmType |= 0x02
    return


def closeAccord():
    global algorithmType
    # #清除二重符合 三重复合 标志
    print("TdcResetAlgorithmType : ", tdc.TdcResetAlgorithmType(0x02 | 0x04))
    algorithmType &= (~(0x02 | 0x04))
    return


def openRandom():
    global algorithmType
    # #随机数0 = 通道3   随机数1 = 通道2   采集文件大小 = 20*10214*1024
    print("TdcConfigAlgorithmRandom : ", tdc.TdcConfigAlgorithmRandom(0, 2, 20971520))
    algorithmType |= 0x01
    return


def closeRandom():
    global algorithmType
    #清除随机数算法
    print("TdcResetAlgorithmType : ", tdc.TdcResetAlgorithmType(0x01))
    algorithmType &= (~0x01)
    return


def saveRandom():
    # #保存随机数到默认文件,文件名默认 格式：TDC_Random_2021-07-13_21-15-36.txt，以时间生成，用户设置保存路径后，在该路径下生成文件（用户设置路径为已有目录）
    # path = "F:\\workSpace\\tdc\\tdcProduct\\TDC1610\\SDK\\PythonSDK\\abc.txt"
    path = ""
    print("TdcSaveRandom : ", tdc.TdcSaveRandom(path))
    return


def start():
    global isStart
    global algorithmType
    #配置算法
    print("TdcSetAlgorithmType : ", tdc.TdcSetAlgorithmType(algorithmType))
    ret = tdc.StartCollect()
    print("StartCollect : ",ret )
    if ret == 0:
        isStart = 1
    else:
        print("开始采集失败")


def stop():
    global isStart
    isStart = 0
    #停止采集
    print("StopCollect : ", tdc.StopCollect())


def exit_Ex(isByuser = 0):
    global isExist
    global isStart
    isExist = 0
    isStart = 0
    #停止采集
    print("StopCollect : ", tdc.StopCollect())
    #断开连接 
    print("\r\nDisConnectDevice : ", tdc.DisConnectDevice())
    if isByuser == 0:
        print("exit by user !")
    else:
        print("exit by call back!")

configGlobal()


def getDataThread():
    global isExist
    global isStart
    global channelEnable
    global algorithmType
    global triggerMode 
    while isExist == 1:
        while isStart != 0:
            for j in range(len(channelEnable)):  # 遍历所有通道
                if channelEnable[j] == 1:  # 打开的通道
                    if j==0 and triggerMode ==0:
                        continue
                    data = tdc.GetCollectDataByUserEx(j)  # 获取数据
                    print("channel:", data[0])
                    print("index:", data[1])
                    print("data:", data[2])
            cps = tdc.GetCpsByUser()
            #cps[0]是start通道，1-16为stop通道
            print("cps:", cps[2])
            if algorithmType&0x01 != 0:
                ret = tdc.TdcGetRandomLastBits(40)
                print("随机数: ",ret[0],"  ",ret[1])
            if (algorithmType & 0x06) != 0:
                ret = tdc.GetAccordByUser()
                print("符合计数: ", ret[0], "  ", ret[1])
            time.sleep(1)
        time.sleep(1)


t = threading.Thread(target=getDataThread)  # 放入线程执行
t.start()


def inputCMD():
    global isExist
    global isStart
    while isExist != 0:

        if isStart != 0:
            input(" enter stop ")
            stop()
        else:
            cmd = input("\r\n\
        -------------------------------------\r\n\
                    0.开始采集\r\n\
                    1.停止采集\r\n\
                    2.打开mark\r\n\
                    3.关闭Mark\r\n\
                    4.打开随机数\r\n\
                    5.关闭随机数\r\n\
                    6.保存随机数\r\n\
                    7.打开符合计数\r\n\
                    8.关闭符合计数\r\n\
                    9.退出\r\n\
        -------------------------------------\r\n\
                    input CMD:")
            if cmd == "0":
                configGlobal()
                start()
            elif cmd == "1":
                stop()
            elif cmd == "2":
                openMark()
            elif cmd == "3":
                closeMark()
            elif cmd == "4":
                openRandom()
            elif cmd == "5":
                closeRandom()
            elif cmd == "6":
                saveRandom()
            elif cmd == "7":
                openAccord()
            elif cmd == "8":
                closeAccord()
            elif cmd == "9":
                exit_Ex()


t1 = threading.Thread(target=inputCMD)  # 异步指令
t1.start()

