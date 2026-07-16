"""Gridding of raw dive profiles and WKB-stretched sampling schedule design.

Port of the non-plotting parts of ``glider_sampling_5_dives_v3_GS.m``: the
per-cast binning onto a common depth grid (including per-cast buoyancy
frequency and vertical temperature gradient), and the "WKB STRETCHING"
section that proposes a new sampling schedule uniform in buoyancy-frequency
-normalized ("WKB-stretched") depth.
"""

import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ctd_sampling.binning import bin_average
from ctd_sampling.buoyancy import buoyancy_frequency
from ctd_sampling.io import load_dive_variables
from ctd_sampling.smoothing import nan_smooth

_DIVE_VARIABLES = (
    "latitude",
    "longitude",
    "ctd_time",
    "sigma_theta",
    "ctd_depth",
    "salinity",
    "temperature",
    "vert_speed",
)
_UNIX_EPOCH = np.datetime64("1970-01-01T00:00:00")


@dataclass
class GriddedDives:
    """Per-cast profile data binned onto a common depth grid.

    Each 2-D field has shape ``(len(z), n_casts)``; columns alternate
    down-cast, up-cast, down-cast, up-cast, ... one pair per dive, matching
    the order dives are supplied to ``build_dive_stack``.
    """

    z: NDArray[np.float64]
    lon: NDArray[np.float64]
    lat: NDArray[np.float64]
    time: NDArray[np.float64]
    sigma_theta: NDArray[np.float64]
    temperature: NDArray[np.float64]
    salinity: NDArray[np.float64]
    vertical_speed: NDArray[np.float64]
    n_points: NDArray[np.int64]
    dt_sampling: NDArray[np.float64]
    sample_index: NDArray[np.float64]
    buoyancy_freq: NDArray[np.float64]
    dtdz: NDArray[np.float64]


@dataclass
class WkbDirectionResult:
    """WKB-stretched sampling schedule for one cast direction (dive or climb)."""

    n_points: int
    time_dive: NDArray[np.float64]
    dt_old: NDArray[np.float64]
    n_new: NDArray[np.int64]
    dt_new: NDArray[np.float64]
    z_1m: NDArray[np.float64]
    sr_1m: NDArray[np.float64]
    buckets_sampling_rate: NDArray[np.float64]


@dataclass
class WkbResult:
    """WKB-stretched sampling schedule for both cast directions."""

    z: NDArray[np.float64]
    buoyancy_freq: NDArray[np.float64]
    reference_buoyancy_freq: float
    dive: WkbDirectionResult
    climb: WkbDirectionResult


