# qtools.slm 全量重构设计

日期：2026-10-07

## 目标

按照新的职责边界彻底重写 `qtools.slm`，用于：

- 描述 SLM 的几何、波长和坐标系统；
- 生成整屏或指定区域内的相位图；
- 将相位图量化为 8/10/16-bit 显示数据，并支持 RGB 打包；
- 通过绑定的第二屏幕显示 Holoeye SLM 图案；
- 提供 headless/simulated 模式用于开发和测试；
- 支持多个 SLM 实例分别绑定不同显示器。

本次为破坏性重构，不保留旧的 `qtools.slm` API 兼容层。

## 约束和范围

- `slm/refs/` 下的所有文件完全保留，作为以后参考资料；本次不得移动、删除或修改这些文件。
- 本次实现 Holoeye 和 simulated backend。
- 本次不实现 Santec backend。
- simulated backend 只有在实际使用时才导入 `slmsuite`。
- 迭代算法只有在实际调用时才导入 `slmsuite`。
- Holoeye backend 当前以第二屏幕全屏输出为主要硬件接口，不假设存在 Holoeye 私有 SDK。

## 目标目录

```text
slm/
├── __init__.py
├── slm.py
├── monitor.py
├── luts.py
├── utils.py
│
├── backends/
│   ├── __init__.py
│   ├── base.py
│   ├── holoeye/
│   │   ├── __init__.py
│   │   ├── backend.py
│   │   ├── models.py
│   │   └── calibration.py
│   └── simulated/
│       ├── __init__.py
│       └── backend.py
│
├── phase/
│   ├── __init__.py
│   ├── phasemask.py
│   ├── basic.py
│   ├── spiral.py
│   ├── blaze.py
│   └── zernike.py
│
├── algorithms/
│   ├── __init__.py
│   └── iterative.py
│
├── display/
│   ├── __init__.py
│   ├── displaymask.py
│   ├── interface.py
│   ├── qt.py
│   ├── headless.py
│   ├── server.py
│   └── client.py
│
├── analysis/
└── scripts/
    └── find_position.py
```

`displaymask.py` 使用完整拼写，修正设计草图中的 `dislaymask.py` 拼写问题。

## 核心对象模型

### SLM

`slm.slm.SLM` 是唯一高层用户入口，负责组合：

- SLM 型号和设备几何；
- 波长、像素间距和坐标网格；
- backend 生命周期；
- 显示器绑定；
- phase/display 加载操作。

主要接口：

```python
SLM("holoeye", monitor=1)
SLM("simulated")

slm.create_canvas()
slm.load(display_mask)
slm.load_phase(phase_mask)
```

不再提供 `SLMDriver`、旧 `api.py` 或旧 `is_mock` 兼容入口。

### PhaseMask 和 PhaseRegion

对象模型简化为：

```text
PhaseRegion → PhaseMask
```

`PhaseRegion` 是带区域约束的空相位掩膜，不是单纯的 bounds 描述器；它直接继承 `PhaseMask`。

因此，`PhaseRegion` 本身也是一个有效的空 `PhaseMask`，可以参与相位组合，也可以在需要时作为全零相位加载。

`slm.create_canvas()` 的返回值是代表整块 SLM 的根 `PhaseRegion`，变量名 `canvas` 只是使用上的语义名称，不对应额外的 `Canvas` class。

```python
canvas = slm.create_canvas()
```

根区域的行为：

- bounds 为整块 SLM；
- 相位数组为全零；
- 未调用相位函数时，就是空相位 `PhaseMask`；
- 可以直接调用 `flat`、`lens`、`spiral` 等相位生成方法。

区域划分：

```python
left, right = canvas.partition(axis="x", ratios=(1, 2))
```

`partition()` 返回子 `PhaseRegion`。每个子区域也从零相位开始，并保存：

- 父 SLM/相位上下文；
- `(left, right, top, bottom)` bounds；
- 局部坐标中心和全局坐标偏移。

区域相位生成：

```python
left_phase = left.spiral(order=1)
right_phase = right.spiral(order=2)
```

生成结果是完整 SLM 尺寸的 `PhaseMask`：

- 区域内包含计算出的弧度相位；
- 区域外填充零；
- 不引入 `PhasePatch` 类型；
- 生成结果可以直接相加或由根 `PhaseRegion.compose()` 合并。

`PhaseMask` 的内部数组统一为 `(height, width)` 的 `float64` 弧度数组；`SLM.resolution` 统一为 `(width, height)`。

