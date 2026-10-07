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

"""Dive plots on dives without the data they need (bench/lab tests, no CTD).

Each plot used to raise a KeyError/ValueError traceback; it should skip with
one error naming what's missing.
"""

import logging
import pathlib
from unittest.mock import MagicMock

import netCDF4
import numpy as np
import pytest

import PlotUtils
from Plotting import DiveCTDCorrections, DiveLegatoPressure


def _dive_file(tmp_path: pathlib.Path, variables: dict[str, np.ndarray]) -> netCDF4.Dataset:
    """A minimal dive netCDF with only the given 1-d variables (on one dimension)."""
    file_name = tmp_path / "p5540006.nc"
    # Path -> str: netCDF4.Dataset wants a string path
    with netCDF4.Dataset(str(file_name), "w") as nc:
        nc.dive_number = 6
        nc.start_time = 1.79e9
        nc.createDimension("n", 4)
        for name, values in variables.items():
            nc.createVariable(name, "f8", ("n",))[:] = values
    return netCDF4.Dataset(str(file_name), "r")


def test_missing_variables(tmp_path: pathlib.Path) -> None:
    nc = _dive_file(tmp_path, {"time": np.arange(4.0), "pressure": np.zeros(4)})
    try:
        assert PlotUtils.missing_variables(nc, ["time", "ctd_time", "pressure", "ctd_depth"]) == [
            "ctd_time",
            "ctd_depth",
        ]
        assert PlotUtils.missing_variables(nc, ["time"]) == []
    finally:
        nc.close()


def test_plot_legato_pressure_without_ctd(
    caplog: pytest.LogCaptureFixture, tmp_path: pathlib.Path
) -> None:
    """sg554 Shilshole_30Sep26 dive 6: truck legato pressure, but no CTD results."""
    nc = _dive_file(
        tmp_path,
        {"time": np.arange(4.0), "eng_rbr_pressure": np.zeros(4), "pressure": np.zeros(4)},
    )
    try:
        with caplog.at_level(logging.ERROR):
            assert DiveLegatoPressure.plot_legato_pressure(MagicMock(), nc) == ([], [])
    finally:
        nc.close()
    assert (
        "Dive 6: no ctd_time, ctd_pressure, ctd_pressure_qc - skipping plot_legato_pressure"
        in caplog.text
    )
    assert "Traceback" not in caplog.text


def test_plot_ctd_corrections_without_corrected_ctd(
    caplog: pytest.LogCaptureFixture, tmp_path: pathlib.Path
) -> None:
    """sg274 lab-test dives: raw CT, but no corrected temperature/salinity or QC."""
    nc = _dive_file(
        tmp_path,
        {
            "ctd_time": np.arange(4.0),
            "ctd_depth": np.zeros(4),
            "ctd_pressure": np.zeros(4),
            "temperature_raw": np.zeros(4),
            "conductivity_raw": np.zeros(4),
        },
    )
    try:
        with caplog.at_level(logging.ERROR):
            assert DiveCTDCorrections.plot_ctd_corrections(MagicMock(), nc) == ([], [])
    finally:
        nc.close()
    assert (
        "Dive 6: no temperature, temperature_qc, temperature_raw_qc, salinity, salinity_qc, "
        "salinity_raw_qc - skipping plot_ctd_corrections" in caplog.text
    )
    assert "Traceback" not in caplog.text
