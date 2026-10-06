# IDQ ID1000 Time Controller Python 使用说明 (README_ID1000_CN)

本文档基于官方参考资料（`TDC_ID1000/Examples/Python`）编写，重点介绍 **ID1000** 的 **Python 驱动使用方法**、**通信架构**以及**各功能模块的代码实现**。

---

## 1. 通信架构与环境准备

ID1000 是基于网络通信的数字时间转换器（TDC），Python 端无需专有 C 驱动，而是通过网络套接字（Socket）进行通信：

1. **SCPI 命令控制层 (Port 5555)**
   - 使用 **ZeroMQ (`pyzmq`)** 的 `REQ-REP` 模式与设备建立 TCP 连接。
   - 所有硬件参数配置、状态查询、符合计数及直方图读取均通过 SCPI 文本指令完成。
2. **高通量时间戳数据传输层 (DLT, Port 6060)**
   - 由上位机本地后台运行的 `DataLinkTargetService.exe`（随官方上位机安装）负责监听并接收时间戳数据包。
   - Python 脚本通过 ZeroMQ 端口 6060 与 DLT 服务交互，控制时间戳文件存盘（`.bin` / `.txt`）或通过 ZeroMQ `PAIR` 套接字实现本地流式传输。

### 依赖安装
```bash
pip install pyzmq numpy matplotlib
```

---

## 2. 核心功能及 Python 实现

在 `Examples/Python` 中，官方提供了完整的模块化封装，涵盖以下主要功能：

### 2.1 建立连接与执行 SCPI 指令 (`utils/common.py`)
所有操作的基础，通过 ZeroMQ 发送 SCPI 字符串并接收返回结果：

```python
import zmq

def connect(address: str, port: int = 5555):
    """连接到 ID1000 设备"""
    context = zmq.Context()
    tc = context.socket(zmq.REQ)
    tc.connect(f"tcp://{address}:{port}")
    return tc

def zmq_exec(tc, cmd: str) -> str:
    """发送 SCPI 命令并获取设备响应"""
    tc.send_string(cmd)
    ans = tc.recv().decode("utf-8")
    return ans

# 示例：连接并查询设备
tc = connect("169.254.99.100")
print("设备状态:", zmq_exec(tc, "*IDN?"))
print("时间分辨率:", zmq_exec(tc, "DEVI:RES:BWID?"))  # ID1000 高精度模式为 1 ps
```

---

### 2.2 通道状态监测与错误处理 (`Inputs_status/inputs_status.py`)
用于检查各物理输入通道（Start, Input 1~4）工作状态，排查高频过载、过密脉冲或需要重新校准的情况：

```python
def check_channel_status(tc):
    is_hires = zmq_exec(tc, "DEVIce:RESolution?") == "HIRES"
    for ch in range(0, 5):
        block = "STARt" if ch == 0 else f"INPU{ch}"
        if is_hires:
            err_code = int(zmq_exec(tc, f"{block}:HIRES:ERROR?"))
            zmq_exec(tc, f"{block}:HIRES:ERROR:CLEAR")  # 清除错误标志
            print(f"通道 {block} 状态码: {err_code}")
        # 常见错误码含义：
        # 0: 正常
        # 1: 需要重新校准 (发送 DEVIce:SAMPling:RECAlibrate)
        # 1001-1003: 计数率过高或阈值不良，请调节输入阈值或降低触发率
```

---

### 2.3 单通道计数与多重符合计数 (`Coincidence_counters_acquisition`)
ID1000 内部硬件可在 FPGA 级配置符合窗口，直接输出各通道单计数（Singles）以及 2重、3重、4重符合计数（Coincidences）。

- **内部预置配置**：通过 `DEVI:CONFI:LOAD COUNT` 加载硬件计数布线。
- **符合时间窗口配置**：通过设置各输入端延迟块（`DELA`）及组合器（`TSCO`）的时间窗口。

