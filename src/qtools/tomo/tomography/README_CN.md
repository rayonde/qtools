# 量子态层析（Quantum State Tomography）

本目录实现的是有限维量子态层析（quantum state tomography, QST）。它最初面向偏振光子的一个或多个 qubit：实验者准备一组已知测量态，记录每个投影结果的计数，再由程序重建密度矩阵 `rho`。

当前实现的核心假设是：系统由 `n_qubits` 个 qubit 组成，因此 Hilbert 空间维度为

\[
d = 2^{n_{\rm qubits}}, \qquad \rho\in\mathbb C^{d\times d}.
\]

这意味着代码可以处理任意有限个 qubit，但不能直接把 OAM 的无限维 Fock/模式空间作为一个无限大小的矩阵传给 `Tomography`。OAM 的可行扩展方式见文末“面向 OAM 的扩展路线”。

## 1. 最短可运行示例

从仓库根目录运行下面的代码。示例文件位于 `src/qtools/tomo/tomography/ExampleFiles/`；如果当前工作目录已经是 `src/qtools/tomo/tomography`，则可以把路径简写为 `ExampleFiles/...`。

```python
from pathlib import Path
import numpy as np

from qtools.tomo.tomography import Tomography, fidelity, purity

root = Path.cwd()
data_file = root / "src/qtools/tomo/tomography/ExampleFiles/1_qubit_example.json"
conf_file = root / "src/qtools/tomo/tomography/ExampleFiles/conf.toml"

t = Tomography(nQ=1)
t.import_conf(conf_file)       # 读取 TOML 算法配置
t.import_data(data_file)       # 读取 JSON 测量数据

rho, intensity, fval = t.run_tomography()

print("rho =\\n", rho)
print("trace(rho) =", np.trace(rho))
print("intensity =", intensity)
print("fit residual =", fval)
print("purity =", purity(rho))

# 该示例的目标态是 |R> = (|H> + i|V>)/sqrt(2)
target = np.array([1, 1j])
target = np.outer(target, target.conj())
print("fidelity =", fidelity(rho, target))
```

也可以直接使用仓库中的完整脚本 `Example.py`，其中还展示了 Bell 态、双探测器、串扰和效率修正。注意旧版 README 中的 `import QuantumTomography as qKLib` 是上游项目的历史包名；在本仓库中优先使用：

```python
from qtools.tomo import tomography
t = tomography.Tomography()
```

或直接从 `qtools.tomo.tomography` 导入 `Tomography`。

### `Tomography` 的典型生命周期

```text
Tomography()
   │
   ├─ import_conf(.toml)       设置 MLE/HMLE、漂移/偶然符合等选项
   ├─ import_data(.json)       解析测量态、计数、探测器元数据
   │      └─ buildTomoInput()  整理成内部二维数组
   ├─ run_tomography()
   │      ├─ filter_data()     构造测量密度算符并做校正
   │      ├─ tomography_LINEAR() 产生 MLE 初值（默认路径）
   │      └─ tomography_MLE()  非线性最小二乘优化
   └─ 返回 (rho, intensity, fval)
```

`rho` 是迹为 1 的复 Hermitian 半正定矩阵；`intensity` 是拟合得到的未归一化总强度；`fval` 是内部加权残差平方和，越小通常表示模型与数据越一致，但它不是严格意义上已归一化的 p-value。

## 2. 输入文件

### 2.1 TOML 配置文件 `conf.toml`

配置只控制算法和校正，不包含逐条实验计数。常用字段如下。

| TOML 字段 | 类型 | 含义 | 默认/注意 |
|---|---|---|---|
| `method` | `"MLE"`, `"HMLE"`, `"LINEAR"` | 重建方法 | 默认 `"MLE"`；代码注释中的 BME 尚未接入 `run_tomography()` |
| `starting_matrix` | `d×d` 复矩阵 | MLE 初始密度矩阵 | 不提供时先做线性反演；矩阵尺寸必须为 `(2**n_qubits, 2**n_qubits)` |
| `do_drift_correction` | 布尔值 | 使用每条数据的 `relative_intensity` 做强度归一 | 不需要漂移修正时为 `false` |
| `do_accidental_correction` | 布尔值 | 用 singles、积分时间和 coincidence window 估计偶然符合 | 主要用于多 qubit；单 qubit 不应启用 |
| `do_error_estimation` | 非负整数 | Monte Carlo 生成的状态数 | `0` 表示不估计；数值越大越慢 |
| `get_bell_settings` | 布尔值 | 对两 qubit 结果搜索 CHSH 测量设置 | 只影响附加分析，不改变 `rho` |
| `beta` | `0..0.5` 的浮点数 | HMLE 的 hedge 强度 | 只有 `method = "HMLE"` 时使用，且必须大于 0 |
| `ftol`, `xtol`, `gtol`, `maxfev` | 数值 | 传给 `scipy.optimize.leastsq` 的停止/迭代参数 | 一般保持默认即可 |

