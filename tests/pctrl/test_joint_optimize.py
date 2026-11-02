from unittest.mock import MagicMock

from qtools.pctrl.joint_optimize import joint_optimize, optimize_joint
from qtools.pctrl.optimize import compose_basis_loss


def test_joint_optimize_delegates_to_two_channel_controller():
    controller = MagicMock()
    controller.optimize.return_value = "result"

    result = joint_optimize(controller, maxiter=12, minimize=True)

    assert result == "result"
    controller.optimize.assert_called_once_with(
        target=["alice", "bob"], maxiter=12, minimize=True
    )


def test_joint_optimize_accepts_custom_targets():
    controller = MagicMock()

    joint_optimize(controller, targets=("left", "right"), verbose=False)

    controller.optimize.assert_called_once_with(
        target=["left", "right"], verbose=False
    )


def test_optimize_joint_is_an_alias():
    assert optimize_joint is joint_optimize


def test_basis_loss_squares_minimized_and_maximized_rates():
    loss = compose_basis_loss(
        minimization_basis=[("h", "v"), ("V", "H")],
        maximization_basis=[("D", "D")],
    )

    assert loss({("H", "V"): 2, ("V", "H"): 3, ("D", "D"): 5}) == -12.0
