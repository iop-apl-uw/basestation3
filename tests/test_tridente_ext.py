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

"""Tests for the truck (serdev) Tridente support in Sensors/tridente_ext.py -
expansion of the compressed truck instrument name (see docs/tridente.md) to
the full name space, and the end-to-end raw-to-netCDF/plot pipeline for a
truck Tridente (sg554, tb700c470f365)."""

import pathlib
import sys
from unittest.mock import MagicMock

import netCDF4
import numpy as np
import pytest
import testutils

import Base

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Sensors"))
import tridente_ext  # noqa: E402  # ty: ignore[unresolved-import]


@pytest.mark.parametrize(
    "truck_name,expected",
    (
        ("tb700c470f365", "tridentebb700chla470fdom365"),
        ("t2b700c470f365", "tridente2bb700chla470fdom365"),
        ("tb700b470c470", "tridentebb700bb470chla470"),
        ("tc470f365t700", "tridentechla470fdom365tu700"),
        # Well formed, but not a known channel combination
        ("tb470c470f365", None),
        # Not tridente names
        ("tmicl", None),
        ("tb700c470f365x", None),
        ("t0b700c470f365", None),
        ("tz700c470f365", None),
        ("aa4330", None),
    ),
)
def test_expand_truck_name(truck_name: str, expected: str | None) -> None:
    assert tridente_ext.expand_truck_name(truck_name) == expected


def test_remap_engfile_columns_netcdf() -> None:
    names = [
        "tb700c470f365",
        "tb700c470f365_bb700",
        "aa4330_O2",
        "elaps_t",
    ]
    assert tridente_ext.remap_engfile_columns_netcdf(None, "tridente_ext", None, names) == 0
    assert names == [
        "tridentebb700chla470fdom365",
        "tridentebb700chla470fdom365_bb700",
        "aa4330_O2",
        "elaps_t",
    ]

    names = ["aa4330_O2", "elaps_t"]
    assert tridente_ext.remap_engfile_columns_netcdf(None, "tridente_ext", None, names) == 1
    assert names == ["aa4330_O2", "elaps_t"]

    assert tridente_ext.remap_engfile_columns_netcdf(None, "tridente_ext", None, None) == -1


def test_asc2eng_scales_and_renames() -> None:
    columns = {
        "tb700c470f365.bb700": np.array([150.0, -150000.0]),
        "tb700c470f365.chla470": np.array([1234.0, 0.0]),
        "aa4330.O2": np.array([1.0, 2.0]),
    }
    datafile = MagicMock()
    datafile.columns = list(columns)
    datafile.remove_col.side_effect = columns.pop
    datafile.eng_cols = []
    datafile.eng_dict = {}

    assert tridente_ext.asc2eng(None, "tridente_ext", datafile) == 0
    assert datafile.eng_cols == [
        "tridentebb700chla470fdom365.bb700",
        "tridentebb700chla470fdom365.chla470",
    ]
    np.testing.assert_allclose(
        datafile.eng_dict["tridentebb700chla470fdom365.bb700"], [0.0015, -1.5]
    )
    np.testing.assert_allclose(
        datafile.eng_dict["tridentebb700chla470fdom365.chla470"], [1.234, 0.0]
    )
    # Non-tridente columns are left for other handlers
    assert list(columns) == ["aa4330.O2"]

    assert tridente_ext.asc2eng(None, "tridente_ext", None) == -1


def test_truck_tridente_pipeline(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """Raw truck uploads with a tb700c470f365 Tridente produce the eng_ netCDF
    variables (scaled) and the tridente dive plots"""
    data_dir = pathlib.Path("testdata/sg554_Shilshole_30Sep26_truck_tridente")
    mission_dir = tmp_path / "mission_dir"

    allowed_msgs = [
        "timeout(s) seen",
        "ALERT:TIMEOUT",
        "Optode data found but foil calibration constant",
        "Missing metadata for log entry $MAMPSTAT",
        "Can't find the climb pump",
        "Engineering data ends at",
        "Substantial unmodeled flight time",
        "Large mis-match between predicted and observed w",
    ]
    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        f"--verbose --local --no-notify_vis --skip_flight_model --plot_types dives --dive_plots plot_tridente --mission_dir {mission_dir}".split(),
        caplog,
        allowed_msgs,
    )

    eng_columns = next(
        line
        for line in (mission_dir / "p5540003.eng").read_text().splitlines()
        if line.startswith("%columns:")
    )
    assert "tridentebb700chla470fdom365.bb700" in eng_columns
    assert "tb700c470f365" not in eng_columns

    with netCDF4.Dataset(mission_dir / "p5540003.nc") as ds:
        for chan in ("bb700", "chla470", "fdom365"):
            var = ds.variables[f"eng_tridentebb700chla470fdom365_{chan}"]
            assert var.dimensions == ("sg_data_point",)
        # Scaled by the .cnf scale factor (raw bb700 counts are O(1e5))
        assert np.nanmax(np.abs(ds.variables["eng_tridentebb700chla470fdom365_bb700"][:])) <= 1.5

    for chan in ("backscatter", "Chlorophyll_fluorescence", "fDOM_fluorescence"):
        assert (mission_dir / "plots" / f"dv0003_tridentebb700chla470fdom365_{chan}.webp").exists()
