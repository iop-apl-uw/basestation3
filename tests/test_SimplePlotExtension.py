# -*- python-fmt -*-

## Copyright (c) 2024, 2025, 2026  University of Washington.
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

import Base
import SimplePlotExtension

data_dir = pathlib.Path("testdata/sg171_EKAMSAT_Apr24_SimplePlotExtension")
mission_dir = data_dir.joinpath("mission_dir")

test_cases = (["--mission_dir", str(mission_dir)], [str(mission_dir / "p1710100.nc")] )

@pytest.mark.parametrize(
    "additional_args", test_cases,
)
def test_simpleplotextension(caplog, additional_args):
    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
    ]

    cmd_line.extend(additional_args)

    testutils.run_mission(
        data_dir,
        mission_dir,
        SimplePlotExtension.main,
        cmd_line,
        caplog,
        allowed_msgs,
    )

    for out_file in (mission_dir / "plots" / "dv0100_testplot.webp", mission_dir / "plots" / "dv0100_testplot.div"):
        assert out_file.exists()


def test_simpleplotextensionbase(caplog):
    data_dir = pathlib.Path("testdata/sg178_Guam_Oct19_SimplePlotExtension/")
    mission_dir = data_dir.joinpath("mission_dir")
    allowed_msgs = [""]

    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        f"--verbose  --local --no-notify_vis --skip_flight_model --plot_types none --ignore_flight_model --mission_dir {mission_dir} --plot_types none".split(),
        caplog,
        allowed_msgs,
    )

    for out_file in (mission_dir / "plots" / "dv0163_testplot.webp", mission_dir / "plots" / "dv0163_testplot.div"):
        assert out_file.exists()
