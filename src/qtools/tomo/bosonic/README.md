# Bosonic Quantum State Tomography (iMLE & Fock Space)

基于 **QuTiP** 底层算符的玻色场/连续变量（Continuous-Variable, CV）量子态层析封装子模块。专用于光学腔模、微波超导谐振腔与自由空间光场的 **Fock 空间光子数态生成、位移光子数计数测量仿真与迭代最大似然估计（iMLE）态重构**。

---

## 核心功能

1. **量子态构建 (`states.py`)**：
   - 光子数 Fock 态 $|n\rangle$ 与密度矩阵 $|n\rangle\langle n|$ (`fock_state`, `fock_density_matrix`)
   - 相干态 $|\alpha\rangle$ (`coherent_state`, `coherent_density_matrix`)
   - 薛定谔猫态与多头相干态叠加（Even, Odd, Yurke-Stoler, Multi-headed Cat）(`cat_state`)
   - 压缩真空态 $S(\xi)|0\rangle$ (`squeezed_vacuum_state`)
   - 热态 $\rho_{\text{th}}$ (`thermal_state`)
   - 相空间位移态 $D(\alpha)\rho D^\dagger(\alpha)$ (`displaced_state`)

2. **测量与统计模拟 (`measurements.py`)**：
   - 位移光子数投影算符构造：$M_{\beta, n} = D(-\beta)^\dagger |n\rangle\langle n| D(-\beta) = D(\beta)|n\rangle\langle n|D(-\beta)$
   - 理论测量概率生成：$P(n|\beta) = \text{Tr}[M_{\beta, n}\rho]$
   - 实际实验散粒噪声/泊松采样模拟 (`simulate_photon_counts`)
   - Husimi $Q$ 函数与 Wigner 准概率分布计算 (`q_function`, `wigner_function`)

3. **迭代最大似然重构 (`tomography.py`)**：
   - 核心类：`BosonicTomography`
   - 结果容器：`BosonicTomographyResult`
   - 算法：基于 Hradil-Řeháček (2001) 的定点算符迭代 $R(\rho) = \sum_k \frac{d_k}{\text{Tr}(M_k \rho)} M_k, \ \rho_{k+1} \propto R \rho_k R$，底层全面采用 NumPy `einsum` 向量化加速，性能比纯 Python 循环快两个数量级。
   - 支持稀释 iMLE 参数 (`dilution`)，平滑噪声干扰。
   - 跟踪步进误差 $\|\Delta\rho\|_F$、对数似然 $\ln\mathcal{L}$、目标态保真度收敛轨迹。

4. **可视化工具 (`visualization.py`)**：
   - 相空间 Husimi $Q$ 函数等高热力图 (`plot_q_function`)
   - 经典 Wigner 函数对称色阶图 (`plot_wigner`)
   - 光子数分布柱状图对比 (`plot_fock_distribution`)
   - 密度矩阵 Hinton 实虚部图 (`plot_hinton`)
   - 四联面板重构全景诊断仪表板 (`plot_reconstruction_summary`)

---

## 快速上手示例

### 示例 1：重构三头薛定谔猫态（QuTiP 教程复现）

```python
import numpy as np
import qutip as qt
from qtools.tomo.bosonic import (
    BosonicTomography,
    cat_state,
    plot_reconstruction_summary,
)

# 1. 定义截断 Fock 空间维数并创建三头猫态: α ∈ (2, -2-1j, -2+1j)
N = 25
target_state = cat_state(N, alphas=[2.0, -2.0 - 1.0j, -2.0 + 1.0j])

# 2. 初始化层析求解器（默认 5 个相空间位移测量点: [0, 2, -2, 2j, -2j]）
tomo = BosonicTomography(hilbert_size=N, betas=[0.0, 2.0, -2.0, 2.0j, -2.0j])

# 3. 生成测量数据（可加入测量散粒噪声，shots=10000）
data = tomo.simulate_data(target_state, shots=10000, seed=42)

# 4. 执行 iMLE 迭代最大似然估计
result = tomo.reconstruct(data, target_state=target_state, max_iter=60)

# 5. 查看重构结果
print(result.summary())
print(f"最终保真度: {result.final_fidelity:.5f}")

# 6. 绘制四联诊断图
fig = plot_reconstruction_summary(result, target_state=target_state)
fig.savefig("cat_state_tomo_summary.png")
```

### 示例 2：使用自定义实验数据进行态重构

```python
from qtools.tomo.bosonic import BosonicTomography

# 假设在 5 个 beta 点下测得的光子数计数矩阵 counts (shape: 5 x N)
tomo = BosonicTomography(hilbert_size=16, betas=[0.0, 1.5, -1.5, 1.5j, -1.5j])

result = tomo.reconstruct(counts, max_iter=100, tol=1e-6)

# 获取 QuTiP Qobj 密度矩阵
rho_qobj = result.rho

# 计算纯度
print("纯度:", result.purity())

# 导出为标准 NumPy 矩阵
rho_np = result.to_numpy()
```
