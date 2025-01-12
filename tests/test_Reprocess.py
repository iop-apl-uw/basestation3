# -*- python-fmt -*-

## Copyright (c) 2024, 2025  University of Washington.
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

import Reprocess

test_dive_inputs = (
    ("--reprocess_dive_extensions", True),
    ("--no-reprocess_dive_extensions", False),
)


@pytest.mark.parametrize("reprocess_dive_extensions,ncf_exists", test_dive_inputs)
def test_dive_extension(caplog, reprocess_dive_extensions, ncf_exists):
    """Tests that the dive extension is being picked up and run and ignored under switch"""
    data_dir = pathlib.Path("testdata/sg171_EKAMSAT_Apr24")
    mission_dir = data_dir.joinpath("mission_dir")

    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        "--skip_flight_model",
        "--force",
        reprocess_dive_extensions,
        "100",
    ]

    def create_dive_extension(mission_dir: pathlib.Path) -> None:
        with open(mission_dir.joinpath(".extensions"), "w") as fo:
            fo.write("[dive]\nSimpleNetCDF.py\n")

    testutils.run_mission(
        data_dir,
        mission_dir,
        Reprocess.main,
        cmd_line,
        caplog,
        allowed_msgs,
        pre_test_hook=create_dive_extension,
    )
    simple_ncf = pathlib.Path(mission_dir.joinpath("p1710100.ncf"))
    assert simple_ncf.exists() == ncf_exists


test_mission_inputs = (
    ("--reprocess_mission_extensions", True),
    ("--no-reprocess_mission_extensions", False),
)


@pytest.mark.parametrize(
    "reprocess_mission_extensions,report_divencf", test_mission_inputs
)
def test_mission_extension(caplog, reprocess_mission_extensions, report_divencf):
    """Tests that the mission extension is being picked up and run and ignored under switch"""
    data_dir = pathlib.Path("testdata/sg171_EKAMSAT_Apr24")
    mission_dir = data_dir.joinpath("mission_dir")

    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        "--skip_flight_model",
        "--force",
        reprocess_mission_extensions,
        "100",
    ]

    def create_dive_extension(mission_dir: pathlib.Path) -> None:
        with open(mission_dir.joinpath(".extensions"), "w") as fo:
            fo.write("[mission]\nSimpleExtension.py\n")

    testutils.run_mission(
        data_dir,
        mission_dir,
        Reprocess.main,
        cmd_line,
        caplog,
        allowed_msgs,
        pre_test_hook=create_dive_extension,
    )
    f_found_msg = False
    for record in caplog.records:
        if all(
            x in record.msg
            for x in (
                "SimpleExtension",
                "Created",
                "testdata/sg171_EKAMSAT_Apr24/mission_dir/p1710100.nc",
            )
        ):
            f_found_msg = True
            break

    assert f_found_msg == report_divencf
