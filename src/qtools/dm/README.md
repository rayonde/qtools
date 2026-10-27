# Thorlabs DMP40 可变形镜控制

`qtools.dm` 以俯仰／偏转和 Zernike 系数为主要接口，底层使用厂商
`TLDFM_64.dll`、`TLDFMX_64.dll`。控制流程来自本包
[`Light_Control_and_Manipulation_Examples`](backends/Thorlabs/DMP40/refs/Light_Control_and_Manipulation_Examples/Python/DMP40%20DMH40%20Deformable%20Mirrors/DMP40%20using%20ctypes%20-%20Python%203.py)。
没有使用 `dmlib`，也没有自行拟合压电电压映射。

目前 Python 控制层、离线测试与案例已实现；**DLL 尚未随包提供，Windows +
DMP40 实机验证待完成**。在 Mac 上可以导入、构造对象、转换模式编号和运行
`--dry-run`，不会尝试加载 Windows DLL。

## Windows 环境与 DLL

在控制电脑上安装 Thorlabs 官方 Deformable Mirror 软件及配套 VISA、USB 驱动和
运行时，使用 64 位 Python。把同一官方版本的两个 DLL 与其许可证复制到：

```text
src/qtools/dm/backends/Thorlabs/DMP40/libs/
    TLDFM_64.dll
    TLDFMX_64.dll
    License.rtf
```

参考示例中的原安装目录是 `C:\Program Files\IVI Foundation\VISA\Win64\Bin`。
qtools 默认从包内 `libs` 加载，支持 `dll_dir=...` 覆盖；不需要 `os.chdir()`。
将 DLL 放入后重新构建的 wheel 会包含它们。只有两个 DLL 并不代表 USB 驱动和
运行时已经安装，详见 [`libs/README.md`](backends/Thorlabs/DMP40/libs/README.md)。

## 打印可调参数、范围与当前设定值

连接后直接 `print(dm.info)` 即可打印参数表，包含参数名称、当前设定值、允许范围、
单位和对应的设置方法。Jupyter 中直接查看 `dm.info` 也会显示同样的表格。

```python
from qtools.dm import DM

with DM() as dm:
    print(dm.info)  # 刚连接时当前值为 unknown，不假定设备处于零状态

    dm.set_orientation(pitch=0.05, yaw=-0.10)
    dm.set_zernikes({"defocus": 0.10, "coma_x": 0.03})
    dm.update_zernikes({"defocus": 0.15})

    print(dm.info)  # 重新取得快照，显示以上命令的当前设定值

    # 也可以逐项读取，便于编写自己的界面或扫描程序。
    for name, parameter in dm.info.parameters.items():
        print(name, parameter.minimum, parameter.maximum,
              parameter.current, parameter.unit)

    print(dm.info.parameters["defocus"].current)  # 0.15

    dm.zero_zernikes()
    dm.set_orientation(pitch=0, yaw=0)
```

若 SDK 返回 Zernike 范围 `[-1, 1]`，上述设置后的表格包含以下行（节选）：

```text
Parameter  Current  Range    Unit        Setter
pitch      0.05     [-1, 1]  normalized  set_orientation
yaw        -0.1     [-1, 1]  normalized  set_orientation
defocus    0.15     [-1, 1]  normalized  set_zernikes
coma_x     0.03     [-1, 1]  normalized  set_zernikes
```

完整表格列出设备支持的全部参数；无倾斜臂设备不列出俯仰／偏转等倾斜参数。
Zernike 范围来自连接时 SDK 的返回值，不硬编码为 `[-1, 1]`。
`azimuth_deg` 接受任意有限角度，按 360° 周期折算，当前值以 `[-180, 180]` 表示。
表格还注明 `pitch² + yaw² ≤ 1` 和组合像差的电压范围限制。

**Current 是本对象最后成功发送的设定值，不是硬件实测值。** 刚连接时未知；
成功设置完整 Zernike 命令后，未指定模式为已知的零；relax 或写入失败后，受影响
部分重新显示 `unknown`，对应 Python 值为 `None`。其他软件修改设备后，本对象
无法自动同步这些值。`snapshot = dm.info` 保留当时的快照，更新命令后需再次读取
`dm.info`。打印信息本身不会写硬件，也不会发起额外的 SDK 查询。

