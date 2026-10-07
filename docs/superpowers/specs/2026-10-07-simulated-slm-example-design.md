# simulated SLM 相位示例设计

日期：2026-10-07

## 目标

新增 `examples/simulated_slm.ipynb`，用项目当前的统一 SLM API 展示从相位生成到 simulated backend 显示帧的完整流程：

1. 创建一个小尺寸的 `SLM("simulated")`；
2. 通过 `create_canvas()` 生成涡旋、透镜和 blaze 相位；
3. 将三个相位组合为单个完整相位图并可视化；
4. 在 simulated SLM 生命周期内通过 `load_phase()` 写入组合相位；
5. 读取 `get_current_image()` 并展示 backend 当前的 RGB 显示帧。

示例面向首次使用者，重点解释相位数组以弧度保存、显示前需要按 `2π` 包裹，以及 `load_phase()` 负责将相位量化为设备显示数据。

## 方案

notebook 使用较小的 `(512, 512)` 分辨率，以便交互式运行时快速完成计算和绘图；像素间距设为 `6.4 µm`，波长设为 `532 nm`。这些参数只用于示例，不代表特定硬件校准。

相位流程如下：

```text
SLM("simulated")
      ↓
create_canvas()
      ↓
partition(axis="x", ratios=(1, 1, 1))
      ↓
spiral / lens / blaze
      ↓
compose(...)
      ↓
phase.array ── matplotlib ── 相位图
      ↓
load_phase()
      ↓
get_current_image() ── matplotlib ── simulated RGB 帧
```

三个非重叠区域分别生成：

- 左侧：`spiral(order=1)`，演示涡旋相位；
- 中间：`lens(f=0.5)`，演示透镜相位；
- 右侧：`blaze(angle=8.0)`，演示线性 blaze 光栅。

使用 `canvas.compose()` 合并，确保每个局部相位只作用于自己的区域。相位图展示使用 `np.mod(phase.array, 2 * np.pi)` 映射到 `[0, 2π)`；组合相位本身仍保持弧度值，不在 notebook 中提前量化。

## Notebook 结构

1. Markdown 标题和学习目标。
2. 导入 `numpy`、`matplotlib.pyplot` 和 `qtools.slm.SLM`，说明模拟 backend 需要安装可选依赖 `slmsuite`。
3. 创建 `SLM("simulated", resolution=(512, 512), pitch_um=6.4, wavelength=532e-9)`，打印名称、型号和分辨率。
4. 创建 canvas、按水平方向划分三个区域，并分别生成三种相位。
5. 使用三个子图展示单独的包裹相位，保持统一的 `hsv` 色图和 `0` 到 `2π` 的色阶。
6. 使用 `canvas.compose()` 得到组合 `PhaseMask`，展示组合相位并检查数组形状、区域外组合结果和有限值。
7. 使用 `with slm:` 连接 simulated backend，调用 `slm.load_phase(combined)`，读取 `slm.get_current_image()`，并展示返回的 RGB 帧。
8. 在生命周期结束后打印说明，表明示例没有连接真实硬件。

notebook 不保存输出图片，不依赖真实显示器，也不直接调用 `slmsuite`；所有设备交互都经由 `qtools.slm.SLM` 完成。

## 错误处理与验证

- 如果环境没有 `slmsuite`，创建 simulated SLM 的单元格会得到项目已有的明确 `ImportError`；Markdown 单元格提示安装 `qtools[slm-simulated]`。
- 加载前使用 `assert combined.shape == slm.shape` 和 `assert np.isfinite(combined.array).all()`，避免把尺寸错误或非有限相位传入 backend。
- 加载后检查当前帧不为 `None`、形状为 `(height, width, 3)`、类型为 `uint8`，并以 `imshow` 展示。
- 不新增生产代码或改变 backend 行为；该示例只消费现有公开接口。

## 验收标准

- 文件位于仓库根目录的 `examples/simulated_slm.ipynb`，且 notebook JSON 有效。
- 从头执行所有代码单元时，能生成三种局部相位、组合相位，并完成 simulated backend 的加载和当前帧读取。
- 输出至少包含：三种局部相位图、组合相位图、simulated backend 当前 RGB 帧。
- notebook 使用 `load_phase()` 而不是手动构造 `DisplayMask`，并且没有真实 Holoeye/显示器依赖。
- 使用 `nbclient` 或等价方式执行检查，确保代码单元没有未捕获异常。
