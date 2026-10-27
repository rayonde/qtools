# `qtools.camera` 子包与 FLIR/PySpin 兼容性设计

## 背景

仓库已经包含 `src/qtools/camera`，其中有通用 camera contract、facade、backend registry
和 FLIR/Spinnaker backend。目标是把它整理成与 `qtools.tdc`、`qtools.tec` 和 `qtools.slm`
一致的可用子包，并核对 FLIR backend 是否按官方 PySpin 生命周期正常工作。

项目本身支持 Python 3.10--3.13；真实 FLIR 相机在另一台安装了匹配 Spinnaker SDK 和
PySpin wheel 的 Windows/Linux 机器上运行。当前参考文件
`spinnaker_python-3.2.0.65-cp310-cp310-win_amd64.whl` 是 CPython 3.10、Windows x86_64
专用的原生扩展，不能安装到 Python 3.13、macOS 或 ARM 环境。

## 目标

- 保留并整理现有 `qtools.camera` 公共包和兼容导入路径。
- 在没有 PySpin 的 Python 3.13 主环境中成功导入和测试 `qtools.camera`。
- 在官方支持的 Windows/Linux + Python/ABI 组合中，通过 Spinnaker/PySpin 完成相机发现、
  按序列号选择、初始化、软件触发、图像采集、曝光、ROI、binning 和关闭。
- 修正与官方示例不一致的节点访问和触发配置细节。
- 提供清晰的 PySpin/Spinnaker 安装和版本矩阵说明，解释新版 Python 的使用边界。

## 非目标

- 不在 Python 3.13/macOS arm64 环境强行加载旧版 PySpin 原生 wheel。
- 不自动下载或重新分发 Teledyne Spinnaker SDK 或 PySpin wheel。
- 不引入独立 camera worker、RPC 协议或通用 GenICam 替代层。
- 不修改现有 SLM、TDC 和 TEC 的行为。

## 包结构

```text
qtools/camera/
├── __init__.py              # 公共导出
├── base.py                  # 跨厂商 CameraBackend contract
├── camera.py                # 高层 facade 和 backend registry
├── exceptions.py            # 依赖、发现、配置、采集错误
├── flir.py                  # 旧导入路径兼容 shim
└── backends/
    ├── __init__.py
    └── flir.py              # 延迟导入 PySpin 的 FLIR backend
```

`qtools.__getattr__` 继续延迟加载 `camera`。`qtools.camera` 的导入不访问 PySpin；只有
`Camera.info()` 或创建 `FLIR` 时才加载 SDK。公共 facade 只暴露跨厂商操作，厂商特有
控制通过 backend 和 facade 的属性转发保留。

## FLIR/PySpin 生命周期

1. `FLIR._load_pyspin()` 延迟导入 `PySpin`，缺少 SDK 时抛出带安装提示的
   `CameraDependencyError`。
2. 通过 `PySpin.System.GetInstance()` 获取进程级 singleton，调用 `GetCameras()` 枚举
   设备；默认使用第一台，传入 `serial` 时严格匹配。
3. 调用 `Init()` 后，在开始采集前配置节点。触发按官方顺序执行：
   `TriggerMode=Off`、`TriggerSelector=FrameStart`、`TriggerSource=Software`、
   `TriggerMode=On`。
4. 图像格式优先使用 Mono16/12-bit，其次 Mono16/10-bit，最后 Mono8/8-bit；对
   GenICam 节点使用正确的 `CEnumerationPtr`、`CIntegerPtr`、`CFloatPtr` 和
   `CCommandPtr` 包装，并在设置前检查可写性。
5. `BeginAcquisition()` 后每次采集执行软件触发（如启用），调用
   `GetNextImage(timeout_ms)`，检查 `IsIncomplete()`，复制 `GetNDArray()`，最后无论
   成功失败都调用 `Release()`。
6. `close()` 幂等地执行 `EndAcquisition()`、`DeInit()` 和 camera list 清理；
   `close_sdk()` 释放进程级 System singleton。

## 公共 API

```python
from qtools.camera import Camera

print(Camera.info(backend="flir", verbose=False))
with Camera(backend="flir", serial="25354617", pitch_um=3.45) as camera:
    camera.set_exposure(0.001)
    frame = camera.capture()
```

保留 `CameraBackend` 的 `discover/info/get_image/capture/get_images/close` contract；
FLIR 提供 `get_exposure/set_exposure/exposure_s`、`autoexpose/exposure_auto`、
`get_properties`、`get_woi/set_woi` 和 `get_binning/set_binning`。

## Python 版本和安装策略

原生 wheel 的文件名决定 CPython ABI、平台和架构。例如：

```text
spinnaker_python-3.2.0.65-cp310-cp310-win_amd64.whl
```

它只适用于 CPython 3.10 + Windows x86_64，并且需要系统中安装同版本的 Spinnaker SDK。
不能通过修改示例代码让该 wheel 运行在 Python 3.11--3.13、macOS 或 ARM 上。

硬件环境应使用厂商实际提供的对应 wheel，例如：

```powershell
py -3.10 -m venv .venv-camera
.venv-camera\Scripts\python -m pip install numpy
.venv-camera\Scripts\python -m pip install spinnaker_python-3.2.0.65-cp310-cp310-win_amd64.whl
.venv-camera\Scripts\python -m pip install -e path\to\qtools
```

Python 3.13 环境可运行不触碰 PySpin 的主程序、文档和 fake-SDK 测试。若 Teledyne 后续
提供当前平台和 Python 版本的 wheel，必须同时升级匹配的 Spinnaker SDK，并先运行硬件
smoke test；项目不把 PySpin 声明为普通 PyPI 依赖。

## 错误处理

- `CameraDependencyError`：PySpin/Spinnaker 不可导入或 singleton 初始化失败。
- `CameraDiscoveryError`：没有设备或序列号不存在。
- `CameraConfigurationError`：初始化、节点配置、曝光、ROI 或 binning 失败。
- `CameraAcquisitionError`：超时、图像不完整或采集失败。
- 可选 GenICam 节点缺失时跳过或报告能力错误，不让无关节点阻断基本采集。

## 测试与验收

- fake PySpin 测试覆盖无依赖导入、发现、序列号选择、触发顺序、Mono16 位移、曝光、
  ROI、binning、frame release、重复 close 和 facade 保存。
- 将 camera 测试放入默认 pytest 的发现路径，确保 CI 会执行。
- 真实硬件 smoke test 只在匹配 OS、SDK、Python wheel 和相机的机器上执行。
- 验收标准是：Python 3.13 主环境可导入；受支持硬件环境能按序列号采集有效 NumPy
  图像；退出上下文后相机停止 streaming 且资源释放。
