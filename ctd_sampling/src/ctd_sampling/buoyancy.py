"""Buoyancy frequency from a gridded temperature/salinity profile.

Port of the ``sw_pres``/``sw_bfrq`` (legacy ``seawater`` toolbox) usage in
the original script, replaced with ``gsw`` (TEOS-10).
"""

import gsw
import numpy as np
from numpy.typing import NDArray


def _linear_extrapolate(z_a: float, bf_a: complex, z_b: float, bf_b: complex, z_target: float) -> complex:
    """Linearly extrapolates from two reference points to a target depth."""
    slope = (bf_b - bf_a) / (z_b - z_a)
    return bf_a + slope * (z_target - z_a)


def buoyancy_frequency(
    z_grid: NDArray[np.floating],
    temperature: NDArray[np.floating],
    salinity: NDArray[np.floating],
    longitude: float,
    latitude: float,
) -> NDArray[np.float64]:
    """Computes buoyancy frequency on a depth grid via TEOS-10 (``gsw``).

    ``temperature`` and ``salinity`` must already be gap-filled (no
    internal NaNs) on ``z_grid``, e.g. via linear interpolation. Buoyancy
    frequency squared (``N²``) is computed at pressure midpoints and
    interpolated back onto ``z_grid``; the square root is taken *before*
    interpolating (matching the original), so statically unstable
    stretches (``N² < 0``) produce a complex intermediate value whose real
    part is taken only after interpolation and edge extrapolation, and
    any residual negative values are then masked to NaN.

    Args:
        z_grid: Depth grid, positive down, strictly increasing, at least
            4 points long.
        temperature: In-situ temperature (°C) on ``z_grid``, no NaNs.
        salinity: Practical salinity on ``z_grid``, no NaNs.
        longitude: Longitude of the profile, degrees East.
        latitude: Latitude of the profile, degrees North.

    Returns:
        Buoyancy frequency (rad/s) on ``z_grid``, NaN where statically
        unstable.
    """
    z_grid = np.asarray(z_grid, dtype=np.float64)
    temperature = np.asarray(temperature, dtype=np.float64)
    salinity = np.asarray(salinity, dtype=np.float64)

    pressure = gsw.p_from_z(-z_grid, latitude)
    absolute_salinity = gsw.SA_from_SP(salinity, pressure, longitude, latitude)
    conservative_temperature = gsw.CT_from_t(absolute_salinity, temperature, pressure)
    n_squared, p_mid = gsw.Nsquared(absolute_salinity, conservative_temperature, pressure, lat=latitude)
    depth_mid = -gsw.z_from_p(p_mid, latitude)

    sqrt_n_squared = np.sqrt(n_squared.astype(complex))
    bf = np.interp(z_grid, depth_mid, sqrt_n_squared.real) + 1j * np.interp(z_grid, depth_mid, sqrt_n_squared.imag)

    bf[0] = _linear_extrapolate(z_grid[1], bf[1], z_grid[2], bf[2], z_grid[0])
    bf[-1] = _linear_extrapolate(z_grid[-2], bf[-2], z_grid[-3], bf[-3], z_grid[-1])

    bf_real = bf.real
    bf_real[bf_real < 0] = np.nan
    return bf_real