一个最小配置：

```toml
method = "MLE"
do_drift_correction = false
do_accidental_correction = false
do_error_estimation = 0
get_bell_settings = false
# starting_matrix = [[0.5, "0.5j"], ["-0.5j", 0.5]]
```

代码内部用大小写不敏感的 `ConfDict` 保存配置。例如 `method` 最终对应 `t.conf["Method"]`，`do_accidental_correction` 对应 `t.conf["DoAccidentalCorrection"]`。直接修改配置时建议使用已有内部键名或 `setConfSetting()`：

```python
t.conf["DoDriftCorrection"] = 1
t.setConfSetting("method", "HMLE")
t.conf["Beta"] = 0.1
```

旧版 `importConf()`、`importData()`、`importEval()` 和 `.txt` 文件仍保留兼容路径，但会产生弃用警告；新代码请使用 `import_conf()`、`import_data()` 和 `.toml/.json`。

### 2.2 JSON 数据文件

顶层结构如下：

```json
{
  "n_qubits": 1,
  "n_detectors_per_qubit": 1,
  "n_measurements_per_qubit": 6,
  "coincidence_window": [0],
  "measurement_states": {"H": [1, 0], "V": [0, 1]},
  "data": [
    {"basis": ["H"], "integration_time": 1, "counts": [50]}
  ]
}
```

#### 顶层字段

| 字段 | 含义 |
|---|---|
| `n_qubits` | qubit 数 `n`；输出 `rho` 的大小是 `2**n × 2**n` |
| `n_detectors_per_qubit` | 每个 qubit 的探测器数，只支持 `1` 或 `2` |
| `n_measurements_per_qubit` | 每个 qubit 使用的测量态数量；主要用于元数据和旧格式兼容，实际数据条数由 `data` 决定 |
| `measurement_states` | 名称到态矢量的字典；复数可写成字符串，如 `"0.5j"`。后端会归一化，不要求输入范数为 1 |
| `coincidence_window` | 各探测器组合的符合时间窗；双探测器时长度应为 `2**n_qubits`，单位按代码计算式解释为 ns |
| `relative_efficiency` | 双探测器的相对效率向量/矩阵；用于不同探测器组合的归一化。JSON 导入时会转换成 NumPy 数组 |
| `crosstalk` | PBS/探测链路串扰矩阵。可以是整体的 `2**n × 2**n` 矩阵，也可以是每个 qubit 一个 `2×2` 矩阵的列表；后者会通过 Kronecker product 合成整体矩阵 |
| `data` | 每一条独立测量记录的列表 |

最常见的偏振 qubit 测量态是：

```text
H = (1, 0),  V = (0, 1)
D = (1, 1),  A = (1, -1)
R = (1, i),  L = (1, -i)
```

输入 `[1, 1]` 和 `[0.5, 0.5]` 表示同一个投影方向；程序会在构造测量算符时归一化。

#### `data` 中每条记录

| 字段 | 例子 | 含义 |
|---|---|---|
| `basis` | `["H"]` 或 `["H", "V"]` | 每个 qubit 本次选择的测量态名称，必须存在于 `measurement_states` |
| `counts` | `[50]` | 计数。长度/顺序取决于探测器数和 qubit 数 |
| `integration_time` | `1.0` | 本次积分时间；只有偶然符合修正启用时参与计算，缺省按 `1.0` |
| `relative_intensity` | `0.9` | 本次测量相对泵浦/光源强度；启用漂移修正时用于不同测量之间归一 |
| `detectors_used` | `[0, 3]` | 双探测器系统中本条记录实际使用的探测器索引；与 `coincidence_window`、`relative_efficiency` 联用 |

