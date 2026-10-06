# CIQTEK（国仪量子）TDC1610 后端

本后端将 **CIQTEK TDC1610** 时间数字转换器接入 `tdc` 框架。

- 后端名称（注册表 / CLI）：`tdc1610`
- 类：`TDC1610Backend`（`tdc.backends.ciqtek.backend`）
- 注册能力：`SINGLES | THRESHOLD_CONTROL`

## 硬件 / 平台

- TDC1610 是 **以太网连接** 的仪器，具有 **1 个 start 输入和 16 个 stop 输入**（共 17 路输入）。
- 厂商 SDK 通过 ctypes 加载 `TDC1610DLL_x64.dll`，这是一个 **Windows x64** 动态链接库，因此真实硬件访问需要 **Windows**。在其他平台上模块可以正常导入，但 `connect()` 会抛出 `ImportError`。
- 厂商 SDK 文件（`tdc1610SDK.py`、`errorCode.py`、`tdc1610example.py`、DLL 等）作为参考材料**原样保留**在 `libs/` 目录下，未做任何修改。

## 连接流程

1. `FindDevice()` —— UDP 广播网络搜索；每台设备用
   `[index, local_ip, des_ip, dst_mac, dst_name]` 描述。
2. `ConnectDevice(local_ip, des_ip, dst_mac)` —— 建立以太网连接。
3. 如果设备报告需要校准，会自动执行码密度校准（默认 `calibrate=True`）。
4. 配置：触发模式、时钟、逐通道 使能/触发方式/阈值(mV)/延迟(ps)、时间分辨率、动态范围、绘图窗口。
5. 采集循环：`StartCollect()` → 读取数据 → `StopCollect()`。
6. `DisConnectDevice()` —— 解除固件的 IP 锁定。

## 通道映射

统一的 1-based 通道模型与 SDK 通道的对应关系：

| 物理通道 | SDK 通道 | 含义 |
|----------|----------|------|
| 1        | 0        | start（触发） |
| 2 … 17   | 1 … 16   | stop1 … stop16 |

单位遵循厂商 SDK：阈值为**毫伏（mV）**（`-5000..5000`），延迟为**皮秒（ps）**（`-200000..200000`）。

## 返回的数据格式

| 方法 | 结果类型 | 状态 | 内容 | 厂商 SDK 数据来源 |
|---|---|---|---|---|
| `get_singles()` | `SinglesResult` | 支持 | `counts`（17, uint64）、`count_rates`（cps）、`integration_time` | `GetCpsByUser()` → 计数率 `[start, stop1..16]`；counts = `rate × 时长` |
| `get_timestamps()` | `TimestampResult` | **不支持** | — | SDK 没有原始时间戳流 |
| `compute_g2()` | `G2Result` | **不支持** | — | 软件 g² 需要原始时间戳 |

## Raw Timestamps vs. 直方图（重要）

- 厂商 SDK **不提供**类似 S15 / IDQ 驱动的逐事件原始时间戳流。TDC1610 本质是时间间隔分析仪：对每个通道在配置的动态范围内累积 **直方图（时间谱）**。
- `GetCollectDataByUserEx(channel)` 返回
  `(channel, index_list, data_list, is_new)`，其中 `index_list` 是非零 bin 的位置，`data_list` 是这些 bin 中的事件计数。
- 因此本后端**不会伪造时间戳**：`get_timestamps()` 和 `compute_g2()` 会抛出 `NotImplementedError`。计数率请用 `get_singles()`，硬件符合计数请用 `get_accord_counts()`。

### 直方图的参考通道

- 在**外触发模式**（`trigger_mode=0`）下，start 通道（SDK 通道 0 / 物理通道 1）就是触发源：每个 stop 通道的直方图表示其事件**相对 start（触发）事件**的时间，即 x = `t_stop − t_start`。
- 在**内触发模式**（`trigger_mode=1`）下，参考源是**内部时钟触发**（`ConfigClockPeriod`），各通道（含 start 通道）的直方图都相对这些内部触发累积。
- 参考通道**无法通过 SDK 直接指定**——它由触发配置隐含决定。（该结论依据厂商示例推断，如有疑问请在硬件上验证。）
- **外触发的触发源固定为 start 输入**（SDK 通道 0 / 物理通道 1），SDK 没有把触发源改到其他 stop 通道的接口；如果要用别的输入做触发，请在硬件上把该信号接到 start 输入。符合计数通道（`configure_accord()`，物理通道 1–17）可独立于触发源任意配置。

## 硬件符合计数（示例：物理通道 3 与 4）

TDC1610 可以在任意已使能的通道之间做硬件符合计数：两个通道为二重符合，三个通道为三重符合。

```python
import time

backend.set_algorithm(0x02)   # 开启二重符合算法
backend.configure_accord(     # 物理通道（1-based）
    code_width_ps=352,        # 符合门宽（ps）；必须是分辨率（8 ps）的整数倍
    channel1=3,
    channel2=4,
)
backend.start_collect()
time.sleep(1.0)
backend.stop_collect()

accord = backend.get_accord_counts()
# -> [符合计数, ch3 计数率, ch4 计数率, 0]（二重符合时第 4 项未使用）
```

