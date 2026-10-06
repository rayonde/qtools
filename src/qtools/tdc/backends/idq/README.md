# IDQ (ID Quantique) TDC 后端重构说明与技术指南

本项目针对 **ID Quantique (IDQ)** 的时间数字转换器（TDC）硬件体系进行了架构重构。由于 **ID801** 与 **ID1000** 存在完全不同的物理接口、底层协议及 FPGA 特性，本模块对两者进行了**独立 Backend 实现**，并在 `src/qtools/tdc/backends/idq/` 进行了统一组织与导出。

---

## 1. 架构总览与分离设计

### 1.1 硬件与通信差异对比

| 特性 | ID801 (`ID801Backend`) | ID1000 (`ID1000Backend`) |
| :--- | :--- | :--- |
| **物理接口** | USB 2.0 (Vendor ID: `0x16c0`) | 千兆以太网 (Gigabit Ethernet, RJ45) |
| **底层驱动方式** | C 共享动态库 (`libtdcbase.so`) | 网络套接字 (ZeroMQ over TCP) |
| **控制协议** | 厂商 C API / Python ctypes 包装 | 标准 SCPI 指令 (TCP 端口 5555) |
| **时间戳传输** | C 驱动内部轮询缓冲区 | 本地后台服务 `DataLinkTargetService.exe` (TCP 端口 6060) |
| **通道配置** | 8 个物理输入通道 | 5 个物理输入通道 (Start + Input 1~4) + 4 个输出通道 |
| **时间分辨率** | 约 81 ps | **1 ps** (HIRES 高分辨率模式) / 100 ps (LOWRES 模式) |
| **FPGA 计算能力** | 纯数据输出，上位机计算 | 内置硬件符合组合器 (TSCO) 与 4 路板载直方图 (HIST1~4) |

### 1.2 模块结构

```text
src/qtools/tdc/backends/idq/
├── __init__.py           # 模块统一入口，导出 ID801Backend, ID1000Backend, IDQBackend
├── backend.py            # 兼容层，重导出各后端类及历史别名 IDQBackend -> ID801Backend
├── backend_id801.py      # ID801 独立后端实现 (基于 USB / libtdcbase.so)
├── backend_id1000.py     # ID1000 独立后端实现 (基于 Ethernet / ZeroMQ / SCPI)
├── README.md             # 本技术文档与重构说明
├── README_ID1000_CN.md   # ID1000 官方 Python 示例解析与详细功能说明
├── TDC_ID801/            # 厂商参考资料：Harvey Mudd College ID801 驱动与源码
└── TDC_ID1000/           # 厂商参考资料：ID1000 用户手册、固件及 Python/SCPI Examples
```

### 1.3 注册标识符 (Registry Keys)

在 `qtools.tdc.connection` 全局注册表中注册了以下标识符：
- **ID1000**: `"id1000"`, `"idq_id1000"`
- **ID801**: `"id801"`, `"idq_id801"`, `"idq"` (向后兼容历史调用)

---

## 2. 已加入到 Backend 中的功能 (对齐 TDCBackend)

`ID1000Backend` 完整实现了 `qtools.tdc.backends.base.TDCBackend` 抽象基类定义的所有标准属性与方法：

### 2.1 基础属性与能力标记
- `name`: 返回 `"id1000"`。
- `vendor`: 返回 `"IDQ (ID Quantique)"`。
- `channel_count`: `5`（通道 1~4 对应物理 `INPUT 1~4`，通道 5 或 0 对应 `START`）。
- `resolution_ps`: 高分辨率模式下动态读取硬件时间基准（默认为 `1.0` ps）。
- `capabilities`: 标记支持 `SINGLES`、`TIMESTAMPS`、`HIST_HARDWARE`、`HIST_SOFTWARE`、`COINCIDENCE`、`COINCIDENCE_SOFTWARE`、`THRESHOLD_CONTROL`。

