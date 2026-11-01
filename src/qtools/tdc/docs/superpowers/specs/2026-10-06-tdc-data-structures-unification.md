# TDC 数据结构精简与统一方案设计 (TDC Data Structures Unification Design)

- **作者/设计者**: AI Assistant & rayonde
- **日期**: 2026-10-06
- **最近修订**: 2026-11-02（三个结果模型统一支持固定通道配置下的重复采样；门控模型明确 heralding/gated 通道角色；采集结果支持 marker）
- **实现状态**: 已完成代码迁移及离线验证；真实设备验证待连接硬件后执行。
- **目标模块**: `qtools.tdc.data`, `qtools.tdc.analysis`, `qtools.tdc.backends`, `qtools.tdc.measurement`, `qtools.tdc.api`

---

## 1. 背景与现状分析 (Background & Motivation)

在 `qtools.tdc` 目前的设计中，数据表示层（`qtools.tdc.data`）定义了多种并列的数据结构：
1. **基础数据结构**：
   - `DeviceInfo`：静态硬件设备发现与连接元数据（保留）；
   - `SinglesResult`：单通道计数率与累计计数（保留）；
   - `TimestampResult`：原始事件级时间戳与通道流（保留）。


---

## 2. 目标统一架构 (Target Architecture)

本方案拟将重合度高的数据模型整合精简为以下 **3 个符合/关联类**（加上原有的 3 个基础类，共 6 个清晰的正交数据模型）：

```
原有模型 (5+1)                         统一后模型 (3)
──────────────────────────             ──────────────────────────
G2Result                 ──┐
                           ├───►       CoincidenceResult
CoincidenceResult        ──┘           (两通道时延直方图与积分符合)

TripletResult            ──┐
                           ├───►       MultiCoincidenceResult
GateResult               ──┘           (N 通道符合，N >= 3)

GatePhotonResult         ──┐
                           └───►       HeraldingGateResult
                                       (门控光子流与门内光子统计)
```

### 模型定位与职责划分
1. **`CoincidenceResult`**：两通道关联与符合的核心模型。单次与多次采样均返回同一个类；`samples` 表示实际完成的采样次数，逐次测量数据统一按列表保存。既能容纳软件分析生成的完整 $g^{(2)}(\tau)$ 直方图与归一化曲线，也能容纳硬件 FPGA（如 TDC1、CIQTEK accord、ID1000 TSCO）直接给出的逐次标量符合计数与偶然估算。
2. **`MultiCoincidenceResult`**：固定一组通道的多通道符合（$N \ge 3$）模型。通道配置只记录一次，`samples` 表示同一配置下的重复测量次数；逐次数据按列表保存，两两直方图用实际通道对标记。整合三通道交叉关联与任意 $N$ 通道星型门控符合、事件列表，并提供高阶符合计数率的均值与标准差。
3. **`HeraldingGateResult`**：一个 heralding 通道与多个 gated 通道的门控光子结果模型。`heralding_channel` 和 `gated_channels` 只记录一次，`samples` 表示同一配置下的重复采样次数；按实际 gated 通道编号保存逐次门内计数、直方图、计数率及其均值和标准差，按需保存门与光子的对应明细。
---

## 3. 详细设计与数据模型定义 (Data Models)

### 3.1 统一后的 `CoincidenceResult`

`CoincidenceResult` 表示同一对通道、同一测量配置下的一次或多次采样。
`samples=1` 时也使用列表，不在单次与多次测量之间切换返回类型。
以下代码定义字段与派生属性；构造校验要求见本节末尾及 3.4 节。

```python
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
from numpy.typing import NDArray


@dataclass(kw_only=True)
class CoincidenceResult:
    """Repeated two-channel correlation and window-count results.

    ``mode="histogram"`` stores full g² delay histograms.
    ``mode="window_count"`` stores window counts with optional histograms.
    Every measurement list has length ``samples``.
    Time fields use ``unit``, with integer ps by default.
    ``integration_time`` is always in seconds.
    """

    # Shared settings; samples counts completed acquisitions.
    mode: Literal["histogram", "window_count"]
    bin_width: int  # Time resolution per bin, shared across samples.
    samples: int = 1
    unit: str = "ps"
    channel_start: int
    channel_stop: int
    method: Literal["software", "hardware"] = "software"

    # Index i identifies the same acquisition in every list.
    counts_start: Optional[list[int]]
    counts_stop: Optional[list[int]]
    singles_start: list[float]
    singles_stop: list[float]
    integration_time: list[float]

    # Additional delay applied to the stop channel per acquisition.
    # Use [0] * samples for zero delay; negative delays are allowed.
    stop_delay: list[int]

    # Histogram and time axis per acquisition.
    n_bins: Optional[list[int]] = None
    stop_offset: Optional[list[int]] = None
    histogram: Optional[list[NDArray[np.uint64]]] = None
    bin_edges: Optional[list[NDArray[np.int64]]] = None

    # Window and counts per acquisition; windows are half open [start, stop).
    window_start: Optional[list[int]] = None
    window_stop: Optional[list[int]] = None
    raw_counts: Optional[list[int]] = None
    accidental_counts: Optional[list[float]] = None
    accidental_counts_per_bin: Optional[list[float]] = None
    accidental_method: Optional[list[Literal["sideband", "rate_product"]]] = None

    @property
    def window_width(self) -> Optional[list[int]]:
        if self.window_start is None or self.window_stop is None:
            return None
        return [
            stop - start
            for start, stop in zip(self.window_start, self.window_stop, strict=True)
        ]

    @property
    def window_n_bins(self) -> Optional[list[int]]:
        """Return each window width divided by bin_width, rounded up."""
        widths = self.window_width
        if widths is None:
            return None
        return [
            (width + self.bin_width - 1) // self.bin_width
            for width in widths
        ]

    @property
    def normalized(self) -> Optional[list[NDArray[np.float64]]]:
        """Normalize each acquisition independently, preserving sample order."""
        if (
            self.mode != "histogram"
            or self.histogram is None
            or self.bin_edges is None
        ):
            return None
        unit_to_s = {"ps": 1e-12, "ns": 1e-9, "us": 1e-6, "ms": 1e-3}
        if self.unit not in unit_to_s:
            raise ValueError(f"Unsupported time unit: {self.unit!r}")
        curves = []
        for hist, edges, start, stop, duration in zip(
            self.histogram,
            self.bin_edges,
            self.singles_start,
            self.singles_stop,
            self.integration_time,
            strict=True,
        ):
            bin_width_s = np.diff(edges) * unit_to_s[self.unit]
            denominator = start * stop * bin_width_s * duration
            curves.append(
                np.divide(
                    hist,
                    denominator,
                    out=np.zeros_like(denominator, dtype=np.float64),
                    where=denominator > 0,
                )
            )
        return curves

    @property
    def net_counts(self) -> Optional[list[float]]:
        if self.raw_counts is None or self.accidental_counts is None:
            return None
        return [
            float(raw) - accidental
            for raw, accidental in zip(
                self.raw_counts, self.accidental_counts, strict=True
            )
        ]

    @property
    def raw_pair_rate(self) -> Optional[list[float]]:
        if self.raw_counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(
                self.raw_counts, self.integration_time, strict=True
            )
        ]

    @property
    def acc_pair_rate(self) -> Optional[list[float]]:
        if self.accidental_counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(
                self.accidental_counts, self.integration_time, strict=True
            )
        ]

    @property
    def net_pair_rate(self) -> Optional[list[float]]:
        counts = self.net_counts
        if counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(counts, self.integration_time, strict=True)
        ]

    @property
    def raw_pair_rate_mean(self) -> Optional[float]:
        rates = self.raw_pair_rate
        return None if rates is None else float(np.mean(rates))

    @property
    def raw_pair_rate_std(self) -> Optional[float]:
        rates = self.raw_pair_rate
        if rates is None or len(rates) < 2:
            return None
        return float(np.std(rates, ddof=1))

    @property
    def net_pair_rate_mean(self) -> Optional[float]:
        rates = self.net_pair_rate
        return None if rates is None else float(np.mean(rates))

    @property
    def net_pair_rate_std(self) -> Optional[float]:
        rates = self.net_pair_rate
        if rates is None or len(rates) < 2:
            return None
        return float(np.std(rates, ddof=1))

```