`counts` 的常见约定：

```text
1 qubit, 1 detector:  [single_or_projection_count]
2 qubits, 1 detector: [single_1, single_2, coincidence]
2 qubits, 2 detectors: [single_channels..., highest_fold_coincidence]
```

对于双探测器，多 qubit 数据最终会为每个探测器组合保留 `2**n_qubits` 个 coincidence 通道；请直接参考 `ExampleFiles/2n_detector_example.json` 的 `counts` 和 `detectors_used` 排列，不要把单探测器的三元组格式机械套用到所有实验设备。

一个两 qubit、单探测器的记录：

```json
{"basis": ["H", "V"], "integration_time": 1, "counts": [1200, 1200, 0]}
```

这里前两个数是两个 qubit 的 singles，最后一个数是该联合投影的 coincidence。若不启用偶然符合，singles 可以按项目约定省略/置零，但必须保持与对应数据解析逻辑一致。

### 2.3 校正字段如何被使用

数据导入后，`_import_data()` 会把 JSON 转换为内部数组：

```text
measurement_states -> measurement basis / pure vectors
counts             -> coincidences
integration_time   -> time
relative_intensity -> intensities
detectors_used     -> Efficiency / Window 的索引
```

`filter_data()` 随后进行：

1. 根据 `basis` 为每个 qubit 构造透射/反射两路态，并取 Kronecker product 得到联合测量基。
2. 将纯态列向量转换为投影密度算符 `M = |psi><psi|`。
3. 根据 `crosstalk` 混合不同探测通道，并归一化每个测量算符的迹。
4. 双探测器情况下用 `relative_efficiency` 形成 `overall_norms`。
5. 若启用偶然符合，按 singles、`integration_time`、`coincidence_window` 计算加性背景 `accidentals`。
6. 把 `relative_intensity` 和效率组合为优化中的测量权重。

## 3. `Tomography` 类的完整用法

### 3.1 从文件运行

```python
from pathlib import Path
from qtools.tomo.tomography import Tomography, printLastOutput

base = Path("src/qtools/tomo/tomography/ExampleFiles")
t = Tomography(nQ=1)
t.import_conf(base / "conf.toml")
t.import_data(base / "1_qubit_example.json")

rho, intensity, fval = t.run_tomography()
printLastOutput(t)       # 打印最后一次重建和性质
print(t.last_rho)        # 与 rho 对应
```

`import_data()` 负责解析和构造输入，但不会代替最后的 `run_tomography()`；因此建议始终显式调用后者。旧版 `importData()` 的行为不同，可能在导入时直接运行，不建议在新代码中混用。

### 3.2 内存中直接运行

如果数据来自实时采集程序，可以跳过文件：

```python
import numpy as np
from qtools.tomo.tomography import Tomography

t = Tomography(nQ=1)
t.conf["Method"] = "MLE"
t.conf["DoDriftCorrection"] = 0

# 每行是一个测量基；每个 qubit 用 (alpha, beta) 表示一个纯态
measurements = np.array([
    [1, 0], [0, 1], [1, 1], [1, -1], [1, 1j], [1, -1j]
], dtype=complex)
# 单 qubit / 单探测器时，StateTomography() 接受形状为 (N,) 的 counts
counts = np.array([50, 50, 50, 50, 100, 0], dtype=float)

rho, intensity, fval = t.StateTomography(
    measurements, counts, method="MLE"
)
```

`StateTomography()` 会调用 `buildTomoInput()`；它适合已经把实验设备数据转换成矩阵的场景。直接使用 JSON 是更不容易弄错字段顺序的推荐方式。

### 3.3 结果与常用分析

```python
from qtools.tomo.tomography import (
    purity, entropy, concurrence, negativity, fidelity,
    makeRhoImages,
)

print(purity(rho), entropy(rho))
if rho.shape == (4, 4):
    print(concurrence(rho), negativity(rho))
```

对两 qubit，还可以调用 `t.getBellSettings()` 搜索 CHSH 设置。可视化函数 `makeRhoImages()` 使用 Matplotlib 绘制密度矩阵的实部和虚部。

## 4. MLE 的代码实现详解