### 2.2 连接管理 (`connect`, `disconnect`, `is_connected`)
- **网络安全性预检查**：在建立 ZeroMQ 长连接前，先进行极轻量级的 TCP socket 连通性预探，设置 2 秒快速超时，避免在目标 IP 不可达时 ZeroMQ 发生阻塞挂起。
- **动态握手与模式配置**：自动执行 SCPI `*IDN?` 识别设备版本，自动下发 `DEVIce:RESolution HIRES` 开启 1 ps 模式，并查询 `DEVI:RES:BWID?` 校准时间分辨率。

### 2.3 单道计数采集 (`get_singles`)
- 按照传入的 `integration_time`（秒），为全部 4 个输入通道与 Start 通道配置周期计数模式 `COUN:MODE CYCL;INTE <ns>`。
- 批量下发 SCPI 计数查询 `INPU1:COUN?;:INPU2:COUN?;...;STARt:COUN?`，返回标准的 `SinglesResult`（包含计数值与每秒计数率）。

### 2.4 硬件加速符合计数 (`get_coincidence`)
- **硬件模式 (`method="hardware"`)**：
  - 自动加载 ID1000 FPGA 硬件符合模版 `DEVI:CONFI:LOAD COUNT`；
  - 根据通道组合自动路由至对应 TSCO 组合器（如 (1, 2) 路由至 `TSCO6`，(1, 3) 路由至 `TSCO7`，(2, 3) 路由至 `TSCO3`，(3, 4) 路由至 `TSCO5` 等）；
  - 硬件级配置延迟线与符合门宽（`WIND:BEGI:DELA`, `WIND:END:DELA`），直接从 FPGA 读取符合计数并估算泊松偶然符合本底，返回 `CoincidenceResult`；
- **软件模式 (`method="software"`)**：继承基类实现，支持通过采集时间戳离线计算。

### 2.5 直方图采集 (`get_hardware_histogram` 与 `get_g2`)
- **硬件直方图**：ID1000 具备 4 路内部硬件直方图生成模块（`HIST1`~`HIST4`），提供专有方法 `get_hardware_histogram(duration, bins, ch_start, ch_stop, ...)`：
  - 硬件自动绑定 REF 与 STOP 通道，支持通过硬件延迟线 `DELA` 增加时延；
  - 启动硬件 `REC:PLAY` 定时器采集，直接读取板载计算好的直方图 `HIST1:DATA?`，极大减轻上位机 CPU 计算负担；
- **软件 g2 接口**：标准统一接口 `get_g2(..., method="software")` 支持基于时间戳的二阶相关分析。

### 2.6 高通量时间戳记录 (`get_timestamps`)
- 与主机后台运行的 `DataLinkTargetService.exe`（DLT 服务，端口 6060）握手，通过 `start-save` 命令将时间戳无丢包存入本地临时二进制文件。
- 自动触发 `REC:PLAY` 并监控采集状态，采集结束后使用 NumPy 以 `np.uint64` 极速解析二进制时间戳并转换为皮秒单位，构建标准的 `TimestampResult`。
- 若主机未启动 DLT 服务，将给出清晰明确的指引提示。

### 2.7 比较器阈值与边沿控制 (`set_threshold`, `set_edge`)
- `set_threshold(threshold, channel=None)`：设置输入比较器鉴别电压（如 `-0.4V`），支持针对指定通道或全部通道。
- `set_edge(channel=None, edge="RISING")`：辅助方法，用于切换上升沿或下降沿触发。

### 2.8 设备自动寻址与安全探测机制 (`discover_devices`)

针对用户关心的“网络自动找寻设备是否安全”的需求，`ID1000Backend.discover_devices()` 实施了**安全隔离的无害探测策略**：

> [!IMPORTANT]
> **安全声明与策略**：
> 在企业网或高校局域网中，全网段（如 `/16` 或 `/24`）大规模 TCP 端口盲扫会被网络安全设备（如防火墙、IDS/IPS）判定为恶意内网扫描行为，且会导致严重的网络延迟与程序卡死。
> **因此，本模块绝不执行全网盲扫！**

