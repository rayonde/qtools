# 多维 OAM Tomography 与偏振-OAM Skyrmion 设计说明

## 1. 目标

在 `qtools.tomo.oam` 子包中提供完全独立的有限维 POVM tomography 工作流，使每个子系统可有任意 Hilbert 维度；不修改现有 `qtools.tomo.tomography` 源码：

- dims=[2, 5]：偏振二维乘 OAM 五维；
- dims=[2, 4, 2]：三个子系统；
- 两个 OAM 子系统可用 dims=[5, 5]，模式标签为 l=-2,-1,0,+1,+2。

重点支持任意有限维显式 POVM MLE/HMLE、两 OAM 子系统纠缠态、偏振-OAM skyrmion 特例及拓扑荷计算。现有 qubit API、旧 JSON/TXT 数据和原 `TomoClass` 行为保持不变；OAM 新入口单独命名为 `OAMTomography`，并在 `qtools.tomo.oam` 内提供短别名 `Tomography`。

本次实现不处理真正无限维 OAM；状态必须在调用方指定的有限截断空间中建模。

## 2. 核心接口

新增通用入口：

    from qtools.tomo.oam import OAMTomography
    tomo = OAMTomography(dims=[2, 5])
    rho, intensity, fval = tomo.StateTomography_POVM(effects, counts, method="MLE")

令 D=prod(dims)。effects 形状为 (n_settings,n_outcomes,D,D)，单结果可简写为 (n_settings,D,D)；counts 形状为 (n_settings,n_outcomes)，单结果可用 (n_settings,)。

每个 effect 必须是有限、Hermitian、半正定的 D x D 矩阵。POVM 完备性由调用方保证，代码不自动补项；显式 POVM 可以表达非 qubit 局域基、模式串扰、非正交模式、标定后的有效测量以及非局域测量。

qtools.tomo.oam 提供 basis/projector 便捷构造器，将偏振和 OAM 局域投影通过 Kronecker 积变为显式 POVM；便捷层不替换 MLE 核心。

## 3. 与旧 API 的边界

现有 `StateTomography`、`buildTomoInput`、旧 JSON/TXT 导入流程继续使用原来的 `NQubits`、detector layout 和 alpha/beta 约定。OAM 入口不写入或依赖旧 `tomo_input` 列布局。

OAM 入口要求显式传入 `dims`。通用路径只使用

    p(j,k|rho) = Re(Tr(E[j,k] @ rho))

并在 `oam/tomography.py` 内部使用自己的 Cholesky-like 参数化。

第一版显式 POVM API 将探测器效率和模式串扰吸收到 E；intensities 用作每个设置的漂移归一化；accidentals 作为同形状的加性项。旧 detector/singles/window 校正只属于兼容 qubit 路径。

OAM 入口只提供显式 POVM 的 MLE/HMLE，不为任意 POVM 虚构 Pauli 反演；其优化和 beta hedge 实现在 `oam/tomography.py` 内部。

## 4. OAM 模块

新增 qtools.tomo.oam：

1. oam_labels(l_values) 提供稳定的标签到索引映射，默认 l_values=(-2,-1,0,1,2)，标签长度必须等于截断维度。
2. two_oam_entangled_state 构造
   (|l_a,l_b> + exp(i phase)|-l_a,-l_b>)/sqrt(2)，并检查模式在截断空间内。
3. polarization_oam_skyrmion 只支持 [2,d_oam]，提供实验使用的偏振-OAM 相关态。
4. skyrmion_topological_charge 只针对上述偏振-OAM 模型，把有限 OAM basis 映射到指定 LG 模式，在横截面网格上生成 Stokes/polarization texture 并做离散归一化纹理积分。函数返回拓扑荷和数值诊断；拓扑荷依赖模式、径向包络、网格与截断，不能从任意 rho 无模型地确定。

## 5. 示例与配置

第一版优先使用 Python 对象，不强行扩展旧 detector-specific JSON schema。提供 [5,5] 两 OAM 纠缠、[2,5] skyrmion、[2,4,2] smoke test 的 Python 示例。后续 JSON 可增加 dims、measurement_effects 和 counts 字段。

## 6. 测试与验收

新增测试覆盖 dims 校验、D=prod(dims)、无效 shape、MLE 输出的 Hermitian/trace/半正定性质、[2,5]/[5,5]/[2,4,2] 模拟重建、intensities/accidentals/HMLE beta、两 OAM 纠缠 fidelity、skyrmion 拓扑荷有限网格结果和旧 tomography 测试集。

验收要求：旧 qubit 示例无需改调用方式；多维显式 POVM 可完成 MLE；没有 NaN/inf/静默 shape 广播；OAM 标签和密度矩阵 basis 顺序一致。

## 7. 非目标

不实现真正无限维优化；不自动推广 concurrence/tangle 等二 qubit 专用量；不把 detector-specific accidental/crosstalk 公式强行推广到多维 OAM；不重写旧显示和数据格式。
