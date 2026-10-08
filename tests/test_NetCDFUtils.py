# -*- python-fmt -*-

## Copyright (c) 2026  University of Washington.
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

"""NetCDFUtils.interp1_extend: equivalence with the original on normal input, and partial dives."""

import warnings

import numpy as np
import pytest
import scipy.interpolate

import NetCDFUtils


def _interp1_extend_v0(t1, data, t2, fill_value=np.nan):
    """The implementation before 2026-10-07, frozen as the reference for equivalence tests."""
    if (t1[0] <= t1[-1] and t2[0] < t1[0]) or (t1[0] > t1[-1] and t2[0] > t1[0]):
        data = np.append(np.array([data[0]]), data)
        t1 = np.append(np.array([t2[0]]), t1)
    if (t1[0] <= t1[-1] and t2[-1] > t1[-1]) or (t1[0] > t1[-1]) and t2[-1] < t1[-1]:
        data = np.append(data, np.array([data[-1]]))
        t1 = np.append(t1, np.array([t2[-1]]))
    return scipy.interpolate.interp1d(t1, data, fill_value=fill_value)(t2)


def _call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except ValueError:
        return None


# --- A. identical to the original for any finite input ------------------------


def _random_case(rng: np.random.Generator):
    """Anything a caller could pass with finite t1: either direction, non-monotonic
    (e.g. a climb that turns back down at the surface), ties, single points."""
    n = int(rng.integers(1, 40))
    kind = rng.choice(["monotonic", "monotonic", "ties", "turns_back", "random"])
    t1 = np.cumsum(rng.uniform(0.0, 5.0, n))
    if kind == "ties":
        t1 = np.sort(np.round(t1 / 5.0) * 5.0)
    elif kind == "turns_back" and n > 3:
        k = int(rng.integers(1, n - 1))
        t1[k:] = t1[k] - np.cumsum(rng.uniform(0.0, 3.0, n - k))  # rises, then turns back
    elif kind == "random":
        t1 = rng.uniform(0.0, 100.0, n)
    t1 = t1 + rng.uniform(-50.0, 50.0)
    data = rng.normal(size=n)
    if rng.random() < 0.2:
        data[rng.integers(0, n)] = np.nan  # NaN data passes through
    lo, hi = t1.min(), t1.max()
    span = max(hi - lo, 1.0)
    t2 = np.linspace(
        lo + rng.choice([-0.5, -0.1, 0.0, 0.2]) * span,
        hi + rng.choice([-0.2, 0.0, 0.1, 0.5]) * span,
        int(rng.integers(1, 30)),
    )
    if rng.random() < 0.5:
        t1, data = t1[::-1].copy(), data[::-1].copy()
    if rng.random() < 0.5:
        t2 = t2[::-1].copy()
    return t1, data, t2


@pytest.mark.parametrize("fill_value", [np.nan, "extrapolate"])
def test_identical_to_original_for_finite_t1(fill_value) -> None:
    """Same result - or the same failure - as the original on every case."""
    rng = np.random.default_rng(20261007)
    for _ in range(2000):
        t1, data, t2 = _random_case(rng)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # degenerate extrapolation, both sides
            old = _call(_interp1_extend_v0, t1, data, t2, fill_value=fill_value)
            new = _call(NetCDFUtils.interp1_extend, t1, data, t2, fill_value=fill_value)
        if old is None:
            assert new is None
        else:
            np.testing.assert_array_equal(np.asarray(new), np.asarray(old))


def test_masked_arrays_with_nothing_masked_match_original_on_plain_arrays() -> None:
    """The original only ever handled plain arrays: interp1d rejects masked ones."""
    rng = np.random.default_rng(1)
    for _ in range(300):
        t1, data, t2 = _random_case(rng)
        old = _call(_interp1_extend_v0, t1, data, t2)
        masked = [np.ma.masked_array(x, mask=np.zeros(x.shape, bool)) for x in (t1, data, t2)]
        new = _call(NetCDFUtils.interp1_extend, *masked)
        if old is None:
            assert new is None
        else:
            np.testing.assert_array_equal(np.asarray(new), np.asarray(old))


# --- B. inputs the original couldn't handle ----------------------------------

# BaseNetwork bins: 5 m from 7.5 m to floor(max depth)
_BINS = np.arange(7.5, 987.0 + 0.01, 5.0)


