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

import os
import pathlib
import shutil
import sys
import time

import pytest

import Base

test_cases = (
    (
        "testdata/sg179_Guam_Oct19_noct",
        "sg179",
        "",
        (
            "Found Disconnect with no previous Connected",
            "No CT data found",
            "Failed to create profiles for",
            "is marked as having a processing error",
            "Profiles for dive [100] had problems during processing.",
            "Could not load variables ctd_time or ctd_depth",
            "mpath failed - skipping mission map",
            "No call data found in database - skipping eng_mission_commlog",
            "Unable to load 'ctd_time' - skipping plot_CTW",
            "Could not load 'ctd_depth'",
            "Could not fetch needed variables 'depth'",
            "skipping bathy in plots",
        ),
    ),
    (
        "testdata/sg179_Guam_Oct19",
        "sg179",
        "--plot_types none",
        (
            "Found Disconnect with no previous Connected:",
            "timeout(s) seen in",
            "CTD out of the water after",
            "Large mis-match between predicted and observed w",
            "Compass invalid out for",
            "is marked as having a processing error",
        ),
    ),
    (
        "testdata/sg178_Guam_Oct19",
        "sg178",
        "--plot_types none",
        (
            "timeout(s) seen in",
            "CTD out of the water after",
            "Large mis-match between predicted and observed w",
            "ALERT:TIMEOUT",
        ),
    ),
    (
        "testdata/sg677_GoMex_2022_M1_Legato",
        "sg677",
        "",
        (
            "Found Disconnect with no previous Connected:",
            "Found Connected with no previous Disconnect:",
            "No handler found for columns",
            "Restarting anomaly after",
            "Large unexplained positive conductivity",
            "No call data found in database",
            "skipping bathy in plots",
        ),
    ),
)

test_inputs = []

for test_data_dir, glider, additional_args, allowed_msgs in test_cases:
    test_inputs.append(
        (
            test_data_dir,
            f"--verbose --local {additional_args} --mission_dir {test_data_dir}/mission_dir --config {test_data_dir}/mission_dir/{glider}.conf".split(),
            allowed_msgs,
        )
    )

# Each test in a "mission_dir" under the testdata/XXXX directory - testdata/sg179_Guam_Oct19/mission_dir for example
# Previous runs are removed and the contents of testdata/XXXX (no sub-directories) are copied to testdata/XXXX/mission_dir


@pytest.mark.parametrize("test_data_dir,cmd_line,allowed_msgs", test_inputs)
def test_conversion(caplog, test_data_dir, cmd_line, allowed_msgs):
    os.environ["TZ"] = "UTC"
    time.tzset()

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
    bad_errors = ""
    for record in caplog.records:
        # Check for known WARNING, ERROR or CRITICAL msgs
        for msg in allowed_msgs:
            if msg in record.msg:
                break
        else:
            if record.levelname in ["CRITICAL", "ERROR", "WARNING"]:
                bad_errors += f"{record.levelname}:{record.getMessage()}\n"
    if bad_errors:
        pytest.fail(bad_errors)
