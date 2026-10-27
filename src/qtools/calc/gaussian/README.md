# Gaussian 光斑分析

直接使用 qtools 已有的 NumPy/SciPy，无需安装 OpenCV、lmfit 或相机 SDK。
普通图像通过 Pillow 读取，只有绘图时才导入 matplotlib。

## 数组与文件

```python
import qtools
from qtools.calc import gaussian

# frame 为相机返回的二维灰度数组；数组下标是 [y, x]。
result = gaussian.fit(frame, pixel_size=3.75, unit="um")
print(result.beam.center)  # (x, y)，单位：像素
print(result.beam.sigma)  # 主轴、次轴标准差，单位：像素
print(result.beam.waist)  # 1/e² 强度半径 = 2 sigma，单位：像素
print(result.beam.theta_deg)  # 主轴方向，单位：度
print(result.to_dict())  # 长度按 pixel_size 换算为 um，含 RMSE、R²
fig = result.plot()  # 返回 Figure，不自动弹窗
fig.savefig("beam-fit.png")
# result.plot(show=True)        # 需要交互窗口时显式开启

# 同样可以通过 qtools.calc.gaussian.fit(...) 调用。
result = gaussian.fit("beam.raw", shape=(1080, 1440), bit_depth=16)
result = gaussian.fit("beam.tif")
```

RAW 是无文件头数据，16 位按小端读取。shape 使用 (height, width)，省略时仅推断
严格满足 4:3 的尺寸，其他尺寸必须指定。NumPy 数组支持整数和浮点数据，保留
16 位动态范围，也允许已扣背景后的负数。彩色文件转为灰度；彩色数组请先转灰度。

## 多光斑与参数

```python
result = gaussian.fit(
    "double_beam.raw",
    n_beams=2,
    pixel_size=3.75,
    unit="um",
    threshold_factor=0.1,
    min_distance=30,
)
for beam in result.beams:
    print(beam.center, beam.sigma, beam.theta_deg)

# 峰值无法自动分开时，给出每个光斑的初始 (x, y) 像素坐标。
result = gaussian.fit(frame, n_beams=2, centers=[(80, 60), (120, 65)])
```

- n_beams 默认为 1，不自动猜测光斑数量。多光斑采用所有分量加共享常数背景的联合拟合。
- threshold_factor 是相对背景以上峰高的检测阈值，必须在 0 到 1 之间；
  min_distance 是检测峰间最小距离（像素），默认 max(3, 短边 // 40)。
  两项只影响自动多峰检测，不会裁掉拟合背景数据。
- fix_theta=True 固定 theta=0，sigma_x/y 对应图像 x/y 方向。
  默认可旋转，sigma_x >= sigma_y，theta 为 [-π/2, π/2) 的弧度，
  从 +x 向 +y 旋转。圆形光斑的方向不具有唯一性。
- pixel_size 默认 1，unit 默认 px；换算物理单位时同时指定二者。
  beams 和 values 始终使用像素/弧度，to_dict() 和绘图使用换算后的单位。
- max_points 默认 100000，以均匀步长减少大图拟合开销；为分辨窄光斑，实际采样
  点数可能超过目标值。result.sample_step 报告步长；max_points=None 使用全部像素。
  采样可能影响噪声数据的估计，精密分析建议全分辨率拟合。
- 单光斑、多光斑都返回 GaussianFitResult，beams 按 (x, y) 排序。
  拟合不收敛时抛出 RuntimeError；输入或峰数不合适时抛出 ValueError。
- fitted_image、residual、rmse、r_squared 在首次访问时计算，始终使用原图全分辨率。
  拟合/残差图采用只读数组；RMSE、R² 衡量残差，并非参数不确定度。

## Profile 与旧脚本

```python
from qtools.calc.gaussian import Profile

profile = Profile(frame, pixel_size=3.75, unit="um")
# 或 Profile().raw2array("beam.raw", bit_depth=8, shape=(1080, 1440))
result = profile.fitted()
result = profile.fitted_multi_beam(n_beams=1)  # 仍返回同一类型，不再返回单元素列表
print(result.values["xo"], result.best_fit.shape)
```

保留 gauss_fit.Profile / gauss_flat 导入、frame2array、raw2array、moment、
x_bar、y_bar、angle、eig、rowmaxs、colmaxs、maxrow_col 和常用拟合入口。
矩使用浮点数据扣除第 10 百分位背景后，对至少达到峰高 10% 的信号计算。
这是初值/粗略形状分析，不应替代最终拟合宽度。旧版 Otsu 二值化与 uint8 强制转换已移除。
结果现在是 GaussianFitResult，保留 values/best_fit；不提供 lmfit 的 params 或 fit_report。

```bash
python -m qtools.calc.gaussian beam.raw --shape 1080 1440 -n 2 --pixel-size 3.75 --unit um
python -m qtools.calc.gaussian beam.tif --fix-theta --save beam-fit.png
python -m qtools.calc.gaussian beam.raw --full-resolution --plot
python -m qtools.calc.gaussian.gauss_fit beam.raw -fit -xy -save
```

CLI 输出 JSON，默认拟合、默认像素单位、不自动打开窗口。旧 -fit/-xy/-save 仍可用；
无路径的 -save 写入 INPUT.fit.png。移除光斑的辅助脚本现在要求显式输入/输出路径：

```bash
python -m qtools.calc.gaussian.create_single_beam_raw double_beam.raw output.raw --beam 2 --radius 150
```

算法沿用原脚本的二维旋转 Gaussian 定义。原实现：Alessandro Cere（2014），
多光斑扩展：Yifan Li（2026）。本次将数值计算、图像读取、绘图和 CLI 分离。