**当前实现的安全探测步骤：**
1. **环境变量识别**：优先检查 `ID1000_IP` 或 `IDQ_IP` 环境变量；
2. **出厂默认链路探测**：仅针对 IDQ 出厂标准的固定直连网段 `169.254.99.100` ~ `169.254.99.105` 进行单点探测；
3. **系统 ARP 缓存只读分析**：调用操作系统本地 `arp -a` 缓存，仅提取当前网卡已经建立通信的本地 IP（只读系统表，不向网络发射广播流量）；
4. **轻量级 150ms 端口试探**：仅对上述少量的候选 IP 发起 5555 端口非阻塞 TCP 握手，成功后再发送 `*IDN?` 获取型号与序列号，确认属于 ID1000 后返回 `DeviceInfo`。

---

## 3. Examples 中存在但未并入通用 Backend 的高级功能

在官方参考代码 `TDC_ID1000/Examples` 中，存在许多 ID1000 专有的高级 FPGA 硬件特性。由于这些功能**超出了跨厂商通用 `TDCBackend` 的抽象范围**，未直接放入通用基类接口中，但用户可以通过 `ID1000Backend` 提供的辅助方法或 `exec_scpi()` 底层指令轻松调用：

### 3.1 任意脉冲生成器与延时生成器 (Pulse / Delay Generators)
- **对应示例**：`Examples/SCPI/tc_as_delay_generator_for_input1.txt`、`tc_as_trigged_pulse_train_generator.txt`、`synchronized_generators.txt`
- **功能描述**：ID1000 板载 8 个独立的内部脉冲生成器（`GEN1`~`GEN8`），可配置脉冲数量（`PNUM`）、脉宽（`PWID`）、周期（`PPER`），并能将输入信号延迟后从物理输出端口（`OUTP1`~`OUTP4`）输出 NIM 或 TTL 电平脉冲。
- **未并入通用 Backend 的原因**：通用 `TDCBackend` 抽象的是**时间测量设备**（输入端），而生成器属于**信号源/时钟源**（输出端）。
- **Python 使用方式**：
  ```python
  # 将 GEN1 配置为 10MHz 脉冲序列并通过 OUTP1 输出
  backend.exec_scpi("GEN1:ENAB ON;PPER 100000;PWID 4000;PNUM INF;PLAY")
  backend.exec_scpi("TSCO1:FIR:LINK GEN1;OPIN ONLYFIR;OPOUt ONLYFIR")
  backend.exec_scpi("OUTP1:ENAB ON;MODE NIM;LINK TSCO1")
  ```

### 3.2 时间窗口门控滤波直方图 (Gated / Filtered Histograms)
- **对应示例**：`Examples/Python/Histogram_acquisition_filtred/`
- **功能描述**：利用 ID1000 的 TSCO 组合器，设定在第三通道（如外部 Trigger 激光同步信号）到达后指定延迟（如 100 ns）打开一个宽度为 500 ns 的时间门，只有处于该时间窗内的探测器脉冲才会被统计进直方图，窗外信号被丢弃（`MUTE`）。
- **未并入通用 Backend 的原因**：高度依赖 ID1000 特有的内部门控触发拓扑结构，其他厂商 TDC（如 S-Fifteen, CIQTEK）无完全等价的硬件指令模型。
- **Python 使用方式**：
  ```python
  backend.exec_scpi("TSCO7:WIND:ENAB ON;:TSCO7:FIR:LINK DELA2")
  backend.exec_scpi("TSCO7:WIND:BEGI:LINK DELA3;DELAY 100000;EDGE RISING") # 门开延迟 100ns
  backend.exec_scpi("TSCO7:WIND:END:LINK DELA3;DELAY 600000;EDGE RISING")  # 门宽 500ns
  backend.exec_scpi("TSCO7:OPIN ONLYFIR;:TSCO7:OPOUt MUTE")
  backend.exec_scpi("HIST1:REF:LINK TSCO5;:HIST1:STOP:LINK TSCO7")
  ```