#### 采样维度与字段约束

- `samples` 是实际完成并保存在结果中的采样次数，为正整数；不是计划次数，也不是符合事件数。测量入口可以默认 `samples=1`，单次与多次采样始终返回 `CoincidenceResult`。
- `mode`、`unit`、`method`、`channel_start`、`channel_stop`、`bin_width` 是整组公共配置，使用标量；起止通道必须不同。`bin_width: int` 表示单个 bin 的时间分辨率，所有采样共用；逐次计数、计数率、采集时间、延迟、`n_bins`、`stop_offset`、窗口参数及偶然估计方法使用列表。公共配置与 `*_mean`、`*_std` 汇总属性不属于逐次数据列表。
- 所有必需列表以及非 `None` 的可选列表，长度必须严格等于 `samples`。索引 `i` 在所有列表中表示同一次采样。不接收标量作为列表的替代，不隐式广播或截断。
- 可选字段为 `None` 表示整组采样未提供该信息；提供时必须包含每次采样的数据，不使用含 `None` 元素的列表，也不在求平均时静默跳过缺失项。
- `counts_start[i]`、`counts_stop[i]` 是第 `i` 次采样的原始 singles 计数，`integration_time[i]` 是该次实际有效采集时间。`singles_start[i]`、`singles_stop[i]` 使用同一次有效采集时间计算。后端提供实际计数，不通过对计数率乘时间并取整来伪造原始计数。仅硬件接口确实不提供 singles 原始计数时（如 CIQTEK accord），对应 counts 列表允许整组为 `None`，保留设备直接报告的 singles 计数率。软件分析必须提供实际计数。
- `bin_width > 0`，其单位由 `unit` 指定。明确采用延迟坐标 `tau = (t_stop + stop_delay[i]) - t_start`；`stop_delay[i]` 可正可负。`stop_offset[i]` 只决定直方图时间轴的起点，不对事件再次施加延迟。
- `histogram` 模式必须提供 `histogram`、`bin_edges`、`n_bins`、`stop_offset` 四个列表；`window_count` 模式可整组省略它们，提供时也必须四者齐全。对每个 `i`：`len(histogram[i]) == n_bins[i]`，`len(bin_edges[i]) == n_bins[i] + 1`，`bin_edges[i][0] == stop_offset[i]`，相邻边界差均等于公共标量 `bin_width`。
- `window_count` 模式必须提供 `raw_counts`，通常同时提供 `window_start`、`window_stop`；仅硬件固定门宽不可查询时（如 S15 TDC1 pairs），窗口两列表允许同时为 `None`，不捏造门宽；`histogram` 模式可以在提供窗口时附带这些统计。每次窗口都满足 `window_stop[i] > window_start[i]`；`window_width` 由边界派生，不另存可修改字段。
- `window_n_bins` 表示窗口宽度对应的名义 bin 数。基于直方图积分得到 `raw_counts` 时，窗口边界须与该次 `bin_edges` 对齐并处于其覆盖范围内，避免把部分 bin 当成完整 bin 计数。
- 一组采样使用相同的通道对、`stop_delay`、直方图时间轴及符合窗口；这些逐次配置列表中的值须一致，bin 分辨率则由公共标量 `bin_width` 记录。改变配置的扫描测量使用多个 `CoincidenceResult`，避免将不同物理窗口的计数率直接求平均。
- 每次 `integration_time` 必须为有限正数；原始计数与偶然估计非负。没有偶然估计时，`net_counts`、`net_pair_rate` 及其统计属性返回 `None`，不将未知本底当成零；扣本底后的净计数允许为负，不做截零。

#### 均值与标准差

- `raw_pair_rate`、`acc_pair_rate`、`net_pair_rate` 返回逐次计数率列表；用 `@property` 从计数和时间计算，不同时定义同名 dataclass 字段。
- `raw_pair_rate_mean` 与 `net_pair_rate_mean` 是逐次计数率的算术平均。每次采集时间不同时，它们不等于“总计数 / 总采集时间”；这里明确采用前者，不隐式改成按时间加权。
- `raw_pair_rate_std` 与 `net_pair_rate_std` 是样本标准差，使用 `np.std(..., ddof=1)`；不足两次采样时返回 `None`，不将缺少重复测量信息解释为零波动。
- 标准差的单位为 counts/s，与计数率相同。
- 这些统计量由逐次列表动态派生，不重复保存，避免列表与缓存统计值不一致。均值和标准差都不是原始整数计数，不回填到计数字段中。
- `normalized[i]` 使用第 `i` 次的 singles、bin 宽度和有效时间分别归一化。若需要平均 g² 曲线，在相同时间轴上对这些曲线求平均；不使用平均 singles 乘积替代逐次归一化。

使用示例：

```python
result = CoincidenceResult(
    mode="window_count",
    channel_start=0,
    channel_stop=2,
    samples=3,
    counts_start=[1000, 1100, 900],
    counts_stop=[2000, 2200, 1800],
    singles_start=[1000.0, 1100.0, 900.0],
    singles_stop=[2000.0, 2200.0, 1800.0],
    integration_time=[1.0, 1.0, 1.0],
    bin_width=100,
    stop_delay=[0, 0, 0],
    window_start=[-500, -500, -500],
    window_stop=[500, 500, 500],
    raw_counts=[10, 20, 30],
    accidental_counts=[1.0, 2.0, 3.0],
    accidental_counts_per_bin=[0.1, 0.2, 0.3],
    accidental_method=["sideband", "sideband", "sideband"],
)

result.raw_pair_rate       # [10.0, 20.0, 30.0]
result.raw_pair_rate_mean  # 20.0
result.raw_pair_rate_std   # 10.0
result.net_pair_rate       # [9.0, 18.0, 27.0]
result.net_pair_rate_mean  # 18.0
result.net_pair_rate_std   # 9.0
```

---

### 3.2 统一后的 `MultiCoincidenceResult`

一个 `MultiCoincidenceResult` 固定对应一组 N 通道。`channels` 只记录一次，
所有采样都测量这一组通道；`samples` 仅表示为降低统计误差而重复测量的次数。
通道维度用明确的通道编号标记，采样维度用列表索引 `i` 标记，两者不混用。
以下代码定义字段与派生属性；实现时的构造校验要求列在本节末尾及 3.4 节。

