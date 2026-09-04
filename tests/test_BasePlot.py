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
import BasePlot

test_dive_inputs = (
    (
        "p6860005.nc --plot_types dives --dive_plot plot_science",
        "sg686_Shilshole_28Oct25",
        ["dv0005_fet.webp", "dv0005_fet.webp"],
    ),
)


@pytest.mark.parametrize(
    "baseplot_options,data_dir,expected_output_files", test_dive_inputs
)
def test_dive_plot(caplog, baseplot_options, data_dir, expected_output_files):
    """Tests Plotting routines"""
    data_dir = pathlib.Path("testdata").joinpath(data_dir)
    mission_dir = data_dir.joinpath("mission_dir")

    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
    ]
    cmd_line += baseplot_options.split(" ")

    testutils.run_mission(
        data_dir,
        mission_dir,
        BasePlot.main,
        cmd_line,
        caplog,
        allowed_msgs,
    )
    for expected_output_file in expected_output_files:
        output_file = pathlib.Path(
            mission_dir.joinpath("plots").joinpath(expected_output_file)
        )
        assert output_file.exists()


# --- Systematic per-plot thumbnail coverage sweep -------------------------
#
# Confirms every registered dive/mission plot (per Plotting.dive_plot_funcs/
# mission_plot_funcs) produces at least one .webp thumbnail via the
# matplotlib thumbnail engine (thumbnail_engine defaults to "matplotlib" -
# see .claude/plans/2026-08-20-matplotlib-thumbnail-engine.md) without
# crashing. Deliberately checks "a thumbnail exists," not any specific
# pixel content - that's covered by manual visual comparison against
# plots_kaleido_baseline/ during development, not something worth pinning
# down in an automated assertion.
#
# plot_sample_example (Plotting/local/DiveSample.py) is deliberately
# excluded: it always returns ([], []) regardless of data - an unfinished
# template stub, not a real plot to cover.
#
# mission_riot (Plotting/local/MissionRiot.py) is deliberately excluded,
# permanently: a one-off plot for one specific mission, not worth a
# tracked fixture gap.
#
# mission_oceanvelocityprofile (adcp/MissionOcean.py) is deliberately
# excluded: needs a mission_dir/sections.yml with an adcp_variables key
# plus a generated ADCP profile-timeseries .nc
# (adcp/BaseADCPMission.py's output). Confirmed empirically (2026-08-20)
# that the .nc itself IS buildable from testdata/sg171_EKAMSAT_Apr24_with_adcp's
# existing per-dive .nc files (ran adcp/BaseADCPMission.py directly
# against them - built a valid file with every variable the plot needs in
# under a second, no raw reprocessing required). The real blocker is
# narrower than "no data exists": actually rendering the plot needs the
# mission DB's `dives` table populated, which needs Base.main's full
# pipeline, which unconditionally requires a real, parseable comm.log -
# and this fixture (built from pre-processed .nc files only) has none. A
# real comm.log does exist in the source production directory
# (~/work/seagliders/sg171_EKAMSAT_Apr24), but only alongside raw uploads
# for dives 1-9, while this fixture's dives are numbered 100-109 (a later
# stretch of the same mission) - closing this gap needs either the raw
# dive-100+ uploads (wherever that part of the mission is archived) or
# confirming dives 1-9 also carry usable ADCP data. Left as a follow-on.

