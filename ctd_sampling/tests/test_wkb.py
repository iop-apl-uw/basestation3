"""Integration tests for ctd_sampling.wkb against the bundled sample dives.

No MATLAB/Octave reference is available for the full pipeline (it depends
on the legacy ``seawater`` toolbox, replaced here by ``gsw``, and on
MATLAB's low-level ``netcdf.*`` API), so these check structural and
physical invariants rather than exact regression values.
"""

from pathlib import Path

import numpy as np
import pytest

from ctd_sampling.wkb import GriddedDives, WkbResult, _flip_prefix, build_dive_stack, compute_wkb_schedule

_FIXTURES = Path(__file__).parent / "fixtures"
_DIVE_NUMBERS = (93, 94, 95, 96, 97)
_BUCKETS_DEPTHS = np.array([100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 1200.0])
_RELATIVE_N = np.array([0.8, 1.0, 1.5])
_DZ = 5.0


@pytest.fixture(scope="module")
def gridded_dives() -> GriddedDives:
    """Grids the bundled sample dives onto the default depth grid."""
    z = np.arange(0.0, 1000.0 + _DZ, _DZ)
    return build_dive_stack(_FIXTURES, "167", _DIVE_NUMBERS, z, _DZ)


@pytest.fixture(scope="module")
def wkb_result(gridded_dives: GriddedDives) -> WkbResult:
    """Computes the WKB-stretched schedule for the bundled sample dives."""
    return compute_wkb_schedule(
        gridded_dives, buckets_depths=_BUCKETS_DEPTHS, top_sampling_rate=5.0, relative_N=_RELATIVE_N
    )


def test_build_dive_stack_shapes(gridded_dives: GriddedDives) -> None:
    """Every gridded field should have shape (len(z), n_casts), with positive per-cast point counts."""
    n_casts = 2 * len(_DIVE_NUMBERS)
    assert gridded_dives.z.shape == (201,)
    for field in (
        gridded_dives.lon,
        gridded_dives.lat,
        gridded_dives.time,
        gridded_dives.sigma_theta,
        gridded_dives.temperature,
        gridded_dives.salinity,
        gridded_dives.vertical_speed,
        gridded_dives.dt_sampling,
        gridded_dives.sample_index,
        gridded_dives.buoyancy_freq,
        gridded_dives.dtdz,
    ):
        assert field.shape == (201, n_casts)
    assert gridded_dives.n_points.shape == (n_casts,)
    assert np.all(gridded_dives.n_points > 0)


def test_build_dive_stack_time_is_monotonic_per_cast(gridded_dives: GriddedDives) -> None:
    """A down-cast's gridded time should be non-decreasing with depth."""
    # Down-casts (even columns): time should be non-decreasing with depth.
    for k in range(0, gridded_dives.time.shape[1], 2):
        t = gridded_dives.time[:, k]
        finite = t[np.isfinite(t)]
        assert np.all(np.diff(finite) >= 0)


def test_reference_buoyancy_frequency_is_finite_and_positive(wkb_result: WkbResult) -> None:
    """N0, the WKB-stretching reference frequency, should be finite and positive."""
    assert np.isfinite(wkb_result.reference_buoyancy_freq)
    assert wkb_result.reference_buoyancy_freq > 0


@pytest.mark.parametrize("direction_name", ["dive", "climb"])
def test_direction_point_counts_match_relative_n(wkb_result: WkbResult, direction_name: str) -> None:
    """n_new should equal round(n_points * relative_N), rounding half away from zero."""
    direction = getattr(wkb_result, direction_name)
    # Round half away from zero (MATLAB's round()), not numpy's round-half-
    # to-even -- matters here since 663 * 1.5 lands exactly on 994.5.
    expected = np.floor(direction.n_points * _RELATIVE_N + 0.5).astype(np.int64)
    np.testing.assert_array_equal(direction.n_new, expected)


@pytest.mark.parametrize("direction_name", ["dive", "climb"])
def test_direction_dt_new_is_mostly_finite_and_positive(wkb_result: WkbResult, direction_name: str) -> None:
    """The proposed sampling interval should be finite and positive almost everywhere."""
    direction = getattr(wkb_result, direction_name)
    finite = direction.dt_new[np.isfinite(direction.dt_new)]
    assert finite.size > 0.9 * direction.dt_new.size
    assert np.all(finite > 0)


@pytest.mark.parametrize("direction_name", ["dive", "climb"])
def test_direction_top_zone_uses_fixed_sampling_rate(wkb_result: WkbResult, direction_name: str) -> None:
    """The shallowest bucket should report exactly the imposed top-zone sampling rate."""
    direction = getattr(wkb_result, direction_name)
    np.testing.assert_allclose(direction.buckets_sampling_rate[0, :], 5.0)


def test_flip_prefix_matches_np_flip_for_fully_valid_array() -> None:
    """No behavior change for a cast that already reaches the bottom of the grid.

    When every entry is finite (a cast reaching the full depth grid),
    _flip_prefix must behave identically to the plain np.flip it replaces.
    """
    arr = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
    np.testing.assert_array_equal(_flip_prefix(arr), np.flip(arr))


def test_flip_prefix_keeps_valid_data_anchored_for_a_partial_array() -> None:
    """The reversed data stays at the same leading indices for a shallow cast.

    For a cast that doesn't reach the full depth grid (a leading finite
    prefix followed by NaN), the reversed data must stay at the same
    leading indices - not get shifted to the unreached (NaN) end, which is
    the bug this replaces a plain np.flip to fix (see wkb.py's
    compute_wkb_schedule/climb docstring).
    """
    arr = np.array([30.0, 20.0, 10.0, 0.0, np.nan])
    result = _flip_prefix(arr)
    np.testing.assert_array_equal(result, np.array([0.0, 10.0, 20.0, 30.0, np.nan]))


def test_too_many_points_in_top_zone_raises(gridded_dives: GriddedDives) -> None:
    """Asking for fewer points than the fixed top zone alone requires should raise."""
    with pytest.raises(ValueError, match="too many points"):
        compute_wkb_schedule(
            gridded_dives,
            buckets_depths=_BUCKETS_DEPTHS,
            top_sampling_rate=5.0,
            relative_N=np.array([1e-6]),
        )


def test_no_data_below_first_bucket_raises_clearly() -> None:
    """A shallow trailing window raises a clear error instead of crashing.

    A trailing window whose dives never reach past buckets_depths[0] (e.g.
    shallow/short shakedown dives) should raise a clear error, not crash
    later on a NaN -> int conversion.
    """
    z = np.arange(0.0, 1000.0 + _DZ, _DZ)
    n = z.size
    all_nan = np.full((n, 2), np.nan)
    shallow_only = np.full((n, 2), np.nan)
    shallow_only[:5, :] = 1.0
    shallow_time = np.full((n, 2), np.nan)
    shallow_time[:5, :] = np.linspace(0.0, 100.0, 5)[:, None]
    gridded = GriddedDives(
        z=z,
        lon=all_nan,
        lat=all_nan,
        time=shallow_time,
        sigma_theta=all_nan,
        temperature=all_nan,
        salinity=all_nan,
        vertical_speed=all_nan,
        n_points=np.array([5, 5]),
        dt_sampling=all_nan,
        sample_index=all_nan,
        buoyancy_freq=shallow_only,
        dtdz=all_nan,
    )
    with pytest.raises(ValueError, match="too shallow/short"):
        compute_wkb_schedule(gridded, buckets_depths=_BUCKETS_DEPTHS, top_sampling_rate=5.0, relative_N=_RELATIVE_N)