## 直接控制俯仰、偏转和像差

```python
from qtools.dm import DM, ZernikeMode

print(DM.discover())  # Windows：返回型号、序列号、VISA resource、可用状态

# 单台设备可以省略 serial；多台时必须明确指定 serial 或 resource。
with DM(backend="dmp40", serial="YOUR_SERIAL") as dm:
    print(dm.info)
    print(dm.capabilities)

    dm.relax()  # 显式运行厂商去迟滞流程；连接时不会自动执行

    dm.set_orientation(pitch=0.05, yaw=-0.10)
    dm.set_zernike("astigmatism_0", 0.10)

    # 一次设置多个模式；省略的模式置零，倾斜臂保持不变。
    dm.set_zernikes(
        {
            "defocus": 0.10,
            "astigmatism_0": -0.05,
            "coma_x": 0.03,
            "spherical": 0.02,
        }
    )

    # 只更新离焦，保留上一次命令中的其他模式。
    dm.update_zernikes({ZernikeMode.DEFOCUS: 0.15})

    # 有连接时可先计算、检查厂商给出的电压图，不立即写入。
    pattern = dm.calculate_zernikes({"defocus": 0.10})
    print(pattern.shape)  # (40,)

    # 明确设置结束状态。关闭连接本身不会改变输出。
    dm.zero_zernikes()
    dm.set_orientation(pitch=0, yaw=0)
```

`set_zernike()` 调用示例中的 `TLDFMX_calculate_single_zernike_pattern`，
**替换整个镜面模式**；其他 Zernike 系数变为零。
`set_zernikes()` 将完整 12 元素系数数组交给
`TLDFMX_calculate_zernike_pattern`，由 SDK 处理模式组合，不在 Python 中简单叠加
各模式的绝对电压。

`update_zernikes()` 需要本对象已有成功设置的模式记录。刚连接、执行镜面 relax
或电压写入失败后，记录未知，此时先用 `set_zernikes()` 设置完整命令。
`dm.zernikes`、`dm.tip_tilt` 是本对象最后成功发送的命令，不是测得的波前／角度，
也不会反映其他软件对同一设备的修改。

## 倾斜坐标和单位

下面三个接口等价地控制 DMP40 的独立倾斜臂：

```python
dm.set_orientation(pitch=0.3, yaw=0.4)
dm.set_tip_tilt(x=0.4, y=0.3)
dm.set_tilt(amplitude=0.5, azimuth_deg=36.86989764584402)
```

- 约定 `yaw = x`、`pitch = y`，两者是厂商坐标系中的**归一化命令**。
- 幅度 `sqrt(x*x + y*y)` 必须不大于 1；方向为 `atan2(y, x)` 的角度值。
- `azimuth_deg` 是倾斜方向在 XY 平面内的方位角，**不是镜面机械倾角**。
- 最终调用 `TLDFM_set_tilt_amplitude_angle`，倾斜臂电压由厂商驱动计算。
- 安装朝向决定这些轴与实验室坐标系的关系。若要以 mrad 等物理单位控制，需要
  实际设备／光路的标定，当前接口不假设通用的角度比例。

DMP40 的倾斜臂与镜面 Zernike 控制相互独立。无倾斜臂的 DMH40 只能使用镜面
模式；请求倾斜会抛出 `DMCapabilityError`。这部分按能力检测实现，尚未做实机验证。

## Zernike 模式、编号和幅度

幅度是 **TLDFMX device amplitude**，常见范围 `[-1, 1]`，连接后以
`TLDFMX_get_parameters` 返回范围为准。它不是单位为 rad、nm、waves 或 RMS 的
波前系数；编号转换也不改变幅度归一化。

厂商原生提供 12 个模式，即径向阶数 2、3、4。不能通过这个接口任意生成更高阶，
也不提供 piston。Noll 的 tip/tilt 模式不能直接当作独立倾斜臂命令。

