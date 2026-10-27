"""Optional plotting, imported only when requested."""

import numpy as np


def plot(result, *, show=False):
    """Return a Figure showing data, 1/e² contours and full-model slices."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Ellipse

    fig = plt.figure(figsize=(10, 8), layout="constrained")
    grid = fig.add_gridspec(2, 2, height_ratios=(1, 4), width_ratios=(4, 1))
    ax = fig.add_subplot(grid[1, 0])
    top = fig.add_subplot(grid[0, 0], sharex=ax)
    right = fig.add_subplot(grid[1, 1], sharey=ax)
    annotation = fig.add_subplot(grid[0, 1])
    annotation.set_axis_off()
    height, width = result.data.shape
    scale = result.pixel_size
    extent = np.array([-0.5, width - 0.5, -0.5, height - 0.5]) * scale
    image = ax.imshow(result.data, origin="lower", extent=extent, cmap="viridis")
    fig.colorbar(image, ax=ax, label="Intensity", orientation="horizontal", shrink=0.7)
    ax.set(xlabel=f"x ({result.unit})", ylabel=f"y ({result.unit})")
    x, y = np.arange(width), np.arange(height)
    for i, beam in enumerate(result.beams):
        color = f"C{i % 10}"
        cx, cy = np.array(beam.center) * scale
        ax.plot(cx, cy, "+", color=color)
        ax.add_patch(
            Ellipse(
                (cx, cy),
                4 * beam.sigma_x * scale,
                4 * beam.sigma_y * scale,
                angle=beam.theta_deg,
                fill=False,
                edgecolor=color,
            )
        )
        ax.annotate(
            str(i + 1), (cx, cy), color=color, xytext=(5, 5), textcoords="offset points"
        )
        row = int(np.clip(round(beam.yo), 0, height - 1))
        col = int(np.clip(round(beam.xo), 0, width - 1))
        top.plot(x * scale, result.data[row], color=color, alpha=0.5)
        top.plot(
            x * scale, result.evaluate(x, row), "--", color=color, label=f"Beam {i + 1}"
        )
        right.plot(result.data[:, col], y * scale, color=color, alpha=0.5)
        right.plot(result.evaluate(col, y), y * scale, "--", color=color)
    top.set_ylabel("Intensity")
    right.set_xlabel("Intensity")
    top.tick_params(labelbottom=False)
    right.tick_params(labelleft=False)
    top.legend(fontsize="small")
    annotation.text(
        0,
        1,
        f"{len(result.beams)} beam(s)\nR² = {result.r_squared:.5f}\n"
        f"RMSE = {result.rmse:.4g}\n1/e² contours\nDashed: fitted slices",
        va="top",
        fontsize=9,
    )
    if show:
        plt.show()
    return fig
