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

import MakePlotTSProfile

dive_90 = [
    "dv0090_reduced_ts.webp",
    "dv0090_reduced_ts.div",
    "dv0090_reduced_ctd.webp",
    "dv0090_reduced_ctd.div",
]
dive_81 = [
    "dv0081_reduced_ts.webp",
    "dv0081_reduced_ts.div",
    "dv0081_reduced_ctd.webp",
    "dv0081_reduced_ctd.div",
]

test_cases: list[tuple[str, list[str]]] = [
    ("p2560090.ncdf", dive_90),
    ("p2560081.npro_ct.dat", dive_81),
    ("", dive_81 + dive_90),
]


@pytest.mark.parametrize(
    "filename,expected_files",
    test_cases,
)
def test_simpleplotextensionbase(caplog, filename, expected_files):
    data_dir = pathlib.Path("testdata/sg256_AMOS_Aug24_TSPlot")
    mission_dir = data_dir.joinpath("mission_dir")
    allowed_msgs = [""]
    filename = mission_dir / filename if filename else ""

    testutils.run_mission(
        data_dir,
        mission_dir,
        MakePlotTSProfile.main,
        f"--verbose {filename}  --mission_dir {mission_dir} ".split(),
        caplog,
        allowed_msgs,
    )

    for out_file in expected_files:
        assert (mission_dir / "plots" / out_file).exists()
