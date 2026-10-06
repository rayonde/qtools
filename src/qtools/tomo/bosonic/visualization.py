"""Visualization tools for bosonic states and tomography reconstruction results.

Wraps QuTiP phase-space tools (qfunc, wigner, hinton) and Matplotlib to provide
clean plotting functions for Husimi Q functions, Wigner distributions, Fock populations,
and reconstruction diagnostics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import colors
import qutip as qt

from .measurements import q_function, wigner_function

if TYPE_CHECKING:
    from .tomography import BosonicTomographyResult


def plot_q_function(
    state: qt.Qobj,
    xvec: np.ndarray | None = None,
    yvec: np.ndarray | None = None,
    ax: plt.Axes | None = None,
    title: str = "Husimi Q Function",
    cmap: str = "RdBu_r",
    colorbar: bool = True,
    show_points: Sequence[complex | float] | None = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Plot the Husimi Q-function in phase space.

    Parameters
    ----------
    state : qt.Qobj
        Ket or density matrix.
    xvec : np.ndarray | None, optional
        Real quadrature grid. Defaults to linspace(-5, 5, 100).
    yvec : np.ndarray | None, optional
        Imaginary quadrature grid. Defaults to linspace(-5, 5, 100).
    ax : plt.Axes | None, optional
        Existing Matplotlib axes to draw on. If None, creates a new figure.
    title : str, optional
        Axes title.
    cmap : str, optional
        Colormap name. Default is "RdBu_r".
    colorbar : bool, optional
        Whether to append a colorbar.
    show_points : Sequence[complex | float] | None, optional
        Optional phase space coordinates (betas) to overlay as scatter markers.

    Returns
    -------
    tuple[plt.Figure, plt.Axes]
        Matplotlib Figure and Axes.
    """
    if xvec is None:
        xvec = np.linspace(-5.0, 5.0, 100)
    if yvec is None:
        yvec = np.linspace(-5.0, 5.0, 100)

    q_data = q_function(state, xvec, yvec)

    if ax is None:
        fig, ax = plt.subplots(figsize=(6, 5))
    else:
        fig = ax.figure

    max_val = max(float(np.max(q_data)), 1e-6)
    norm = colors.TwoSlopeNorm(vmin=-1e-9, vcenter=0.0, vmax=max_val)
    im = ax.pcolor(xvec, yvec, q_data, norm=norm, cmap=cmap, shading="auto")

    if show_points is not None:
        re_pts = [np.real(b) for b in show_points]
        im_pts = [np.imag(b) for b in show_points]
        ax.scatter(re_pts, im_pts, marker="x", color="black", s=40, label="Measurements (β)")
        ax.legend(loc="upper right", fontsize=9)

    ax.set_title(title, fontsize=12)
    ax.set_xlabel(r"Re($\alpha$)", fontsize=11)
    ax.set_ylabel(r"Im($\alpha$)", fontsize=11)
    ax.set_aspect("equal", adjustable="box")

    if colorbar:
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    return fig, ax


def plot_wigner(
    state: qt.Qobj,
    xvec: np.ndarray | None = None,
    yvec: np.ndarray | None = None,
    ax: plt.Axes | None = None,
    title: str = "Wigner Function",
    cmap: str = "RdBu_r",
    colorbar: bool = True,
) -> tuple[plt.Figure, plt.Axes]:
    """Plot the Wigner function with symmetric color normalization.

    Parameters
    ----------
    state : qt.Qobj
        Ket or density matrix.
    xvec : np.ndarray | None, optional
        Position grid. Defaults to linspace(-5, 5, 100).
    yvec : np.ndarray | None, optional
        Momentum grid. Defaults to linspace(-5, 5, 100).
    ax : plt.Axes | None, optional
        Target Matplotlib axes.
    title : str, optional
        Plot title.
    cmap : str, optional
        Colormap name. Default is "RdBu_r".
    colorbar : bool, optional
        Whether to add a colorbar.

    Returns
    -------
    tuple[plt.Figure, plt.Axes]
        Matplotlib Figure and Axes.
    """
    if xvec is None:
        xvec = np.linspace(-5.0, 5.0, 100)
    if yvec is None:
        yvec = np.linspace(-5.0, 5.0, 100)

    w_data = wigner_function(state, xvec, yvec)

    if ax is None:
        fig, ax = plt.subplots(figsize=(6, 5))
    else:
        fig = ax.figure

    w_lim = max(abs(float(np.min(w_data))), abs(float(np.max(w_data))), 1e-4)
    norm = colors.Normalize(vmin=-w_lim, vmax=w_lim)
    im = ax.pcolor(xvec, yvec, w_data, norm=norm, cmap=cmap, shading="auto")

    ax.set_title(title, fontsize=12)
    ax.set_xlabel(r"$x$", fontsize=11)
    ax.set_ylabel(r"$p$", fontsize=11)
    ax.set_aspect("equal", adjustable="box")

    if colorbar:
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    return fig, ax


