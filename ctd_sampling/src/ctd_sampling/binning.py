"""Bin-averaging of scattered data onto a regular grid.

Port of ``bindata_AS.m``.
"""

import numpy as np
from numpy.typing import NDArray


def bin_average(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    bin_centers: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Bin-averages ``y(x)`` onto bins centered at ``bin_centers``, ignoring NaNs.

    Bins are half-open on the left and closed on the right, i.e. a point
    falls in bin ``i`` when ``edge[i-1] < x <= edge[i]``, where the edges
    are the midpoints between consecutive ``bin_centers`` (extrapolated by
    half the end bin widths at the two ends).

    Args:
        x: Sample locations, any shape (flattened internally).
        y: Sample values at each ``x``, same size as ``x``. NaNs are ignored.
        bin_centers: Strictly increasing bin center locations.

    Returns:
        A tuple ``(mean, count)``:
            mean: NaN-averaged ``y`` value in each bin, NaN where the bin is
                empty. Same shape as ``bin_centers``.
            count: Number of finite ``y`` points that fell in each bin, as a
                float array (NaN where the bin is empty).

    Raises:
        ValueError: If ``bin_centers`` has fewer than 2 entries.
    """
    bin_centers = np.asarray(bin_centers, dtype=np.float64).ravel()
    n_bins = bin_centers.size
    if n_bins < 2:
        raise ValueError("bin_centers must have at least 2 entries")

    x = np.asarray(x, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()

    finite = np.isfinite(y)
    if not np.any(finite):
        nan_out = np.full(n_bins, np.nan)
        return nan_out, nan_out.copy()

    x = x[finite]
    y = y[finite]

    half_widths = np.diff(bin_centers) / 2
    edges = np.concatenate(
        (
            [bin_centers[0] - half_widths[0]],
            bin_centers[:-1] + half_widths,
            [bin_centers[-1] + half_widths[-1]],
        )
    )

    bin_idx = np.digitize(x, edges, right=True) - 1
    in_range = (bin_idx >= 0) & (bin_idx < n_bins)

    counts = np.bincount(bin_idx[in_range], minlength=n_bins).astype(np.float64)
    sums = np.bincount(bin_idx[in_range], weights=y[in_range], minlength=n_bins)

    empty = counts == 0
    with np.errstate(invalid="ignore"):
        mean = sums / counts
    mean[empty] = np.nan
    counts[empty] = np.nan

    return mean, counts