本节把数学公式和源码逐一对应。主要涉及：

```text
TomoClass.StateTomography_Matrix()
  ├─ filter_data()
  ├─ tomography_LINEAR()        没有 starting_matrix 时生成初值
  └─ tomography_MLE()
       └─ scipy.optimize.leastsq(maxlike_fitness, ...)

TomoClassHelpers.maxlike_fitness()
TomoFunctions.t_matrix(), t_to_density()
```

### 4.1 测量模型：从数据到 `M_j`

设第 `j` 条记录对应投影/POVM 元素 `M_j`，未知态为 `rho`。理想情况下该结果的期望计数近似为：

\[
\mu_j = s_j\,\operatorname{Re}\operatorname{Tr}(M_j\rho) + a_j,
\]

其中：

- `s_j` 是 `overall_norms[j]`，包含相对强度和探测器效率的影响；
- `a_j` 是偶然符合背景 `accidentals[j]`，未启用校正时为 0；
- `M_j` 是 `filter_data()` 构造并归一化后的测量密度算符。

对于每个 qubit，代码先从 `(alpha, beta)` 构造透射态和反射态，再用 `np.kron` 组成多 qubit 基。串扰矩阵会把理想通道投影按系数混合：

\[
M_k^{\rm eff}=\sum_l C_{kl}M_l.
\]

所以 MLE 并不是直接对原始字符串 `"H"`、`"R"` 优化，而是对经过校正的矩阵 `measurements_densities` 优化。

### 4.2 为什么不用直接优化 `rho`：`T` 参数化

直接优化一个复矩阵容易产生非 Hermitian 或负特征值的结果。代码用 `TomoFunctions.t_matrix()` 把长度为 `d**2` 的实向量 `t` 填成下三角复矩阵 `T`，再定义：

\[
\tilde\rho(t)=T(t)T(t)^\dagger, \qquad
\rho(t)=\frac{\tilde\rho(t)}{\operatorname{Tr}\tilde\rho(t)}.
\]

这一步保证：

1. `T T†` 自动 Hermitian；
2. `T T†` 自动半正定；
3. 除以迹后得到合法密度矩阵；
4. 未归一化的迹可以承载整体强度信息。

`density2t()` 用于把线性反演得到的初始 `rho` 转成优化所需的实参数向量。对于半正定但非正定的初始矩阵，`density2tm()` 会先调用 `make_positive()` 或给对角线加一个极小量，再做 Cholesky 分解。

### 4.3 初值：线性反演不是最终结果

`StateTomography_Matrix()` 的逻辑是：

1. 如果用户提供了 `conf["RhoStart"]` 且尺寸正确，直接使用它。
2. 否则调用 `tomography_LINEAR()`。
3. 线性反演使用广义 Pauli 基和 Stokes 参数，通过
   `B_inv = (S^T S)^(-1)` 求解系数。
4. 当前实现随后对线性结果做转置、`make_positive()` 和迹归一化。
5. 如果线性反演失败，MLE/HMLE 会退回最大混合态 `I/d`；若用户明确选择 `LINEAR`，则直接抛出错误。

这也是为什么 `method="MLE"` 仍然会执行一段线性代数：线性结果主要用来给非线性优化提供合理起点，而不是 MLE 的最终输出。

### 4.4 `tomography_MLE()` 的逐行逻辑

源码的核心可以概括为下面的伪代码（变量名与实现保持一致）：

```python
def tomography_MLE(starting_matrix, coincidences,
                   measurements, accidentals, overall_norms):
    if overall_norms is absent:
        overall_norms = ones(number_of_observations)

    # 估计 T 的尺度，使预测计数和实验计数处于同一量级
    init_intensity = mean(coincidences / overall_norms) * dimension

    # rho_start -> 下三角复 T -> 实向量 t
    starting_tvals = density2t(starting_matrix)
    starting_tvals = (starting_tvals + 1e-4) * sqrt(init_intensity)

    # 每个 observation 返回一个残差
    final_tvals = leastsq(
        maxlike_fitness,
        real(starting_tvals),
        args=(coincidences.flatten(), accidentals.flatten(),
              measurements, overall_norms),
        ftol=..., xtol=..., gtol=..., maxfev=...
    )[0]

    fval = sum(maxlike_fitness(final_tvals, ...)**2)
    rho_unnormalized = t_to_density(final_tvals, normalize=False)
    intensity = real(trace(rho_unnormalized))
    rho = rho_unnormalized / trace(rho_unnormalized)
    return rho, intensity, fval
```

