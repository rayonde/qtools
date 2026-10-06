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
   - 此外，`qtools.tdc.analysis.efficiency.compute_pairs()` 和 `TDC.measure_pairs()` 返回的是无类型定义的散装字典（`dict`），计算预警效率（heralding efficiency）和偶然符合本底。

### 存在的问题
- **概念割裂**：$g^{(2)}(\tau)$ 微分直方图与门内积分符合计数本质上属于同一物理测量流程的不同抽象层级，但被拆分在 `G2Result` 与 `CoincidenceResult` 两个互不相通的类中；
- **通道数硬编码与重叠**：`TripletResult` 只是 $N=3$ 的特例，与通用 $N$ 通道的 `GateResult` 功能重叠；
- **预警门控场景缺少类型化支持**：`GatePhotonResult` 与 `compute_pairs` 分散在不同模块，量子光学中最核心的预警单光子/纠缠源表征（Heralding efficiency, CAR, 门控光子到达统计）缺乏统一的一等公民（First-class citizen）数据模型。

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
                           ├───►       HeraldingGateResult
compute_pairs (dict)     ──┘           (门控光子流、预警效率与 CAR)
```

### 模型定位与职责划分
1. **`CoincidenceResult`**：两通道关联与符合的核心模型。既能容纳软件分析生成的完整 $g^{(2)}(\tau)$ 直方图与归一化曲线，也能容纳硬件 FPGA（如 TDC1、CIQTEK accord、ID1000 TSCO）直接给出的纯标量符合计数与偶然估算。
2. **`MultiCoincidenceResult`**：多通道符合（$N \ge 3$）的通用模型。整合 $N=3$ 时的完整交叉关联直方图与任意 $N$ 通道下的星型门控符合、事件列表。
3. **`HeraldingGateResult`**：预警门控与单光子源表征模型。以 Trigger/Herald 为基准，统一管理门内光子时延分布、预警效率（$\eta_{herald}, \eta_{signal}, \eta_{avg}$）、符合偶然比（CAR）及多光子到达映射。

---

## 3. 详细设计与数据模型定义 (Data Models)

### 3.1 统一后的 `CoincidenceResult`

```python
@dataclass
class CoincidenceResult:
    """两通道时延关联与符合测量结果 (2-fold Coincidence / g² correlation).
    
    统一支持：
    1. 软件 g² 直方图测量 (含归一化 g²(τ))
    2. 软件时间窗标量符合计算与偶然侧带扣除
    3. 硬件 FPGA 标量符合计数 (无直方图时 histogram 为 None)
    """
    count: int                                      # 门宽内的原始符合计数
    channel1_rate: float                            # 通道 1 计数率 (counts/s)
    channel2_rate: float                            # 通道 2 计数率 (counts/s)
    integration_time: float                         # 积分测量时间 (s)
    order: int = 2                                  # 符合阶数，默认 2
    
    # 门宽与本底估算 (标量符合相关)
    window_ps: Optional[int] = None                 # 门宽 (ps)
    window_start_ps: Optional[float] = None         # 窗口起始时延 (ps)
    window_stop_ps: Optional[float] = None          # 窗口截止时延 (ps)
    accidental_count: Optional[float] = None        # 估算的偶然符合数
    acc_count_perbin: Optional[float] = None        # 侧带单 bin 平均偶然计数
    accidental_method: Optional[str] = None         # 'sideband' 或 'rate_product'
    method: str = "software"                        # 'software' 或 'hardware'
    
    # 直方图数据 (纯硬件模式下为 None)
    histogram: Optional[NDArray[np.uint64]] = None  # 延时直方图，shape (n_bins,)
    bin_edges: Optional[NDArray[np.float64]] = None # 直方图 bin 边缘，shape (n_bins + 1,)
    resolution_ps: Optional[float] = None           # 单个 bin 的时间精度 (ps)

    # -- 向下兼容与便利属性 --
    @property
    def singles_start(self) -> float:
        """兼容原 G2Result: start 通道计数率."""
        return self.channel1_rate

    @property
    def singles_stop(self) -> float:
        """兼容原 G2Result: stop 通道计数率."""
        return self.channel2_rate

    @property
    def bin_centers(self) -> Optional[NDArray[np.float64]]:
        """直方图中心坐标 (bin 单位)."""
        if self.bin_edges is None:
            return None
        return (self.bin_edges[:-1] + self.bin_edges[1:]) / 2.0

    @property
    def n_bins(self) -> int:
        """直方图 bin 数."""
        return len(self.histogram) if self.histogram is not None else 0

    @property
    def normalized(self) -> Optional[NDArray[np.float64]]:
        """兼容原 G2Result: 归一化 g²(τ) 数组."""
        if self.histogram is None or self.bin_edges is None or self.integration_time <= 0:
            return None
        bin_width_s = np.diff(self.bin_edges) * 1e-12
        denominator = self.channel1_rate * self.channel2_rate * bin_width_s * self.integration_time
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(denominator > 0, self.histogram / denominator, 0.0)

    @property
    def net_count(self) -> float:
        """净符合数 (原始符合扣除偶然符合)."""
        return float(self.count) if self.accidental_count is None else float(self.count) - self.accidental_count

    @property
    def net_rate(self) -> float:
        """净符合率 (counts/s)."""
        return self.net_count / self.integration_time if self.integration_time > 0 else 0.0

    @property
    def rate(self) -> float:
        """粗符合率 (counts/s)."""
        return self.count / self.integration_time if self.integration_time > 0 else 0.0
