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
import FlightModel
import FlightModelCLI


@pytest.mark.parametrize("fm_plot_engine", ["matplotlib", "plotly"])
def test_fmcli(tmp_path, caplog, fm_plot_engine):
    """Tests that the mission with completes a FMS run"""
    data_dir = pathlib.Path("testdata/sg561_provolo_lofoten_may2016_dive2on")
    mission_dir = tmp_path / "mission_dir"

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
def test_fmcli_replot_and_dac_dives(tmp_path, caplog, fm_plot_engine):
    """Tests --replot (Phase 2) and dive_specs-driven DAC plot generation
    (Phase 3) against an already-processed flight/ directory"""
    data_dir = pathlib.Path("testdata/sg561_provolo_lofoten_may2016_dive2on")
    mission_dir = tmp_path / "mission_dir"

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
    # Direct call, not routed through testutils.run_mission - reset here too.
    FlightModel.set_globals()
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
    FlightModel.set_globals()
    assert FlightModelCLI.main([*cmd_line, "5:9"]) == 0
    assert not any(r.levelname in ("ERROR", "CRITICAL") for r in caplog.records)
    # 5 and 9 have cached grid solutions in this fixture - 6, 7, 8 don't, and
    # should be skipped with a warning rather than fail the run.
    for dive_num in (5, 9):
        assert (mission_dir / "flight" / f"dv{dive_num:04d}_DAC.{ext}").exists()
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    for dive_num in (6, 7, 8):
        assert any(f"dive {dive_num}" in w for w in warnings)


@pytest.mark.parametrize("fm_plot_engine", ["matplotlib"])
def test_fmcli_after_sgx_mission_in_same_process(tmp_path, caplog, fm_plot_engine):
    """Regression (2026-09-29): FlightModel built its a/b contour mesh
    (HD_A/HD_B) once per process. After an SGX mission (25-point drag grid)
    ran in the same process, a standard Seaglider mission (17-point grid) -
    here sg263 then sg561, the order a pytest-xdist worker happened to run
    them in - failed plotting with "Shapes of x (25, 31) and z (17, 31) do
    not match". Production runs one mission per process, so only the test
    suite (and anything else running several missions in one process) hit it.
    """
    # 1. An SGX mission (sg263: 72.98 kg > FlightModel.SGX_MASS) through Base,
    #    which runs FlightModel and leaves its figure state behind
    sgx_data_dir = pathlib.Path("testdata/sg263_NANOOS_Mar25_missingupload")
    sgx_mission_dir = tmp_path / "sgx_mission_dir"
    testutils.run_mission(
        sgx_data_dir,
        sgx_mission_dir,
        Base.main,
        f"--verbose --local --plot_types none --no-notify_vis --mission_dir {sgx_mission_dir} "
        f"--config {sgx_mission_dir}/sg263.conf".split(),
        caplog,
        [""],  # this fixture's known transfer errors don't matter here
    )
    # hd_b_grid only exists once set_globals()/FlightModel.main() has run
    hd_b_grid = FlightModel.hd_b_grid  # ty: ignore[unresolved-attribute]
    assert hd_b_grid is not None and len(hd_b_grid) == 25  # SGX drag grid

    # 2. A standard Seaglider mission (17-point drag grid) in the same process
    caplog.clear()
    data_dir = pathlib.Path("testdata/sg561_provolo_lofoten_may2016_dive2on")
    mission_dir = tmp_path / "mission_dir"
    testutils.run_mission(
        data_dir,
        mission_dir,
        FlightModelCLI.main,
        ["--verbose", "--mission_dir", str(mission_dir), "--fm_plot_engine", fm_plot_engine],
        caplog,
        [],
    )
    hd_a_grid = FlightModel.hd_a_grid  # ty: ignore[unresolved-attribute]
    hd_b_grid = FlightModel.hd_b_grid  # ty: ignore[unresolved-attribute]
    assert hd_b_grid is not None and len(hd_b_grid) == 17
    assert FlightModel.HD_A is not None and FlightModel.HD_A.shape == (17, len(hd_a_grid))
    for basename in ("eng_FM_vbdbias", "eng_FM_abs_compress", "eng_FM_ab_dives"):
        assert (mission_dir / "flight" / f"{basename}.webp").exists()
