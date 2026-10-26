# TDC 数据结构精简与统一方案设计 (TDC Data Structures Unification Design)

- **作者/设计者**: AI Assistant & rayonde
- **日期**: 2026-10-06
- **目标模块**: `qtools.tdc.data`, `qtools.tdc.analysis`, `qtools.tdc.backends`, `qtools.tdc.measurement`, `qtools.tdc.api`

---

## 1. 背景与现状分析 (Background & Motivation)

在 `qtools.tdc` 目前的设计中，数据表示层（`qtools.tdc.data`）定义了多种并列的数据结构：
1. **基础数据结构**：
   - `DeviceInfo`：静态硬件设备发现与连接元数据（保留）；
   - `SinglesResult`：单通道计数率与累计计数（保留）；
   - `TimestampResult`：原始事件级时间戳与通道流（保留）。
2. **重叠/割裂的关联与符合数据结构**：
   - `G2Result`：两通道二阶时域关联直方图 $g^{(2)}(\tau)$，包含 `histogram`、`bin_edges`、`singles_start/stop`、归一化计算等；
   - `CoincidenceResult`：两通道（或曾尝试支持三通道）符合计数，包含标量符合数 `count`、门宽 `window_ps`、偶然符合估算 `accidental_count` 等；
   - `TripletResult`：固定三通道符合测量，硬编码返回 4 个两两延时直方图（$h_{21}, h_{31}, h_{32}, h_{23}$）和离散事件列表；
   - `GateResult`：$N$ 通道门控符合测量（1 个基准通道 + $M$ 个信号通道），返回星型两两直方图、N 重符合数 `n_fold_count` 和离散事件列表；
   - `GatePhotonResult`：门控光子对应关系，返回单次门触发内所有到达光子的映射与扁平数组；
   - 此外，`qtools.tdc.analysis.efficiency.compute_pairs()` 和 `TDC.measure_pairs()` 返回的是独立的无类型定义散装字典（`dict`），计算预警效率（heralding efficiency）和偶然符合本底。

### 存在的问题
- **概念割裂**：$g^{(2)}(\tau)$ 微分直方图与门内积分符合计数本质上属于同一物理测量流程的不同抽象层级，但被拆分在 `G2Result` 与 `CoincidenceResult` 两个互不相通的类中；
- **通道数硬编码与重叠**：`TripletResult` 只是 $N=3$ 的特例，与通用 $N$ 通道的 `GateResult` 功能重叠；
- **门控光子模型职责不清**：`GatePhotonResult` 需要独立统一为门控光子结果；`compute_pairs` 则继续作为独立的效率分析函数，不与门控光子事件模型混合。

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
1. **`CoincidenceResult`**：两通道关联与符合的核心模型。既能容纳软件分析生成的完整 $g^{(2)}(\tau)$ 直方图与归一化曲线，也能容纳硬件 FPGA（如 TDC1、CIQTEK accord、ID1000 TSCO）直接给出的纯标量符合计数与偶然估算。
2. **`MultiCoincidenceResult`**：多通道符合（$N \ge 3$）的通用模型。整合 $N=3$ 时的完整交叉关联直方图与任意 $N$ 通道下的星型门控符合、事件列表。
3. **`HeraldingGateResult`**：门控光子结果模型。以 Trigger/Herald 为基准，统一管理门内光子时延分布、多光子到达映射及门控统计。`compute_pairs()` 属于独立的效率分析函数，不并入该模型。

---

## 3. 详细设计与数据模型定义 (Data Models)

### 3.1 统一后的 `CoincidenceResult`