| 名称／枚举值 | Thorlabs 编号 | Noll 编号 | `(n,m)` | SDK flag |
|---|---:|---:|---|---|
| `astigmatism_45` | Z4 | 5 | (2,-2) | `0x001` |
| `defocus` | Z5 | 4 | (2,0) | `0x002` |
| `astigmatism_0` | Z6 | 6 | (2,2) | `0x004` |
| `trefoil_y` | Z7 | 9 | (3,-3) | `0x008` |
| `coma_x` | Z8 | 8 | (3,1) | `0x010` |
| `coma_y` | Z9 | 7 | (3,-1) | `0x020` |
| `trefoil_x` | Z10 | 10 | (3,3) | `0x040` |
| `tetrafoil_y` | Z11 | 15 | (4,-4) | `0x080` |
| `secondary_astigmatism_y` | Z12 | 13 | (4,-2) | `0x100` |
| `spherical` | Z13 | 11 | (4,0) | `0x200` |
| `secondary_astigmatism_x` | Z14 | 12 | (4,2) | `0x400` |
| `tetrafoil_x` | Z15 | 14 | (4,4) | `0x800` |

负 `m` 代表 sine，正 `m` 代表 cosine；实际正方向仍取决于厂商与安装坐标。
参考 Python 示例的 `zernike = 4` 是 **bit flag `0x004`**，表示 0° 像散，
不是 Thorlabs Z4 或 Noll Z4。用名称／枚举避免混淆：

```python
from qtools.dm import ZernikeMode

assert ZernikeMode.from_noll(4) is ZernikeMode.DEFOCUS
assert ZernikeMode.from_thorlabs(4) is ZernikeMode.ASTIGMATISM_45
assert ZernikeMode.from_nm(2, 0) is ZernikeMode.DEFOCUS

dm.set_zernike(ZernikeMode.from_noll(4), 0.10)
```

组合模式的总电压仍可能超出硬件范围，即使每个系数都在允许区间内。后端开启
SDK pattern range check，并在下发前检查计算结果；超限会报错，不静默裁剪或缩放。
`zero_zernikes()` 设置的是 SDK 零系数参考面，**不保证实测光学平面**。

## Relax、关闭与错误

`dm.relax(part="both")` 默认按参考 MATLAB 示例间隔 10 ms 逐步应用 SDK
给出的去迟滞图案，也可选择 `"mirror"` 或 `"tilt"`。无倾斜臂设备的 `"both"`
退化为仅镜面。`max_steps` 限制循环长度，错误或超限会停止，输出停留在最后成功
应用的步骤；未自动回滚。relax 不等同于零系数，也不等同于将所有压电电压归零。

负 VISA 状态转为带函数名、状态码和厂商说明的 `DMDriverError`；正警告状态以
`DMDriverWarning` 发出。SDK 计算失败不会下发新镜面电压，实际写入失败后相应
缓存标记为未知。`with` 会关闭连接，关闭不会隐式 relax 或修改输出。

诊断时可用 `mirror_voltages, tilt_voltages = dm.read_voltages()` 读取驱动电压
设定值；这不是波前测量接口。

## Mac 离线案例与 Windows 控制案例

```bash
# Mac / Linux / Windows，纯命令预览，不加载 SDK，不模拟真实执行器响应：
python -m qtools.dm.examples.dmp40_modes --dry-run

# Windows + DLL + 已安装驱动 + DMP40：
python -m qtools.dm.examples.dmp40_modes --serial YOUR_SERIAL --relax
```

硬件案例依次展示单模式、多模式组合和保留其他模式的更新；结束时显式设置零系数
与居中的倾斜命令。可用 `--hold-s 2` 调整展示时间。

从源码开发环境运行软件测试：

```bash
python -m pytest -q tests/dm
```

测试用隔离的 fake DLL 验证 ABI 声明、调用流程和错误处理，不能替代 Windows
驱动加载、设备通信、实际波前形状和机械方向的实机检查。