### 3.3 长时精准计数随时间演化轨迹 (Precise Counters Over Time)
- **对应示例**：`Examples/Python/Precise_counters_acquisition_over_time/`
- **功能描述**：通过巧妙地将直方图时间轴（Bin）与 RECord 生成器进行时间步进关联，记录多达 16,384 个连续时间片内的计数值，绘制计数率随时间的动态演变曲线。
- **未并入通用 Backend 的原因**：属于厂商专有的测量技巧，通用 `TDCBackend` 采用标准的轮询 `get_singles`。

### 3.4 流式时间戳实时接收与在线归并 (Timestamp Stream & Sync Merge)
- **对应示例**：`Examples/Python/Timestamp_acquisition_stream/`, `Timestamp_acquisition_sync_stream/`
- **功能描述**：通过本地后台多线程监听 DLT 的 ZeroMQ `PAIR` 套接字（`start-stream`），在内存缓冲区中动态对多通道时间戳进行交织排序（`TimestampsMergerThread`）。
- **未并入通用 Backend 的原因**：该模式需要用户常驻多线程并发消费者，且在超高计数率下 Python 垃圾回收容易导致内存膨胀，适合作为高级专用脚本运行，而非同步的 `get_timestamps()` 调用。

### 3.5 多台设备分布式级联同步 (Multi-Device Operation)
- **对应示例**：`Examples/Python/Timestamp_acquisition_multi_tc/`
- **功能描述**：基于主从树形拓扑（Master-Agent），通过公共同步时钟和线缆延时补偿（`wire_latency`），将多台 ID1000 级联同步，实现 64+ 通道的大规模时间测量系统。
- **未并入通用 Backend 的原因**：需要通过外部 `config.json` 描述网络物理拓扑，属于系统级多设备编排，超出了单个 `TDCBackend` 实例的管理职责。

### 3.6 采样错误排查与重新校准 (HIRES Sampling Error Diagnostics)
- **对应示例**：`Examples/Python/Inputs_status/`
- **功能描述**：查询输入通道是否存在由于计数率超限（>300 Mcps）或阈值不当引起的采样失真（错误码 1001~1003），并在需要时触发硬件重新校准 `DEVIce:SAMPling:RECAlibrate`。
- **集成支持**：`ID1000Backend` 已将此封装为 `get_input_status()` 与 `recalibrate()` 专有辅助方法。

---

## 4. 快速使用示例

### 4.1 使用高层统一接口 `TDC` 控制 ID1000

```python
from qtools.tdc import get_device

# 1. 连接设备 (指定 IP 地址)
tdc = get_device("id1000", port="169.254.99.100")

# 2. 设置通道 1 和 2 的鉴别阈值与边沿
tdc.backend.set_threshold(-0.2, channel=1)
tdc.backend.set_threshold(-0.2, channel=2)

# 3. 测量单道计数 (0.5 秒积分)
singles = tdc.get_singles(integration_time=0.5)
print(f"通道 1 计数率: {singles.count_rates[0]:.1f} cps")
print(f"通道 2 计数率: {singles.count_rates[1]:.1f} cps")

# 4. 硬件加速 2 重符合测量 (10 ns 符合窗口)
coinc = tdc.backend.get_coincidence(
    duration=1.0,
    ch_start=1,
    ch_stop=2,
    window_start=0,
    window_stop=10,
    unit="ns",
    method="hardware",
)
print(f"硬件符合计数: {coinc.count}, 偶然符合估计: {coinc.accidental_count}")

# 5. 板载硬件直方图测量 (1 ps 分辨率)
hist_res = tdc.backend.get_hardware_histogram(
    duration=1.0,
    bins=1000,
    ch_start=1,
    ch_stop=2,
    unit="ns",
)
print(f"直方图总事件数: {hist_res.histogram.sum()}")

# 6. 断开连接
tdc.backend.disconnect()
```

### 4.2 执行高级 SCPI 自定义指令

```python
from qtools.tdc.backends.idq import ID1000Backend

with ID1000Backend("169.254.99.100") as dev:
    # 诊断输入通道状态
    status = dev.get_input_status()
    print("输入通道状态:", status)
    
    # 直接下发任意原生 SCPI 指令
    response = dev.exec_scpi("DEVIce:RESolution?")
    print("当前采样模式:", response)
```