```python
@dataclass
class CoincidenceResult:
    """两通道时延关联与符合结果。

    ``mode="histogram"`` 用于完整 g² 延迟直方图；
    ``mode="window_count"`` 用于指定窗口内的符合计数。
    时间字段使用 ``unit`` 指定的单位，默认统一为整数 ps。
    """
    mode: Literal["histogram", "window_count"]
    singles_start: float
    singles_stop: float
    integration_time: float
    unit: str = "ps"
    method: Literal["software", "hardware"] = "software"

    # 分析参数。bin_width 是本次 histogram 的 bin 宽度，
    # stop_delay 是 stop 通道相对 start 通道的延迟。
    bin_width: Optional[int] = None
    stop_delay: int = 0

    # 窗口与标量计数
    window_start: Optional[int] = None
    window_stop: Optional[int] = None
    raw_count: Optional[int] = None
    accidental_count: Optional[float] = None
    accidental_count_per_bin: Optional[float] = None
    accidental_method: Optional[Literal["sideband", "rate_product"]] = None

    # 直方图数据；硬件或 count-only 模式可以为空
    histogram: Optional[NDArray[np.uint64]] = None
    bin_edges: Optional[NDArray[np.int64]] = None

    @property
    def window(self) -> Optional[int]:
        """符合窗口宽度。"""
        if self.window_start is None or self.window_stop is None:
            return None
        return self.window_stop - self.window_start

    @property
    def n_bins(self) -> int:
        """直方图 bin 数。"""
        return 0 if self.histogram is None else len(self.histogram)

    @property
    def window_n_bins(self) -> Optional[int]:
        """窗口宽度对应的 bin 数；没有 bin_width 时返回 None。"""
        if self.window is None or self.bin_width is None:
            return None
        return int(np.ceil(self.window / self.bin_width))

    @property
    def bin_centers(self) -> Optional[NDArray[np.float64]]:
        """直方图 bin 中心。"""
        if self.bin_edges is None:
            return None
        return (self.bin_edges[:-1] + self.bin_edges[1:]) / 2.0

    @property
    def normalized(self) -> Optional[NDArray[np.float64]]:
        """归一化 g²(τ)；没有完整直方图时返回 None。"""
        if (
            self.mode != "histogram"
            or self.histogram is None
            or self.bin_edges is None
            or self.integration_time <= 0
        ):
            return None
        unit_to_s = {"ps": 1e-12, "ns": 1e-9, "us": 1e-6, "ms": 1e-3}
        if self.unit not in unit_to_s:
            raise ValueError(f"Unsupported time unit: {self.unit!r}")
        bin_width_s = np.diff(self.bin_edges) * unit_to_s[self.unit]
        denominator = self.singles_start * self.singles_stop * bin_width_s * self.integration_time
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(denominator > 0, self.histogram / denominator, 0.0)

    @property
    def net_count(self) -> Optional[float]:
        """扣除偶然符合后的窗口内计数。"""
        if self.raw_count is None:
            return None
        return (
            float(self.raw_count)
            if self.accidental_count is None
            else float(self.raw_count) - self.accidental_count
        )

    @property
    def raw_pair_rate(self) -> Optional[float]:
        if self.raw_count is None or self.integration_time <= 0:
            return None
        return self.raw_count / self.integration_time

    @property
    def net_pair_rate(self) -> Optional[float]:
        if self.net_count is None or self.integration_time <= 0:
            return None
        return self.net_count / self.integration_time
```

---

### 3.2 统一后的 `MultiCoincidenceResult`

```python
@dataclass
class MultiCoincidenceResult:
    """N 通道高阶符合结果 (N >= 3)。

    统一原 TripletResult 与 GateResult 的数据模型；所有两两延迟直方图
    使用 ``(channel_a, channel_b)`` 键存放在同一个字典中。
    """
    channels: List[int]
    singles: List[float]
    integration_time: float
    count: int = 0
    unit: str = "ps"
    bin_width: Optional[int] = None
    window_start: Optional[int] = None
    window_stop: Optional[int] = None

    # 键为 (channel_a, channel_b)，值为 delay(channel_a - channel_b) 直方图
    pairwise_hists: Dict[Tuple[int, int], NDArray[np.uint64]] = field(default_factory=dict)

    bin_edges: Optional[NDArray[np.int64]] = None
    events: Optional[List[Tuple[Tuple[int, ...], int]]] = None

    @property
    def order(self) -> int:
        return len(self.channels)

    @property
    def n_signals(self) -> int:
        return len(self.channels) - 1

    @property
    def n_bins(self) -> int:
        if self.pairwise_hists:
            return len(next(iter(self.pairwise_hists.values())))
        return 0

    @property
    def window(self) -> Optional[int]:
        if self.window_start is None or self.window_stop is None:
            return None
        return self.window_stop - self.window_start

    @property
    def bin_centers(self) -> Optional[NDArray[np.float64]]:
        if self.bin_edges is None:
            return None
        return (self.bin_edges[:-1] + self.bin_edges[1:]) / 2.0

    def pair_hist(self, channel_a: int, channel_b: int) -> Optional[NDArray[np.uint64]]:
        """返回指定方向的两两延迟直方图。"""
        return self.pairwise_hists.get((channel_a, channel_b))
```

