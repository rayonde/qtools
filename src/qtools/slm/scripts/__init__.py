"""Experiment-oriented SLM scripts."""

from importlib import import_module

__all__ = [
    "AxisScan",
    "BeamCenterResult",
    "cumulative_gaussian",
    "fit_cumulative_gaussian",
    "make_camera_measurement",
    "measure_camera_roi",
    "plot_scan",
    "roi_sum",
    "scan_beam_center",
]


def __getattr__(name: str) -> object:
    """Load script helpers lazily so ``python -m`` has no runpy warning."""

    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(".find_position", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