```python
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
from numpy.typing import NDArray


@dataclass(kw_only=True)
class MultiCoincidenceResult:
    """Repeated coincidence results for a fixed group of N channels, N >= 3.

    channels[0] is the reference; remaining channels are signals.
    Keys are actual channel IDs; all measurement lists have length samples.
    Time fields use unit; integration_time is always in seconds.
    """

    # Shared settings and channel IDs.
    channels: tuple[int, ...]
    mode: Literal["histogram", "window_count"]
    bin_width: int  # Bin resolution shared by all channel pairs and samples.
    count_mode: Literal["combinations", "reference_events"]
    histogram_scope: Literal["coincident_events", "all_pair_hits"]
    samples: int = 1
    unit: str = "ps"
    method: Literal["software", "hardware"] = "software"
    deduplicate: bool = False

    # Use counts[channel][i] and singles[channel][i] with actual channel IDs.
    counts: dict[int, list[int]]
    singles: dict[int, list[float]]
    integration_time: list[float]

    # Per-channel delay; reference delays are [0] * samples.
    channel_delays: dict[int, list[int]]

    # Signal window relative to the reference, and N-channel counts.
    window_start: list[int]
    window_stop: list[int]
    raw_counts: list[int]
    accidental_counts: Optional[list[float]] = None
    accidental_method: Optional[list[Literal["sideband", "rate_product"]]] = None

    # Keys are (channel_start, channel_stop), directed as stop - start.
    # Each pair has its own repeated histograms and time axes.
    pairwise_hists: Optional[dict[tuple[int, int], list[NDArray[np.uint64]]]] = None
    bin_edges: Optional[dict[tuple[int, int], list[NDArray[np.int64]]]] = None

    # events[i] contains acquisition i; details are omitted by default.
    # Each event is (relative delays in channels order, ref_index).
    events: Optional[list[list[tuple[tuple[int, ...], int]]]] = None

    @property
    def channel_ref(self) -> int:
        return self.channels[0]

    @property
    def order(self) -> int:
        return len(self.channels)

    @property
    def n_signals(self) -> int:
        return len(self.channels) - 1

    @property
    def n_bins(self) -> Optional[dict[tuple[int, int], list[int]]]:
        if self.pairwise_hists is None:
            return None
        return {
            pair: [len(hist) for hist in histograms]
            for pair, histograms in self.pairwise_hists.items()
        }

    @property
    def stop_offset(self) -> Optional[dict[tuple[int, int], list[int]]]:
        if self.bin_edges is None:
            return None
        return {
            pair: [int(edges[0]) for edges in axes]
            for pair, axes in self.bin_edges.items()
        }

    @property
    def bin_centers(self) -> Optional[dict[tuple[int, int], list[NDArray[np.float64]]]]:
        if self.bin_edges is None:
            return None
        return {
            pair: [(edges[:-1] / 2.0 + edges[1:] / 2.0) for edges in axes]
            for pair, axes in self.bin_edges.items()
        }

    @property
    def window_width(self) -> list[int]:
        return [
            stop - start
            for start, stop in zip(self.window_start, self.window_stop, strict=True)
        ]

    @property
    def window_n_bins(self) -> list[int]:
        return [
            (width + self.bin_width - 1) // self.bin_width
            for width in self.window_width
        ]

    @property
    def net_counts(self) -> Optional[list[float]]:
        if self.accidental_counts is None:
            return None
        return [
            float(raw) - accidental
            for raw, accidental in zip(
                self.raw_counts, self.accidental_counts, strict=True
            )
        ]

    @property
    def raw_coincidence_rate(self) -> list[float]:
        """Return the coincidence rate for the entire N-channel group."""
        return [
            count / duration
            for count, duration in zip(
                self.raw_counts, self.integration_time, strict=True
            )
        ]

    @property
    def acc_coincidence_rate(self) -> Optional[list[float]]:
        if self.accidental_counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(
                self.accidental_counts, self.integration_time, strict=True
            )
        ]

    @property
    def net_coincidence_rate(self) -> Optional[list[float]]:
        counts = self.net_counts
        if counts is None:
            return None
        return [
            count / duration
            for count, duration in zip(counts, self.integration_time, strict=True)
        ]

    @property
    def raw_coincidence_rate_mean(self) -> float:
        return float(np.mean(self.raw_coincidence_rate))

    @property
    def raw_coincidence_rate_std(self) -> Optional[float]:
        if self.samples < 2:
            return None
        return float(np.std(self.raw_coincidence_rate, ddof=1))

    @property
    def net_coincidence_rate_mean(self) -> Optional[float]:
        rates = self.net_coincidence_rate
        return None if rates is None else float(np.mean(rates))

    @property
    def net_coincidence_rate_std(self) -> Optional[float]:
        rates = self.net_coincidence_rate
        if rates is None or len(rates) < 2:
            return None
        return float(np.std(rates, ddof=1))

    def pair_hist(
        self, channel_start: int, channel_stop: int
    ) -> Optional[list[NDArray[np.uint64]]]:
        """Return repeated histograms for this direction, or None if unavailable."""
        if self.pairwise_hists is None:
            return None
        return self.pairwise_hists.get((channel_start, channel_stop))
```

#### 固定通道、重复采样与通道标记

- `channels=(0, 2, 5)` 表示参考通道 0 和信号通道 2、5，所有采样保持此顺序及配置。`samples=3` 只表示同样的测量重复三次，不表示三组通道。`samples=1` 也返回同一个类，逐次数据仍为长度 1 的列表。
- `counts[2][i]`、`singles[2][i]` 明确属于物理通道 2；`raw_counts[i]` 则属于整个 `channels` 元组代表的 N 重符合。`counts`、`singles`、`channel_delays` 的键必须恰好覆盖这组通道，不通过索引猜测通道编号，也不混用物理编号和组内序号。
- `pairwise_hists[(0, 2)][i]` 表示第 `i` 次采样中通道 2 相对通道 0 的直方图，与 `CoincidenceResult.channel_start/channel_stop` 的方向一致。令 `t'_ch = t_ch + channel_delays[ch][i]`，则其横轴为 `tau = t'_2 - t'_0`。键 `(2, 0)` 是另一个方向，不能自动合并、排序或通过翻转数组代替实际结果。
- 原三通道 `hist_21`、`hist_31`、`hist_32`、`hist_23` 分别映射为 `(ref, sig1)`、`(ref, sig2)`、`(sig1, sig2)`、`(sig2, sig1)`，键中填写实际通道编号。每个方向的时间轴独立保存，`stop_offset` 由其首个 bin 边界派生，与 `channel_delays` 区分。
- 若一次分析需要保存多组不同的 N 重符合，使用 `dict[tuple[int, ...], MultiCoincidenceResult]`，键与各对象的 `channels` 一致。例如 `(0, 2, 5)` 与 `(0, 2, 7)` 是两组结果；它们内部同名的 `(0, 2)` 直方图保留各自所属组，不互相覆盖。不将不同组塞进采样列表，也不引入新的平均结果类。

#### 计数语义与均值、标准差

- `count_mode="combinations"` 表示每个参考事件下满足窗口的信号击中组合数；`"reference_events"` 表示所有信号通道均命中的参考事件数，每个参考事件最多计一次。这是整组重复采样共用的计数定义，不能在列表中混用。
- `compute_triplet_g2` 使用 `count_mode="combinations"`、`histogram_scope="coincident_events"`，四条直方图均以满足三重符合的事件组合为条件。`compute_gate_coincidence` 使用 `count_mode="reference_events"`、`histogram_scope="all_pair_hits"`，星型直方图记录窗口内的全部两两击中，即使其它信号通道没有命中也会贡献。
- `deduplicate` 保留原算法的每参考事件、每个延迟 bin 去重设置；高阶计数必须由对应算法直接提供，不能对任意一条直方图求和来替代。
- `events[i]` 按符合组合记录；每条记录的延迟元组与 `channels` 一一对应，参考通道位置为 0，其余为应用通道延迟后的相对时间，单位为 `unit`。`ref_index` 是该次采样参考通道事件流中的索引。适配旧的 bin 单位事件时须恢复窗口偏移并转换单位，明确保留原算法的量化精度，不能冒充原始精确时间戳。门控模式下 `len(events[i])` 可以大于 `raw_counts[i]`，不得用事件列表长度替代参考事件计数。
- `raw_coincidence_rate`、`acc_coincidence_rate`、`net_coincidence_rate` 是整组 N 通道的逐次符合计数率。为避免将 N 重符合误称为二重符合，这里使用 `coincidence_rate`；两通道模型继续使用 `pair_rate`。
- `raw_coincidence_rate_mean/std`、`net_coincidence_rate_mean/std` 与 3.1 节采用相同统计规则：分别除以各次实际时间后求算术平均；标准差使用 `ddof=1`，不足两次时为 `None`。没有偶然估计时，净计数、净计数率及其均值、标准差均为 `None`。
- `accidental_counts` 表示该组 N 重符合的偶然计数估计，由相应高阶分析提供；不直接套用两通道 singles 乘积，也不把某一通道对的每 bin 本底当作 N 重偶然计数。`accidental_method` 与估计同时提供。不直接为有高阶符合条件的两两直方图复用 3.1 节的二通道 `normalized` 公式。

#### 构造校验

- `channels` 至少含 3 个不重复的整数通道编号；第一项为参考通道。`samples` 是实际完成的正整数采样数，所有逐次列表长度严格等于它；不广播标量、不截断、不静默跳过缺失采样。可选字段整组为 `None` 或提供完整逐次数据。
- `bin_width` 是唯一的公共标量分辨率，必须为正整数。延迟、窗口与各通道对时间轴在所有重复采样中保持一致；列表保留采样索引以对齐 3.1 节。改变通道、窗口或其它公共配置时另建结果，不把配置扫描当作重复测量求平均。
- `integration_time[i]` 是有限正数；`counts[ch][i]` 与 `singles[ch][i]` 来自同一次有效采集，不能从浮点计数率反推并取整来伪造原始计数。原始计数及偶然估计非负，扣本底后的净值允许为负。
- 窗口为所有信号通道相对参考通道的半开区间 `[window_start[i], window_stop[i])`，上界大于下界。参考通道的 `channel_delays` 恒为零，其它通道延迟可正可负。
- `histogram` 模式要求非空的 `pairwise_hists` 与 `bin_edges`，二者键集相同；`window_count` 模式允许二者同时为 `None`。提供时，每个键包含组内两个不同的通道，每个方向包含完整的 `samples` 个数组；每个 histogram 长度为对应 edges 长度减 1，边界严格递增且相邻差等于 `bin_width`，计数为 `uint64`，边界为 `int64`。不要求不同通道对共用一个时间轴。
- 提供直方图时，三通道交叉关联必须保留全部四个原有方向，N 通道星型门控必须保留全部 `(ref, signal)` 方向。可选事件明细还须校验每条延迟元组长度等于 `order`、参考位置为零及参考事件索引有效；未保存明细使用 `None`，保存但某次无事件使用空列表。

