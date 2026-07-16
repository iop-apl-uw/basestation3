"""Loading Seaglider dive NetCDF profiles.

Replaces ``read_netcdf.m`` with ``xarray``, which already applies CF
fill-value masking (the manual ``>1e30 -> NaN`` replacement done by hand in
the original is unnecessary) and decodes ``ctd_time`` natively to
``datetime64``.
"""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import xarray as xr


def load_dive_variables(file_nc: Path, variables: Sequence[str]) -> dict[str, np.ndarray]:
    """Loads a set of variables from a Seaglider dive profile NetCDF file.

    Args:
        file_nc: Path to a single-dive NetCDF profile file.
        variables: Names of the data variables to extract.

    Returns:
        A dict mapping variable name to its values as a 1-D numpy array.

    Raises:
        KeyError: If a requested variable is not present in the file.
    """
    with xr.open_dataset(file_nc, decode_timedelta=False) as ds:
        return {name: ds[name].to_numpy() for name in variables}
