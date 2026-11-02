"""Two-channel polarization-controller optimization."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def joint_optimize(
    controller: Any,
    targets: Sequence[str] = ("alice", "bob"),
    **kwargs: Any,
):
    """Optimize the Alice and Bob controller channels together.

    ``PolarizationController.optimize`` is the single optimization loop for
    both one-channel and multi-channel runs. This named entry point keeps the
    two-sided operation explicit for callers that prefer it.
    """

    return controller.optimize(target=list(targets), **kwargs)


# Keep the historical spelling as a direct alias, without another code path.
optimize_joint = joint_optimize


__all__ = ["joint_optimize", "optimize_joint"]
