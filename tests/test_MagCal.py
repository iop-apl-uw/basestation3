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
import MakeDiveProfiles

test_cases = (("tcm2mat.cal.0001.0004",["tcm2mat.cal.0001.0004 to correct heading"],[""]),
              ("search",["tcm2mat.cal.0001.0004 to correct heading"],[""]),
              ("tcm2mat.cal",[""],["tcm2mat.cal does not exist"]))

@pytest.mark.parametrize(
    "magcal_filename,required_msgs,allowed_msgs", test_cases,
)
def test_simpleplotextensionbase(caplog, magcal_filename, required_msgs, allowed_msgs):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_magcal")
    mission_dir = data_dir.joinpath("mission_dir")
    magcal_filename = mission_dir / magcal_filename

    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        f"--verbose  --local --no-notify_vis --skip_flight_model --plot_types none --ignore_flight_model --magcalfile {magcal_filename} --mission_dir {mission_dir}".split(),
        caplog,
        allowed_msgs,
        required_msgs = required_msgs
    )


@pytest.mark.parametrize(
    "magcal_filename,required_msgs,allowed_msgs", test_cases,
)
def test_simpleplotextensionMDP(caplog, magcal_filename, required_msgs, allowed_msgs):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_magcal_ncf")
    mission_dir = data_dir.joinpath("mission_dir")
    magcal_filename = mission_dir / magcal_filename

    testutils.run_mission(
        data_dir,
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose  --reprocess 2 --magcalfile {magcal_filename} --mission_dir {mission_dir}".split(),
        caplog,
        allowed_msgs,
        required_msgs = required_msgs
    )
    
