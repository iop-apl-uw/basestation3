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
import shutil

import pytest
import testutils

import BaseNetwork
import BaseOpts
import MakePlotTSProfile
import PlotUtils

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
dive_81_wl = [
    "dv0081_reduced_wl.webp",
    "dv0081_reduced_wl.div",
]

test_cases: list[tuple[str, list[str]]] = [
    ("p2560090.ncdf", dive_90),
    ("p2560081.npro_ct.dat", dive_81),
    ("p2560081.npro_wl.dat", dive_81_wl),
    ("", dive_81 + dive_81_wl + dive_90),
]


@pytest.mark.parametrize(
    "filename,expected_files",
    test_cases,
)
def test_makeplottsprofile(caplog, filename, expected_files):
    data_dir = pathlib.Path("testdata/sg256_AMOS_Aug24_TSPlot")
    mission_dir = data_dir.joinpath("mission_dir")
    allowed_msgs = [""]
    filename = filename if filename else ""

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


def test_makeplottsprofile_ncdf_with_wl_variables(tmp_path, caplog):
    """plot_ncdf_profile() must plot both the T/S profile and the wl
    profile when an .ncdf contains both sets of variables - regression
    guard for the wl support added alongside BaseNetwork.py's own
    .npro_wl.dat handling."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    nlog_path = data_dir / "p2560005.nlog"
    nlog_path.write_text("$ID,256\n$DIVE,5\nstart:01 01 26 00 00 00\n")
    ct_path = data_dir / "p2560005.npro_ct.dat"
    ct_path.write_text(
        "%first_bin_depth: 7.50\n%bin_width: 5.00\n%columns: temperature salinity \n"
        "10.5 34.2 \n10.3 34.1 \n"
    )
    wl_path = data_dir / "p2560005.npro_wl.dat"
    wl_path.write_text(
        "%first_bin_depth: 2.50\n%bin_width: 5.00\n"
        "%columns: 470sig 700sig Chlsig temp \n"
        "74.0 74.0 53.0 572.0 \n73.0 73.0 54.0 571.0 \n"
    )
    mission_dir = tmp_path / "mission_dir"
    mission_dir.mkdir()
    for f in (nlog_path, ct_path, wl_path):
        shutil.copy(f, mission_dir / f.name)

    ncdf_path = BaseNetwork.make_netcdf_network_file(
        mission_dir / "p2560005.nlog",
        mission_dir / "p2560005.npro_ct.dat",
        mission_dir / "p2560005.npro_wl.dat",
    )
    assert ncdf_path is not None

    base_opts = BaseOpts.BaseOptions(
        "",
        cmdline_args=["--mission_dir", str(mission_dir)],
        calling_module="MakePlotTSProfile",
    )
    PlotUtils.setup_plot_directory(base_opts)
    plots = MakePlotTSProfile.plot_ncdf_profile(ncdf_path, base_opts)
    assert plots

    plot_dir = mission_dir / "plots"
    assert (plot_dir / "dv0005_reduced_ts.div").exists()
    assert (plot_dir / "dv0005_reduced_wl.div").exists()