使用示例：固定通道 `(0, 2, 5)`，重复测量三次。

```python
multi = MultiCoincidenceResult(
    channels=(0, 2, 5),
    mode="histogram",
    bin_width=100,
    count_mode="combinations",
    histogram_scope="coincident_events",
    samples=3,
    counts={0: [1000, 1100, 900], 2: [2000, 2200, 1800], 5: [1500, 1600, 1400]},
    singles={0: [1000.0, 1100.0, 900.0],
             2: [2000.0, 2200.0, 1800.0],
             5: [1500.0, 1600.0, 1400.0]},
    integration_time=[1.0, 1.0, 1.0],
    channel_delays={0: [0, 0, 0], 2: [0, 0, 0], 5: [0, 0, 0]},
    window_start=[0, 0, 0],
    window_stop=[200, 200, 200],
    raw_counts=[10, 20, 30],
    accidental_counts=[1.0, 2.0, 3.0],
    accidental_method=["sideband", "sideband", "sideband"],
    pairwise_hists={
        pair: [np.array([count, 0], dtype=np.uint64) for count in [10, 20, 30]]
        for pair in [(0, 2), (0, 5), (2, 5), (5, 2)]
    },
    bin_edges={
        pair: [np.array([0, 100, 200], dtype=np.int64) for _ in range(3)]
        for pair in [(0, 2), (0, 5), (2, 5), (5, 2)]
    },
)

multi.channels                     # (0, 2, 5), shared across samples
multi.singles[2]                   # [2000.0, 2200.0, 1800.0]
multi.pair_hist(0, 2)[1]            # t_2 - t_0 histogram for the second acquisition
multi.raw_coincidence_rate         # [10.0, 20.0, 30.0]
multi.raw_coincidence_rate_mean    # 20.0
multi.raw_coincidence_rate_std     # 10.0
multi.net_coincidence_rate_mean    # 18.0
multi.net_coincidence_rate_std     # 9.0

# Keep different channel groups in a dictionary of repeated results.
results_by_channels = {multi.channels: multi}
results_by_channels[(0, 2, 5)].pair_hist(2, 5)[0]  # This group's first t_5 - t_2 histogram
```

---

### 3.3 统一后的 `HeraldingGateResult`

`HeraldingGateResult` 明确区分单个触发通道 `heralding_channel: int` 与多个
被门控通道 `gated_channels: tuple[int, ...]`，不再把两种角色混在一个 `channels` 列表中。
所有采样使用相同通道配置；`samples=1` 与多次重复采样始终使用同一个类。
以下代码定义字段与派生属性；实现时的构造校验要求见本节末尾及 3.4 节。

```python
from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
from numpy.typing import NDArray


@dataclass(kw_only=True)
class HeraldingGateResult:
    """Repeated gate associations for one heralding and multiple gated channels.

    Every herald opens a gate that records all gated-channel hits.
    Channels need not all hit; channel configuration is shared.
    All measurement lists have length samples; integration_time is in seconds.
    Efficiency and CAR analysis belong to separate analysis functions.
    """

    # Fixed channel roles and shared settings.
    heralding_channel: int
    gated_channels: tuple[int, ...]
    mode: Literal["histogram", "window_count"]
    bin_width: int  # Bin resolution shared by all channels and samples.
    samples: int = 1
    unit: str = "ps"
    method: Literal["software", "hardware"] = "software"

    # Raw singles counts and rates over the entire live acquisition time.
    counts_heralding: list[int]
    singles_heralding: list[float]
    counts_gated: dict[int, list[int]]
    singles_gated: dict[int, list[float]]
    integration_time: list[float]

    # Keys are actual gated channel IDs; the gate window is relative to heralding.
    stop_delay: dict[int, list[int]]
    window_start: list[int]
    window_stop: list[int]
    raw_counts: dict[int, list[int]]  # Gate-hit associations per gated channel.
    accidental_counts: Optional[dict[int, list[float]]] = None
    accidental_counts_per_bin: Optional[dict[int, list[float]]] = None
    accidental_method: Optional[
        dict[int, list[Literal["sideband", "rate_product"]]]
    ] = None

    # histogram[ch][i] is acquisition i for (heralding_channel, ch).
    # Gated channels share the delay axis for each acquisition.
    histogram: Optional[dict[int, list[NDArray[np.uint64]]]] = None
    bin_edges: Optional[list[NDArray[np.int64]]] = None
    n_bins: Optional[list[int]] = None
    stop_offset: Optional[list[int]] = None

    # Optional details: outer lists index samples; offsets split gates.
    # flat_photons stores relative delays; flat_channels stores actual IDs.
    flat_photons: Optional[list[NDArray[np.int64]]] = None
    flat_channels: Optional[list[NDArray[np.int32]]] = None
    flat_offsets: Optional[list[NDArray[np.int64]]] = None
    # Alternative representation: per_gate[sample][gate][hit] = (delay, channel).
    per_gate: Optional[list[list[list[tuple[int, int]]]]] = None

    @property
    def n_gates(self) -> list[int]:
        """Return the number of herald gates, including empty gates."""
        return self.counts_heralding.copy()

    @property
    def total_photons(self) -> list[int]:
        """Return total associations per sample, independently of saved details."""
        return [
            sum(self.raw_counts[ch][i] for ch in self.gated_channels)
            for i in range(self.samples)
        ]

    @property
    def window_width(self) -> list[int]:
        return [
            stop - start
            for start, stop in zip(self.window_start, self.window_stop, strict=True)
        ]

    @property
    def window_n_bins(self) -> list[int]:
        return [
            (width + self.bin_width - 1) // self.bin_width
            for width in self.window_width
        ]

    @property
    def net_counts(self) -> Optional[dict[int, list[float]]]:
        if self.accidental_counts is None:
            return None
        return {
            ch: [
                float(raw) - accidental
                for raw, accidental in zip(
                    self.raw_counts[ch], self.accidental_counts[ch], strict=True
                )
            ]
            for ch in self.gated_channels
        }

    @property
    def raw_pair_rate(self) -> dict[int, list[float]]:
        return {
            ch: [
                count / duration
                for count, duration in zip(
                    self.raw_counts[ch], self.integration_time, strict=True
                )
            ]
            for ch in self.gated_channels
        }

    @property
    def acc_pair_rate(self) -> Optional[dict[int, list[float]]]:
        if self.accidental_counts is None:
            return None
        return {
            ch: [
                count / duration
                for count, duration in zip(
                    self.accidental_counts[ch], self.integration_time, strict=True
                )
            ]
            for ch in self.gated_channels
        }

    @property
    def net_pair_rate(self) -> Optional[dict[int, list[float]]]:
        counts = self.net_counts
        if counts is None:
            return None
        return {
            ch: [
                count / duration
                for count, duration in zip(
                    counts[ch], self.integration_time, strict=True
                )
            ]
            for ch in self.gated_channels
        }

    @property
    def raw_pair_rate_mean(self) -> dict[int, float]:
        return {ch: float(np.mean(rates)) for ch, rates in self.raw_pair_rate.items()}

    @property
    def raw_pair_rate_std(self) -> Optional[dict[int, float]]:
        if self.samples < 2:
            return None
        return {
            ch: float(np.std(rates, ddof=1))
            for ch, rates in self.raw_pair_rate.items()
        }

    @property
    def net_pair_rate_mean(self) -> Optional[dict[int, float]]:
        rates = self.net_pair_rate
        if rates is None:
            return None
        return {ch: float(np.mean(values)) for ch, values in rates.items()}

    @property
    def net_pair_rate_std(self) -> Optional[dict[int, float]]:
        rates = self.net_pair_rate
        if rates is None or self.samples < 2:
            return None
        return {ch: float(np.std(values, ddof=1)) for ch, values in rates.items()}

    def gate_hits(
        self, sample_index: int, gate_index: int
    ) -> Optional[list[tuple[int, int]]]:
        """Read (delay, actual channel ID) details for one sample and gate."""
        if not 0 <= sample_index < self.samples:
            raise IndexError("sample_index out of range")
        if not 0 <= gate_index < self.counts_heralding[sample_index]:
            raise IndexError("gate_index out of range")
        if self.flat_photons is not None:
            offsets = self.flat_offsets[sample_index]
            start, stop = int(offsets[gate_index]), int(offsets[gate_index + 1])
            return [
                (int(delay), int(ch))
                for delay, ch in zip(
                    self.flat_photons[sample_index][start:stop],
                    self.flat_channels[sample_index][start:stop],
                    strict=True,
                )
            ]
        if self.per_gate is not None:
            return self.per_gate[sample_index][gate_index].copy()
        return None
```

