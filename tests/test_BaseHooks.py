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

known_errors = (
    "Substantial unmodeled flight time",
    "Large mis-match between predicted and observed w",
    "Estimated DAC magnitude",
    "No call data found in database",
    "mpath failed",
)


test_cases = (
    (
        Base.main,
        "testdata/sg236_NANOOS_May23_hooks",
        "",
        known_errors,
        (),
    ),
    (
        Base.main,
        "testdata/sg236_NANOOS_May23_hooks",
        "--post_dive_timeout 1",
        known_errors,
        ("Timeout",),
    ),
    (
        Base.main,
        "testdata/sg236_NANOOS_May23_hooks",
        "--post_mission_timeout 1",
        known_errors,
        ("Timeout",),
    ),
    # These tests require some re-structuring of BaseLogin.py
    # (
    #     BaseLogin.main,
    #     "testdata/sg236_NANOOS_May23_hooks",
    #     "",
    #     (),
    #     (),
    # ),
    # (
    #     BaseLogin.main,
    #     "testdata/sg236_NANOOS_May23_hooks",
    #     "--pre_login_timeout 1",
    #     (),
    #     ("Timeout",),
    # ),
)

test_inputs = []

for (
    main_func,
    test_data_dir,
    additional_args,
    allowed_msgs,
    required_msgs,
) in test_cases:
    test_inputs.append(
        (
            main_func,
            test_data_dir,
            f"--verbose  --local --skip_flight_model --plot_types none --ignore_flight_model {additional_args} --mission_dir {test_data_dir}/mission_dir".split(),
            allowed_msgs,
            required_msgs,
        )
    )


@pytest.mark.parametrize(
    "main_func,test_data_dir,cmd_line,allowed_msgs,required_msgs", test_inputs
)
def test_BaseHooks(
    caplog, main_func, test_data_dir, cmd_line, allowed_msgs, required_msgs
):
    data_dir = pathlib.Path(test_data_dir)
    mission_dir = data_dir.joinpath("mission_dir")

    testutils.run_mission(
        data_dir,
        mission_dir,
        main_func,
        cmd_line,
        caplog,
        allowed_msgs,
        required_msgs=required_msgs,
    )
