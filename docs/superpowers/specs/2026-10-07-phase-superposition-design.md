# PhaseMask 复场叠加设计

日期：2026-10-07

## 目标

根据 `src/qtools/slm/phase/Laguerre-Gaussian (l=0) - 实验室笔记.pdf` 中的相位取复场辐角方法，新增 `qtools.slm.phase.superposition` 模块，支持使用已有 `PhaseMask`（特别是 `spiral()` 生成的方位相位）计算相干叠加态，并生成对应的 `DisplayMask`。

目标调用方式：

```python
spiral_1 = canvas.spiral(order=1)
spiral_2 = canvas.spiral(order=2)

phase = superposition(
    spiral_1,
    spiral_2,
    coefficients=(amplitude_0, amplitude_1 * np.exp(1j * delta)),
)
display = phase.to_display(bits=8)
```

## 数学定义

对每一个输入 `PhaseMask`，其弧度数组 `phi_k` 先转换成单位复数场：

```text
u_k = exp(1j * phi_k)
```

给定复系数 `c_k` 或与 SLM 同形状的复振幅数组 `c_k(x, y)`，叠加场和输出相位为：

```text
u(x, y) = sum_k c_k(x, y) * exp(1j * phi_k(x, y))
u_norm = u / sqrt(sum_x,y(abs(u(x, y)) ** 2))
phase(x, y) = angle(u_norm(x, y))
```

因此 `coefficients=(amplitude_0, amplitude_1 * exp(1j * delta))` 同时表达两个模式的振幅和相对相位；例如 `amplitude_0=1`、`amplitude_1=1`、`delta=π/2` 等价于 `(1, 1j)`。系数也可以是实数径向包络或复数径向包络，从而覆盖实验室笔记中的 `LG00 ± LG0l` 形式。输出仍然只保存相位，不把叠加场的振幅加载到相位型 SLM。

`amplitude_0` 和 `amplitude_1` 被视为叠加态的相对比例。归一化在生成 `PhaseMask` 之前对完整复场执行；由于最终 `PhaseMask` 只保存 `angle()`，对非零复场而言全局正实数归一化不会改变相位，但它明确了叠加态的归一化语义。若完整复场的 L2 范数为零，则抛出 `ValueError`，不生成没有物理意义的相位图。

## API 设计

新增 `slm/phase/superposition.py`：

```python
def superposition(
    *masks: PhaseMask,
    coefficients: Sequence[complex | npt.ArrayLike],
) -> PhaseMask:
    ...
```

约定：

- 至少传入一个 `PhaseMask`；
- `coefficients` 是必需的，并且数量必须与 mask 数量一致；
- 函数只接收 `PhaseMask` 实例；内部读取各实例的 `.array` 生成 NumPy 复场，最后将 `np.angle(field)` 包装回 `PhaseMask`；
- 每个系数可以是标量，或形状严格等于 `mask.shape` 的实数/复数数组；
- 所有 mask 必须引用同一个 `SLMGeometry` 对象；
- 输入 mask 的区域 metadata 不参与区域拼接，输出 `region_bounds=None`，因为相干叠加允许输入区域重叠；
- 输入系数必须为有限数；
- 使用完整复场的全局 L2 范数进行 normalization；所有输入系数同时为零或导致完整复场范数为零时抛出 `ValueError`；
- 空场位置使用 NumPy `angle(0)` 的定义，输出为 `0`，不引入 NaN；
- 输出通过现有 `PhaseMask.to_display(bits=..., rgb=...)` 生成 `DisplayMask`，不增加新的显示编码路径。

`slm/phase/__init__.py` 导出 `superposition`。本次不改变现有 `spiral()`、`PhaseMask` 算术和 `DisplayMask` 编码规则，也不强制新增 `PhaseMask.superposition()` 方法；函数式入口与用户提出的 `superposition(spiral(...), spiral(...), coefficients=...)` 保持一致。

模块同时提供 `lg_radial_amplitude(mask, waist, order, center=None)`，生成 PDF 中 p=0 LG 模式的未归一化径向因子：

```text
exp(-(r / waist) ** 2) * (sqrt(2) * r / waist) ** abs(order)
```

该数组作为 `coefficients` 的逐像素振幅传入 `superposition()`；归一化仍由复场叠加函数统一完成。

## 示例

更新 `examples/simulated_slm.ipynb`，增加独立章节：

1. 生成 `spiral(order=1)` 和 `spiral(order=2)`；
2. 计算 `coefficients=(1, 1)` 的同相叠加，以及 `coefficients=(1, np.exp(1j * np.pi / 2))` 的正交相位叠加；
3. 显示两张包裹相位图；
4. 分别调用 `.to_display(bits=8)`，显示灰度 display mask，并打印其类型、shape 和 dtype；
5. 说明复系数既可以写成相对相位，也可以替换为径向复振幅数组。

示例继续使用 simulated backend，不连接真实硬件。

## 验证

新增 SLM 单元测试覆盖：

1. 同一零相位 mask 使用 `(1, 1j)` 得到 `π/4`；
2. 负系数和复系数的相位结果与手工 NumPy 复场计算一致；
3. 空间系数数组可以表达逐像素振幅和相对相位；
4. 输出 shape、geometry、`region_bounds` 和有限值满足约定；
5. 不同 geometry、系数长度、系数 shape 和非有限系数得到明确 `ValueError`；
6. 输出可以通过现有 `to_display(bits=8)` 得到 `DisplayMask`。

验收标准是新增测试通过、notebook 从头执行无异常，并且两个叠加态和对应 display mask 均有可视化输出。