`MultiCoincidenceResult` 不再为 N=3 单独定义 `hist_21`、`hist_31`、`hist_32`、
`hist_23` 等重复属性。调用方通过 `pair_hist(channel_a, channel_b)` 访问所有方向；
`order`、`n_bins` 和 `window` 都由 canonical 字段派生。这样三通道和 N 通道使用同一套接口。

---

### 3.3 统一后的 `HeraldingGateResult`

```python
@dataclass
class HeraldingGateResult:
    """门控光子与门内光子统计结果。

    该模型只对应原 GatePhotonResult。预警效率、CAR 及 pairs 分析
    不属于本模型；``compute_pairs`` 继续作为独立的效率分析函数。
    """
    channels: List[int]
    singles: List[float]
    integration_time: float
    unit: str = "ps"
    bin_width: Optional[int] = None
    window_start: Optional[int] = None
    window_stop: Optional[int] = None

    histogram: Optional[NDArray[np.uint64]] = None
    bin_edges: Optional[NDArray[np.int64]] = None

    # 可选的门控光子对应关系；默认不保存 Python 事件列表
    flat_photons: Optional[NDArray[np.int64]] = None
    flat_channels: Optional[NDArray[np.int32]] = None
    flat_offsets: Optional[NDArray[np.int32]] = None
    per_gate: Optional[List[List[Tuple[int, int]]]] = None

    @property
    def n_gates(self) -> int:
        if self.flat_offsets is not None:
            return max(0, len(self.flat_offsets) - 1)
        return 0 if self.per_gate is None else len(self.per_gate)

    @property
    def total_photons(self) -> int:
        if self.flat_photons is not None:
            return len(self.flat_photons)
        return sum(len(hits) for hits in self.per_gate or [])
```

### 3.4 时间单位与数值类型约定

- 字段名称使用通用命名：`bin_width`、`window_start`、`window_stop`、`bin_edges`，不在名称中重复单位。
- `unit` 保留在三个统一模型中，默认值为 ``"ps"``；它描述这些时间字段的单位。
- 后端读取 ns、ps 或原生 tick 后，先转换为整数 ps，再创建默认结果对象。若调用方显式要求其他输出单位，适配层必须同时转换全部时间字段并更新 `unit`。
- 时间戳、延迟、窗口和 bin 边界使用 `int64`；histogram 计数使用 `uint64`；计数率、偶然估算和归一化结果使用 `float64`。
- `bin_width` 表示分析 histogram 的 bin 宽度，不表示设备原生时间分辨率；原生 tick 信息作为采集元数据单独保存。
- `window`、`n_bins`、`window_n_bins`、`net_count` 和计数率等值通过 `@property` 派生，不重复存储。
- `__post_init__` 负责校验模式字段：`histogram` 模式必须具备 histogram、bin_edges 和 bin_width；`window_count` 模式必须具备 raw_count 及完整窗口，附带 histogram 则按同一形状规则校验。
- 所有模型都校验时间边界的顺序、`unit` 的支持范围、数组长度和通道数量；校验失败立即抛出 `ValueError`，不在下游静默修正。

---

## 4. 未覆盖信息与潜在物理/工程盲区深度分析 (Edge Cases Analysis)

在进行合并时，必须审慎处理以下 5 项潜在信息丢失或物理盲区：

### 4.1 硬件符合模式下直方图缺失的非空安全
- **盲区**：纯硬件符合计数器（如 S15 TDC1 的 `pairs`，ID1000 的 `TSCO`，CIQTEK 的 `accord`）由板载 FPGA 处理，只输出标量整数，没有直方图。
- **应对**：`CoincidenceResult.histogram` 必须严格标为 `Optional[NDArray] = None`。下游绘图或提取峰值的函数（如 CLI 导出 npz）必须先检查 `result.histogram is not None`，不能假设直方图永远存在。

