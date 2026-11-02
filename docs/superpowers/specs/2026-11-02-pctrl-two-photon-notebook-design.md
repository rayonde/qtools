# pctrl 四组 basis 双光子计数优化 Notebook 设计

## 目标

在 `examples/` 中提供一个可从 Jupyter 逐单元执行的 `pctrl` 示例。示例控制 QWP-HWP-QWP 波片，并在 Alice/Bob 的测量基为 `HV`、`VH`、`DA`、`AD` 时读取 TDC coincidence rate，将四组计数的平均值作为目标进行 Nelder-Mead 最小化。

## 方案

- 将 basis 测量适配器放入 `qtools.pctrl.optimize.BasisMeasurement`；`joint_optimize` 只保留双侧优化的薄封装，调用统一的 `PolarizationController.optimize`。
- Notebook 使用 `qtools.motor.MotorConfigManager` 从独立的 `motor_config.yaml` 读取电机端口和 backend 参数；使用 `polmeas_config.yaml` 保存 optical path 的 basis 校准角度。
- Notebook 只创建 `BasisMeasurement`，注入 `HV`、`VH`、`DA`、`AD` 四组 key 以及平方和 loss，然后调用唯一的 `PolarizationController.optimize`。
- 优化历史和 basis 切换由 pctrl 现有实现负责；Notebook 仅展示收敛曲线。

## 生命周期与错误边界

- pctrl、motor 和 polmeas 配置文件路径以及 TDC 参数由用户在 notebook 参数单元显式修改；电机连接参数不在 notebook 中重复硬编码。
- `PolarizationController` 与 `MotorManager` 在 notebook 中显式创建，最后一个单元关闭连接；异常后可重复执行清理单元。
- TDC 的 `ch_start/ch_stop/delay/window_start/window_stop/threshvolt` 必须一起与现有实验配置匹配；缺少窗口参数时由 `MeasManager` 抛出明确错误。
- 优化结果只在内存中更新，避免示例覆盖实验配置。

## 验证

- 检查 notebook 是合法 nbformat JSON。
- 对代码单元做 AST 编译，确保示例不含语法错误。
- 不连接硬件运行优化；硬件执行由用户在配置正确的实验目录中启动。