### 相位合并

```python
combined = canvas.compose(left_phase, right_phase)
```

`compose()` 在 phase 层执行：

- 检查所有 mask 属于同一个 SLM 相位上下文；
- 检查 mask 尺寸一致；
- 检查带区域 metadata 的 mask 是否重叠；
- 对不重叠区域进行组合；
- 返回一个完整的 `PhaseMask`。

相位合并完成后才进行 LUT 和灰度量化，避免在显示编码层合并造成量化误差或 LUT 语义混乱。

## 相位函数模块

基础解析相位函数拆分到独立模块：

- `basic.py`：`flat`、`lens`、`binary`；
- `spiral.py`：螺旋/涡旋相位；
- `blaze.py`：blaze grating；
- `zernike.py`：Zernike 相位。

这些模块接收明确的相位上下文和区域 bounds，使用 NumPy 计算，不在模块导入阶段加载 `slmsuite`。

`algorithms/iterative.py` 只封装需要 slmsuite 的迭代算法，并在函数调用时延迟导入依赖。

## DisplayMask 和显示输出

`display.displaymask.DisplayMask` 表示设备最终接收的显示数据，负责：

- 8/10/16-bit 灰度量化；
- Holoeye LUT 应用后的灰度值；
- 10-bit 及更高位深的 RGB 打包；
- 图像保存和基本图像变换。

目标转换 API：

```python
display = phase.to_display(bits=8, rgb=False)
slm.load(display)
```

快捷路径：

```python
slm.load_phase(phase)
```

`slm.load()` 只负责加载已经编码好的 `DisplayMask` 或显示数组；`slm.load_phase()` 负责调用相位上下文/设备校准完成转换后再加载。

显示输出通过统一 `DisplayInterface` 抽象：

- `QtDisplay`：真实第二屏幕全屏输出；
- `HeadlessDisplay`：内存 framebuffer，用于测试和无显示器环境；
- `server.py` / `client.py`：RPC 显示服务。

## Backend 和 monitor

### Backend registry

`backends/__init__.py` 维护显式 backend 模块表，只按需导入目标 backend：

```python
_BACKEND_MODULES = {
    "holoeye": "qtools.slm.backends.holoeye.backend",
    "simulated": "qtools.slm.backends.simulated.backend",
}
```

选择 backend 时才导入对应模块；导入 `qtools.slm` 不应强制加载 simulated 的 `slmsuite`。

### Holoeye

`HoloeyeBackend` 提供：

- LETO / LETO-II；
- PLUTO / PLUTO-2；
- GAEA / GAEA-2；
- LUNA；
- LUT calibration；
- 第二屏幕 Qt 全屏输出；
- headless 输出用于测试。

### Simulated

`SimulatedBackend` 在实例化或真正需要计算时延迟导入：

```python
with SLM("simulated") as slm:
    phase = slm.create_canvas().spiral(order=1)
```

若环境没有 `slmsuite`，只在使用 `simulated` 时报告明确的可选依赖错误。

### Monitor binding

`monitor.py` 负责：

- 枚举可用显示器；
- 返回显示器 index、名称、分辨率和几何信息；
- 解析显式 monitor index；
- 在 `monitor=None` 时选择第二屏幕，没有第二屏幕时回退到主屏幕；
- 为每个 `SLM` 实例创建固定的 `MonitorBinding`。

backend 不在加载每一帧时重新猜测显示器，而是只使用 SLM 初始化时解析的绑定。多个 SLM 通过不同的 `monitor` 参数绑定不同显示器。

## 测试计划

重写测试而不是保留旧测试，覆盖：

1. `PhaseRegion` 根区域、partition 比例和 bounds；
2. 局部相位生成的区域限制和局部中心；
3. 多个 `PhaseMask` 的 compose、尺寸校验和重叠检查；
4. phase 到 8/10/16-bit DisplayMask 的转换；
5. RGB 打包和 LUT round-trip；
6. Holoeye model metadata 和 headless framebuffer；
7. monitor 枚举/绑定逻辑；
8. simulated backend 的延迟依赖加载；
9. display interface 的 Qt/headless 一致行为；
10. `SLM.load()` 与 `SLM.load_phase()` 的职责边界。

## 不在本次范围

- Santec backend；
- 修改 `slm/refs/` 参考项目；
- 真实 Holoeye 私有 SDK/USB 通信；
- 将 calibration 扫描脚本全面产品化；
- 为旧 API 提供兼容别名或迁移层。
