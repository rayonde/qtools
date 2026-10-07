from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy.typing as npt

from slmutils.typing import Integer

if TYPE_CHECKING:
    from slmsuite.hardware.slms.simulated import SimulatedSLM

    from slmutils.generate.display import DisplayMask
    from slmutils.generate.phase import PhaseMask

EMPTY_WINDOW = (None, None, None, None)


class AbstractGenericSLM(ABC):
    @abstractmethod
    def get_device(self) -> "SimulatedSLM":
        # TODO: replace with generic slmsuite.SLM
        pass

    @abstractmethod
    def phase2display(self, phase) -> "DisplayMask":
        pass

    ###############
    #  FUNCTIONS  #
    ###############

    @abstractmethod
    def flat(self, phase) -> "PhaseMask":
        pass

    @abstractmethod
    def blaze(self, angle) -> "PhaseMask":
        pass

    @abstractmethod
    def binary(self, period) -> "PhaseMask":
        pass

    @abstractmethod
    def lens(self, f, x, y) -> "PhaseMask":
        pass

    @abstractmethod
    def spiral(self, order, x, y) -> "PhaseMask":
        pass

    @abstractmethod
    def random(self) -> "PhaseMask":
        pass


# class PhaseMaskInterface(ABC):

#     @abstractmethod
#     def to_display(self)


def resolve_bounds(
    left: Integer | None,
    right: Integer | None,
    top: Integer | None,
    bottom: Integer | None,
    array: npt.NDArray,
):
    """Assign default window."""
    left = int(left) if left is not None else 0
    right = int(right) if right is not None else array.shape[1]
    top = int(top) if top is not None else 0
    bottom = int(bottom) if bottom is not None else array.shape[0]
    return left, right, top, bottom
