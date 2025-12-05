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

import BasePlot

test_dive_inputs = (
    (
        "p6860005.nc --plot_types dives --dive_plot plot_science",
        "sg686_Shilshole_28Oct25",
        ["dv0005_fet_fet.webp", "dv0005_fet_fet.webp"],
    ),
)


@pytest.mark.parametrize(
    "baseplot_options,data_dir,expected_output_files", test_dive_inputs
)
def test_dive_plot(caplog, baseplot_options, data_dir, expected_output_files):
    """Tests Plotting routines"""
    data_dir = pathlib.Path("testdata").joinpath(data_dir)
    mission_dir = data_dir.joinpath("mission_dir")

    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
    ]
    cmd_line += baseplot_options.split(" ")

    testutils.run_mission(
        data_dir,
        mission_dir,
        BasePlot.main,
        cmd_line,
        caplog,
        allowed_msgs,
    )
    for expected_output_file in expected_output_files:
        output_file = pathlib.Path(
            mission_dir.joinpath("plots").joinpath(expected_output_file)
        )
        assert output_file.exists()
