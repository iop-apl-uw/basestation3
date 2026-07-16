"""Command-line entry point: designs and plots a WKB-stretched sampling schedule."""

import argparse
from pathlib import Path

import numpy as np

from ctd_sampling.plotting import build_buoyancy_figure, build_sampling_schedule_figure
from ctd_sampling.wkb import build_dive_stack, compute_wkb_schedule

_DEFAULT_BUCKETS_DEPTHS = (100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 1200.0)
_DEFAULT_RELATIVE_N = (0.8, 1.0, 1.5)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parses command-line arguments.

    Args:
        argv: Argument strings to parse; defaults to ``sys.argv[1:]`` if None.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory containing the p<label><NNNN>.nc profile files.",
    )
    parser.add_argument("--sg-label", type=str, default="167", help="Seaglider numeric label.")
    parser.add_argument("--latest-profile", type=int, default=97, help="Most recent dive number to include.")
    parser.add_argument("--n-dives", type=int, default=5, help="Number of most recent dives to include.")
    parser.add_argument("--dz", type=float, default=5.0, help="Depth grid spacing (m).")
    parser.add_argument("--z-max", type=float, default=1000.0, help="Maximum depth of the output grid (m).")
    parser.add_argument(
        "--top-sampling-rate",
        type=float,
        default=5.0,
        help="Fixed sampling interval (s) imposed above the first bucket depth.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory to write the output HTML figures to.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Open the generated figures in the default web browser.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Designs a WKB-stretched sampling schedule and writes the figures as HTML.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]`` if None).
    """
    args = _parse_args(argv)

    z = np.arange(0.0, args.z_max + args.dz, args.dz)
    dive_numbers = range(args.latest_profile - args.n_dives + 1, args.latest_profile + 1)

    sg = build_dive_stack(args.data_dir, args.sg_label, dive_numbers, z, args.dz)
    result = compute_wkb_schedule(
        sg,
        buckets_depths=np.array(_DEFAULT_BUCKETS_DEPTHS),
        top_sampling_rate=args.top_sampling_rate,
        relative_N=np.array(_DEFAULT_RELATIVE_N),
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    label = f"sg{args.sg_label}"
    build_buoyancy_figure(sg, result).write_html(args.output_dir / "buoyancy_frequency.html", auto_open=args.show)
    build_sampling_schedule_figure(
        result, label, (dive_numbers[0], dive_numbers[-1]), np.array(_DEFAULT_RELATIVE_N)
    ).write_html(args.output_dir / "sampling_schedule.html", auto_open=args.show)


if __name__ == "__main__":  # pragma: no cover
    main()
