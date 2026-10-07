# qtools.slm

`qtools.slm` 用于生成 SLM 相位图，并通过 Holoeye SLM 所绑定的第二屏幕
进行显示。历史版本和校准示例完整保留在 [`refs/`](refs/) 中。

核心对象关系：

```text
PhaseRegion（带区域限制的空 PhaseMask）
        ↓ 调用 lens / spiral / blaze / binary / zernike
PhaseMask（整屏弧度相位）
        ↓ to_display()
DisplayMask（设备灰度值或 RGB 传输数据）
```

## 基本用法

```python
from qtools.slm import SLM

with SLM("holoeye", monitor=None) as slm:
    phase = slm.create_canvas().lens(f=2.0)
    slm.load_phase(phase)
```

等价的显式转换方式：

```python
display = phase.to_display(bits=8, rgb=False)
slm.load(display)
```

直接向 `slm.load()` 传入 NumPy 数组时，它必须已经是与 SLM 分辨率一致的
整数 8-bit 灰度/RGB 图像；高于 8-bit 的数据应先转换为 RGB 打包的
`DisplayMask`。

`monitor=None` 默认选择副屏；没有副屏时会回退到主屏。测试和无 GUI 环境
可以使用 `headless=True`。

## 左右区域相位

`slm.create_canvas()` 返回的是整块 SLM 的根 `PhaseRegion`，不存在额外的
`Canvas` class。区域生成结果始终保持整屏尺寸，区域外相位为零。

```python
with SLM("holoeye", headless=True) as slm:
    canvas = slm.create_canvas()
    left, right = canvas.partition(axis="x", ratios=(1, 2))

    left_phase = left.spiral(order=1)
    right_phase = right.spiral(order=2)
    combined = canvas.compose(left_phase, right_phase)

    slm.load_phase(combined)
```

## 后端

- `holoeye`：Holoeye LETO、PLUTO、GAEA、LUNA 等型号，支持 LUT 和 Qt 副屏输出；
- `simulated`：使用 `slmsuite` 的模拟设备，只在实际选择该 backend 时导入依赖。

迭代算法也只在调用时加载 `slmsuite`。本次不实现 Santec backend，也不保留旧 API
兼容层。
