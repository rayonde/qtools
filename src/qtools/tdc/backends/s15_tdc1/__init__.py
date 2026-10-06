"""S-Fifteen TDC1 backend implementation."""

from qtools.tdc.backends.s15_tdc1.config import DEFAULT_TDC1_BACKEND

if DEFAULT_TDC1_BACKEND == "exp_s15_tdc1":
    from qtools.tdc.backends.s15_tdc1.exp_backend import ExpS15TDC1Backend

    __all__ = ["ExpS15TDC1Backend"]
elif DEFAULT_TDC1_BACKEND == "s15_tdc1":
    from qtools.tdc.backends.s15_tdc1.backend import S15TDC1Backend

    __all__ = ["S15TDC1Backend"]
else:
    raise ValueError(
        f"Unsupported DEFAULT_TDC1_BACKEND: {DEFAULT_TDC1_BACKEND!r}. "
        "Expected 's15_tdc1' or 'exp_s15_tdc1'."
    )