def plot_fock_distribution(
    state: qt.Qobj,
    max_n: int = 15,
    ax: plt.Axes | None = None,
    title: str = "Photon Number Distribution",
    color: str = "#2b5c8f",
    label: str | None = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Plot photon occupancy probabilities P(n) = ⟨n|rho|n⟩.

    Parameters
    ----------
    state : qt.Qobj
        Ket or density matrix.
    max_n : int, optional
        Maximum photon number to display. Default is 15.
    ax : plt.Axes | None, optional
        Target Matplotlib axes.
    title : str, optional
        Plot title.
    color : str, optional
        Bar color.
    label : str | None, optional
        Legend label for the bar series.

    Returns
    -------
    tuple[plt.Figure, plt.Axes]
        Matplotlib Figure and Axes.
    """
    hilbert_size = state.dims[0][0]
    n_show = min(max_n, hilbert_size)
    probs = np.real(np.diag(state.full() if state.isoper else (state * state.dag()).full()))[:n_show]
    ns = np.arange(n_show)

    if ax is None:
        fig, ax = plt.subplots(figsize=(6, 4))
    else:
        fig = ax.figure

    ax.bar(ns, probs, color=color, alpha=0.8, edgecolor="black", linewidth=0.8, label=label)
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("Photon Number n", fontsize=11)
    ax.set_ylabel("Probability P(n)", fontsize=11)
    ax.set_xticks(ns[:: max(1, n_show // 10)])
    ax.set_ylim(0, max(1.05 * float(np.max(probs)), 0.1))
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    if label:
        ax.legend(fontsize=9)

    return fig, ax


def plot_hinton(
    state: qt.Qobj,
    max_n: int = 16,
    ax: plt.Axes | None = None,
    title: str = "Hinton Plot of Density Matrix",
) -> tuple[plt.Figure, plt.Axes]:
    """Render a Hinton plot of the density matrix using QuTiP's visualization helper.

    Parameters
    ----------
    state : qt.Qobj
        Ket or density matrix.
    max_n : int, optional
        Trims matrix to the first max_n elements to avoid overcrowded plots. Default: 16.
    ax : plt.Axes | None, optional
        Target Matplotlib axes.
    title : str, optional
        Plot title.

    Returns
    -------
    tuple[plt.Figure, plt.Axes]
        Matplotlib Figure and Axes.
    """
    rho = state if state.isoper else state * state.dag()
    hilbert_size = rho.dims[0][0]

    # Sub-slice if Hilbert space is larger than max_n
    if hilbert_size > max_n:
        sub_data = rho.full()[:max_n, :max_n]
        rho_to_plot = qt.Qobj(sub_data)
    else:
        rho_to_plot = rho

    if ax is None:
        fig, ax = plt.subplots(figsize=(6, 5))
    else:
        fig = ax.figure

    from qutip.visualization import hinton as qutip_hinton

    qutip_hinton(rho_to_plot, ax=ax)
    ax.set_title(title, fontsize=12)

    return fig, ax


def plot_reconstruction_summary(
    result: BosonicTomographyResult,
    target_state: qt.Qobj | None = None,
    xvec: np.ndarray | None = None,
    yvec: np.ndarray | None = None,
    max_fock_n: int = 16,
    figsize: tuple[float, float] = (14.0, 7.5),
    save_path: str | None = None,
) -> plt.Figure:
    """Generate a comprehensive multi-panel diagnostic dashboard for a reconstruction.

    Panels include:
    1. Target State Husimi Q-function (or Hinton if no target)
    2. Reconstructed State Husimi Q-function
    3. Photon Number Distribution comparison
    4. Convergence curves (Fidelity / Step Delta vs Iterations)

    Parameters
    ----------
    result : BosonicTomographyResult
        Reconstruction output from BosonicTomography.reconstruct.
    target_state : qt.Qobj | None, optional
        True reference state for comparison.
    xvec : np.ndarray | None, optional
        Phase space real quadrature grid. Default linspace(-6, 6, 80).
    yvec : np.ndarray | None, optional
        Phase space imaginary quadrature grid. Default linspace(-6, 6, 80).
    max_fock_n : int, optional
        Maximum photon number shown in Fock population plot. Default: 16.
    figsize : tuple[float, float], optional
        Figure dimensions. Default (14, 7.5).
    save_path : str | None, optional
        If specified, saves the figure to this file path.

    Returns
    -------
    plt.Figure
        Completed diagnostic Matplotlib Figure.
    """
    if xvec is None:
        xvec = np.linspace(-6.0, 6.0, 80)
    if yvec is None:
        yvec = np.linspace(-6.0, 6.0, 80)

    fig, axes = plt.subplots(2, 2, figsize=figsize)
    ax_target, ax_recon = axes[0, 0], axes[0, 1]
    ax_fock, ax_conv = axes[1, 0], axes[1, 1]

    # Panel 1: Target state or Hinton plot
    if target_state is not None:
        plot_q_function(
            target_state,
            xvec=xvec,
            yvec=yvec,
            ax=ax_target,
            title="Target State: Husimi Q Function",
            show_points=result.betas,
        )
    else:
        plot_hinton(result.rho, max_n=max_fock_n, ax=ax_target, title="Reconstructed State Hinton Plot")

    # Panel 2: Reconstructed Q-function
    plot_q_function(
        result.rho,
        xvec=xvec,
        yvec=yvec,
        ax=ax_recon,
        title=f"Reconstructed Q Function (Pur={result.purity():.3f})",
        show_points=result.betas,
    )

    # Panel 3: Fock population comparison
    n_show = min(max_fock_n, result.hilbert_size)
    ns = np.arange(n_show)
    recon_probs = result.fock_distribution(max_n=n_show)

    if target_state is not None:
        target_probs = np.real(
            np.diag(
                target_state.full()
                if target_state.isoper
                else (target_state * target_state.dag()).full()
            )
        )[:n_show]
        width = 0.38
        ax_fock.bar(
            ns - width / 2,
            target_probs,
            width=width,
            label="Target",
            color="#386cb0",
            edgecolor="black",
            alpha=0.85,
        )
        ax_fock.bar(
            ns + width / 2,
            recon_probs,
            width=width,
            label="Reconstructed",
            color="#f0027f",
            edgecolor="black",
            alpha=0.85,
        )
        ax_fock.legend(fontsize=9)
    else:
        ax_fock.bar(ns, recon_probs, color="#386cb0", edgecolor="black", alpha=0.85)

    ax_fock.set_title("Photon Number Distribution P(n)", fontsize=12)
    ax_fock.set_xlabel("Photon Number n", fontsize=11)
    ax_fock.set_ylabel("Probability", fontsize=11)
    ax_fock.set_xticks(ns)
    ax_fock.grid(axis="y", linestyle="--", alpha=0.5)

    # Panel 4: Convergence history
    iters = np.arange(1, len(result.deltas) + 1)
    color_delta = "#7570b3"
    ax_conv.semilogy(iters, result.deltas, color=color_delta, linewidth=1.8, label=r"Step Delta ||Δρ||_F")
    ax_conv.set_xlabel("Iteration", fontsize=11)
    ax_conv.set_ylabel(r"||Δρ||", color=color_delta, fontsize=11)
    ax_conv.tick_params(axis="y", labelcolor=color_delta)
    ax_conv.grid(True, linestyle="--", alpha=0.5)

    if result.fidelities is not None and len(result.fidelities) > 0:
        ax_fid = ax_conv.twinx()
        color_fid = "#1b9e77"
        ax_fid.plot(
            iters[: len(result.fidelities)],
            result.fidelities,
            color=color_fid,
            linewidth=2.0,
            linestyle="-",
            label="Fidelity",
        )
        ax_fid.set_ylabel("Fidelity", color=color_fid, fontsize=11)
        ax_fid.tick_params(axis="y", labelcolor=color_fid)
        ax_fid.set_ylim(min(0.8, min(result.fidelities)), 1.002)

        # Combined legend
        lines_1, labels_1 = ax_conv.get_legend_handles_labels()
        lines_2, labels_2 = ax_fid.get_legend_handles_labels()
        ax_conv.legend(lines_1 + lines_2, labels_1 + labels_2, loc="center right", fontsize=9)
    else:
        ax_conv.legend(loc="upper right", fontsize=9)

    final_fid_str = (
        f" | Fid: {result.final_fidelity:.5f}" if result.final_fidelity is not None else ""
    )
    ax_conv.set_title(
        f"Convergence History (Iter {result.iterations}{final_fid_str})", fontsize=12
    )

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=200, bbox_inches="tight")

    return fig