### 4.2 多通道网状拓扑 vs 星型拓扑的直方图丢失
- **盲区**：原 `TripletResult` 包含了信号通道之间的互相关直方图（如 $h_{32}: t_3 - t_2$），这对于三光子态（如 GHZ）检测或 HOM 干涉至关重要；而原 `GateResult` 的 C 核心实现为了速度只记录了星型直方图（$t_{sig,k} - t_{ref}$）。
- **应对**：在 `MultiCoincidenceResult` 中使用 `pairwise_hists: Dict[Tuple[int, int], NDArray]`。在三通道调用 `compute_triplet_g2` 时，将全部 4 个直方图均存入字典；在通用 $N$ 通道调用时，存入星型直方图，避免丢失通道间互相关。

### 4.3 脉冲激光 (Pulsed) vs 连续光 (CW) 的分析差异
- **盲区**：目前无论是 `CoincidenceResult` 还是 `compute_pairs`，都只设定了一个单一的门控区间 `[window_start, window_stop]`。对于脉冲激光，需同时对比零延时中心峰（$k=0$）与周期性边带脉冲峰（$k=\pm 1, \pm 2$）的积分比值以计算非后选择的 $g^{(2)}(0)$。
- **应对**：在 `CoincidenceResult` 中增加对周期性多窗口（Pulsed multi-peak integration）或边峰面积比率字段的预留。

### 4.4 大数据量下离散 `events` 列表的内存开销
- **盲区**：在 1 MHz 计数率下采集数秒，符合事件可能达到上千万个。如果盲目将每个符合事件保存为 Python 元组列表 `((t1, t2), ref_idx)`，内存将膨胀至数 GB。
- **应对**：
  1. 默认设置 `store_events=False`，仅在用户显式需要事件重构时生成；
  2. 采用类似 `GatePhotonResult` 的扁平化 `int64` NumPy 数组方式进行存储。

### 4.5 门内单通道死时间与多光子分辨力限制
- **盲区**：普通单光子探测器与 TDC 输入通道存在死时间（几十纳秒），单通道在单个门内很难分辨第二个光子。
- **应对**：`HeraldingGateResult` 必须明确多光子分布是指跨多个物理通道还是单通道多次击中，并在统计属性中区分。

---

## 5. Downstream (下游) 修改清单与波及面评估

| 文件路径 | 原有依赖/行为 | 调整内容与修改要点 |
| :--- | :--- | :--- |
| **`src/qtools/tdc/data.py`** | 定义 5+1 个分散类 | 1. 重构 `CoincidenceResult`；<br/>2. 新增 `MultiCoincidenceResult`；<br/>3. 新增只负责门控光子结果的 `HeraldingGateResult`；<br/>4. 删除旧模型的重复定义，不建立兼容别名层。 |
| **`src/qtools/tdc/analysis/g2.py`** | `compute_g2` 返回 `G2Result`；<br/>`compute_triplet_g2` 返回 `TripletResult`；<br/>`compute_gate_coincidence` 返回 `GateResult`；<br/>`compute_gate_photons` 返回 `GatePhotonResult` | 1. `compute_g2` 改为返回 `CoincidenceResult`；<br/>2. `compute_triplet_g2` 与 `compute_gate_coincidence` 改为返回 `MultiCoincidenceResult`；<br/>3. `compute_gate_photons` 改为返回 `HeraldingGateResult`。 |
| **`src/qtools/tdc/analysis/efficiency.py`** | `compute_pairs` 返回无类型的 `dict` | 保持 `compute_pairs` 作为独立效率分析函数；本次不将它并入 `HeraldingGateResult`。后续若需要类型化，另行设计 `PairAnalysisResult`。 |
| **`src/qtools/tdc/backends/base.py`** | `TDCBackend.get_g2` 注记为 `G2Result`；<br/>`TDCBackend.get_coincidence` | 1. 统一类型注记为 `CoincidenceResult`；<br/>2. `get_coincidence` 软件分支自动将底层的直方图挂载到返回对象中。 |
| **`src/qtools/tdc/backends/idq/backend_id1000.py`** | `get_g2` / `get_hardware_histogram` 返回 `G2Result` | 返回扩展后的 `CoincidenceResult`。 |
| **`src/qtools/tdc/backends/ciqtek/backend.py`** | `get_coincidence` 返回 `CoincidenceResult` | 保持不变，直方图保持为 `None`。 |
| **`src/qtools/tdc/backends/s15_tdc1/`** | `backend.py` 与 `exp_backend.py` 中的 `get_coincidence` 与 `get_g2` | 返回类型适配。 |
| **`src/qtools/tdc/measurement.py`** | `TDC.measure_g2`, `measure_pairs`, `measure_triplet`, `measure_gate` | `measure_g2`、`measure_coincidence`、`measure_triplet`、`measure_gate` 对齐新模型；`measure_pairs` 保持独立效率分析返回值。 |
| **`src/qtools/tdc/api.py`** | `g2()`, `pairs()`, `triplet()`, `gate()` | 保持 `pairs()` 返回 9-tuple 行为不变（或增强）；其它函数返回新模型。 |
| **`src/qtools/tdc/cli.py`** | 调用 `measure_pairs`, `measure_g2`, `measure_coincidence` | 适配类型，直方图访问增加空值保护。 |
| **`tests/tdc/`** | `test_coincidence.py`, `test_cli.py`, `test_idq_backends.py` 等 | 校验新模型、模式约束、单位转换、空直方图保护及多通道 pairwise histogram。 |

