"""Command-line Gaussian beam analysis."""

import argparse
import json
from pathlib import Path

from ._fit import fit


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fit Gaussian beams in an image or RAW file."
    )
    parser.add_argument("inputfile", type=Path)
    parser.add_argument("-n", "--n-beams", type=int, default=1)
    parser.add_argument("-b", "--bit-depth", type=int, choices=(8, 16), default=8)
    parser.add_argument("--shape", type=int, nargs=2, metavar=("HEIGHT", "WIDTH"))
    parser.add_argument("--pixel-size", type=float, default=1.0)
    parser.add_argument("--unit", default="px")
    parser.add_argument("-xy", "--fix-theta", action="store_true")
    parser.add_argument("--threshold-factor", type=float, default=0.1)
    parser.add_argument("--min-distance", type=int)
    parser.add_argument("--max-points", type=int, default=100_000)
    parser.add_argument("--full-resolution", action="store_true")
    parser.add_argument("--plot", action="store_true", help="Show the fit figure.")
    parser.add_argument(
        "-save",
        "--save",
        nargs="?",
        const=True,
        metavar="PATH",
        help="Save a figure (default: INPUT.fit.png).",
    )
    parser.add_argument("-fit", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        result = fit(
            args.inputfile,
            n_beams=args.n_beams,
            bit_depth=args.bit_depth,
            shape=args.shape,
            pixel_size=args.pixel_size,
            unit=args.unit,
            fix_theta=args.fix_theta,
            threshold_factor=args.threshold_factor,
            min_distance=args.min_distance,
            max_points=None if args.full_resolution else args.max_points,
        )
        if args.save or args.plot:
            import matplotlib.pyplot as plt

            figure = result.plot()
            if args.save:
                output = (
                    args.inputfile.with_suffix(".fit.png")
                    if args.save is True
                    else Path(args.save)
                )
                figure.savefig(output, dpi=150)
            if args.plot:
                plt.show()
            else:
                plt.close(figure)
    except (ValueError, RuntimeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0