#### 通道、采样与计数语义

- `heralding_channel=0`、`gated_channels=(2, 5)` 表示通道 0 的每个触发分别打开一个门，记录通道 2 和 5 在门内的全部击中。不要求两个 gated 通道同时命中；每个 gated 通道独立保留结果，不能将此计数当作三重符合。
- 触发通道为单个整数；`gated_channels` 是固定的通道编号元组，所有重复采样共用。`samples` 只表示同一配置的实际重复次数，不是门数、光子数或 gated 通道数。`bin_width` 仍是单个公共标量。
- `counts_heralding[i]`、`singles_heralding[i]` 属于 heralding 通道；`counts_gated[ch][i]`、`singles_gated[ch][i]` 是实际通道 `ch` 在整个有效采集时间内的 singles 信息。`raw_counts[ch][i]` 是该通道在所有门内的击中关联数，与窗口外的 singles 计数区分。
- `histogram[ch][i]` 明确对应 `(heralding_channel, ch)`，延迟坐标为 `tau = (t_ch + stop_delay[ch][i]) - t_heralding`。所有 gated 通道共用同一个门区间和每次的 `bin_edges[i]`；`stop_offset[i]` 是时间轴起点，不再施加一次通道延迟。
- `n_gates[i] == counts_heralding[i]`，每个有效 heralding 触发均打开一个门，包括没有击中的空门。`n_gates` 和 `total_photons` 从必需计数字段派生，不依赖可选明细，避免未保存明细时错误地返回零。
- `total_photons[i]` 是所有 gated 通道的门内关联数之和。如果门重叠，同一个物理击中可以关联多个 heralding 门并分别计数，因此它不保证等于去重后的光子数，`raw_counts[ch][i]` 也可能大于该通道的 singles 计数。
- `raw_pair_rate[ch]`、`acc_pair_rate[ch]`、`net_pair_rate[ch]` 分别是 `(heralding_channel, ch)` 的逐次门内关联计数率，使用各次 `integration_time[i]`，单位 counts/s。各通道的 `mean/std` 采用 3.1 节相同规则：算术平均、`ddof=1` 样本标准差；`samples=1` 时整个 `*_std` 属性为 `None`。
- 没有偶然估计时，`net_counts`、`net_pair_rate` 及其均值、标准差均为 `None`；有估计时逐通道扣除，净值允许为负。`accidental_counts_per_bin` 表示每个 gated 通道各自的每 bin 偶然基线。此处记录计数及计数率，不新增效率或 CAR 分析。

#### 可选门内明细与构造校验

- `samples` 为正整数；所有逐次列表，包括通道字典中的列表、histogram 列表及可选明细的外层列表，长度均严格等于 `samples`。`integration_time[i]` 为有限正数。`singles_heralding`、`singles_gated` 来自对应的实际计数和有效时间，不反推取整来伪造原始计数。
- `heralding_channel` 为整数，`gated_channels` 至少包含一个整数通道、不重复且不包含 heralding 通道。所有以 gated 通道为键的字典，提供时必须恰好覆盖 `gated_channels`；不接受组内序号替代实际通道编号。可选字典整组为 `None` 或包含所有通道、所有采样，不静默跳过缺失项。
- `stop_delay[ch]` 可正可负；同一通道的延迟、窗口和时间轴在所有重复采样中保持一致。每次窗口满足 `window_stop[i] > window_start[i]`，使用半开区间 `[start, stop)`。改变通道或测量配置时另建结果。
- `histogram` 模式必须提供 `histogram`、`bin_edges`、`n_bins`、`stop_offset`；`window_count` 模式可同时省略四者，提供则须齐全。对每个 gated 通道与采样：histogram 长度等于 `n_bins[i]`，edges 长度为其加 1，首边界等于 `stop_offset[i]`，相邻差等于正整数 `bin_width`；计数数组为 `uint64`、边界为 `int64`。若由直方图积分得到门内计数，门边界必须对齐 bin 边界且在时间轴范围内。
- `counts_heralding`、`counts_gated`、`raw_counts` 为非负整数，偶然估计为有限非负浮点数；`accidental_method` 与偶然估计一并提供。零 heralding 触发的采样必须有零门内关联计数，即使 gated singles 非零。
- 默认不保存光子明细，四个明细字段均为 `None`；需要时只选择一种完整表示：扁平三数组列表，或 `per_gate`。不同时保存两套明细。明细中的 `delay` 已应用该 gated 通道的 `stop_delay`，单位为 `unit`，位于公共门窗口内；`channel` 是实际 gated 通道编号。
- 扁平表示中，每次的 `flat_photons[i]`、`flat_channels[i]` 长度相同，分别为 `int64` 延迟与 `int32` 实际通道编号；`flat_offsets[i]` 为 `int64` 非递减数组，长度为 `n_gates[i] + 1`，首项为 0、末项等于该次明细条数。第 `g` 个门由 `[offsets[g]:offsets[g+1]]` 切片读取；空门必须保留重复 offset。没有 heralding 触发时 offsets 仍为 `[0]`，两个击中数组为空。
- `per_gate[i]` 必须恰好包含 `n_gates[i]` 个门，空门用空列表表示；每个击中为 `(delay, 实际通道编号)`。无论选择哪种表示，明细按通道统计的条数必须等于 `raw_counts[ch][i]`，总条数等于 `total_photons[i]`。`gate_hits(i, g)` 在未保存明细时返回 `None`，已保存但该门无击中时返回空列表。
- 适配旧 `compute_gate_photons` 输出时，将组内编号 `k` 映射为 `gated_channels[k]`；将旧的偏移后 bin 时间值恢复窗口偏移、减去该门的 heralding 时间并转换为 `unit`，只应用一次通道延迟，保留原算法量化精度。不能把组内编号或旧 bin 时间值直接写入新结果。

使用示例：一个 heralding 通道，两个固定 gated 通道，重复采样三次。

```python
heralded = HeraldingGateResult(
    heralding_channel=0,
    gated_channels=(2, 5),
    mode="window_count",
    samples=3,
    bin_width=100,
    counts_heralding=[1000, 1100, 900],
    singles_heralding=[1000.0, 1100.0, 900.0],
    counts_gated={2: [2000, 2200, 1800], 5: [1500, 1600, 1400]},
    singles_gated={2: [2000.0, 2200.0, 1800.0],
                   5: [1500.0, 1600.0, 1400.0]},
    integration_time=[1.0, 1.0, 1.0],
    stop_delay={2: [0, 0, 0], 5: [100, 100, 100]},
    window_start=[0, 0, 0],
    window_stop=[1000, 1000, 1000],
    raw_counts={2: [10, 20, 30], 5: [20, 30, 40]},
    accidental_counts={2: [1.0, 2.0, 3.0], 5: [2.0, 3.0, 4.0]},
    accidental_counts_per_bin={2: [0.1, 0.2, 0.3], 5: [0.2, 0.3, 0.4]},
    accidental_method={2: ["sideband"] * 3, 5: ["sideband"] * 3},
)

heralded.heralding_channel          # 0
heralded.gated_channels             # (2, 5), shared across samples
heralded.n_gates                    # [1000, 1100, 900], available without details
heralded.raw_counts[2]              # [10, 20, 30], associations for channel 2 per sample
heralded.total_photons              # [30, 50, 70], total associations per sample
heralded.raw_pair_rate_mean         # {2: 20.0, 5: 30.0}
heralded.raw_pair_rate_std          # {2: 10.0, 5: 10.0}
heralded.net_pair_rate_mean[5]      # 27.0
heralded.net_pair_rate_std[5]       # 9.0
heralded.gate_hits(0, 0)            # None: details were not saved
```

