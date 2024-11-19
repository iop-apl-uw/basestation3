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
import shutil

import pytest

import Base

import pdb

test_inputs = []

test_dirs = [("testdata/sg179_Guam_Oct19", "sg179")]

for test_data_dir, glider in test_dirs:
    test_inputs.append(
        (
            test_data_dir,
            f"--verbose --local --plot_types none --mission_dir {test_data_dir}/mission_dir --config {test_data_dir}/mission_dir/{glider}.conf".split(),
            [
                "Found Disconnect with no previous Connected:",
                "timeout(s) seen in",
                "CTD out of the water after",
                "Large mis-match between predicted and observed w",
                "Compass invalid out for",
                "is marked as having a processing error",
            ],
        )
    )

# Each test in a "mission_dir" under the testdata/XXXX directory - testdata/sg179_Guam_Oct19/mission_dir for example
# Previous runs are removed and the contents of testdata/XXXX (no sub-directories) are copied to testdata/XXXX/mission_dir


@pytest.mark.parametrize("test_data_dir,cmd_line,allowed_msgs", test_inputs)
def test_downward(caplog, test_data_dir, cmd_line, allowed_msgs):
    data_dir = pathlib.Path(test_data_dir)
    mission_dir = data_dir.joinpath("mission_dir")
    # Clean up previous run - if any
    if mission_dir.exists():
        shutil.rmtree(mission_dir)
    # Populate the new mission_dir
    mission_dir.mkdir()
    for p in data_dir.iterdir():
        if p.is_dir():
            continue
        shutil.copy(p, mission_dir)
    result = Base.main(cmd_line)
    assert result == 0
    for record in caplog.records:
        # Check for known WARNING, ERROR or CRITICAL msgs
        for msg in allowed_msgs:
            if msg in record.msg:
                break
        else:
            assert record.levelname not in ["CRITICAL", "ERROR", "WARNING"]
