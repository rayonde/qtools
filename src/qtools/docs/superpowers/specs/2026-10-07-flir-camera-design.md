# qtools.camera FLIR 相机适配层设计

## 背景

项目需要用 Python 控制 Teledyne FLIR 相机。SLMSuite 的 FLIR backend 已经验证了
Spinnaker SDK/PySpin 的相机发现、初始化、软件触发、图像采集和资源释放流程；本功能将
这些与 FLIR 直接相关的部分移植到 `qtools.camera`，避免让 `qtools` 为了使用真实相机
而依赖完整的 `slmsuite`。

当前环境是 macOS arm64 + Python 3.13，不能假设本地已经存在一个与 Spinnaker 匹配的
PySpin 安装。因此 PySpin 必须延迟导入，真实硬件依赖在运行时检查，代码测试不能依赖
实体相机。

## 目标

- 提供 `qtools.camera` 公共包。
- 提供与现有 `slmutils.camera.flir` 用法兼容的高层 `Camera` 类。
- 提供直接对应 SLMSuite FLIR backend 的 `FLIR` 类。
- 支持相机发现、按序列号选择、初始化/关闭、软件触发、原始图像采集、曝光控制、
  ADC 位深选择、相机属性查询、ROI 和 binning。
- 在没有 Spinnaker/PySpin 或没有相机时给出明确、可操作的错误。
- 允许在没有 PySpin 的环境中导入 `qtools.camera`，以便文档、类型检查和单元测试工作。

## 非目标

- 不把完整 `slmsuite.hardware.cameras.camera.Camera` 基类及其 HDR、标定、自动对焦、
  绘图和全套分析功能复制进项目。
- 不自动下载或安装厂商 Spinnaker SDK。SDK 下载需要用户在 Teledyne 官方页面登录，
  且 Python wheel 必须和操作系统、Python 版本及 SDK 版本匹配。
- 不在当前 macOS arm64/Python 3.13 环境中假设真实 FLIR 硬件验证可用。
- 不修改现有 `qtools.slm` API。

## 方案

### 包结构

```text
camera/
├── __init__.py       # 公共导出
├── camera.py         # 面向实验脚本的高层 Camera facade
├── flir.py           # PySpin/Spinnaker FLIR backend
├── exceptions.py     # 依赖、发现、采集和关闭错误
└── tests/            # fake PySpin 驱动的单元测试
```

`qtools.camera.FLIR` 是硬件 backend；`qtools.camera.Camera` 是默认面向用户的薄封装。
两者都支持上下文管理器。高层类持有 backend，不在模块导入时访问 SDK。

### PySpin 生命周期

1. 第一次创建 `FLIR` 或调用 `FLIR.info()` 时，通过 `importlib.import_module("PySpin")`
   延迟加载 PySpin。
2. 使用 `PySpin.System.GetInstance()` 获取进程内 singleton，并通过 `GetCameras()` 枚举。
3. 默认选择第一台相机；传入 `serial` 时严格按设备序列号选择。
4. 调用 `Init()`，停止遗留 streaming 状态，配置图像格式、曝光、增益、黑电平、gamma
   和软件触发，然后 `BeginAcquisition()`。
5. 每帧先执行软件触发（软件触发模式下），调用 `GetNextImage(timeout_ms)`，复制
   `GetNDArray()`，检查完整性并 `Release()` frame。
6. `close()` 负责 `EndAcquisition()`、`DeInit()` 和 camera list 清理；
   `close_sdk()` 负责释放进程级 System singleton。

### 图像和位深

- 优先使用 `Mono16 + Bit12`，其次 `Mono16 + Bit10`，最后 `Mono8 + Bit8`。
- 对 Mono16 的左移存储值按实际 ADC bit depth 右移，返回有效范围内的 NumPy 数组。
- `capture()` 返回原始灰度数组；不在 backend 内隐式缩放到 8-bit。
- `save()` 保存 `.npy` 原始数据；`save_image()` 将有效位深压缩到 8-bit 后写入常规图像格式。

### 公共 API

```python
from qtools.camera import Camera, FLIR

ids = Camera.info()
with Camera(serial="25354617", pitch_um=(3.45, 3.45)) as camera:
    camera.set_exposure(0.001)
    frame = camera.capture()
    camera.save("image.npy", preview=True)
```

`FLIR` backend 的核心 API：

- `__init__(serial="", bitdepth=None, pitch_um=None, **kwargs)`
- `info(verbose=True)`
- `get_image(timeout_s=1.0)` / `capture(timeout_s=1.0)`
- `get_images(image_count, timeout_s=1.0)`
- `get_exposure()` / `set_exposure(exposure_s)` / `exposure_s`
- `autoexpose(fraction=0.8)`，以及兼容别名 `exposure_auto(fraction=0.8)`
- `get_properties(verbose=True)`
- `get_woi()` / `set_woi(...)`
- `get_binning()` / `set_binning(...)`
- `close()` / `close_sdk()`

高层 `Camera` 增加：

- `capture()`
- `save(filename, preview=False)`
- `save_image(filename)`
- `show()`
- `monitor()`
- `cam` 属性，用于需要访问 backend 的实验脚本

### 错误处理

- `CameraDependencyError`：PySpin 未安装或 PySpin/Spinnaker 版本不可用，并包含安装提示。
- `CameraDiscoveryError`：没有相机或序列号不匹配，并包含可用序列号。
- `CameraConfigurationError`：相机初始化、像素格式或节点配置失败。
- `CameraAcquisitionError`：超时、图像不完整或 frame 释放失败。
- 清理路径尽量幂等；初始化中途失败时立即释放已取得的资源。
- 对不同 FLIR 型号不具备的 GenICam 节点使用能力检查和警告，不让可选节点导致整个
  相机无法工作。

### 依赖和许可证

- NumPy 是运行时必需依赖。
- PySpin 不作为普通 PyPI 依赖强制安装；由用户从 Teledyne 官方 Spinnaker 下载页面
  安装匹配的完整 SDK 和 `spinnaker-python` wheel。
- matplotlib、imageio、Pillow 只作为 `show/monitor/save_image` 的可选能力使用，避免
  导入 `qtools.camera` 时强制加载图形栈。
- 移植的 SLMSuite 代码保留 MIT attribution；新增代码按本项目现有许可证和版权约定处理。

## 测试设计

使用 fake PySpin 模块模拟 SDK，不需要相机或 Spinnaker 安装，覆盖：

1. 无 PySpin 时公共包可导入，创建真实相机时报 `CameraDependencyError`。
2. `info()` 能枚举序列号和型号；按序列号选择及不存在序列号的错误。
3. 初始化顺序、软件触发、`GetNextImage`、Mono16 位移、frame `Release()`。
4. 曝光范围限制、`capture()`/`get_image()` 别名、`get_images()`。
5. `close()` 重复调用安全，初始化失败时释放资源。
6. 高层 `Camera` 的 `.npy` 保存和 8-bit preview 行为。

真实硬件验证在具备对应操作系统、Spinnaker SDK、Python wheel 和 FLIR 相机的机器上
作为手工 smoke test，不作为默认 CI 测试。

## 成功标准

- `from qtools.camera import Camera, FLIR` 在未安装 PySpin 的环境中成功。
- 连接真实 FLIR 时可通过序列号发现、初始化并采集一帧有效 NumPy 图像。
- 软件触发模式下每次采集都只触发并释放对应 frame。
- 退出上下文后相机不再 streaming，重复关闭不会抛出清理异常。
- 测试覆盖上述 fake SDK 路径，且不修改现有 SLM/TDC/TEC 行为。