**Python 实现核心逻辑 (`utils/acquisitions/coincidences.py`)**：
```python
# 1. 配置符合窗口与积分时间
def configure_coincidences(tc, coincidence_window_ps: int, integration_time_ns: int = 1000):
    # 加载符合计数硬件模版
    zmq_exec(tc, "DEVI:CONFI:LOAD COUNT")
    
    # 设置输入通道延时偏移，防止硬件时钟死锁/边界竞争
    # 例如：INPU2 + window, INPU3 + 2*window, INPU4 + 3*window
    zmq_exec(tc, f"DELA6:VALU {coincidence_window_ps * 1}")
    zmq_exec(tc, f"DELA7:VALU {coincidence_window_ps * 2}")
    zmq_exec(tc, f"DELA8:VALU {coincidence_window_ps * 3}")

    # 设置 TSCO (Time Specific Combiner) 符合窗口的起始与结束时间
    # 2重符合: TSCO6(1/2), TSCO7(1/3), TSCO8(1/4), TSCO3(2/3), TSCO4(2/4), TSCO5(3/4)
    # 3重符合: TSCO13(1/2/3), TSCO14(1/2/4), TSCO15(1/3/4), TSCO16(2/3/4)
    # 4重符合: TSCO24(1/2/3/4)
    # 设置计数器模式 (CYCL: 循环周期模式；ACCU: 累积模式)
    zmq_exec(tc, f"INPU1:COUN:MODE CYCL;INTE {integration_time_ns};RESEt")

# 2. 一次性批量读取所有计数器
def read_counters(tc):
    blocks = [
        "STARt", "INPU1", "INPU2", "INPU3", "INPU4",     # 单通道
        "TSCO6", "TSCO7", "TSCO8", "TSCO3", "TSCO4", "TSCO5", # 2重符合
        "TSCO13", "TSCO14", "TSCO15", "TSCO16",          # 3重符合
        "TSCO24"                                         # 4重符合
    ]
    query = ";:".join([f"{blk}:COUNter?" for blk in blocks])
    resp = zmq_exec(tc, query)
    counts = [int(x) for x in resp.splitlines()]
    return dict(zip(blocks, counts))
```

---

### 2.4 实时 Start-Stop 直方图采集 (`Histogram_acquisition`)
ID1000 支持在板卡内部实时构建 4 组独立的 Start-Stop 直方图（`HIST1` ~ `HIST4`），极大节省上位机传输与计算开销。

**Python 实现核心逻辑 (`utils/acquisitions/histograms.py`)**：
```python
def acquire_histograms(tc, duration_s: float, bin_width_ps: int, bin_count: int, hist_list=[1]):
    # 1. 配置 RECord 记录生成器作为采样定时器
    zmq_exec(tc, "REC:TRIG:ARM:MODE MANUal")
    zmq_exec(tc, "REC:ENABle ON")
    zmq_exec(tc, "REC:STOP")
    zmq_exec(tc, "REC:NUM 1")
    zmq_exec(tc, f"REC:DURation {int(duration_s * 1e12)}") # 单位：ps

    # 2. 配置各直方图通道参数
    for i in hist_list:
        zmq_exec(tc, f"HIST{i}:BCOUnt {bin_count}")  # 最大 bin 数量 (1~16384)
        zmq_exec(tc, f"HIST{i}:BWID {bin_width_ps}") # bin 宽度 (ID1000 最小为 1 ps)
        zmq_exec(tc, f"HIST{i}:FLUSh")               # 清空直方图缓存

    # 3. 启动采集并等待结束
    zmq_exec(tc, "REC:PLAY")
    while zmq_exec(tc, "REC:STAGe?").upper() == "PLAYING":
        time.sleep(0.5)

    # 4. 获取直方图数据 (返回为 Python 列表字符串)
    histograms = {}
    for i in hist_list:
        raw_data = zmq_exec(tc, f"HIST{i}:DATA?")
        histograms[i] = eval(raw_data) # 解析为 list of int
    return histograms
```

