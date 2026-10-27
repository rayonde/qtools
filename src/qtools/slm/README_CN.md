# qtools.slm

`qtools.slm` 用于生成 SLM 相位图，并通过 Holoeye SLM 所绑定的第二屏幕
进行显示。历史版本和校准示例完整保留在 [`refs/`](refs/) 中。

核心对象关系：

```text
PhaseRegion（带区域限制的空 PhaseMask）
        ↓ 调用 lens / spiral / blazed_grating / binary / zernike
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
屏幕编号从 1 开始，`monitor=2` 指定第二块屏幕；可以先用
`list_monitors()` 查看编号和分辨率。

`SLM` 和相位对象都提供 `info` 属性，分别查看设备/几何参数和区域/相位参数：

```python
print(slm.info)
canvas = slm.create_canvas()
print(canvas.info)
```

相位图可以直接显示。Jupyter 中会 inline 显示，普通终端会打开系统图片查看器：

```python
import numpy as np

phase = canvas.blazed_grating(
    period=16,          # 每 16 个像素重复一次
    angle=90,            # +90：相位从下到上增加
    direction=1,         # 0 -> max_phase；-1 表示反向
    max_phase=2 * np.pi,
    order=None,          # 默认每周期一个像素一个相位台阶
)
phase.show()
print(phase.info)
```

`angle` 是光栅方向角，使用角度制；`angle=-90` 表示相位从上到下增加。
`order=8` 或 `order=16` 表示每个周期量化为 8 或 16 个相位台阶。
`phase.info` 会给出像素周期、量化台阶数和按波长/像素间距预测的偏转角。

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

## 完美涡旋光相位

`perfect_spiral()` 生成常用的“轴锥径向相位 + 方位涡旋相位”，用于制备完美
涡旋光。`radial_frequency` 的单位是 cycles/pixel。

```python
with SLM("holoeye", headless=True) as slm:
    phase = slm.create_canvas().perfect_spiral(
        order=1,
        radial_frequency=0.02,
    )
    slm.load_phase(phase)
```

## 伪刀口测量与光束中心

`pseudo_knife_edge()` 在指定区域内生成固定随机相位纹理，并用 `edge` 移动
随机相位与平坦相位的边界。对每个边界位置测量一次探测器的标量信号（例如
相机 ROI 的像素和），再分别对 x、y 扫描结果拟合累计高斯曲线，即可得到光束
中心和 `1σ` 宽度。它测量的是选定光学通道的总强度，不是直接从相机图像寻找
亮斑质心。

```python
from qtools.slm import pseudo_knife_edge

phase = pseudo_knife_edge(
    shape=(1080, 1920),
    bounds=(200, 1720, 100, 980),
    axis="x",
    edge=960,
    seed=0,
)
```

完整的 SLM + 相机流程可运行：

```bash
python -m qtools.slm.scripts.find_position \
    --scan-bounds 200 1720 100 980 \
    --roi 0 640 0 480 \
    --step 10 \
    --plot beam_center_scan.png
```

脚本会依次显示 x、y 方向的相位图，通过 `qtools.camera.Camera` 采集相机
ROI 强度，最后恢复基础相位并输出中心坐标；没有相机时也可以直接调用
`scan_beam_center()`，传入自己的 `display_phase` 和 `measure` 回调进行测试
或连接功率计。

## 后端

- `holoeye`：Holoeye LETO、PLUTO、GAEA、LUNA 等型号，支持 LUT 和 Qt 副屏输出；
- `simulated`：使用 `slmsuite` 的模拟设备，只在实际选择该 backend 时导入依赖。

迭代算法也只在调用时加载 `slmsuite`。本次不实现 Santec backend，也不保留旧 API
兼容层。
