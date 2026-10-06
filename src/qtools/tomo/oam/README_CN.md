# 多维 OAM Tomography

本目录提供独立的有限维 OAM tomography 实现，不修改也不依赖旧的
`qtools.tomo.tomography.TomoClass` MLE 工作流。

```python
from qtools.tomo.oam import OAMTomography

tomo = OAMTomography(dims=[2, 5])       # 偏振 x 五维 OAM
rho, intensity, fval = tomo.StateTomography_POVM(
    effects, counts, method="MLE"
)
```

`dims` 是各子系统维度的列表，例如 `[5, 5]` 表示两个五维 OAM
子系统，`[2, 4, 2]` 表示三个子系统。总维度为 `D = prod(dims)`；显式
POVM 的完备性由调用方保证；至少需要 `D**2` 个结果，并且每个 effect 必须是
Hermitian、半正定的 `D x D` 矩阵。`MLE` 和 `HMLE` 使用本目录自己的 Cholesky 参数化，支持
`accidentals`、`intensities` 和 `rho_start`。

OAM 工具还提供：

- `two_oam_entangled_state()`：有限 OAM 截断下的双 OAM 纠缠态；
- `polarization_oam_skyrmion()`：偏振-OAM 态；
- `skyrmion_topological_charge()`：只针对 `[2, d_oam]` 偏振-OAM 态；
- `partial_transpose()` 和 `negativity()`：需要显式传入 `dims`。

完整可运行示例见仓库根目录的 `examples/oam_multidim_tomography.py`。