---

### 2.5 滤波直方图采集 (`Histogram_acquisition_filtred`)
可在硬件上给 Stop 通道增加时间门控窗口（Window Filter），仅统计在外部 Trigger 或 Start 事件后指定延迟（`window_delay`）并在指定时间窗口（`window_duration`）内到达的脉冲：
```python
# 示例：INPU2 作为 Stop，仅在 INPU3 (Trigger) 到达后 100ns 打开 500ns 的观测窗口
zmq_exec(tc, "TSCO7:WIND:ENAB ON;:TSCO7:FIR:LINK DELA2")
zmq_exec(tc, "TSCO7:WIND:BEGI:LINK DELA3;DELAY 100000;EDGE RISING") # 100,000 ps = 100 ns
zmq_exec(tc, "TSCO7:WIND:END:LINK DELA3;DELAY 600000;EDGE RISING")  # 600,000 ps = 600 ns
zmq_exec(tc, "TSCO7:OPIN ONLYFIR;:TSCO7:OPOUt MUTE") # 窗口内放行信号，窗口外静音
zmq_exec(tc, "HIST1:REF:LINK TSCO5;:HIST1:STOP:LINK TSCO7") # 关联到直方图
```

---

### 2.6 计数率随时间轨迹监测 (`Precise_counters_acquisition_over_time`)
通过将直方图模块的采样源按时间推进，可以采集连续 $N$ 个时间段（如每 1 秒统计一次）的计数值，输出计数率随时间的动态演化曲线（Trace）。

---

### 2.7 原始时间戳采集与存盘 (`Timestamp_acquisition`)
当需要进行无损的二阶相干度 $g^{(2)}(\tau)$、多光子时间关联分析时，需采集原始纳秒/皮秒级时间戳（Timestamps）。

时间戳采用 **DLT 服务** 协助保存，避免 Python 单线程由于网络 I/O 阻塞导致丢包：
1. Python 连接本地 DLT 服务：
   ```python
   # 启动并连接 DataLinkTargetService.exe
   dlt = connect("localhost", port=6060)
   ```
2. 发送开始存盘命令：
   ```python
   # 指示 DLT 将指定通道的数据保存至本地磁盘
   # format 可为 'bin' (二进制, 速度快) 或 'ascii' (文本)
   cmd = f'start-save --address {tc_ip} --channel 1 --filename "C:/Temp/ch1.bin" --format bin'
   resp = json.loads(zmq_exec(dlt, cmd))
   acq_id = resp["id"]

   # 开启板卡端时间戳流
   zmq_exec(tc, "RAW1:SEND ON")
   zmq_exec(tc, "REC:PLAY") # 配合 RECord 控制采集时长
   ```
3. 采集结束时停止并保存：
   ```python
   zmq_exec(tc, "RAW1:SEND OFF")
   zmq_exec(dlt, f"stop --id {acq_id}")
   ```

---

### 2.8 二进制时间戳读取与解析 (`Read_binary_timestamps/read_binary_timestamps.py`)
ID1000 保存的 `.bin` 格式时间戳使用 64 位无符号整数存储，解析极快：

```python
import numpy as np

def read_binary_timestamps(filepath: str, with_ref_index: bool = True):
    """
    读取 ID1000 原始二进制时间戳
    - timestamp: 64 位时间数值 (单位对应硬件的分辨率，如 1 ps)
    - refIndex: 64 位参考脉冲计数索引 (若启用 with_ref_index)
    """
    if with_ref_index:
        dtype = np.dtype([("timestamp", np.uint64), ("refIndex", np.uint64)])
    else:
        dtype = np.uint64
    return np.fromfile(filepath, dtype=dtype)

# 读取并展示前 5 个时间戳
data = read_binary_timestamps("C:/Temp/ch1.bin", with_ref_index=True)
for i in range(min(5, len(data))):
    print(f"Index: {i}, Timestamp: {data[i]['timestamp']} ps, Ref: {data[i]['refIndex']}")
```

