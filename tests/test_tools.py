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

import tools.GetCodaMeta
import tools.GetLegatoPressCorr
import tools.GetOptodeConstants
import tools.GetTridenteChannels
import tools.PlotBathy

test_cases = (
    (
        tools.GetCodaMeta.main,
        "pt2720005.cap",
        [
            "calibcomm_codaTODO='RBRcoda serialnum:237923 temp15:2025-03-15T13:54:16Z doxy24:2025-03-20T11:35:41Z opt_05:2025-03-03T14:18:09Z';",
            "codaTODO_c0=0.000032;",
        ],
        [""],
    ),
    (
        tools.GetLegatoPressCorr.main,
        "pt2720005.cap",
        ["legato_cond_press_correction = 0;"],
        [""],
    ),
    (
        tools.GetTridenteChannels.main,
        "pt2720005.cap",
        [
            "calibcomm_tridentebb700bb470chla470='RBRtridente serialnum:238008 backscatter_00:2025-03-12T13:01:47Z backscatter_01:2025-03-12T13:06:10Z chlorophyll_00:2025-03-11T12:40:47Z';"
        ],
        [""],
    ),
    (
        tools.GetOptodeConstants.main,
        "pt2630012.cap",
        [
            "calibcomm_optode = 'Optode 4831 SN: 940  Foil ID: 1824M calibrated ??/??/????';",
            "optode_PhaseCoef0 = -2.734;",
        ],
        [""],
    ),
)


@pytest.mark.parametrize(
    "entry_point,selftest,required_msgs,allowed_msgs",
    test_cases,
)
def test_selftest(caplog, capsys, entry_point, selftest, required_msgs, allowed_msgs):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_tools")
    mission_dir = data_dir.joinpath("mission_dir")
    st = mission_dir / selftest

    testutils.run_mission(
        data_dir,
        mission_dir,
        entry_point,
        f"--verbose  {st}".split(),
        caplog,
        allowed_msgs,
        required_msgs=required_msgs,
        capsys=capsys,
    )


def test_plot_bathymap(caplog):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_tools")
    mission_dir = data_dir.joinpath("mission_dir")

    bathy_maps = ""
    for ii in range(1, 4):
        b_map = mission_dir / f"bathymap.00{ii}"
        bathy_maps += f"{b_map} "

    testutils.run_mission(
        data_dir,
        mission_dir,
        tools.PlotBathy.main,
        f"--verbose  {bathy_maps}".split(),
        caplog,
        [""],
    )
    assert (mission_dir / "bathymap.kml").exists()
    assert (mission_dir / "bathymap.png").exists()