注意事项：

- 符合门宽（`code_width_ps`）必须是时间分辨率的整数倍，否则 SDK 返回错误 16385。
- 只有已使能的通道参与符合（默认全部 17 路都使能）。
- 符合计数在采集中累积，因此顺序是 `start_collect()` → 等待 → `stop_collect()` → `get_accord_counts()`。
- SDK 只返回**总符合数**，没有按延迟展开的 g² 直方图（那需要原始时间戳，SDK 不提供）。
- 符合门**锚定在 start（触发）事件**上：SDK 只接受门**宽度**，没有门位置/偏移参数。要移动窗口位置只能靠**逐通道延迟**（`set_channel_config(..., delay=...)`，±200 ns；厂商注释在 ns/ps 单位上表述不一致，真机需验证）。

## 使用方法

```python
from tdc.connection import get_backend

backend_cls = get_backend("tdc1610")
backend = backend_cls()

devices = backend.discover_devices()
backend.connect()  # 或 backend.connect(devices[0].device_path)

# 单光子计数（计数率）—— 支持：
singles = backend.get_singles(integration_time=1.0)

# 原始时间戳 / 软件 g2 —— 不支持（会抛 NotImplementedError）：
# ts = backend.get_timestamps(duration=1.0)
# g2 = backend.get_g2(...)

# 硬件符合计数 —— 支持（先开启符合算法）：
backend.set_algorithm(0x02)
backend.start_collect()
time.sleep(1.0)
backend.stop_collect()
accord = backend.get_accord_counts()

backend.disconnect()
```

`connect()` 支持以下可选 kwargs：

- `dev_info`：完整的厂商设备条目 `[index, local_ip, des_ip, dst_mac, dst_name]`。
- `calibrate=True`（默认）：在需要时运行码密度校准。
- `trigger_mode`、`clock_period_ns`、`resolution_ps`（8/16/32/64/128/256/1024）、
  `dynamic_range_ps`、`draw_window_ps`、`clock_input_type`、
  `clock_input_value`、`clock_output`、`collect_time_ms`、`fresh_time_s`、
  `error_callback`：连接后应用的初始配置。

## SDK Extensions（不属于 `TDCBackend` 接口）

以下厂商特有方法位于 `TDC1610Backend` 类的末尾，**不属于**通用的 `TDCBackend` 接口：

| 分组 | 方法 | 说明 |
|---|---|---|
| 采集控制 | `start_collect()`、`stop_collect()` | 显式开始/停止采集 |
| 配置 | `set_trigger_mode()`、`set_clock_period()`、`set_time_resolution()`、`set_dynamic_range()`、`set_draw_window()`、`set_clock()`、`set_collect_time()`、`set_fresh_time()`、`set_channel_config()`、`set_error_callback()` | 触发、时钟、窗口以及逐通道 使能/触发方式/阈值/延迟 |
| 校准 | `calibrate()`、`get_calibration_result()` | 码密度校准 |
| 符合计数 | `set_algorithm()`、`reset_algorithm()`、`configure_accord()`、`get_accord_counts()` | 硬件二重 / 三重符合 |
| QRNG | `configure_random()`、`get_random_bits()`、`save_random()` | 量子随机数生成 |
| Mark 触发 | `configure_mark()`、`set_mark_max_delay()`、`set_mark_save_path()`、`get_mark_status()` | 外部 mark 信号触发 |

## 建议下放到 `TDCBackend` 的功能

以下 TDC1610 功能适合加入通用的 `TDCBackend` 接口，让其他后端（如 IDQ、S-Fifteen）也实现：

1. **硬件符合计数** —— `get_coincidence_counts()`：对应 `GetAccordByUser()`；IDQ 驱动里已有等价实现（`wait_to_get_coinc_counters_for`）。对快速 pairs 测量价值很高。
2. **显式采集启停** —— `start_acquisition()` / `stop_acquisition()`：便于长时间连续采集和多设备同步；可直接映射到 `start_collect()` / `stop_collect()`。
3. **实时计数率** —— `get_cps()`：便于光路对准和实时监控；base 可以用 `get_singles()` 派生默认实现。
4. **校准** —— `calibrate()`：通用的设备维护操作。

`TDCBackend.get_g2(method="software")` 为能提供原始时间戳的后端提供通用的 "`get_timestamps()` + `tdc.analysis.g2.compute_g2`" 实现。backend 如果支持硬件 g²，可以重写同一个方法处理 `method="hardware"`；这不适用于 TDC1610。

以下内容保持 TDC1610 特有：QRNG、Mark 触发、动态范围 / 绘图窗口、触发模式 / 时钟配置，以及底层错误回调。

## 备注

- `get_singles()` 使用 `GetCpsByUser()`（设备上报的每秒计数率）；counts 由 `rate × integration_time` 重构。
- `get_timestamps()` / `compute_g2()` 有意不支持：SDK 只返回逐通道直方图——详见上文"Raw Timestamps vs. 直方图"。
- 厂商 SDK 在加载 DLL 时会向 stdout 打印一些启动信息，并且会缓存单例实例；这是上游 SDK 的行为。