---

### 2.9 流式时间戳实时接收与合并 (`Timestamp_acquisition_stream` / `sync_stream`)
如果需要实时处理数据而不想等写入硬盘后再读入，可让 DLT 服务建立一个本地 ZeroMQ 转发套接字（`start-stream`）：
- Python 启动 `StreamClient` 监听对应端口（如 `4241 + channel`）。
- 接收端通过线程从 ZeroMQ `PAIR` 套接字批量接收二进制数据块。
- 在内存中通过 `array.array('Q')` 或 `np.frombuffer` 解析，并按时间戳先后次序归并多通道事件（`TimestampsMergerThread`）。

---

### 2.10 多台设备同步级联采集 (`Timestamp_acquisition_multi_tc`)
支持通过配置文件（`config.json`）管理多台 ID1000 组成的树形网络（Master-Agent 拓扑）：
- 主机（Master）通过输出通道发送公共同步触发脉冲到从机（Agent）的 `START` 通道。
- 软件通过补偿各物理同轴线的线缆延迟（`wire_latency`），在 Python 端实现多台设备（64+ 通道）的时间基准严格统一。

---

## 3. 典型代码示例：快速获取单通道与符合计数

以下提供一个可直接供业务调用的最小集成代码范例：

```python
import time
import zmq

class ID1000Controller:
    def __init__(self, ip: str, port: int = 5555):
        self.ip = ip
        self.port = port
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.REQ)
        self.sock.connect(f"tcp://{ip}:{port}")

    def query(self, cmd: str) -> str:
        self.sock.send_string(cmd)
        return self.sock.recv().decode("utf-8").strip()

    def setup_channel(self, ch: int, threshold_v: float = -0.4, edge: str = "RISING"):
        """配置通道阈值与触发边沿"""
        block = "STARt" if ch == 0 else f"INPU{ch}"
        self.query(f"{block}:ENAB ON;THRE {threshold_v}V;EDGE {edge};COUP DC;SELE UNSHAPED")

    def get_counts(self, integration_ms: int = 1000):
        """配置并获取 1 秒内的单道计数值"""
        # 设置积分时间 (ns) 与循环模式
        for ch in range(1, 5):
            self.query(f"INPU{ch}:COUN:MODE CYCL;INTE {integration_ms * 1000000};RESEt")
        time.sleep(integration_ms / 1000.0)
        
        counts = {}
        for ch in range(1, 5):
            counts[f"ch{ch}"] = int(self.query(f"INPU{ch}:COUN?"))
        return counts

    def close(self):
        self.sock.close()
        self.ctx.term()

if __name__ == "__main__":
    tc = ID1000Controller("169.254.99.100")
    tc.setup_channel(1, threshold_v=-0.2, edge="RISING")
    tc.setup_channel(2, threshold_v=-0.2, edge="RISING")
    print("各通道计数:", tc.get_counts(integration_ms=500))
    tc.close()
```

---

## 4. 总结与集成建议

| 功能需求 | 推荐实现方式 | 优势 |
| :--- | :--- | :--- |
| **单路计数 (Singles)** | SCPI `INPU#:COUN?` 轮询 | 轻量、无依赖，毫秒级响应 |
| **符合计数 (Coincidences)** | SCPI 加载 `COUNT` 预设，读取 `TSCO#:COUN?` | FPGA 硬件计算符合，速度极快 |
| **Start-Stop 直方图** | 硬件 `HIST#:DATA?` | 内部硬件构建直方图，不占用计算机 CPU |
| **原始时间戳 (Timestamps)** | 借助 `DataLinkTargetService.exe` 存盘或 ZMQ 流传输 | 支持亿级事件采集，不丢包 |
| **离线关联分析** | `numpy.fromfile(..., dtype=np.uint64)` | 极速解包二进制时间戳，可无缝对接 `qtools` 的 C++ 关联核 |
