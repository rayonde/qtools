"""Remove a selected beam from RAW data; no hardcoded paths or pixel loops."""

import argparse

import numpy as np

from qtools.calc.gaussian import find_beam_centers as _find_centers
from qtools.calc.gaussian import read_raw as _read_raw
from qtools.calc.gaussian._io import validate_image


def read_raw(raw_filename, bit_depth=8, *, shape=None):
    data = _read_raw(raw_filename, bit_depth=bit_depth, shape=shape)
    height, width = data.shape
    return data, width, height


def find_beam_centers(data, n_beams=2, **kwargs):
    """Legacy helper: return (row, column) centers and their pixel intensities."""
    coordinates = np.rint(_find_centers(data, n_beams, **kwargs)[:, ::-1]).astype(int)
    return coordinates, np.asarray(data)[tuple(coordinates.T)]


def remove_beam(data, center, radius=150):
    """Return a copy with a disk at (row, column) set to zero."""
    array = validate_image(data)
    center = np.asarray(center, dtype=float)
    if center.shape != (2,) or not np.isfinite(center).all():
        raise ValueError("center must contain finite (row, column) coordinates.")
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("radius must be finite and positive.")
    y, x = np.ogrid[: array.shape[0], : array.shape[1]]
    result = array.copy()
    result[(y - center[0]) ** 2 + (x - center[1]) ** 2 < radius**2] = 0
    return result


def save_raw(data, filename, bit_depth=8):
    if bit_depth not in (8, 16):
        raise ValueError("bit_depth must be 8 or 16.")
    array = validate_image(data)
    dtype = np.dtype("u1" if bit_depth == 8 else "<u2")
    if np.any(array < 0) or np.any(array > np.iinfo(dtype).max):
        raise ValueError("Image values are outside the selected RAW bit depth.")
    array.astype(dtype).tofile(filename)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputfile")
    parser.add_argument("outputfile")
    parser.add_argument("--shape", nargs=2, type=int, metavar=("HEIGHT", "WIDTH"))
    parser.add_argument("-b", "--bit-depth", type=int, choices=(8, 16), default=8)
    parser.add_argument("-n", "--n-beams", type=int, default=2)
    parser.add_argument(
        "--beam", type=int, default=2, help="1-based beam number, ordered by x then y."
    )
    parser.add_argument("--radius", type=float, default=150)
    args = parser.parse_args(argv)
    if not 1 <= args.beam <= args.n_beams:
        parser.error("--beam must be between 1 and --n-beams.")
    try:
        data, _, _ = read_raw(args.inputfile, args.bit_depth, shape=args.shape)
        centers, _ = find_beam_centers(data, args.n_beams)
        result = remove_beam(data, centers[args.beam - 1], args.radius)
        save_raw(result, args.outputfile, args.bit_depth)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
