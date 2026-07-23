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

import FlightModelCLI


@pytest.mark.parametrize("fm_plot_engine", ["matplotlib", "plotly"])
def test_fmcli(caplog, fm_plot_engine):
    """Tests that the mission with completes a FMS run"""
    data_dir = pathlib.Path("testdata/sg561_provolo_lofoten_may2016_dive2on")
    mission_dir = data_dir.joinpath("mission_dir")

    allowed_msgs = [
    ]
    required_msgs = [
    ]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        "--fm_plot_engine",
        fm_plot_engine,
    ]

    testutils.run_mission(
        data_dir,
        mission_dir,
        FlightModelCLI.main,
        cmd_line,
        caplog,
        allowed_msgs,
        required_msgs=required_msgs,
    )

    for dd in range(2, 10):
        mat_file = mission_dir / "flight" / f"fm_{dd:04d}.m"
        assert(mat_file.exists())

    # .div is the one file PlotUtilsPlotly.write_output_files always writes
    # regardless of save_* flags, making it the reliable existence check for
    # the plotly engine; matplotlib only ever writes .webp.
    ext = "div" if fm_plot_engine == "plotly" else "webp"
    for basename in (
        "eng_FM_vbdbias",
        "eng_FM_abs_compress",
        "eng_FM_ab_dives",
    ):
        assert (mission_dir / "flight" / f"{basename}.{ext}").exists()


@pytest.mark.parametrize("fm_plot_engine", ["matplotlib", "plotly"])
def test_fmcli_replot_and_dac_dives(caplog, fm_plot_engine):
    """Tests --replot (Phase 2) and dive_specs-driven DAC plot generation
    (Phase 3) against an already-processed flight/ directory"""
    data_dir = pathlib.Path("testdata/sg561_provolo_lofoten_may2016_dive2on")
    mission_dir = data_dir.joinpath("mission_dir")

    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        "--fm_plot_engine",
        fm_plot_engine,
    ]

    # Populate flight/flight.pkl with a normal run first - dives 5 and 9 are
    # known (from this fixture) to end up with a cached a/b grid solution.
    testutils.run_mission(
        data_dir,
        mission_dir,
        FlightModelCLI.main,
        cmd_line,
        caplog,
        allowed_msgs=[],
    )

    ext = "div" if fm_plot_engine == "plotly" else "webp"

    caplog.clear()
    assert FlightModelCLI.main([*cmd_line, "--replot"]) == 0
    assert not any(r.levelname in ("ERROR", "CRITICAL") for r in caplog.records)
    for basename in (
        "dv0005_ab",
        "dv0009_ab",
        "eng_FM_vbdbias",
        "eng_FM_abs_compress",
        "eng_FM_ab_dives",
    ):
        assert (mission_dir / "flight" / f"{basename}.{ext}").exists()

    caplog.clear()
    assert FlightModelCLI.main([*cmd_line, "5:9"]) == 0
    assert not any(r.levelname in ("ERROR", "CRITICAL") for r in caplog.records)
    # 5 and 9 have cached grid solutions in this fixture - 6, 7, 8 don't, and
    # should be skipped with a warning rather than fail the run.
    for dive_num in (5, 9):
        assert (mission_dir / "flight" / f"dv{dive_num:04d}_DAC.{ext}").exists()
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    for dive_num in (6, 7, 8):
        assert any(f"dive {dive_num}" in w for w in warnings)
