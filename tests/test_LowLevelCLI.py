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

import BaseCtrlFiles
import BaseGZip
import CalibConst
import DataFiles
import LogFile
import Strip1A

test_cases = (
    (
        DataFiles.main,
        "",
        ["mission_dir/p2720002.dat"],
        [""],
    ),
    (
        DataFiles.main,
        "p2720002.dat",
        ["mission_dir/p2720002.dat"],
        [""],
    ),
    (
        BaseGZip.main,
        "sg0002lz.x sc0002ag.x",
        ["mission_dir/sg0002lz.decomp", "mission_dir/sc0002ag.decomp"],
        [""],
    ),
    (
        LogFile.main,
        "",
        ["mission_dir/p2720002.log"],
        [""],
    ),
    (
        LogFile.main,
        "p2720002.log",
        ["mission_dir/p2720002.log"],
        [""],
    ),
    (
        CalibConst.main,
        "",
        ["legato_sealevel"],
        [""],
    ),
)


@pytest.mark.parametrize(
    "entry_point,extra_args,required_msgs,allowed_msgs",
    test_cases,
)
def test_lowlevelcli(caplog, entry_point, extra_args, required_msgs, allowed_msgs):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_lowlevelcli")
    mission_dir = data_dir.joinpath("mission_dir")
    mission_dir_opt = f"--mission_dir {mission_dir}"

    testutils.run_mission(
        data_dir,
        mission_dir,
        entry_point,
        f"--verbose  {mission_dir_opt} {extra_args}".split(),
        caplog,
        allowed_msgs,
        required_msgs=required_msgs,
    )


strip_sizes = (0, 2048, 4096)


@pytest.mark.parametrize(
    "strip_size",
    strip_sizes,
)
def test_strip1a(caplog, strip_size):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_lowlevelcli")
    mission_dir = data_dir.joinpath("mission_dir")
    inp_file = mission_dir / "sc0002ag.x"
    out_file = mission_dir / "sc0002ag.x.1a"
    strip_size_str = f"{strip_size}" if strip_size else ""

    testutils.run_mission(
        data_dir,
        mission_dir,
        Strip1A.main,
        f"--verbose  {inp_file} {out_file} {strip_size_str}".split(),
        caplog,
        [""],
    )

    if strip_size == 0:
        assert out_file.stat().st_size == 3782
    else:
        assert out_file.stat().st_size == strip_size


def test_pagers_yml(caplog):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_lowlevelcli")
    mission_dir = data_dir.joinpath("mission_dir")
    group_etc = mission_dir / "etc"

    testutils.run_mission(
        data_dir,
        mission_dir,
        BaseCtrlFiles.main,
        f"--verbose  --mission_dir {mission_dir} --group_etc {group_etc} dump_pagers_yml".split(),
        caplog,
        [""],
        required_msgs=[
            "Subscriptions: gps:{'geoff'}",
            "email:[{'address': 'gbs2@uw.edu'}]",
        ],
    )