```

---

### 3.2 统一后的 `MultiCoincidenceResult`

```python
@dataclass
class MultiCoincidenceResult:
    """N 通道高阶符合测量结果 (Multi-fold Coincidence, N >= 3).
    
    整合原 TripletResult (N=3) 与 GateResult (任意 N).
    """
    channels: List[int]                                    # 参与符合的通道列表 [ref, sig1, sig2, ...]
    count: int                                             # 全通道共同触发的符合事件总数 (即原 n_fold_count)
    singles: List[float]                                   # 各通道计数率 (counts/s)
    integration_time: float                                # 积分时间 (s)
    order: int = 3                                         # 符合阶数 (len(channels))
    bins: int = 500                                        # 直方图 bin 数
    window_ps: Optional[float] = None                      # 符合门宽 (ps)
    
    # 两两通道时延直方图映射，键为 (ch_stop, ch_start)，值为 uint64 直方图
    pairwise_hists: Dict[Tuple[int, int], NDArray[np.uint64]] = field(default_factory=dict)
    
    # 离散符合事件元组列表: ((t_ref, t_sig1, ...), ref_idx)
    events: List[Tuple[Tuple[int, ...], int]] = field(default_factory=list)

    # -- 兼容原 GateResult 属性 --
    @property
    def n_fold_count(self) -> int:
        return self.count

    @property
    def n_signals(self) -> int:
        return len(self.channels) - 1

    # -- 兼容原 TripletResult 属性 (仅当 N=3 时生效) --
    @property
    def hist_21(self) -> Optional[NDArray[np.uint64]]:
        return self.pairwise_hists.get((self.channels[1], self.channels[0]))

    @property
    def hist_31(self) -> Optional[NDArray[np.uint64]]:
        return self.pairwise_hists.get((self.channels[2], self.channels[0]))

    @property
    def hist_32(self) -> Optional[NDArray[np.uint64]]:
        return self.pairwise_hists.get((self.channels[2], self.channels[1]))

    @property
    def hist_23(self) -> Optional[NDArray[np.uint64]]:
        return self.pairwise_hists.get((self.channels[1], self.channels[2]))