有两个容易忽略的点：

- `t_to_density(..., normalize=False)` 的结果故意保留迹；这使 `T` 的整体尺度可以拟合计数强度。只有返回 `rho` 时才除以迹。
- 代码调用的是 `scipy.optimize.leastsq`，即把目标写成“残差向量”，而不是显式调用一个标量最小化器。

### 4.5 `maxlike_fitness()` 到底最小化什么

`TomoClassHelpers.maxlike_fitness()` 每次被优化器调用时执行：

```python
rho_unnormalized = t_to_density(t, normalize=False)
for j in range(len(coincidences)):
    prediction[j] = (
        overall_norms[j]
        * real(trace(measurements[j] @ rho_unnormalized))
        + accidentals[j]
    )
    prediction[j] = max(prediction[j], 0.01)

residual[j] = (prediction[j] - coincidences[j]) / sqrt(prediction[j])
return real(residual)
```

因此实际最小化的是 Pearson/Poisson 高斯近似形式的加权残差平方和：

\[
f(t)=\sum_j\frac{(\mu_j(t)-c_j)^2}{\mu_j(t)},
\quad \mu_j(t)\leftarrow\max(\mu_j(t),0.01).
\]

这里的 `0.01` 是数值保护，避免零预测导致除零；它不是实验背景计数。`fval` 是这个残差向量的平方和。

严格地说，函数名叫 MLE，但当前实现使用的是基于计数方差的 least-squares 似然近似，而不是把完整 Poisson 对数似然直接作为一个标量目标。高计数、模型正确且各计数近似独立时，这种形式通常是实用的；低计数或大量零计数时应结合仿真和不确定度检查结果。

### 4.6 校正项怎样进入 MLE

#### 漂移修正

`relative_intensity` 形成每条测量的相对强度。若这些强度不是全 1，`StateTomography_Matrix()` 会自动打开 `DoDriftCorrection` 的路径，最终把它们乘进 `overall_norms`。MLE 看到的是不同测量的不同尺度，而不是强行假设所有采集时刻光源亮度相同。

#### 偶然符合修正

在 `filter_data()` 中，双 qubit 等情况下用 singles 估计偶然符合。概念上：

\[
a_j \propto \prod_k S_{j,k}\left(\frac{\Delta t_j}{T_j}\right)^{n-1},
\]

代码中的 `window * 1e-9 / time` 把 ns 窗口换成秒尺度。得到的 `accidentals[j]` 作为预测计数的加法项，并不从原始 `counts` 物理地“删掉”一份数据。

#### 双探测器与效率

双探测器时，每个测量可能产生多个 coincidence 通道。`relative_efficiency` 和 `detectors_used` 决定对应通道的 `overall_norms`；这样 MLE 会同时利用各通道，而不是把低效率通道当成低概率态。

#### 串扰

`crosstalk` 在测量算符层面混合通道，因此它改变的是 `M_j`，不是直接修改 `rho`。如果输入的是每个 PBS 的局部 `2×2` 矩阵，导入逻辑通过 Kronecker product 得到全局矩阵。

### 4.7 HMLE、`beta` 和线性方法

- `LINEAR`：只返回线性反演结果，速度快，但可能需要正定化，统计噪声下通常不如 MLE 稳健。
- `MLE`：默认方法，使用上面的 `maxlike_fitness`。
- `HMLE`：使用 `maxlike_fitness_hedged`，在目标中加入与 `beta * log(det(rho))` 相关的 hedge，抑制有限样本下过度偏向秩亏/纯态的解。`beta <= 0` 时源码会拒绝运行 HMLE。
- `BME`：源码中有实验性/注释代码，但 `StateTomography_Matrix()` 当前不会把它作为可用方法分派，不应在配置中使用。

### 4.8 如何判断一次 MLE 是否可信

至少检查以下项目：