# (plot_name, data_dir, dive_nc_filename, extra_cmd_line_args, instrument_id,
#  use_base_pipeline)
#
# instrument_id: some of these dirs (e.g. sg171_EKAMSAT_Apr24_with_adcp,
# sg249_NANOOS_Apr24) are reduced fixtures built for other tests and have no
# comm.log committed - BasePlot.main alone can't auto-detect the glider id
# from that (it doesn't read the id back out of an existing .nc), so it
# needs -i/--instrument_id passed explicitly. None where comm.log exists.
#
# use_base_pipeline: some dirs (sg178_Guam_Oct19, sg160_sbe43_scicon, and
# both new fixtures added this round) are raw-upload-only (per this
# project's fixture convention - see .claude/CLAUDE.md's "Test Fixture
# Data" section) with no per-dive .nc committed. BasePlot.main expects the
# .nc to already exist; Base.main runs the full raw-to-netCDF pipeline
# *and* the plotting stage in one pass (confirmed via direct manual runs -
# it accepts the identical --dive_plots/--plot_types/--mission_plots
# flags), so it's used instead for these.
test_dive_plot_coverage_inputs = (
    ("plot_CTD", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    (
        "plot_CTD_series",
        "sg686_Shilshole_28Oct25",
        "p6860005.nc",
        "--enable_ctd_series",
        None,
        False,
    ),
    (
        "plot_ctd_corrections",
        "sg686_Shilshole_28Oct25",
        "p6860005.nc",
        "",
        None,
        False,
    ),
    ("plot_CTW", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    ("plot_legato_data", "sg249_NANOOS_Apr24", "p2490010.nc", "", "249", False),
    ("plot_legato_pressure", "sg249_NANOOS_Apr24", "p2490010.nc", "", "249", False),
    ("plot_mag", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    (
        "plot_ocr504i",
        "sg171_EKAMSAT_Apr24_with_adcp",
        "p1710100.nc",
        "",
        "171",
        False,
    ),
    ("plot_optode", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    ("plot_pitch_roll", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    ("plot_diveplot", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    ("plot_PMAR", "sg178_Guam_Oct19", "p1780163.nc", "", None, True),
    ("plot_sbe43", "sg160_sbe43_scicon", "p1600001.nc", "", None, True),
    ("plot_TMICL", "sg171_EKAMSAT_Apr24_with_adcp", "p1710100.nc", "", "171", False),
    ("plot_tridente", "sg272_NANOOS_Feb26_base", "p2720002.nc", "", None, False),
    ("plot_TS", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    ("plot_vert_vel_new", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    ("plot_wetlabs", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    # dive 108: 5th from the end of this dir's 10 consecutive dives
    # (100-109) - satisfies wkb_dives_back's default of 5 with margin.
    (
        "plot_wkb_schedule",
        "sg171_EKAMSAT_Apr24_with_adcp",
        "p1710108.nc",
        "",
        "171",
        False,
    ),
    ("plot_science", "sg686_Shilshole_28Oct25", "p6860005.nc", "", None, False),
    ("plot_coda", "sg272_NANOOS_Feb26_base", "p2720002.nc", "", None, False),
    (
        "plot_compare_aux",
        "sg124_NISKINe_May18_compass_compare",
        "p1240200.nc",
        "",
        None,
        True,
    ),
    (
        "plot_compare_auxb",
        "sg249_Shilshole_08Apr21_auxB_compare",
        "p2490001.nc",
        "",
        None,
        True,
    ),
    (
        "plot_compare_cp",
        "sg124_NISKINe_May18_compass_compare",
        "p1240200.nc",
        "",
        None,
        True,
    ),
    (
        "plot_compare_ad2cp",
        "sg171_EKAMSAT_Apr24_with_adcp",
        "p1710100.nc",
        "",
        "171",
        False,
    ),
    (
        "plot_ocean_velocity",
        "sg171_EKAMSAT_Apr24_with_adcp",
        "p1710100.nc",
        "",
        "171",
        False,
    ),
    (
        "plot_ocean_velocity_3d",
        "sg171_EKAMSAT_Apr24_with_adcp",
        "p1710100.nc",
        "--ocean_velocity_3d",
        "171",
        False,
    ),
)


@pytest.mark.parametrize(
    "plot_name,data_dir,dive_nc,extra_args,instrument_id,use_base_pipeline",
    test_dive_plot_coverage_inputs,
)
def test_dive_plot_coverage(
    caplog, plot_name, data_dir, dive_nc, extra_args, instrument_id, use_base_pipeline
):
    """Every registered dive plot produces at least one .webp thumbnail without crashing."""
    if plot_name in ("plot_ocean_velocity", "plot_ocean_velocity_3d"):
        import Plotting

        if plot_name not in Plotting.dive_plot_funcs:
            pytest.skip(
                reason=f"{plot_name} needs the Plotting/local/ (adcp) site extension, not present"
            )

    if plot_name == "plot_compare_cp" and not pathlib.Path("Sensors/ad2cpMAT").exists():
        # ad2cpMAT (Sensors/ad2cpMAT.c) converts the raw cp*.x CP/ad2cp
        # upload files this plot's cp_time data comes from. It's gitignored
        # (built locally via "gcc -o ad2cpMAT ad2cpMAT.c -lm", never checked
        # in) and CI now compiles it as its own step
        # (.github/workflows/action.yml's "Compile ad2cpMAT"), so this skip
        # is a defensive fallback for a local dev environment that hasn't
        # built it yet, not an expected CI path.
        pytest.skip(reason="plot_compare_cp needs Sensors/ad2cpMAT, not present")

    data_dir_path = pathlib.Path("testdata").joinpath(data_dir)
    mission_dir = data_dir_path.joinpath("mission_dir")

    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        dive_nc,
        "--plot_types",
        "dives",
        "--dive_plots",
        plot_name,
    ]
    if instrument_id:
        cmd_line += ["--instrument_id", instrument_id]
    if extra_args:
        cmd_line += extra_args.split(" ")
    if use_base_pipeline:
        # --no-notify_vis isn't a registered option for BasePlot.main (only
        # Base/Reprocess/MakeKML/BaseCtrlFiles/CommLog/GliderEarlyGPS) - it
        # would fail argparse with "unrecognized arguments" there, so this
        # must stay conditional on which entry point is actually used.
        cmd_line += ["--no-notify_vis"]

    testutils.run_mission(
        data_dir_path,
        mission_dir,
        Base.main if use_base_pipeline else BasePlot.main,
        cmd_line,
        caplog,
        allowed_msgs,
    )
    webp_files = list(mission_dir.joinpath("plots").glob("*.webp"))
    assert webp_files, f"{plot_name} produced no .webp thumbnail"


# (plot_name, data_dir, dive_nc_filename)
#
# All use Base.main, not BasePlot.main - unlike the dive-plot sweep above,
# every one of these needs Base.main's fuller per-dive DB population
# (update_db stage) to have anything to plot at mission level, even for
# dirs (sg686_Shilshole_28Oct25) where BasePlot.main alone is sufficient
# for dive-level plots.
#
# sg686_Shilshole_28Oct25's testdata dir holds only a pre-built .nc (no
# raw upload files), so Base.main logs "No dives to process" and never
# runs its per-dive processing stage there. That's fine for plots that can
# draw from data already present (parquet/existing .nc), but
# mission_disk/energy/map/profiles specifically need output only real
# per-dive processing produces (disk usage, energy accounting, GPS fixes,
# profile data) - confirmed empirically, these silently produced zero
# .webp output even via Base.main. sg686_Shilshole_25Oct25_multidive (a
# curated fixture built this round from the real source mission at
# ~/work/seagliders/sg686_Shilshole_25Oct25 - real raw upload files for
# dives 1-4 plus a real comm.log) drives genuine per-dive processing and
# is used for these instead. It also carries a committed sections.yml
# (needed by mission_profiles - see MissionProfiles.py's early-return when
# mission_dir/sections.yml is absent) and --make_mission_profile is passed
# unconditionally below since MissionProfiles.mission_profiles() is a
# harmless no-op without a sections.yml present, so it doesn't affect the
# other fixtures.
#
# mission_commlog is deliberately excluded: its "calls" DB table
# (BaseDB.addSession) is only ever populated by the live glider-login code
# path (GliderEarlyGPS.py/CommLog.addSession), never by batch
# reprocessing of a static comm.log via Base.main - confirmed by tracing
# every addSession call site. No fixture, however constructed, can make
# this plot produce output through this pipeline; it would need a
# dedicated test that seeds the calls table directly. Left as a follow-on.
test_mission_plot_coverage_inputs = (
    ("mission_callstats", "sg686_Shilshole_28Oct25", "p6860005.nc"),
    ("mission_depthangle", "sg686_Shilshole_28Oct25", "p6860005.nc"),
    ("mission_disk", "sg686_Shilshole_25Oct25_multidive", "p6860001.nc"),
    ("mission_pmar_disk", "sg178_Guam_Oct19", "p1780163.nc"),
    ("mission_energy", "sg686_Shilshole_25Oct25_multidive", "p6860001.nc"),
    ("mission_int_sensors", "sg686_Shilshole_28Oct25", "p6860005.nc"),
    ("mission_map", "sg686_Shilshole_25Oct25_multidive", "p6860001.nc"),
    ("mission_motors", "sg686_Shilshole_28Oct25", "p6860005.nc"),
    ("mission_pmar_stats", "sg178_Guam_Oct19", "p1780163.nc"),
    ("mission_profiles", "sg686_Shilshole_25Oct25_multidive", "p6860001.nc"),
    ("mission_volume", "sg686_Shilshole_28Oct25", "p6860005.nc"),
)


@pytest.mark.parametrize(
    "plot_name,data_dir,dive_nc", test_mission_plot_coverage_inputs
)
def test_mission_plot_coverage(caplog, plot_name, data_dir, dive_nc):
    """Every registered mission plot produces at least one .webp thumbnail without crashing."""
    data_dir_path = pathlib.Path("testdata").joinpath(data_dir)
    mission_dir = data_dir_path.joinpath("mission_dir")

    allowed_msgs = [""]
    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        dive_nc,
        "--plot_types",
        "mission",
        "--mission_plots",
        plot_name,
        "--make_mission_profile",
        "--no-notify_vis",
    ]

    testutils.run_mission(
        data_dir_path,
        mission_dir,
        Base.main,
        cmd_line,
        caplog,
        allowed_msgs,
    )
    webp_files = list(mission_dir.joinpath("plots").glob("*.webp"))
    assert webp_files, f"{plot_name} produced no .webp thumbnail"
