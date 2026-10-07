# Holoyeye LETO-II

# Initialization / 初始化

## First use / 首次使用

Prepare the SLM (powered by 12Vdc, and connected to computer via USB mini-B), the `Configs_LETO-2` archive containing device configurations, and install the `HOLOEYE LETO-GAEA Configuration Manager` software on Windows.

准备 SLM（使用 12Vdc 供电，并通过 USB mini-B 连接计算机）、包含设备配置的 `Configs_LETO-2` 压缩包，并在 Windows 上安装 `HOLOEYE LETO-GAEA Configuration Manager` 软件。

1. On the software, open the SLM device port.
2. Under “File > Restore SPI Memory”, load the configuration `default-HOLOEYE-LetoII.cfg`.
3. Under “Control”, change the active configuration to `2piG`.
4. Under “File > LUT”, load the LUT `VIS_009/532nm/8-5_lin2pi_532nm_0,2-1,4V.lut` (for the manufacturer-provided LUT for 532nm, with voltages 0.2V to 1.4V), then trigger “Write CLUT”.
5. Under “Voltages”, change the corresponding VWhite1 voltage to 0.2V and VBlack1 voltage to 1.4V. Notice that the voltages are inverted as expected, see [Spatial light modulators](/doc/503d560c-54f0-40bb-883e-7527260f6df0) for an explanation.


---


1. 在软件中打开 SLM 设备端口。
2. 在 “File > Restore SPI Memory” 下，加载配置 `default-HOLOEYE-LetoII.cfg`。
3. 在 “Control” 下，将当前配置（active configuration）切换为 `2piG`。
4. 在 “File > LUT” 下，加载 LUT `VIS_009/532nm/8-5_lin2pi_532nm_0,2-1,4V.lut`（厂商提供的 532nm LUT，电压为 0.2V 至 1.4V），然后触发 “Write CLUT”。
5. 在 “Voltages” 下，将对应的 VWhite1 电压改为 0.2V、VBlack1 电压改为 1.4V。注意电压是按预期反相的，具体说明见。

## Save configuration / 保存配置

These configurations can be preserved across power cycles:

这些配置可以跨断电周期保留：

1. Commit changes on each pane, then selecting “Write All to SPI” on the main pane.在每个面板上提交（Commit）修改，然后在主面板上选择 “Write All to SPI”。
2. Set the boot configuration: select the active configuration dropdown, then hit `Ctrl-B` to switch it to the boot configuration dropdown. Change the boot configuration and “Commit to SPI”.设置启动配置：选中 active configuration 下拉框，按 `Ctrl-B` 将其切换为 boot configuration 下拉框。修改启动配置并 “Commit to SPI”。



From here onwards, the USB connection is no longer necessary. The SLM is addressed by connecting the HDMI port to a computer (which will show up as a secondary display), and projecting images on it. Ensure the resolution of the secondary display fits exactly the SLM dimensions, i.e. 1920x1080.

此后不再需要 USB 连接。SLM 通过将 HDMI 端口连接到计算机（会显示为副显示器）并在其上投射图像来寻址。请确保副显示器的分辨率与 SLM 尺寸完全一致，即 1920x1080。

# Usage / 使用

## Important notes / 注意事项

* If the SLM is observed to stop reacting to the displayed image, and cycles between images, reset it with a simple power cycle.

* 如果发现 SLM 不再对显示的图像作出响应，并在图像之间循环切换，进行一次简单的断电重启（power cycle）即可复位。

## Software / 软件

For initial testing, use the manufacturer provided pattern generator and camera viewer.

初始测试时，请使用厂商提供的图案生成器（pattern generator）和相机查看器（camera viewer）。


---