```

---

### 3.3 统一后的 `HeraldingGateResult`

```python
@dataclass
class HeraldingGateResult:
    """门控预警与单光子源特性测量结果 (Heralding / Gated Photon Result).
    
    涵盖：
    1. 预警效率 (Heralding Efficiency: η_start, η_stop, η_avg)
    2. 符合与偶然统计、符合偶然比 (CAR)
    3. 门控单次/多光子详细时间戳对应 (可选，原 GatePhotonResult)
    """
    ch_herald: int                                         # 预警/触发通道
    ch_signals: List[int]                                  # 探测信号通道列表
    herald_counts: int                                     # 预警触发事件数
    coinc_counts: float                                    # 门内符合计数 (净计数或粗计数)
    accidental_counts: float                               # 偶然符合计数
    integration_time: float                                # 测量时间 (s)
    
    # 效率指标 (来源于原 compute_pairs)
    eff_herald: float = 0.0                                # 预警端效率 η_herald = C_net / N_herald
    eff_signal: float = 0.0                                # 信号端效率 η_signal = C_net / N_signal
    eff_avg: float = 0.0                                   # 几何平均效率 η_avg = R_net / sqrt(R1 * R2)
    car: float = 0.0                                       # 符合偶然比 Coincidence-to-Accidental Ratio
    
    # 计数率
    start_rate: float = 0.0                                # 触发通道计数率 (cps)
    stop_rate: float = 0.0                                 # 信号通道计数率 (cps)
    raw_pair_rate: float = 0.0                             # 粗符合率 (cps)
    net_pair_rate: float = 0.0                             # 净符合率 (cps)
    
    # 门控直方图与光子微观信息 (可选)
    histogram: Optional[NDArray[np.uint64]] = None         # 门内信号光子到达直方图
    bin_edges: Optional[NDArray[np.float64]] = None
    coinc_start_bin: Optional[int] = None
    coinc_stop_bin: Optional[int] = None
    
    # 扁平化门控光子列表 (若执行了细粒度光子追踪)
    flat_photons: Optional[NDArray[np.int64]] = None
    flat_channels: Optional[NDArray[np.int32]] = None
    flat_offsets: Optional[NDArray[np.int32]] = None
    per_gate: Optional[List[List[Tuple[int, int]]]] = None

    # -- 兼容原 compute_pairs 字典访问 --
    def __getitem__(self, item: str) -> Any:
        mapping = {
            "pair_counts": self.coinc_counts,
            "acc_pair_counts": self.accidental_counts,
            "raw_pair_rate": self.raw_pair_rate,
            "net_pair_rate": self.net_pair_rate,
            "integration_time": self.integration_time,
            "start_rate": self.start_rate,
            "stop_rate": self.stop_rate,
            "eff_start": self.eff_herald,
            "eff_stop": self.eff_signal,
            "eff_avg": self.eff_avg,
            "coinc_start": self.coinc_start_bin,
            "coinc_stop": self.coinc_stop_bin,
            "bin_edges": self.bin_edges,
            "histogram": self.histogram,
        }
        if item in mapping:
            return mapping[item]
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        """导出为原有 compute_pairs 字典格式."""
        return {k: self[k] for k in [
            "pair_counts", "acc_pair_counts", "raw_pair_rate", "net_pair_rate",
            "integration_time", "start_rate", "stop_rate", "eff_start",
            "eff_stop", "eff_avg", "coinc_start", "coinc_stop", "bin_edges", "histogram"
        ]}
```

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
| **`src/qtools/tdc/data.py`** | 定义 5+1 个分散类 | 1. 重构 `CoincidenceResult`；<br/>2. 新增 `MultiCoincidenceResult`；<br/>3. 新增 `HeraldingGateResult`；<br/>4. 保留 `G2Result`, `TripletResult`, `GateResult`, `GatePhotonResult` 为向后兼容别名。 |
| **`src/qtools/tdc/analysis/g2.py`** | `compute_g2` 返回 `G2Result`；<br/>`compute_triplet_g2` 返回 `TripletResult`；<br/>`compute_gate_coincidence` 返回 `GateResult`；<br/>`compute_gate_photons` 返回 `GatePhotonResult` | 1. `compute_g2` 改为返回 `CoincidenceResult`；<br/>2. `compute_triplet_g2` 与 `compute_gate_coincidence` 改为返回 `MultiCoincidenceResult`；<br/>3. `compute_gate_photons` 改为返回 `HeraldingGateResult`。 |
| **`src/qtools/tdc/analysis/efficiency.py`** | `compute_pairs` 返回无类型的 `dict` | 改为返回结构化的 `HeraldingGateResult`（通过实现 `__getitem__` 保证原字典取值代码 100% 兼容）。 |
| **`src/qtools/tdc/backends/base.py`** | `TDCBackend.get_g2` 注记为 `G2Result`；<br/>`TDCBackend.get_coincidence` | 1. 统一类型注记为 `CoincidenceResult`；<br/>2. `get_coincidence` 软件分支自动将底层的直方图挂载到返回对象中。 |
| **`src/qtools/tdc/backends/idq/backend_id1000.py`** | `get_g2` / `get_hardware_histogram` 返回 `G2Result` | 返回扩展后的 `CoincidenceResult`。 |
| **`src/qtools/tdc/backends/ciqtek/backend.py`** | `get_coincidence` 返回 `CoincidenceResult` | 保持不变，直方图保持为 `None`。 |
| **`src/qtools/tdc/backends/s15_tdc1/`** | `backend.py` 与 `exp_backend.py` 中的 `get_coincidence` 与 `get_g2` | 返回类型适配。 |
| **`src/qtools/tdc/measurement.py`** | `TDC.measure_g2`, `measure_pairs`, `measure_triplet`, `measure_gate` | `measure_pairs` 返回 `HeraldingGateResult`，其它方法对齐新模型。 |
| **`src/qtools/tdc/api.py`** | `g2()`, `pairs()`, `triplet()`, `gate()` | 保持 `pairs()` 返回 9-tuple 行为不变（或增强）；其它函数返回新模型。 |
| **`src/qtools/tdc/cli.py`** | 调用 `measure_pairs`, `measure_g2`, `measure_coincidence` | 适配类型，直方图访问增加空值保护。 |
| **`tests/tdc/`** | `test_coincidence.py`, `test_cli.py`, `test_idq_backends.py` 等 | 校验新类型及别名断言，新增多通道与预警单元测试。 |

---

## 6. 向下兼容性保障方案 (Backward Compatibility)

为确保现有用户代码、示例脚本及测试用例零报错破坏，采用以下平滑兼容策略：

```python
# 1. 兼容别名与子类绑定
class G2Result(CoincidenceResult):
    """向下兼容别名：旧代码 isinstance(res, G2Result) 依然为 True."""
    pass

