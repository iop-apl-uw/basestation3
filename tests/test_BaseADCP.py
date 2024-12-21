# -*- python-fmt -*-

## Copyright (c) 2024  University of Washington.
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

import pathlib

import pytest

import testutils

import numpy as np
import xarray as xr

import MakeMissionTimeSeries
import MakeMissionProfile
import Reprocess


def test_reprocess(caplog):
    extension_filename = pathlib.Path.cwd().joinpath("etc/.extensions")
    if not extension_filename.exists():
        pytest.skip(reason=f"{extension_filename} does not exist")

    with open(extension_filename) as fi:
        if "BaseADCP.py" not in fi.read():
            pytest.skip(reason=f"BaseADCP.py not installed in {extension_filename}")

    data_dir = pathlib.Path("testdata/sg171_EKAMSAT_Apr24")
    mission_dir = data_dir.joinpath("mission_dir")

    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        "--skip_flight_model",
        "--force",
        "100:109",
    ]

    testutils.run_mission(
        data_dir,
        mission_dir,
        Reprocess.main,
        cmd_line,
        caplog,
        allowed_msgs,
    )

    # Check for variables
    dsi = xr.load_dataset(mission_dir.joinpath("p1710100.nc"))

    var_dict = {
        "ad2cp_inv_glider_vocn": np.dtype("float32"),
        "ad2cp_inv_glider_uocn": np.dtype("float32"),
        "ad2cp_inv_glider_wocn": np.dtype("float32"),
    }

    for v, t in var_dict.items():
        assert v in dsi.variables
        assert dsi.variables[v].dtype == t


def test_whole_mission(caplog):
    extension_filename = pathlib.Path.cwd().joinpath("etc/.extensions")
    if not extension_filename.exists():
        pytest.skip(reason=f"{extension_filename} does not exist")

    with open(extension_filename) as fi:
        if "BaseADCP.py" not in fi.read():
            pytest.skip(reason=f"BaseADCP.py not installed in {extension_filename}")

    data_dir = pathlib.Path("testdata/sg171_EKAMSAT_Apr24_with_adcp")
    mission_dir = data_dir.joinpath("mission_dir")

    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        "--whole_mission_config",
        str(mission_dir.joinpath("sg171_mission.yml")),
    ]

    for mission_product, main_func in (
        ("sg171_EKAMSAT_2024_timeseries.nc", MakeMissionTimeSeries.main),
        ("sg171_EKAMSAT_2024_1.0m_up_and_down_profile.nc", MakeMissionProfile.main),
    ):
        testutils.run_mission(
            data_dir,
            mission_dir,
            main_func,
            cmd_line,
            caplog,
            allowed_msgs,
        )

        # Check for variables
        dsi = xr.load_dataset(mission_dir.joinpath(mission_product))

        var_dict = {
            "ad2cp_inv_glider_vocn": np.dtype("float32"),
            "ad2cp_inv_glider_uocn": np.dtype("float32"),
            "ad2cp_inv_glider_wocn": np.dtype("float32"),
        }

        for v, t in var_dict.items():
            assert v in dsi.variables
            assert dsi.variables[v].dtype == t