def _fill_gaps(z: NDArray[np.float64], values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Linearly interpolates interior NaN gaps; holds the leading value constant before the first finite sample.

    Trailing NaNs (after the last finite sample) are left as NaN, matching
    MATLAB's default (non-extrapolating) ``interp1``.

    Args:
        z: Depth grid corresponding to ``values``.
        values: Samples on ``z``, possibly containing NaNs.

    Returns:
        The gap-filled array, same shape as ``values``.
    """
    finite = np.isfinite(values)
    finite_idx = np.flatnonzero(finite)
    first, last = finite_idx[0], finite_idx[-1]
    filled = np.full_like(values, np.nan)
    filled[first : last + 1] = np.interp(z[first : last + 1], z[finite], values[finite])
    filled[:first] = filled[first]
    return filled


def _matlab_round(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Rounds half away from zero, matching MATLAB's ``round()`` (numpy rounds half to even)."""
    return np.sign(x) * np.floor(np.abs(x) + 0.5)


def _interp1(xq: NDArray[np.float64], xp: NDArray[np.float64], fp: NDArray[np.float64]) -> NDArray[np.float64]:
    """Linear interpolation that is NaN outside ``[xp[0], xp[-1]]``, matching MATLAB's default ``interp1``."""
    result = np.interp(xq, xp, fp)
    return np.where((xq < xp[0]) | (xq > xp[-1]), np.nan, result)


def _flip_prefix(arr: NDArray[np.float64]) -> NDArray[np.float64]:
    """Reverses only the leading finite prefix of ``arr``, leaving the rest NaN.

    Used for the climb direction's ``time_dive`` (climb runs shallow-to-deep
    in z-index order but late-to-early in elapsed time, the reverse of a
    dive, so it needs reversing to share the dive's WKB-stretching code) -
    a plain ``np.flip`` reverses the *entire* fixed-length z grid, which is
    only correct when the cast reaches the grid's full depth. For a
    shallower/shorter cast, the valid (non-NaN) prefix is shorter than the
    grid, and a whole-array flip shifts it to the *opposite* end - lining
    the reversed timing data up against completely unrelated, unreached
    depths instead of the depths it actually came from. This reverses just
    that valid prefix and keeps it anchored at index 0, which is provably
    identical to ``np.flip`` when the prefix already spans the whole array
    (i.e. no behavior change for casts that do reach the full depth grid).

    Args:
        arr: A 1-D array whose valid (finite) values form a leading prefix,
            e.g. one column of ``GriddedDives.time``.

    Returns:
        ``arr``'s valid prefix, reversed, still occupying the same leading
        indices; trailing (previously NaN) entries remain NaN.
    """
    finite = np.isfinite(arr)
    n_valid = int(np.count_nonzero(finite))
    result = np.full_like(arr, np.nan)
    if n_valid:
        result[:n_valid] = arr[finite][::-1]
    return result


def _grid_one_cast(
    depth: NDArray[np.float64],
    data: dict[str, np.ndarray],
    cast: slice,
    z: NDArray[np.float64],
    dz: float,
) -> dict[str, NDArray[np.float64] | int]:
    """Bin-averages one down- or up-cast onto ``z``, plus derived buoyancy frequency and dT/dz."""
    cast_depth = depth[cast]
    time_s = (data["ctd_time"][cast] - _UNIX_EPOCH) / np.timedelta64(1, "s")

    lon, _ = bin_average(cast_depth, data["longitude"][cast], z)
    lat, _ = bin_average(cast_depth, data["latitude"][cast], z)
    time, _ = bin_average(cast_depth, time_s, z)
    sigma_theta, _ = bin_average(cast_depth, data["sigma_theta"][cast], z)
    temperature, _ = bin_average(cast_depth, data["temperature"][cast], z)
    salinity, _ = bin_average(cast_depth, data["salinity"][cast], z)
    vertical_speed, _ = bin_average(cast_depth, data["vert_speed"][cast], z)
    dt_sampling, _ = bin_average(cast_depth[1:], np.diff(time_s), z)
    sample_index, _ = bin_average(cast_depth, np.arange(1, cast_depth.size + 1, dtype=np.float64), z)

    # gsw needs a longitude (for the Absolute Salinity spatial correction);
    # the original seawater-toolbox sw_bfrq call never used one. The cast's
    # own median position is the natural choice.
    cast_lat = float(np.nanmedian(lat))
    cast_lon = float(np.nanmedian(lon))
    filled_temperature = _fill_gaps(z, temperature)
    filled_salinity = _fill_gaps(z, salinity)
    freq = buoyancy_frequency(z, filled_temperature, filled_salinity, cast_lon, cast_lat)

    dtdz_diff = -np.diff(filled_temperature) / dz
    dtdz = np.concatenate(([dtdz_diff[0]], 0.5 * (dtdz_diff[:-1] + dtdz_diff[1:]), [dtdz_diff[-1]]))

    return {
        "lon": lon,
        "lat": lat,
        "time": time,
        "sigma_theta": sigma_theta,
        "temperature": temperature,
        "salinity": salinity,
        "vertical_speed": vertical_speed,
        "n_points": cast_depth.size,
        "dt_sampling": dt_sampling,
        "sample_index": sample_index,
        "buoyancy_freq": freq,
        "dtdz": dtdz,
    }


def build_dive_stack(
    nc_dir: Path,
    sg_label: str,
    dive_numbers: Sequence[int],
    z: NDArray[np.floating],
    dz: float,
) -> GriddedDives:
    """Grids the down- and up-casts of a sequence of dives onto a common depth grid.

    Args:
        nc_dir: Directory containing the per-dive NetCDF profile files.
        sg_label: Seaglider numeric label (e.g. ``"167"``), used in the file
            name pattern ``p{sg_label}{dive_number:04d}.nc``.
        dive_numbers: Dive numbers to load, in order; each dive contributes
            one down-cast and one up-cast column (down, up, down, up, ...).
        z: Common depth grid to bin onto.
        dz: Depth grid spacing (m); must equal ``np.diff(z)``.

    Returns:
        A GriddedDives with one down/up column pair per requested dive.
    """
    z = np.asarray(z, dtype=np.float64)
    field_names = (
        "lon",
        "lat",
        "time",
        "sigma_theta",
        "temperature",
        "salinity",
        "vertical_speed",
        "dt_sampling",
        "sample_index",
        "buoyancy_freq",
        "dtdz",
    )
    n_casts = 2 * len(dive_numbers)
    fields: dict[str, NDArray[np.float64]] = {name: np.full((z.size, n_casts), np.nan) for name in field_names}
    n_points = np.zeros(n_casts, dtype=np.int64)

    k = 0
    for dive_number in dive_numbers:
        file_nc = nc_dir / f"p{sg_label}{dive_number:04d}.nc"
        data = load_dive_variables(file_nc, _DIVE_VARIABLES)
        depth = data["ctd_depth"]
        i_apogee = int(np.argmax(depth))

        for cast in (slice(0, i_apogee + 1), slice(i_apogee, None)):
            result = _grid_one_cast(depth, data, cast, z, dz)
            for name in field_names:
                fields[name][:, k] = result[name]
            n_points[k] = result["n_points"]
            k += 1

    return GriddedDives(z=z, n_points=n_points, **fields)


def _wkb_stretch_direction(
    n_points: int,
    time_dive: NDArray[np.float64],
    time_top: float,
    dt_old: NDArray[np.float64],
    z: NDArray[np.float64],
    i_max: int,
    buckets_depths: NDArray[np.float64],
    top_sampling_rate: float,
    relative_N: NDArray[np.float64],
    mean_bf: NDArray[np.float64],
    dz_weights: NDArray[np.float64],
    n0: float,
) -> WkbDirectionResult:
    """Computes the WKB-stretched schedule for one cast direction."""
    if not np.isfinite(time_top):
        raise ValueError(
            "No valid dive-time data below the first depth bucket for this "
            "cast direction - the dives in this window may be too "
            "shallow/short to compute a WKB-stretched schedule."
        )
    time_dive = nan_smooth(time_dive, np.ones(5) / 5)
    n_new = _matlab_round(n_points * np.asarray(relative_N, dtype=np.float64)).astype(np.int64)
    n_top = int(_matlab_round(np.asarray(time_top / top_sampling_rate)))

    dt_new = np.full((z.size, n_new.size), np.nan)
    # Fixed rate imposed in the top zone, for every option. (The original
    # MATLAB used a bare `dt_new(1:i_max) = ...` here, which under
    # column-major linear indexing only actually fills the first option's
    # column; this port applies it to all columns, matching the script's
    # own stated intent of imposing the same top-zone rate for every option.)
    dt_new[:i_max, :] = top_sampling_rate

    z_wkb_domain = z[i_max:]
    cumulative = np.cumsum(mean_bf[i_max:] * dz_weights[i_max:])
    z_wkb = np.concatenate(([0.0], cumulative / n0))[:-1] + z[i_max]

    depth_range_mask = (z >= buckets_depths[0]) & (z <= z.max())

    for option, target_n in enumerate(n_new):
        n_new_points = int(target_n) - n_top
        if n_new_points < 0:
            raise ValueError("too many points in the prescribed top!")

        z_uniform = np.linspace(z[i_max], z[-1], n_new_points)
        z_stretched = _interp1(z_uniform, z_wkb, z_wkb_domain)
        time_stretched = _interp1(z_stretched, z, time_dive)
        time_stretched = time_stretched - time_stretched[0] + n_top * top_sampling_rate

        dt_new[depth_range_mask, option] = _interp1(z[depth_range_mask], z_stretched[:-1], np.diff(time_stretched))

    z_1m = np.arange(z[0], z[-1] + 1)
    sr_1m = np.full((z_1m.size, n_new.size), np.nan)
    buckets_sampling_rate = np.full((buckets_depths.size, n_new.size), np.nan)

    for kk in range(buckets_depths.size):
        if kk == 0:
            in_bucket = z < buckets_depths[kk]
            in_bucket_1m = z_1m < buckets_depths[kk]
        else:
            in_bucket = (z < buckets_depths[kk]) & (z >= buckets_depths[kk - 1])
            in_bucket_1m = (z_1m < buckets_depths[kk]) & (z_1m >= buckets_depths[kk - 1])
        for option in range(n_new.size):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                rate = np.nanmean(dt_new[in_bucket, option])
            buckets_sampling_rate[kk, option] = rate
            sr_1m[in_bucket_1m, option] = rate

    return WkbDirectionResult(
        n_points=n_points,
        time_dive=time_dive,
        dt_old=dt_old,
        n_new=n_new,
        dt_new=dt_new,
        z_1m=z_1m,
        sr_1m=sr_1m,
        buckets_sampling_rate=buckets_sampling_rate,
    )


def compute_wkb_schedule(
    sg: GriddedDives,
    buckets_depths: NDArray[np.float64],
    top_sampling_rate: float,
    relative_N: NDArray[np.float64],
) -> WkbResult:
    """Designs a WKB-stretched sampling schedule from a stack of gridded dives.

    A fixed sampling interval (``top_sampling_rate``) is imposed down to the
    first grid depth past ``buckets_depths[0]``; below that, sample spacing
    is chosen to be uniform in WKB-stretched (buoyancy-frequency-normalized)
    depth, separately for each candidate total point count in
    ``n_points * relative_N``, and separately for the dive and the climb.
    The dive uses the last dive's down-cast as its point-count/timing
    reference; the climb uses the last dive's up-cast.

    Args:
        sg: Gridded dive stack, as returned by ``build_dive_stack``.
        buckets_depths: Upper edges of the depth buckets used for reporting
            bucket-averaged sampling rates; ``buckets_depths[0]`` also marks
            the bottom of the fixed-rate top zone.
        top_sampling_rate: Fixed sampling interval (s) imposed in the top zone.
        relative_N: Candidate point-count multipliers, e.g. ``[0.8, 1, 1.5]``.

    Returns:
        The WKB-stretched schedule for both the dive and the climb.

    Raises:
        ValueError: ``sg`` has no valid data below ``buckets_depths[0]``
            (e.g. every dive in the window is too shallow/short to reach
            it), so a WKB-stretched schedule cannot be computed.
    """
    z = sg.z
    i_max = int(np.flatnonzero(z > buckets_depths[0])[0])

    # The deepest few grid bins are legitimately unreached by every cast
    # (real dives don't all hit the exact same max depth), so nanmedian/
    # nanmean produce all-NaN slices there by design; silence numpy's
    # warning about it rather than the underlying (expected) NaN.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        dt_old = np.nanmedian(sg.dt_sampling, axis=1)

        # Direction-invariant (the original script recomputes this
        # identically inside both passes of its direction loop).
        mean_bf = np.nanmean(sg.buoyancy_freq, axis=1)
    mean_bf = nan_smooth(mean_bf, np.ones(10) / 10)
    # Deliberate deviation from the original MATLAB `mean(BF(i_max:end))`
    # (which propagates NaN if even a single depth bin is NaN, e.g. the
    # deepest bins where casts didn't all reach the same max depth):
    # nanmean is used here instead so a few missing deep bins don't NaN
    # out the whole WKB stretch.
    n0 = float(np.nanmean(mean_bf[i_max:]))
    if not np.isfinite(n0):
        raise ValueError(
            "No valid buoyancy-frequency data below the first depth bucket "
            "(buckets_depths[0]) across the trailing dive window - the "
            "dives in this window may be too shallow/short to compute a "
            "WKB-stretched schedule."
        )

    z_diff = np.diff(z)
    dz_weights = np.concatenate(([z_diff[0] / 2], (z_diff[:-1] + z_diff[1:]) / 2, [z_diff[-1] / 2]))

    dive = _wkb_stretch_direction(
        n_points=int(sg.n_points[-2]),
        time_dive=sg.time[:, -2] - np.nanmin(sg.time[:, -2]),
        time_top=float(np.nanmean(sg.time[i_max, 0::2] - np.nanmin(sg.time[: i_max + 1, 0::2], axis=0))),
        dt_old=dt_old,
        z=z,
        i_max=i_max,
        buckets_depths=buckets_depths,
        top_sampling_rate=top_sampling_rate,
        relative_N=relative_N,
        mean_bf=mean_bf,
        dz_weights=dz_weights,
        n0=n0,
    )
    climb = _wkb_stretch_direction(
        n_points=int(sg.n_points[-1]),
        time_dive=_flip_prefix(sg.time[:, -1] - np.nanmin(sg.time[:, -1])),
        time_top=float(np.nanmean(np.abs(sg.time[i_max, 1::2] - np.nanmax(sg.time[: i_max + 1, 1::2], axis=0)))),
        dt_old=dt_old,
        z=z,
        i_max=i_max,
        buckets_depths=buckets_depths,
        top_sampling_rate=top_sampling_rate,
        relative_N=relative_N,
        mean_bf=mean_bf,
        dz_weights=dz_weights,
        n0=n0,
    )

    return WkbResult(z=z, buoyancy_freq=mean_bf, reference_buoyancy_freq=n0, dive=dive, climb=climb)