For subsequent scripting, use the [slmutils](https://git.hzqlab.cn/justin/slmutils) library with Python 3.10 on Windows:

后续脚本开发请使用 [slmutils](https://git.hzqlab.cn/justin/slmutils) 库，在 Windows 上配合 Python 3.10：

1. For connectivity to the lab’s FLIR camera, a compatible Spinnaker and `spinnaker-python` must be installed (as of June 2026, [v3.2.0.65](https://git.hzqlab.cn/justin/-/packages/pypi/spinnaker-python/3.2.0.65) for Windows). These will be automatically handled when installing the library within the lab network.  要连接实验室的 FLIR 相机，必须安装兼容的 Spinnaker 与 `spinnaker-python`（截至 2026 年 6 月，Windows 使用 [v3.2.0.65](https://git.hzqlab.cn/justin/-/packages/pypi/spinnaker-python/3.2.0.65)）。在实验室内网安装该库时会自动处理这些依赖。

2. Open a full screen window on the secondary display with the command below. This opens a TCP port for clients to interact with the window, necessary due to the way wxPython works: 
用下面的命令在副显示器上打开全屏窗口。该窗口会开放一个 TCP 端口供客户端交互，这是 wxPython 工作方式的必要要求：

```bash
python -m slmutils.display.server
```

3. Prepare the phase masks. These functionality are implemented in [slmutils.generate.phase](https://git.hzqlab.cn/justin/slmutils/src/branch/main/src/slmutils/generate/phase.py) (or you could consider using the [slmsuite](https://slmsuite.readthedocs.io/en/latest/index.html) backend which uses slightly different conventions). For example, to create a real-valued spiral phase (using phase) or a integer-valued binary grating (using display): 
准备相位掩模。这些功能在 [slmutils.generate.phase](https://git.hzqlab.cn/justin/slmutils/src/branch/main/src/slmutils/generate/phase.py) 中实现（也可以考虑使用 [slmsuite](https://slmsuite.readthedocs.io/en/latest/index.html) 后端，其约定略有不同）。例如，创建实数值的涡旋相位（使用 phase）或整数值的二元光栅（使用 display）：

```python
from slmutils.generate import HoloeyeLETO, PhaseMask

slm = HoloeyeLETO(532e-9)  # 532nm
mask = PhaseMask(slm).spiral(order=1).to_display()  # real -> 8-bit integer

mask = DisplayMask((1080, 1920)).binary(2)  # or work in gray levels directly
```

4. In your control script, import the display client to automatically connect to the windowing server, then load the phase mask through it. 在控制脚本中导入 display 客户端，它会自动连接到窗口服务端，然后通过它加载相位掩模。

```python
from slmutils.display.client import display

display.load(mask)  # display mask, or raw array
```

5. Capture images through the FLIR camera: 通过 FLIR 相机采集图像：

```python
import imageio.v3 as iio
from slmutils.camera.flir import FLIR

camera = FLIR()
camera.save("image.npy")  # raw data

image = camera.capture()  # warning: array contents are 12-bit
iio.imwrite("image.png", image >> 4)  # downsample to 8-bit
```

As always, please always read the code you use, as well as their documentation.


---

For Linux usage, some key pointers:

在 Linux 上使用时，一些关键提示：

* Supported only for Ubuntu 22.04 (v4.3.0) and 24.04 (v4.4.0) as of June 2026.
* Install the corresponding Spinnaker, and the `spinnaker-python` wheels. Also will be automatically handled during package installation.
* wxPython wheels must be manually located and installed as per [instructions](https://extras.wxpython.org/wxPython4/extras/linux). A copy for Python 3.10 compatible with Spinnaker v4.2.5 is located below, as an example:

```none
smb://files.hzqlab.cn/lab/resources/software/programs/linux/lab/ \
    wxpython-4.2.5-cp310-cp310-linux_x86_64.whl
```

* `libsdl2-2.0-0` library may also be required, to install via Ubuntu’s apt.


* 截至 2026 年 6 月，仅支持 Ubuntu 22.04（v4.3.0）和 24.04（v4.4.0）。
* 安装对应的 Spinnaker 以及 `spinnaker-python` wheel 包。安装软件包时也会自动处理这些依赖。
* wxPython 的 wheel 需按[说明](https://extras.wxpython.org/wxPython4/extras/linux)手动查找并安装。下面给出一个与 Spinnaker v4.2.5 兼容、适用于 Python 3.10 的副本作为示例：

```none
smb://files.hzqlab.cn/lab/resources/software/programs/linux/lab/ \
    wxpython-4.2.5-cp310-cp310-linux_x86_64.whl
```

* 可能还需要 `libsdl2-2.0-0` 库，可通过 Ubuntu 的 apt 安装。