def test_climb_with_nan_tail() -> None:
    """sg244 AMOS_Jul25 dive 890 (2026-09-20): the climb's later depths not in yet."""
    depth = np.array([988.0, 987.9, 987.5, np.nan, np.nan])
    time = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
    with pytest.raises(ValueError, match=r"x_new is below the interpolation range's minimum value \(987.5\)"):
        _interp1_extend_v0(depth, time, _BINS[::-1])
    t = NetCDFUtils.interp1_extend(depth, time, _BINS[::-1])
    assert np.all(np.isfinite(t))
    assert t[-1] == 20.0  # shallower than the data: its shallowest point's time


def test_climb_with_nan_head() -> None:
    depth = np.array([np.nan, 990.0, 500.0, 100.0, 5.0])
    time = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
    t = NetCDFUtils.interp1_extend(depth, time, _BINS[::-1])
    assert np.all(np.isfinite(t)) and np.all(np.diff(t) >= 0)


def test_no_finite_points_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="no finite points"):
        NetCDFUtils.interp1_extend(np.array([np.nan, np.nan]), np.array([1.0, 2.0]), np.array([1.0]))


def test_single_point_is_extended_as_before() -> None:
    for func in (_interp1_extend_v0, NetCDFUtils.interp1_extend):
        np.testing.assert_array_equal(func(np.array([5.0]), np.array([2.0]), np.array([3.0, 7.0])), [2.0, 2.0])


def test_nan_data_passes_through() -> None:
    t = NetCDFUtils.interp1_extend(np.array([0.0, 1.0, 2.0]), np.array([1.0, np.nan, 3.0]), np.array([0.5, 2.0]))
    assert np.isnan(t[0]) and t[1] == 3.0


def test_masked_arrays_are_accepted_and_masked_points_are_missing() -> None:
    """interp1d rejects masked arrays, so the original always raised on them."""
    t1 = np.ma.masked_array([0.0, 1.0, 2.0, 9e36], mask=[False, False, False, True])
    data = np.ma.masked_array([1.0, 2.0, 3.0, 4.0], mask=[False, True, False, False])
    t2 = np.ma.masked_array([0.5, 3.0, 2.5], mask=[False, True, False])
    with pytest.raises(ValueError, match="masked arrays are not supported"):
        _interp1_extend_v0(t1, data, t2)
    t = NetCDFUtils.interp1_extend(t1, data, t2)
    assert np.isnan(t[0])  # between 0 and the masked (NaN) value at 1
    assert np.isnan(t[1])  # masked t2
    assert t[2] == 3.0  # beyond the last unmasked t1 (the 9e36 fill is ignored)


# --- bindata: NaN x (the same partial climb) ----------------------------------

from scipy.stats import binned_statistic  # noqa: E402 - used by the frozen copy below


def _bindata_v0(x, y, bins, sigma=False):
    """
    Bins y(x) onto bins by averaging, when bins define the right hand side of the bin
    NaNs are ignored.  Values less then bin[0] LHS are included in bin[0],
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
    idx = np.logical_not(np.isnan(y))
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


@pytest.mark.parametrize("sigma", [False, True])
def test_bindata_matches_original_without_nan_x(sigma: bool) -> None:
    rng = np.random.default_rng(890)
    for _ in range(200):
        n = int(rng.integers(1, 60))
        x = rng.uniform(-10.0, 1000.0, n)
        y = rng.normal(size=n)
        y[rng.random(n) < 0.1] = np.nan
        bins = np.sort(rng.uniform(-20.0, 1050.0, int(rng.integers(2, 30))))
        for old, new in zip(_bindata_v0(x, y, bins, sigma), NetCDFUtils.bindata(x, y, bins, sigma), strict=True):
            np.testing.assert_array_equal(new, old)


def test_bindata_ignores_nan_x() -> None:
    x = np.array([1.0, 2.0, np.nan, 7.0, np.nan])
    y = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    bins = np.array([0.0, 5.0, 10.0])
    with pytest.raises(ValueError, match="NaN"):
        _bindata_v0(x, y, bins)
    avgs, counts = NetCDFUtils.bindata(x, y, bins)
    np.testing.assert_array_equal(avgs, [15.0, 40.0])
    np.testing.assert_array_equal(counts, [2, 1])