class TripletResult(MultiCoincidenceResult):
    pass

class GateResult(MultiCoincidenceResult):
    pass

class GatePhotonResult(HeraldingGateResult):
    pass
```

- **模块级导出保持**：`qtools.tdc.__init__` 和 `qtools.tdc.data.__all__` 依然导出旧类名；
- **字典访问仿真**：`HeraldingGateResult` 实现 `__getitem__` 和 `.get()`，旧代码中 `res["eff_avg"]` 或 `res["pair_counts"]` 照常执行；
- **渐进废弃告警**：在导入旧类名时发出可选的 `PendingDeprecationWarning`，给调用者充分的迁移窗口。

---

## 7. 分步实施计划 (Implementation Roadmap)

### Phase 1: 数据模型升级与兼容垫片 (`data.py`)
- [ ] 扩展 `CoincidenceResult`，接入直方图与归一化计算属性；
- [ ] 实现 `MultiCoincidenceResult`，整合 3 通道与 $N$ 通道属性映射；
- [ ] 实现 `HeraldingGateResult`，整合效率统计与门控光子流；
- [ ] 建立 `G2Result`、`TripletResult`、`GateResult`、`GatePhotonResult` 的别名与继承垫片。

### Phase 2: 核心分析算法层重构 (`analysis/`)
- [ ] 重构 `g2.py` 中的 `compute_g2`，返回扩展后的 `CoincidenceResult`；
- [ ] 统一 `compute_triplet_g2` 与 `compute_gate_coincidence`，输出 `MultiCoincidenceResult`；
- [ ] 更新 `compute_gate_photons`，输出 `HeraldingGateResult`；
- [ ] 更新 `efficiency.py` 中的 `compute_pairs`，输出 `HeraldingGateResult`。

### Phase 3: 硬件驱动与抽象基类对齐 (`backends/`)
- [ ] 更新 `backends/base.py` 中 `get_g2` 与 `get_coincidence` 的返回类型注记与实现；
- [ ] 适配 `id1000`、`ciqtek`、`s15_tdc1`，验证硬件标量模式与软件直方图模式。

### Phase 4: 高层测量接口与 CLI 对齐 (`measurement.py`, `api.py`, `cli.py`)
- [ ] 更新 `TDC.measure_pairs` 返回 `HeraldingGateResult`；
- [ ] 确保 CLI 脚本与 `api.pairs()` 正常工作。

### Phase 5: 测试用例验证与文档更新 (`tests/`, `README.md`)
- [ ] 运行现有全部单元测试（确保现有 99 个测试 100% 通过）；
- [ ] 新增 `test_data_unification.py`，测试别名兼容性、空值保护与新模型属性；
- [ ] 更新 `qtools/tdc/README.md` 的架构图与 API 说明。