### 3.4 时间单位与数值类型约定

- 字段名称使用通用命名：`bin_width`、`window_start`、`window_stop`、`bin_edges`，不在名称中重复单位。
- `unit` 保留在三个统一模型中，默认值为 ``"ps"``；它描述这些时间字段的单位。
- 后端读取 ns、ps 或原生 tick 后，先转换为整数 ps，再创建默认结果对象。若调用方显式要求其他输出单位，适配层必须同时转换全部时间字段并更新 `unit`；三个模型都应转换每次采样的时间数据，多通道及门控模型还须覆盖所有通道、通道对及事件/光子明细；`integration_time` 仍以秒为单位，offset 索引数组不随时间单位缩放。
- 时间戳、延迟、窗口和 bin 边界使用整数，NumPy 时间数组使用 `int64`；histogram 计数使用 `uint64`；计数率、偶然估算和归一化结果使用浮点数，NumPy 数组使用 `float64`。三个模型的采样维度统一为列表；`MultiCoincidenceResult` 用通道或有向通道对作为字典键，`HeraldingGateResult` 用 gated 通道编号标记各通道数据，字典值保留逐次列表。`bin_width` 等公共配置保持标量，通道配置只保存一次。
- `bin_width` 表示分析 histogram 的 bin 宽度，不表示设备原生时间分辨率；原生 tick 信息作为采集元数据单独保存。
- 两个 coincidence 模型的 `window_width`、`window_n_bins`、`net_counts`、计数率及其 `mean/std` 通过 `@property` 派生，不重复存储。`CoincidenceResult.n_bins` 为逐次配置列表；`MultiCoincidenceResult` 的 `channel_ref`、`order`、`n_signals` 以及按通道对返回的 `n_bins`、`stop_offset`、`bin_centers` 由其自身字段派生。
- `HeraldingGateResult` 的 `n_gates`、`total_photons`、窗口宽度、净计数、逐通道计数率及其 `mean/std` 同样由必需计数字段派生；不从可选明细推断测量是否有门、有光子。它的 `bin_edges`、`n_bins`、`stop_offset` 是所有 gated 通道共用的逐次时间轴配置。
- 实现三个模型时，`__post_init__` 必须校验 `samples` 为正整数、所有已提供逐次列表的长度等于 `samples`、各次有效时间为有限正数、模式字段完整以及每次数组形状与数据类型正确；多通道及门控模型须递归校验字典中的列表与通道键。`histogram` 模式要求完整的逐次 histogram 与时间轴元数据；`window_count` 模式要求逐次 `raw_counts` 及完整窗口；两通道硬件计数模式若设备不公开固定门宽，允许 `window_start/window_stop` 同时为 `None`，不可伪造窗口。附带 histogram 则执行相同的形状校验。仅返回 singles rates 的两通道硬件驱动可将 `counts_start/counts_stop` 设为 `None`，不由计数率反推原始计数。
- 所有模型都校验时间边界的顺序、`unit` 的支持范围、数组长度、通道数量及同组重复采样的配置一致。`HeraldingGateResult` 还须校验单个 heralding/多个 gated 的角色分离、可选明细表示互斥，以及明细与门数、各通道计数一致。校验失败立即抛出 `ValueError`，不在下游静默修正。

---

#### 采集接口与重复采样实现

- `TDC.measure_g2/measure_coincidence/measure_triplet/measure_gate/measure_heralding_gate` 和对应便利函数都接受 `samples=1`，单次与重复测量使用同一结果类型。`combine_samples()` 负责拼接并拒绝配置变化；扫描参数时另建对象。
- `get_g2/measure_g2` 的 `ch_stop_delay` 和 `get_coincidence/measure_coincidence` 的窗口输入采用 `unit` 指定的物理单位；`bins/bin_offset` 仍为 bin 数。分析函数 `compute_g2(stop_delay=...)` 接收整数 ps，在分 bin 前仅施加一次延迟。默认返回对象统一为整数 ps；`convert_time_unit()` 同时转换全部物理时间，不能表示为整数的转换立即拒绝。
- 软件窗口向外对齐 bin 边界。自动选窗在第一次采样后固定窗口和 histogram 轴，后续采样不重新追踪峰值，以保证重复测量配置一致。
- `measure_heralding_gate` 明确单个 `heralding_channel` 和多个 `gated_channels`；`measure_gate` 保留所有信号通道同时命中的 N 重符合语义。

### 3.5 原始采集层的 marker 支持

marker 与光子属于同一次采集，由 `TimestampResult.markers` 一起返回与持久化。
光子 `timestamps/channels` 数组保持纯光子事件；marker 不充当普通计数通道。

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MarkerEvent:
    """A marker and its boundary in the acquired photon stream."""

    mask: int
    photon_index: int
    timestamp_ps: int | None = None
    stream_index: int | None = None
