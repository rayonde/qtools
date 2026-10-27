"""Run with: python -m qtools.dm.examples.dmp40_modes --dry-run.

Omit --dry-run on Windows to apply the example commands to a connected mirror.
No output changes occur merely by importing this module.
"""

from __future__ import annotations

import argparse
import time

from qtools.dm import DM, TipTilt, ZernikeMode, zernike_vector


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands only; no SDK or hardware access.",
    )
    parser.add_argument(
        "--serial",
        help="Select a mirror explicitly when multiple devices are attached.",
    )
    parser.add_argument(
        "--dll-dir", help="Override the package-local DMP40/libs directory."
    )
    parser.add_argument(
        "--relax", action="store_true", help="Run the vendor relaxation sequence first."
    )
    parser.add_argument(
        "--hold-s", type=float, default=1.0, help="Seconds to hold each example shape."
    )
    args = parser.parse_args(argv)
    if not 0 <= args.hold_s < float("inf"):
        parser.error("--hold-s must be finite and nonnegative")

    pointing = TipTilt(x=-0.10, y=0.05)  # yaw=-0.10, pitch=0.05
    coefficients = {"defocus": 0.10, "astigmatism_0": -0.05, "coma_x": 0.03}

    if args.dry_run:
        print(
            "DRY RUN: command conversion only; no DLLs, hardware, or physical voltage simulation."
        )
        print(
            f"pitch={pointing.y}, yaw={pointing.x} -> amplitude={pointing.amplitude:.6f}, "
            f"azimuth_deg={pointing.azimuth_deg:.6f}"
        )
        print("Factory mode table: name, Thorlabs index, Noll index, (n,m), SDK flag")
        for mode in ZernikeMode:
            print(
                f"{mode.value:26s} Z{mode.thorlabs_index:<2} j={mode.noll_index:<2} "
                f"{mode.nm!s:8s} 0x{mode.flag:03X}"
            )
        print("Combined coefficients in SDK array order:", zernike_vector(coefficients))
        print("Voltage patterns require the real SDK and a connected device.")
        return

    with DM(serial=args.serial, dll_dir=args.dll_dir) as dm:
        print(dm.info)
        print(dm.capabilities)
        if args.relax:
            print("Relaxation steps:", dm.relax())
        try:
            dm.set_orientation(pitch=pointing.y, yaw=pointing.x)
            # Same function/flag as the reference astigmatism-0 example, at a
            # deliberately modest amplitude rather than the reference's 0.99.
            dm.set_zernike(ZernikeMode.ASTIGMATISM_0, 0.10)
            time.sleep(args.hold_s)
            dm.set_zernikes(coefficients)
            time.sleep(args.hold_s)
            # Preserve the previous astigmatism/coma commands while changing focus.
            dm.update_zernikes({ZernikeMode.from_noll(4): 0.15})
            print(dm.info)  # Supported ranges and the latest commanded values.
            time.sleep(args.hold_s)
        finally:
            # Explicit end state. Closing alone does not reset the mirror.
            try:
                dm.zero_zernikes()
            finally:
                dm.set_orientation(pitch=0, yaw=0)


if __name__ == "__main__":
    main()
