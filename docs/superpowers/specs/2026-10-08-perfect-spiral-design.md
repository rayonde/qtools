# 完美涡旋光相位设计

日期：2026-10-08

## 目标

在 `qtools.slm.phase` 中增加完美涡旋光的解析相位，并通过现有 fluent
`PhaseRegion` API 使用：

```python
phase = canvas.perfect_spiral(order=1, radial_frequency=0.02)
```

输出与其他解析相位函数一致：完整 SLM 尺寸、单位为弧度的 `PhaseMask`，区域外为零相位。

## 数学定义

对区域内像素坐标 `(x, y)`，以像素为单位计算：

```text
r     = sqrt((x - cx)^2 + (y - cy)^2)
theta = atan2(y - cy, x - cx)
phase = order * theta + 2*pi * radial_frequency * r
```

其中：

- `order` 是整数拓扑荷，正负号分别表示相反的方位相位方向；
- `radial_frequency` 是 cycles/pixel 的径向空间频率，正负值表示径向相位方向；
- `center=None` 时使用当前区域中心，也可以用全局像素坐标 `(cx, cy)` 显式指定中心。

该实现对应常用的“方位涡旋相位 + 轴锥径向相位”制备方式。径向频率直接以像素为单位，避免把相位生成函数绑定到某个 SLM 的物理像素间距或波长；需要物理单位时由调用方换算为 cycles/pixel。

## API 和实现边界

新增 `slm/phase/perfect_spiral.py`：

```python
def perfect_spiral(
    shape: tuple[int, int],
    bounds: tuple[int, int, int, int],
    order: int,
    radial_frequency: float,
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    ...
```

新增 `PhaseRegion.perfect_spiral(...)`，调用上述纯 NumPy 函数并包装为 `PhaseMask`。
`PhaseMask` 也提供同名便捷方法，使已有相位可以继续叠加新的完美涡旋相位。

`slm/phase/__init__.py` 导出函数。顶层 `qtools.slm` 不额外重复导出解析函数，遵循当前 `superposition` 等 phase API 的导出方式。

参数约束：

- `radial_frequency` 必须是有限实数；允许为零，此时退化为普通 `spiral` 相位；
- `order` 转为整数使用，与现有 `spiral()` 的数值语义一致；
- `center` 的坐标不限制在区域内，便于生成离轴完美涡旋；
- 输出数组 dtype 为 `float64`，区域外为零。

不新增显示编码路径、不修改现有 `spiral()`、区域切分、组合或 LUT 行为。

## 验证

新增测试覆盖：

1. 输出 shape、dtype、区域限制和有限值；
2. `radial_frequency=0` 时与现有 `spiral()` 数值一致；
3. 对若干像素验证方位项与径向项的手工公式；
4. `PhaseRegion.perfect_spiral()` 返回正确 geometry、bounds metadata；
5. 零频率、负频率、离轴中心和无效非有限频率；
6. 生成结果可通过现有 `to_display(bits=8)` 编码。
