"""NaN-aware 1-D smoothing by convolution with mirror-padded edges.

Port of ``conv2P.m``, restricted to the 1-D column-vector case (the only
case exercised by the WKB sampling-schedule pipeline).
"""

import numpy as np
from numpy.typing import NDArray


def nan_smooth(x: NDArray[np.float64], kernel: NDArray[np.float64]) -> NDArray[np.float64]:
    """Smooths a 1-D array by convolution, filling NaN gaps and mirroring edges.

    Leading/trailing all-NaN runs are left untouched. Within the span
    between the first and last finite value, interior NaNs are linearly
    interpolated before convolving, edges are mirror-padded by half the
    kernel width, and the convolution result is restored to NaN wherever
    the input was originally NaN. Even-length kernels produce a result
    offset by half a sample, which is corrected back onto the original
    grid by linear interpolation (matching the original MATLAB behavior).

    Args:
        x: 1-D input array, may contain NaNs.
        kernel: 1-D convolution kernel (e.g. a boxcar ``np.ones(n) / n``).

    Returns:
        The smoothed array, same shape as ``x``.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    result = np.full_like(x, np.nan)

    finite = np.isfinite(x)
    if not np.any(finite):
        return x.copy()

    m1 = int(np.argmax(finite))
    m2 = len(x) - 1 - int(np.argmax(finite[::-1]))
    span = x[m1 : m2 + 1].copy()
    nan_mask = ~np.isfinite(span)

    finite_idx = np.flatnonzero(~nan_mask)
    if finite_idx.size < 2:
        # Nothing meaningful to interpolate/convolve through; leave as-is.
        result[m1 : m2 + 1] = span
        return result

    positions = np.arange(span.size)
    filled = np.interp(positions, finite_idx, span[finite_idx])

    kernel = np.asarray(kernel, dtype=np.float64).ravel()
    pad = kernel.size // 2
    padded = np.pad(filled, pad, mode="symmetric")
    raw = np.convolve(padded, kernel, mode="valid")

    if kernel.size % 2 == 0:
        # Even-length kernels center on half-integer offsets; resample
        # back onto the original integer grid.
        source_positions = np.arange(raw.size) - 0.5
        smoothed = np.interp(positions, source_positions, raw)
    else:
        smoothed = raw

    smoothed[nan_mask] = np.nan
    result[m1 : m2 + 1] = smoothed
    return result
