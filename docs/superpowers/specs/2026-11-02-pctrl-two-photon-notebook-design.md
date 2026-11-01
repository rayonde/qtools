# pctrl 四组 basis 双光子计数优化 Notebook 设计

## 目标

在 `examples/` 中提供一个可从 Jupyter 逐单元执行的 `pctrl` 示例。示例控制 QWP-HWP-QWP 波片，并在 Alice/Bob 的测量基为 `HV`、`VH`、`DA`、`AD` 时读取 TDC coincidence rate，将四组计数的平均值作为目标进行 Nelder-Mead 最小化。

## 方案

- 使用公开的 `PolarizationController` API 优化指定 pctrl channel 的波片角度。
- 使用 `qtools.motor.MotorConfigManager` 从独立的 `motor_config.yaml` 读取电机端口和 backend 参数；使用 `polmeas_config.yaml` 保存 optical path 的 basis 校准角度，并自动驱动 Alice/Bob 测量基电机。
- 每次目标函数评估依次切换四组 basis，调用 `MeasManager.measure(measure_type="pairs")`，记录每组 rate 和标准差。
- Notebook 集中展示配置项（两个配置文件、TDC 通道和 coincidence window、积分时间、优化器参数），并在优化前后展示四组计数。
- 通过 `callback` 保存评估历史；末尾绘制目标值和四组 basis 计数收敛曲线，并可导出 CSV。

## 生命周期与错误边界

- pctrl、motor 和 polmeas 配置文件路径以及 TDC 参数由用户在 notebook 参数单元显式修改；电机连接参数不在 notebook 中重复硬编码。
- `PolarizationController` 与 `TaskController` 在 notebook 中显式创建，最后一个单元关闭两个控制器；异常后可重复执行清理单元。
- TDC 的 `ch_start/ch_stop/delay/window_start/window_stop/threshvolt` 必须一起与现有实验配置匹配；缺少窗口参数时由 `MeasManager` 抛出明确错误。
- 优化结果只在内存中更新；CSV 导出由用户显式执行，避免示例覆盖实验配置。

## 验证

- 检查 notebook 是合法 nbformat JSON。
- 对代码单元做 AST 编译，确保示例不含语法错误。
- 不连接硬件运行优化；硬件执行由用户在配置正确的实验目录中启动。