---

## 6. 迁移边界

本次统一不建立旧模型的别名、继承垫片或字典访问模拟层。实现阶段需要一次性更新内部调用方、类型注解、CLI、示例和测试，使它们直接使用三个 canonical 模型：

- `CoincidenceResult`：两通道 histogram 或 window count；
- `MultiCoincidenceResult`：N 通道符合及 pairwise histograms；
- `HeraldingGateResult`：门控光子及门内光子统计。

`compute_pairs()` 继续返回当前独立的效率分析结果；它不属于上述三个数据模型。

---

## 7. 分步实施计划 (Implementation Roadmap)

### Phase 1: 数据模型升级 (`data.py`)
- [ ] 扩展 `CoincidenceResult`，接入 histogram/window_count 两种模式与派生属性；
- [ ] 实现 `MultiCoincidenceResult`，以统一的 `pairwise_hists` 字典覆盖 3 通道与 $N$ 通道；
- [ ] 实现只负责门控光子统计的 `HeraldingGateResult`；
- [ ] 删除旧模型的重复定义，内部调用方全部切换到 canonical 模型。

### Phase 2: 核心分析算法层重构 (`analysis/`)
- [ ] 重构 `g2.py` 中的 `compute_g2`，返回扩展后的 `CoincidenceResult`；
- [ ] 统一 `compute_triplet_g2` 与 `compute_gate_coincidence`，输出 `MultiCoincidenceResult`；
- [ ] 更新 `compute_gate_photons`，输出 `HeraldingGateResult`；
- [ ] 保持 `efficiency.py` 中的 `compute_pairs` 为独立效率分析接口，不与 `HeraldingGateResult` 合并。

### Phase 3: 硬件驱动与抽象基类对齐 (`backends/`)
- [ ] 更新 `backends/base.py` 中 `get_g2` 与 `get_coincidence` 的返回类型注记与实现；
- [ ] 适配 `id1000`、`ciqtek`、`s15_tdc1`，验证硬件标量模式与软件直方图模式。

### Phase 4: 高层测量接口与 CLI 对齐 (`measurement.py`, `api.py`, `cli.py`)
- [ ] 更新 `TDC.measure_g2`、`measure_coincidence`、`measure_triplet`、`measure_gate` 的返回类型；
- [ ] 保持 `TDC.measure_pairs` 的独立效率分析语义；
- [ ] 确保 CLI 脚本与 `api.pairs()` 正常工作。

### Phase 5: 测试用例验证与文档更新 (`tests/`, `README.md`)
- [ ] 运行现有测试套件并修复接口迁移导致的失败；
- [ ] 新增 `test_data_unification.py`，测试模式约束、单位转换、空值保护、派生属性与新模型接口；
- [ ] 更新 `qtools/tdc/README.md` 的架构图与 API 说明。
