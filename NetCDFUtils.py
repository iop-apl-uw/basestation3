#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025  University of Washington.
##
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are met:
##
## 1. Redistributions of source code must retain the above copyright notice, this
##    list of conditions and the following disclaimer.
##
## 2. Redistributions in binary form must reproduce the above copyright notice,
##    this list of conditions and the following disclaimer in the documentation
##    and/or other materials provided with the distribution.
##
## 3. Neither the name of the University of Washington nor the names of its
##    contributors may be used to endorse or promote products derived from this
##    software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE UNIVERSITY OF WASHINGTON AND CONTRIBUTORS “AS
## IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
## DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF WASHINGTON OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
## GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
## HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
## LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
## OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Utilities related to extensions processing netcdf files"""

import numpy as np
import scipy.interpolate
from scipy.stats import binned_statistic


def interp1_extend(t1, data, t2, fill_value=np.nan):
    """Interpolates t1/data onto t2, extending t1/data to cover the range of t2.

    The nearest data item at each end is copied out to the end of t2, decided
    from the first and last elements of t1 and t2. Points where t1 isn't finite
    (or is masked) are dropped first: a climb whose later depths were still NaN
    (a dive processed before its data was all in - sg244 AMOS_Jul25 dive 890)
    made the end tests compare against NaN, so nothing was extended and interp1d
    raised. For finite t1 the result is exactly as before.

    Args:
        t1: Positions of the data (e.g. depth or time). Masked points
            (netCDF4 masked arrays) are treated as missing.
        data: Values at t1; masked values become NaN.
        t2: Positions to interpolate onto; masked positions become NaN.
        fill_value: Passed to scipy.interpolate.interp1d.

    Returns:
        The values at t2.

    Raises:
        ValueError: t1 has no finite points, or interp1d can't interpolate
            (e.g. t2 outside the extended range).
    """
    # interp1d rejects masked arrays ("masked arrays are not supported"), which
    # netCDF4 variables arrive as - so masked points count as missing (NaN)
    t1 = np.ma.filled(np.ma.asarray(t1, dtype=np.float64), np.nan)
    data = np.ma.filled(np.ma.asarray(data, dtype=np.float64), np.nan)
    t2 = np.ma.filled(np.ma.asarray(t2, dtype=np.float64), np.nan)

    finite = np.isfinite(t1)
    if not finite.all():
        t1 = t1[finite]
        data = data[finite]
    if t1.size == 0:
        raise ValueError("interp1_extend: no finite points to interpolate from")

    # add 'nearest' data item to the ends of data and t1
    if (t1[0] <= t1[-1] and t2[0] < t1[0]) or (t1[0] > t1[-1] and t2[0] > t1[0]):
        # Copy the first value below the interpolation range
        data = np.append(np.array([data[0]]), data)
        t1 = np.append(np.array([t2[0]]), t1)

    if (t1[0] <= t1[-1] and t2[-1] > t1[-1]) or (t1[0] > t1[-1]) and t2[-1] < t1[-1]:
        # Copy the last value above the interpolation range
        data = np.append(data, np.array([data[-1]]))
        t1 = np.append(t1, np.array([t2[-1]]))

    return scipy.interpolate.interp1d(t1, data, fill_value=fill_value)(t2)


def bindata(x, y, bins, sigma=False):
    """
    Bins y(x) onto bins by averaging, when bins define the right hand side of the bin
    NaNs (in x or y) are ignored.  Values less then bin[0] LHS are included in bin[0],
    values greater then bin[-1] RHS are included in bin[-1]

    Input:
        x: values to be binned
        y: data upon which the averaging will be calculated
        bins: right hand side of the bins
        sigma: boolean to indicated if the standard deviation should also be calculated

    Returns:
        b: binned data (averaged)
        n: number of points in each bin
        sigma: standard deviation of the data (if so requested)

    Notes:
        Current implimentation only handles the 1-D case
    """
    # NaN x too: binned_statistic raises on it ("contains at least one NaN") -
    # e.g. a climb whose later depths aren't in yet (sg244 AMOS_Jul25 dive 890)
    idx = np.logical_not(np.logical_or(np.isnan(y), np.isnan(x)))
    if not idx.any():
        nan_return = np.empty(bins.size - 1)
        nan_return[:] = np.nan
        if sigma:
            return (nan_return, nan_return.copy(), nan_return.copy())
        else:
            return (nan_return, nan_return.copy())

    # Only consider the non-nan data
    x = x[idx]
    y = y[idx]

    # Note - this treats things to the left of the first bin edge as in "bin[0]",
    # but does not include it in the first bin statistics - that is avgs[0], which is considered
    # bin 1.  Same logic on the right.
    avgs, _, inds = binned_statistic(x, y, statistic="mean", bins=bins)

    bin_count = np.bincount(inds, minlength=bins.size)
    # Bin number zero number len(bins) are not in the stats, so remove them
    bin_count = bin_count[1 : bins.size]
    # Old code
    # bin_count = bin_count * 1.0  # Convert to float
    # bin_count[bin_count == 0] = np.nan
    # Leave bin_count as int

    if sigma:
        sigma, _, _ = binned_statistic(x, y, statistic="std", bins=bins)
        return (avgs, bin_count, sigma)
    else:
        return (avgs, bin_count)


def merge_dict(a, b, path=None, allow_override=False):
    "Merges dict b into dict a"
    if path is None:
        path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dict(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass  # same leaf value
            elif allow_override:
                a[key] = b[key]
            else:
                raise Exception("Conflict at %s" % ".".join(path + [str(key)]))
        else:
            a[key] = b[key]
    return a


def typecode_mapper(dtype):
    """Maps a nectdf4 (numpy) type into a netcdf3 typecode"""
    if dtype == np.dtype(np.float64):
        return "d"
    elif dtype == np.dtype(np.float32):
        return "f"
    elif dtype == np.dtype(np.int32):
        return "i"
    elif dtype == np.dtype("S1"):
        return "c"
    else:
        # import pdb
        # pdb.set_trace()
        raise Exception(
            f"Unknown dtype for mapping from netcdf4 to netcdf3 typecode {dtype}", "exc"
        )
