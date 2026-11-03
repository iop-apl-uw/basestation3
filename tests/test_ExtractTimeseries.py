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


"""ExtractTimeseries.extractVars: variables on the time base of the best-sampled one."""

import logging
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import pytest

import ExtractTimeseries
import Utils

# One dive, 0-100 s. depth is sampled every 10 s, temperature every 20 s, salinity only after the dive.
_DEPTH_T = np.arange(5.0, 100.0, 10.0)
_DEPTH = _DEPTH_T * 2.0
_TEMP_T = np.arange(10.0, 100.0, 20.0)
_TEMP = 10.0 + _TEMP_T / 100.0
_SALIN_T = np.array([200.0, 210.0])
_SALIN = np.array([34.0, 34.1])


def _timeseries_nc(path: Path) -> Path:
    """Writes a minimal mission timeseries netCDF.

    Args:
        path: The file to write.

    Returns:
        path.
    """
    with netCDF4.Dataset(path, "w") as ds:
        for dim, n in (
            ("trajectory", 1),
            ("sg_data_point", len(_DEPTH)),
            ("ctd_data_point", len(_TEMP)),
            ("salin_data_point", len(_SALIN)),
        ):
            ds.createDimension(dim, n)
        for name, dim, values in (
            ("dive_number", "trajectory", [1]),
            ("start_time", "trajectory", [0.0]),
            ("end_time", "trajectory", [100.0]),
            ("time", "sg_data_point", _DEPTH_T),
            ("depth", "sg_data_point", _DEPTH),
            ("ctd_time", "ctd_data_point", _TEMP_T),
            ("temperature", "ctd_data_point", _TEMP),
            ("salin_time", "salin_data_point", _SALIN_T),
            ("salinity", "salin_data_point", _SALIN),
        ):
            ds.createVariable(name, "f8", (dim,))[:] = values
    return path


def _pandas_collection() -> Utils.PandasCollection:
    """The same data as a parquet cache would hold it.

    Returns:
        A PandasCollection with one dataframe per dimension.
    """
    return Utils.PandasCollection(
        {
            "gps_info": pd.DataFrame(
                {"trajectory": [1, 1, 1], "log_gps_time": [-10.0, 0.0, 100.0]}
            ),
            "sg_data_point": pd.DataFrame(
                {"trajectory": 1, "time": _DEPTH_T, "depth": _DEPTH}
            ),
            "ctd_data_point": pd.DataFrame(
                {"trajectory": 1, "ctd_time": _TEMP_T, "temperature": _TEMP}
            ),
            "salin_data_point": pd.DataFrame(
                {"trajectory": 1, "salin_time": _SALIN_T, "salinity": _SALIN}
            ),
        }
    )


def _extract(source: str, tmp_path: Path, var_names: list[str]) -> dict | None:
    """Runs extractVars for dive 1 from a netCDF file or a parquet cache.

    Args:
        source: "netcdf" or "parquet".
        tmp_path: Where the netCDF file goes.
        var_names: The variables to extract.

    Returns:
        extractVars' message.
    """
    if source == "netcdf":
        return ExtractTimeseries.extractVars(
            _timeseries_nc(tmp_path / "ts.nc"), var_names, 1, 1
        )
    return ExtractTimeseries.extractVars(
        None, var_names, 1, 1, pd_df_c=_pandas_collection()
    )


@pytest.mark.parametrize("source", ["netcdf", "parquet"])
@pytest.mark.parametrize(
    "var_names", [["depth", "temperature"], ["temperature", "depth"]]
)
def test_best_sampled_variable_is_the_time_base(
    source: str, tmp_path: Path, var_names: list[str]
) -> None:
    """Whatever the order asked for, depth (most samples) is the base and keeps its own values."""
    message = _extract(source, tmp_path, var_names)
    assert message is not None
    assert message["epoch"] == _DEPTH_T.tolist()
    assert message["time"] == (_DEPTH_T - _DEPTH_T[0]).tolist()
    assert message["depth"] == _DEPTH.tolist()
    assert message["temperature"] == pytest.approx(
        np.interp(_DEPTH_T, _TEMP_T, _TEMP).tolist()
    )


@pytest.mark.parametrize("source", ["netcdf", "parquet"])
def test_variable_without_samples_is_left_out(
    source: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A variable with no samples in the dive range is left out with a warning, the rest returned."""
    with caplog.at_level(logging.WARNING):
        message = _extract(source, tmp_path, ["depth", "salinity"])
    assert message is not None
    assert message["depth"] == _DEPTH.tolist()
    assert "salinity" not in message
    assert "No samples in the dive range for salinity - left out" in caplog.text


@pytest.mark.parametrize("source", ["netcdf", "parquet"])
def test_no_variable_with_samples_returns_none(source: str, tmp_path: Path) -> None:
    """Nothing to build a time base from: None, not an AttributeError."""
    assert _extract(source, tmp_path, ["salinity"]) is None


@pytest.mark.parametrize("source", ["netcdf", "parquet"])
def test_unknown_variable_is_left_out(
    source: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A name the data set doesn't have is left out like one without samples (netCDF raised KeyError)."""
    with caplog.at_level(logging.WARNING):
        message = _extract(source, tmp_path, ["depth", "nosuchvar"])
    assert message is not None
    assert message["depth"] == _DEPTH.tolist()
    assert "nosuchvar" not in message
    assert "No samples in the dive range for nosuchvar - left out" in caplog.text