```

- `mask` 保留同时触发的位组合：M1/M2/M3/M4 对应 1/2/4/8；M1 与 M2 同时触发为 3。
- `photon_index` 是该 marker 之前的光子记录数，取值为 `[0, total_events]`。两个 marker 对应的索引 `a/b` 可直接用于 `timestamps[a:b]` 和 `channels[a:b]`，表示原始数据流中的分段，而不是精确时间门。
- `stream_index` 保存原始记录位置，区分处于同一个光子分界点的多个 marker；它不是光子数组下标。改变光子顺序或筛选光子时必须同步重建 marker 的分界索引。
- `timestamp_ps` 仅在有可靠时间信息且与光子时间轴一致时填写。当前星秒 TTTR 解码没有独立 marker 时间戳，因此填 `None`，不使用邻近光子时间替代。原始 word、T2/T3 mode 等设备信息保留在后端完整 `TTTREvent` 中。
- `TimestampResult.markers: list[MarkerEvent] | None = None`：`None` 表示未提供，空列表表示已读取但没有 marker。按数据流顺序保存并验证索引单调性和范围；marker 可位于首个光子之前、最后一个光子之后，也可连续出现。
- marker 分段是否构成一次重复测量由测量流程决定；marker 数量不等于 `samples`。分段计数率需要另有可靠的实际积分时间。三个分析结果类不重复保存整份 marker 流。
- 星秒解析器直接生成通用 `MarkerEvent`，`get_timestamps()` 将同次 marker 附到返回对象；完整事件流仍用于设备诊断。
- 原始数据保存函数统一接收 `TimestampResult`。二进制使用新的 `TDC\x02` 格式，保存采集时长、marker 提供状态、mask、光子分界索引及可空的时间/流位置；HDF5 保存等价字段。提供配套读取函数，验证往返保存不丢失 marker；不保留旧文件格式适配层。
- 所有新增或修改的 Python 注释与 docstring 使用英文；设计文档正文可以使用中文。

---

## 4. 未覆盖信息与潜在物理/工程盲区深度分析 (Edge Cases Analysis)

在进行合并时，必须审慎处理以下 5 项潜在信息丢失或物理盲区：

### 4.1 硬件符合模式下直方图缺失的非空安全
- **盲区**：纯硬件符合计数器（如 S15 TDC1 的 `pairs`，ID1000 的 `TSCO`，CIQTEK 的 `accord`）由板载 FPGA 处理，只输出标量整数，没有直方图。
- **应对**：`CoincidenceResult.histogram` 标为 `Optional[list[NDArray[np.uint64]]] = None`，缺失时整组为 `None`。下游绘图或导出 npz 必须先检查 `result.histogram is not None`；存在时按采样索引访问对应 histogram 与 bin_edges，不能将整个列表当成一维直方图。
  `HeraldingGateResult` 的计数模式同样允许没有直方图和门内明细；仍保留每次 heralding 触发计数及逐 gated 通道的门内计数，绘图按实际通道键和采样索引读取。

### 4.2 多通道网状拓扑 vs 星型拓扑的直方图丢失
- **盲区**：原 `TripletResult` 包含了信号通道之间的互相关直方图（如 $h_{32}: t_3 - t_2$），这对于三光子态（如 GHZ）检测或 HOM 干涉至关重要；而原 `GateResult` 的 C 核心实现为了速度只记录了星型直方图（$t_{sig,k} - t_{ref}$）。
- **应对**：在 `MultiCoincidenceResult` 中使用 `pairwise_hists[(channel_start, channel_stop)][sample_index]`，方向统一为 `stop - start`，通道编号为实际编号。在三通道调用 `compute_triplet_g2` 时，将全部 4 个方向存入字典；在通用 $N$ 通道调用时，存入全部星型方向。各通道对分别保存逐次时间轴，并通过 `histogram_scope` 区分“三重符合条件下的直方图”与“全部两两击中直方图”。多个 N 通道组分别存入以 `channels` 元组为键的结果字典，避免共享某个通道对时丢失所属组信息。

### 4.3 脉冲激光 (Pulsed) vs 连续光 (CW) 的分析差异
- **盲区**：目前无论是 `CoincidenceResult` 还是 `compute_pairs`，都只设定了一个单一的门控区间 `[window_start, window_stop]`。对于脉冲激光，需同时对比零延时中心峰（$k=0$）与周期性边带脉冲峰（$k=\pm 1, \pm 2$）的积分比值以计算非后选择的 $g^{(2)}(0)$。
- **应对**：在 `CoincidenceResult` 中增加对周期性多窗口（Pulsed multi-peak integration）或边峰面积比率字段的预留。

### 4.4 大数据量下离散 `events` 列表的内存开销
- **盲区**：在 1 MHz 计数率下采集数秒，符合事件可能达到上千万个。如果盲目将每个符合事件保存为 Python 元组列表 `((t1, t2), ref_idx)`，内存将膨胀至数 GB。
- **应对**：
  1. 默认设置 `store_events=False`，仅在用户显式需要事件重构时生成；
  2. 本轮 `MultiCoincidenceResult.events` 保留可选的逐次事件列表；需要保存大量明细时，后续另行设计类似门控光子模型的扁平化 `int64` 数组存储，不默认收集全部事件。

### 4.5 门内单通道死时间与多光子分辨力限制
- **盲区**：普通单光子探测器与 TDC 输入通道存在死时间（几十纳秒），单通道在单个门内很难分辨第二个光子。
- **应对**：`HeraldingGateResult` 用固定的 `heralding_channel`/`gated_channels` 区分触发与检测通道，并按 gated 通道分别记录击中。若分析单个门的多击中，必须读取带实际通道编号的明细，以区分“同通道多次击中”与“多个通道各命中”；只保存汇总计数时不推断逐门分布，也不将探测器击中次数直接解释为入射光子数。

---

## 5. Downstream (下游) 修改清单与波及面评估

| 文件路径 | 原有依赖/行为 | 调整内容与修改要点 |
| :--- | :--- | :--- |
| **`src/qtools/tdc/data.py`** | 定义 5+1 个分散类 | 1. 重构 `CoincidenceResult`，增加 `samples`、逐次列表及计数率 `mean/std` 属性；<br/>2. 新增同样支持重复采样的 `MultiCoincidenceResult`，固定通道元组、按通道/通道对标记数据；<br/>3. 新增 `HeraldingGateResult`，明确单个 heralding 与多个 gated 通道、逐次列表、逐通道计数率 `mean/std` 和可选明细；<br/>4. 删除旧模型的重复定义，不建立兼容别名层。 |
| **`src/qtools/tdc/analysis/g2.py`** | `compute_g2` 返回 `G2Result`；<br/>`compute_triplet_g2` 返回 `TripletResult`；<br/>`compute_gate_coincidence` 返回 `GateResult`；<br/>`compute_gate_photons` 返回 `GatePhotonResult` | 1. `compute_g2` 改为返回 `samples=1`、测量数据均为长度 1 列表的 `CoincidenceResult`；<br/>2. `compute_triplet_g2` 与 `compute_gate_coincidence` 返回 `samples=1` 的 `MultiCoincidenceResult`，写入真实通道编号、计数定义与直方图来源，保留四向/星型直方图并转换时间坐标；<br/>3. `compute_gate_photons` 返回 `samples=1` 的 `HeraldingGateResult`，将 `ch_gate/ch_photons` 写入明确的通道角色，按 gated 通道分别累计门内计数、按需生成直方图与一种明细表示，并映射实际编号及相对延迟。 |
| **`src/qtools/tdc/analysis/efficiency.py`** | `compute_pairs` 返回无类型的 `dict` | 保持 `compute_pairs` 作为独立效率分析函数；本次不将它并入 `HeraldingGateResult`。后续若需要类型化，另行设计 `PairAnalysisResult`。 |
| **`src/qtools/tdc/backends/base.py`** | `TDCBackend.get_g2` 注记为 `G2Result`；<br/>`TDCBackend.get_coincidence` | 1. 统一类型注记为 `CoincidenceResult`；<br/>2. 单次读取返回 `samples=1` 的逐次列表；<br/>3. `get_coincidence` 软件分支挂载该次 histogram 与完整时间轴元数据。 |
| **`src/qtools/tdc/backends/idq/backend_id1000.py`** | `get_g2` / `get_hardware_histogram` 返回 `G2Result` | 返回扩展后的 `CoincidenceResult`，单次读数与数组包装为长度 1 的列表。 |
| **`src/qtools/tdc/backends/ciqtek/backend.py`** | `get_coincidence` 返回旧 `CoincidenceResult` | 将硬件计数与时间包装为长度 1 的列表，直方图整组为 `None`；未测量的偶然符合保持 `None`。 |
| **`src/qtools/tdc/backends/s15_tdc1/`** | `backend.py` 与 `exp_backend.py` 中的 `get_coincidence` 与 `get_g2` | 返回类型适配。 |
| **`src/qtools/tdc/measurement.py`** | `TDC.measure_g2`, `measure_pairs`, `measure_triplet`, `measure_gate` | `measure_g2`、`measure_coincidence`、`measure_triplet`、`measure_gate` 增加 `samples` 参数，默认 1；固定通道与配置重复采集，按索引及通道键拼接数据，每次实际时间独立保存；前两者始终返回 `CoincidenceResult`，后两者始终返回 `MultiCoincidenceResult`；`measure_pairs` 保持独立效率分析返回值，并适配单次 g² 列表读取。 |
| **`src/qtools/tdc/api.py`** | `g2()`, `pairs()`, `triplet()`, `gate()` | 保持 `pairs()` 返回 9-tuple 行为不变（或增强）；其它函数返回新模型。 |
| **`src/qtools/tdc/cli.py`** | 调用 `measure_pairs`, `measure_g2`, `measure_coincidence` | 适配逐次列表与 `samples`；显示计数率均值、可用时显示标准差，明确标注采样数；导出保留采样索引，直方图访问增加空值保护。 |
| **`tests/tdc/`** | `test_coincidence.py`, `test_cli.py`, `test_idq_backends.py` 等 | 校验三个模型的采样列表长度、固定返回类型、计数率 `mean/std`、模式约束、单位转换和空直方图保护；多通道覆盖实际编号、有向直方图、跨组隔离及两种计数语义；门控覆盖单 heralding/多 gated 映射、无明细时的门数与计数、空门、明细表示及重叠门关联计数。 |

---

## 6. 迁移边界

### 6.1 设备入口与分析 bin width（2026-11-02 补充）

- 工厂入口统一改名为 `get_tdc`，删除 `get_device`，同步修改 API、下游调用、示例和测试，不保留旧别名。
- `get_tdc(backend="s15_tdc1", bin_width=2_000)` 和 `TDC(backend="s15_tdc1", bin_width=2_000)` 等价；二者接受 backend 名称或发现返回的 `DeviceInfo`，`TDC` 也可包装现有 backend 实例。构造时不建立硬件连接，进入 context 时连接，退出时断开。
- `bin_width` 是单个正整数，始终以 ps 为单位，不受测量参数 `unit` 影响。测量调用显式指定的值优先于实例默认值；两处均省略时使用原生时间戳分辨率。g²、符合、pairs、triplet、gate、heralding 及其重复采样和便捷函数均使用这个规则。
- `bins` 和 `bin_offset` 继续以 bin 为单位；计算直方图、物理时间轴、窗口对齐及以 bin 表达的 delay 时使用所选宽度。重复采样固定 bin width 与时间轴，自动符合窗口在第一轮选定后保持固定。
- 原始 `TimestampResult.resolution_ps` 和 backend 的硬件分辨率保持真实硬件含义；设置分析宽度不修改原始时间戳，也不改变硬件标量计数器本身的符合门能力。无直方图的硬件结果将所选宽度记录为分析元数据。
- `list_tdc()` 扫描并打印已接入电脑、可发现的 TDC 硬件，返回 `list[DeviceInfo]`，支持将其中一项直接传给 `get_tdc` 或 `TDC`。没有发现设备时返回空列表并打印相应提示。
- 显式指定 `s15_tdc1` 或 `exp_s15_tdc1` 时可按需加载相应驱动，配置中的默认 backend 继续用于未指定 backend 的便捷函数和 CLI。

```python
from qtools.tdc import TDC, get_tdc, list_tdc