1. `rho` 是否 Hermitian、`trace(rho)` 是否接近 1、最小特征值是否仅为数值误差范围。
2. `fval` 是否与测量条数同量级；极大值通常表示数据和测量模型不一致，但没有一个脱离实验统计模型的固定阈值。
3. 用 `purity`、`fidelity`、`concurrence` 等物理量和已知标定态比较。
4. 改变 `starting_matrix` 或优化容差后结果是否稳定。
5. 对低计数/零计数数据增加 `do_error_estimation`，或自行进行重复采样和 bootstrap。
6. 检查测量态是否覆盖完整算符空间；`tomography_LINEAR()` 中的矩阵求逆在测量不完备或严重共线时会失败。

## 5. 代码整体结构

```text
src/qtools/tomo/tomography/
├── __init__.py              对外导出 Tomography、性质函数和显示函数
├── TomoClass.py             主类、文件导入、预处理、StateTomography、MLE/HMLE
├── TomoClassHelpers.py      maxlike_fitness、HMLE 残差等优化辅助函数
├── TomoFunctions.py         rho/T 转换、Pauli 基、熵、保真度等数学函数
├── TomoFunctionsHelpers.py  矩阵/态向量和其他底层辅助函数
├── Utilities.py             ConfDict、JSON/旧格式解析、数组转换
├── TomoDisplay.py           rho 图片、HTML、终端输出
├── TomoDisplayHelpers.py    显示格式化辅助函数
├── interface.py             qtools 面向应用/API 的 presets、数据解析和高层返回字典
├── uncertainties.py         基于重复采样的状态性质不确定度估计
├── Example.py               文件导入、Bell 态和双探测器示例
└── ExampleFiles/            JSON/TOML/旧 TXT 示例数据
```

一次 JSON 运行的主要调用关系是：

```text
import_data
  ├─ cast_to_numpy(measurement_states)
  ├─ 按 detectors_used 聚合 simultaneous measurements
  └─ buildTomoInput

run_tomography
  └─ StateTomography_Matrix
      ├─ filter_data
      │   ├─ accidentals / efficiency / crosstalk
      │   └─ measurements_densities
      ├─ tomography_LINEAR (可选初值)
      └─ tomography_MLE 或 tomography_HMLE
```

`interface.run_tomography()` 是更适合 Web/API 的包装器：它创建 `Tomography`、导入内存中的 `config/data`、运行重建，再计算 purity、entropy、fidelity、Bell 设置和不确定度，最后返回可 JSON 序列化的字典。若只在 Python 实验脚本中使用，直接调用 `Tomography` 更透明。

## 6. 面向 OAM（光轨道角动量）的扩展路线

### 6.1 先澄清“无限维”

OAM 模式通常写成 `|ell>`，`ell ∈ Z`，所以理论模式空间是无限维。计算机无法构造真正的无限大小 `rho` 并运行当前 MLE。可行做法有三类：

1. **有限截断**：选择 `ell ∈ [-L, ..., L]`，维度 `d = 2L+1`。
2. **子空间编码**：只选实验实际使用的有限个 OAM 模式，把它们重新标号为 `|0>, ..., |d-1>`。
3. **参数化/低秩模型**：不估计整个 `d×d` 矩阵，而估计少量模式权重、相干项或物理生成模型参数。

第一种最容易复用当前 MLE；第三种最接近“无限维物理”的先验模型，但需要重新设计优化目标。

### 6.2 将 qubit 抽象推广为 `d` 维 qudit

建议把当前代码中写死的以下假设抽象化：

| 当前 qubit 假设 | OAM/qudit 版本 |
|---|---|
| `d = 2**n_qubits` | 显式传入 `hilbert_dim = d` |
| 每个局部态长度 2 | 每个模式矢量长度 `d` |
| Pauli/广义 Pauli 基 | 完整的 qudit 算符基、互补基或实验 POVM |
| `2**n_qubits` 个 coincidence 通道 | 与 OAM 分析器输出端口数相应的 POVM 元素 |
| 每个 qubit 的 `2×2` 串扰 | `d×d` 模式串扰/探测响应矩阵 |
| Kronecker product 的 qubit 组合 | 多光子/多自由度张量积，或直接提供全局 POVM |

核心 MLE 其实可以保持不变：只要给定一组同维的正半定测量算符 `M_j`，预测仍是

\[
\mu_j = s_j\operatorname{Tr}(M_j\rho)+a_j,
\quad \rho = TT^\dagger/\operatorname{Tr}(TT^\dagger).
\]

需要改的是维度管理、测量生成和实验校正，而不是 MLE 的基本正定参数化。

### 6.3 OAM 的测量数据结构建议

可以把现有 JSON 扩展为显式维度和 POVM：

```json
{
  "hilbert_dim": 7,
  "basis_labels": [-3, -2, -1, 0, 1, 2, 3],
  "measurement_states": {
    "LG_superposition_0": ["... complex amplitudes ..."]
  },
  "data": [
    {
      "measurement_id": "LG_superposition_0",
      "counts": [123],
      "integration_time": 1.0
    }
  ],
  "mode_crosstalk": [["d by d matrix"]]
}
```

更通用的设计是允许每条记录直接提供 `measurement_operator`（`d×d` Hermitian 矩阵）或 `povm_id`，这样可以表示空间光调制器、模式分解器、干涉仪和相机像素形成的非投影测量。对于相机数据，还需要定义像素到模式投影的标定矩阵和计数噪声模型。

### 6.4 规模和统计问题

完整 `d` 维密度矩阵有 `d²-1` 个实自由度；`T` 参数化仍需约 `d²` 个实优化变量，内存和计算量随 `d` 快速增长。OAM 扩展应优先考虑：

- 选择足够但不过大的截断窗口，并报告截断泄漏；
- 使用模式稀疏性、低秩性或已知相位匹配结构作为正则/先验；
- 用分块、矩阵自由（matrix-free）或自动微分实现大维度梯度；
- 把探测器模式串扰、有限孔径、模式依赖效率和背景计数纳入 `M_j` 或 `a_j`；
- 在实验设计层面选择信息完备且条件数良好的 POVM，而不是事后依赖病态线性反演。

### 6.5 推荐的实现顺序

1. 先把 `Tomography` 中 `2**n_qubits` 抽象成 `hilbert_dim`，但保留现有 qubit JSON 兼容。
2. 新增 `measurement_operators` 输入，让代码直接接受归一化 POVM/投影算符。
3. 将 `filter_data()` 的 qubit 专用测量生成与通用算符路径分开。
4. 为 OAM 加入模式串扰、效率、背景和截断泄漏的标定接口。
5. 在相同 `maxlike_fitness` 框架下先做有限维 OAM MLE，再评估稀疏/低秩正则和贝叶斯方法。
6. 用仿真态、已知 OAM 叠加态和不同截断 `L` 做收敛性测试。

这样得到的是“无限维 OAM 问题的可控有限维近似”；只有在额外引入解析参数化或生成模型时，才有可能讨论不显式截断的模型拟合。

## 7. 常见问题

### `ModuleNotFoundError` 或找不到示例文件

确保从仓库根目录执行并已安装当前包，例如：

```bash
uv sync --dev
uv run python your_script.py
```

如果直接运行 `Example.py`，要么把当前目录切到 `src/qtools/tomo/tomography`，要么把示例中的相对路径改成从仓库根目录出发的路径。

### `starting_matrix` 尺寸错误

`n_qubits = n` 时必须使用 `(2**n, 2**n)` 矩阵。不要把态矢量直接填给 `starting_matrix`；纯态矢量应先通过 `np.outer(psi, psi.conj())` 变成密度矩阵。

### HMLE 报 beta 错误

配置 `method = "HMLE"` 时必须设置正的 `beta`，例如 `beta = 0.1`。否则使用普通 MLE。

### 拟合结果不物理或残差很大

优先检查 `basis` 顺序、复数字符串、counts 的列顺序、双探测器的 `detectors_used`、效率矩阵和 coincidence window；随后检查测量是否信息完备，以及是否错误地启用了偶然符合/漂移校正。

## 8. 参考资料与许可证

- 英文说明：[`README.md`](README.md)
- 开发者说明：[`README_developer.md`](README_developer.md)
- 代码示例：[`Example.py`](Example.py)
- 教程资料：[`refs/tutorial_for_tomography2019.pdf`](refs/tutorial_for_tomography2019.pdf)
- 本目录上游代码的许可证：[`LICENSE`](LICENSE)

本中文文档是对当前代码行为的技术说明；许可证文本本身不构成使用指导，也不改变上游 MIT 许可证的条款。