devices = list_tdc()
tdc = TDC(backend="s15_tdc1", bin_width=2_000)
with tdc:
    result = tdc.measure_g2(1.0, ch_start=1, ch_stop=2, samples=5)
    finer = tdc.measure_g2(1.0, ch_start=1, ch_stop=2, bin_width=1_000)

if devices:
    tdc = get_tdc(devices[0], bin_width=2_000)
```

本次统一不建立旧模型的别名、继承垫片或字典访问模拟层。实现阶段需要一次性更新内部调用方、类型注解、CLI、示例和测试，使它们直接使用三个 canonical 模型：

- `CoincidenceResult`：两通道 histogram 或 window count，统一通过 `samples` 和逐次列表支持单次、多次采样；
- `MultiCoincidenceResult`：固定一组 N 通道的符合及有向 pairwise histograms，通过 `samples` 和逐次列表支持重复测量；不同通道组使用按 `channels` 元组索引的结果字典；
- `HeraldingGateResult`：固定一个 heralding 通道与多个 gated 通道的门控光子及门内统计，通过 `samples` 和逐通道列表支持重复采样，门内明细可选。

`compute_pairs()` 继续返回当前独立的效率分析结果；它不属于上述三个数据模型。

---

## 7. 分步实施计划 (Implementation Roadmap)

### Phase 1: 数据模型升级 (`data.py`)
- [x] 增加通用 `MarkerEvent` 与 `TimestampResult.markers`；星秒解析、采集返回值和二进制/HDF5 保存读取保留同次 marker 及光子分界索引；
- [x] 扩展 `CoincidenceResult`，接入 histogram/window_count 两种模式、`samples` 及逐次列表；实现窗口、计数率和 `mean/std` 派生属性；
- [x] 实现 `MultiCoincidenceResult`，固定通道元组并增加 `samples`、逐次列表及高阶符合计数率 `mean/std`；以真实有向通道对为键的 `pairwise_hists` 覆盖 3 通道与 $N$ 通道，保留计数/直方图语义；
- [x] 实现 `HeraldingGateResult`，明确 `heralding_channel`/`gated_channels`，接入 `samples`、逐通道采样列表及计数率 `mean/std`；从必需计数派生门数与关联总数，按需选择一种门内明细表示；
- [x] 删除旧模型的重复定义，内部调用方全部切换到 canonical 模型。

### Phase 2: 核心分析算法层重构 (`analysis/`)
- [x] 重构 `g2.py` 中的 `compute_g2`，返回扩展后的 `CoincidenceResult`；
- [x] 统一 `compute_triplet_g2` 与 `compute_gate_coincidence` 的返回模型为 `samples=1` 的 `MultiCoincidenceResult`；保留各自组合计数/参考事件计数以及四向/星型直方图语义，按真实通道编号映射并转换时间轴、事件单位；
- [x] 更新 `compute_gate_photons`，输出 `samples=1` 的 `HeraldingGateResult`；映射单个 heralding 与多个实际 gated 通道，逐通道累计门内计数，转换相对延迟及单位；默认只累计摘要，按需直接生成一种明细表示，避免先保存全部事件再丢弃；
- [x] 保持 `efficiency.py` 中的 `compute_pairs` 为独立效率分析接口，不与 `HeraldingGateResult` 合并。

### Phase 3: 硬件驱动与抽象基类对齐 (`backends/`)
- [x] 更新 `backends/base.py` 中 `get_g2` 与 `get_coincidence` 的返回类型注记与实现；
- [x] 适配 `id1000`、`ciqtek`、`s15_tdc1`，验证硬件标量模式与软件直方图模式。

### Phase 4: 高层测量接口与 CLI 对齐 (`measurement.py`, `api.py`, `cli.py`)
- [x] 更新 `TDC.measure_g2`、`measure_coincidence`、`measure_triplet`、`measure_gate` 的返回类型；四者均增加 `samples=1` 参数，固定通道和配置重复采集并拼接数据列表，多通道按真实通道/通道对键拼接；
- [x] 门控光子调用方在同一 heralding/gated 配置下重复采集时，按采样索引、实际 gated 通道键拼接 `HeraldingGateResult`，包括选用明细表示的外层采样列表；`measure_gate` 保持 N 重符合语义，不替代门控光子分析；
- [x] 保持 `TDC.measure_pairs` 的独立效率分析语义；
- [x] 确保 CLI 脚本与 `api.pairs()` 正常工作。

### Phase 5: 测试用例验证与文档更新 (`tests/`, `README.md`)
- [x] 运行现有测试套件并修复接口迁移导致的失败；
- [x] 新增 `test_data_unification.py`，覆盖三个模型的模式约束、单位转换、空值保护、采样列表长度与索引对齐、各次时间归一化、计数率均值及样本标准差；覆盖 `samples=1` 时标准差为 `None` 和无偶然估计时净计数率不可用；
- [x] 多通道测试使用非连续编号（如 0、2、5、7），检查通道映射、四条有向直方图、不同通道组的同名 pair 隔离，以及单个参考事件含多组信号击中时组合数与门控参考事件数不同；
- [x] 门控光子测试使用单个 heralding 通道和至少两个非连续 gated 通道，检查逐通道计数率及 `mean/std`、只命中部分通道、无明细仍有门数与计数、零触发、空门、两种明细表示与实际编号、重叠门中的重复关联，以及明细长度/offset/计数不一致时拒绝构造；
- [x] 更新 `qtools/tdc/README.md` 的架构图与 API 说明。


### 实现验证记录（2026-11-02）

- TDC 离线测试：`uv run --no-sync pytest tests/tdc -m 'not hardware' -q`，183 项通过，53 项硬件测试未执行。
- 下游调用验证：`tests/pctrl/test_tdc_pairs.py`、`tests/pctrl/test_tdc_singles.py`、`tests/pmeas/test_tdc_reconnect.py`、`tests/pmeas/test_tdc_thresholds.py`，共 9 项通过；使用临时 uv 环境提供已有运行时依赖，未改动依赖声明或锁文件。
- 统一模型覆盖重复采样、各次实际积分时间、均值与样本标准差、模式约束及时间单位转换；多通道覆盖真实编号和两种计数语义；heralding 覆盖空门、重叠门和互斥明细格式。
- marker 覆盖同次采集、首尾及连续分界、同时触发位组合、无独立时间戳以及二进制/HDF5 往返保存。
- 设备配置覆盖 `get_tdc` 与命名构造、发现列表、默认及逐次覆盖的 `bin_width`、真实直方图分箱与窗口对齐、重复采样、便捷函数传递和连接生命周期。
- CLI 的有限采样显示采样数及计数率 `mean/std`，CSV 保存显式 `SAMPLE` 列；单次标准差为 `None`。
- 修改过的 Python 文件通过 Ruff 的 `F/E9/I` 检查；源码注释、docstring 和本文 Python 示例均已检查为英文。
- 本记录表示代码与离线测试完成；未连接真实 TDC，不将驱动 mock 测试视为设备实测。
