#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2026  University of Washington.
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

"""Utility functions for plotting routines"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import copy
import os
import stat
import time
import typing

import gsw
import netCDF4
import numpy as np
import scipy
from numpy.typing import NDArray

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import NetCDFUtils
import Utils
from BaseLog import log_error, log_warning


#
# Utility Routines
#
def get_mission_dive(dive_nc_file, dives_str=None):
    """Gets common information for all plot headers

    Input:
         dive_nc_file - netcdf file object

    Returns:
         String containing the mission title
    """
    glider_id = 0
    dive_num = 0
    mission_title = ""
    if hasattr(dive_nc_file, "glider"):
        glider_id = dive_nc_file.glider
    elif "log_ID" in dive_nc_file.variables:
        glider_id = dive_nc_file.variables["log_ID"].getValue()
    if hasattr(dive_nc_file, "dive_number"):
        dive_num = dive_nc_file.dive_number
    elif "log_DIVE" in dive_nc_file.variables:
        dive_num = dive_nc_file.variables["log_DIVE"].getValue()
    if hasattr(dive_nc_file, "project"):
        mission_title = dive_nc_file.project
    elif "sg_cal_mission_title" in dive_nc_file.variables:
        mission_title = (
            dive_nc_file.variables["sg_cal_mission_title"][:].tobytes().decode("utf-8")
        )

    if hasattr(dive_nc_file, "start_time"):
        start_time = time.strftime(
            "%d-%b-%Y %H:%M:%S ", time.gmtime(dive_nc_file.start_time)
        )
    else:
        start_time = "(No start time found)"

    if dives_str:
        dive_str = dives_str
    else:
        dive_str = f"Dive {dive_num:d}"

    return f"SG{glider_id:03d} {mission_title} {dive_str} Started {start_time}"


def get_mission_str(dive_nc_file):
    """Gets common information for all plot headers"""
    log_id = None
    mission_title = ""
    if "log_ID" in dive_nc_file.variables:
        log_id = int(dive_nc_file.variables["log_ID"].getValue())
    if "sg_cal_mission_title" in dive_nc_file.variables:
        mission_title = (
            dive_nc_file.variables["sg_cal_mission_title"][:].tobytes().decode("utf-8")
        )
    return f"SG{'%03d' % (log_id if log_id else 0,)} {mission_title}"


def get_mission_str_comm_log(comm_log, mission_title):
    """Gets common information for all plot headers"""
    log_id = None
    for s in comm_log.sessions:
        if s.sg_id is not None:
            log_id = s.sg_id
            break
    return f"SG{'%03d' % log_id if log_id else 0} {mission_title}"


def setup_plot_directory(base_opts: BaseOpts.BaseOptions) -> int:
    """Ensures plot_directory is set in base_opts and creates it if needed

    Returns:
        0 for success
        1 for failure

    """
    if not base_opts.plot_directory:
        base_opts.plot_directory = os.path.join(base_opts.mission_dir, "plots")

    if not os.path.exists(base_opts.plot_directory):
        try:
            os.mkdir(base_opts.plot_directory)
            # Ensure that MoveData can move it as pilot if not run as the glider account
            os.chmod(
                base_opts.plot_directory,
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR
                | stat.S_IRGRP
                | stat.S_IXGRP
                | stat.S_IWGRP
                | stat.S_IROTH
                | stat.S_IXOTH,
            )
        except Exception:
            log_error(f"Could not create {base_opts.plot_directory}", "exc")
            return 1
    return 0


def extract_gc_moves(ncf: scipy.io._netcdf.netcdf_file) -> tuple:
    """
    Motor positions returned contain positions at all times from the GC table, plus locations
    interpolated from the those positions onto the engineering file time grid.  This is a good
    for plotly based plotting code, but does not accurately where motors may have been between
    GC reported positions.
    """
    gc_moves = []

    # Figure it out from the actual moves
    start_time = ncf.start_time
    gc_st_secs = ncf.variables["gc_st_secs"][:]
    gc_end_secs = ncf.variables["gc_end_secs"][:]
    gc_vbd_secs = ncf.variables["gc_vbd_secs"][:]
    gc_pitch_secs = ncf.variables["gc_pitch_secs"][:]
    gc_roll_secs = ncf.variables["gc_roll_secs"][:]
    if "gc_gcphase" in ncf.variables:
        gc_phase = ncf.variables["gc_gcphase"][:]
    elif "gc_flags" in ncf.variables:
        gc_phase = ncf.variables["gc_flags"][:]
    else:
        log_error(
            "Could not find gc_gcphase or gc_flags in netcdf file - skipping gcphase/flags in plots"
        )
        return ()

    gc_roll_pos = np.concatenate(
        (ncf.variables["gc_roll_ad_start"][:], ncf.variables["gc_roll_ad"][:])
    )

    gc_pitch_pos = np.concatenate(
        (ncf.variables["gc_pitch_ad_start"][:], ncf.variables["gc_pitch_ad"][:])
    )

    try:
        vbd_lp_ignore = ncf.variables["log_VBD_LP_IGNORE"].getValue()
    except KeyError:
        vbd_lp_ignore = 0  # both available

    gc_vbd_pot1_ad = np.concatenate(
        (
            np.array(ncf.variables["gc_vbd_pot1_ad_start"][:]),
            np.array(ncf.variables["gc_vbd_pot1_ad"][:]),
        )
    )
    gc_vbd_pot2_ad = np.concatenate(
        (
            np.array(ncf.variables["gc_vbd_pot2_ad_start"][:]),
            np.array(ncf.variables["gc_vbd_pot2_ad"][:]),
        )
    )

    if vbd_lp_ignore == 0:
        gc_start_vbd_ad_v = (
            np.array(ncf.variables["gc_vbd_pot1_ad_start"][:])
            + np.array(ncf.variables["gc_vbd_pot2_ad_start"][:])
        ) / 2
        gc_vbd_ad = (
            np.array(ncf.variables["gc_vbd_pot1_ad"][:])
            + np.array(ncf.variables["gc_vbd_pot2_ad"][:])
        ) / 2
    elif vbd_lp_ignore == 1:  # ignore pot1?
        gc_start_vbd_ad_v = np.array(ncf.variables["gc_vbd_pot2_ad_start"][:])
        gc_vbd_ad = np.array(ncf.variables["gc_vbd_pot2_ad"][:])
    elif vbd_lp_ignore == 2:  # ignore pot2?
        gc_start_vbd_ad_v = np.array(ncf.variables["gc_vbd_pot1_ad_start"][:])
        gc_vbd_ad = np.array(ncf.variables["gc_vbd_pot1_ad"][:])
    else:
        log_error("Unknown value for $VBD_LP_IGNORE: {vbd_lp_ignore}")
    gc_vbd_pos = np.concatenate((gc_start_vbd_ad_v, gc_vbd_ad))

    gc_time = np.concatenate(
        (
            (gc_st_secs - start_time),
            (gc_end_secs - start_time),
        )
    )

    sort_i = np.argsort(gc_time)
    gc_time = gc_time[sort_i]
    gc_roll_pos_ad = gc_roll_pos[sort_i]
    gc_pitch_pos_ad = gc_pitch_pos[sort_i]
    gc_vbd_pos_ad = gc_vbd_pos[sort_i]
    gc_vbd_pot1_ad = gc_vbd_pot1_ad[sort_i]
    gc_vbd_pot2_ad = gc_vbd_pot2_ad[sort_i]
    gc_roll_time = np.copy(gc_time)
    gc_pitch_time = np.copy(gc_time)
    gc_vbd_time = np.copy(gc_time)

    if "gc_vbd_start_time" in ncf.variables:
        motor_times = {}
        motors = {
            "roll": gc_roll_time,
            "pitch": gc_pitch_time,
            "vbd": gc_vbd_time,
        }
        for motor, motor_code in (("vbd", 1), ("pitch", 2), ("roll", 4)):
            for start_stop in ("start", "end"):
                col_name = f"gc_{motor}_{start_stop}_time"
                motor_times[col_name] = ncf.variables[col_name][:]
                good_pts = np.logical_not(np.isnan(motor_times[col_name]))
                motor_times[col_name][good_pts] -= ncf.start_time
            for ii in np.nonzero(good_pts)[0]:
                gc_moves.append(
                    gc_move(
                        motor_times[f"gc_{motor}_start_time"][ii],
                        motor_times[f"gc_{motor}_end_time"][ii],
                        motor_code,
                    )
                )
            for ii in range(len(gc_st_secs)):
                if motor_times[f"gc_{motor}_start_time"][ii] > 0.0:
                    motors[motor][ii * 2] = motor_times[f"gc_{motor}_start_time"][ii]
                    motors[motor][(ii * 2) + 1] = motor_times[f"gc_{motor}_end_time"][
                        ii
                    ]

    else:
        for ii in range(len(gc_st_secs)):
            g_autonomous_turning = gc_phase[ii] & 1024
            if g_autonomous_turning:
                motors = [
                    ("roll", gc_roll_secs[ii]),
                    ("pitch", gc_pitch_secs[ii]),
                    ("vbd", gc_vbd_secs[ii]),
                ]
            else:
                motors = [
                    ("pitch", gc_pitch_secs[ii]),
                    ("vbd", gc_vbd_secs[ii]),
                    ("roll", gc_roll_secs[ii]),
                ]
            st = gc_st_secs[ii] - ncf.start_time
            for m in motors:
                if m[1] > 0.0:
                    if m[0] == "vbd":
                        gc_moves.append(gc_move(st, st + m[1], 1))
                        gc_vbd_time[ii * 2] = st
                        gc_vbd_time[(ii * 2) + 1] = st + m[1]
                    elif m[0] == "pitch":
                        gc_moves.append(gc_move(st, st + m[1], 2))
                        gc_pitch_time[ii * 2] = st
                        gc_pitch_time[(ii * 2) + 1] = st + m[1]
                    elif m[0] == "roll":
                        gc_moves.append(gc_move(st, st + m[1], 4))
                        gc_roll_time[ii * 2] = st
                        gc_roll_time[(ii * 2) + 1] = st + m[1]

                    st += m[1]

    # GBS 2025/04/03 - very corner case for bug with gc_state lines being garbage in the
    # GC table
    try:
        gc_state_state = ncf.variables["gc_state_state"][:]
        gc_state_time = ncf.variables["gc_state_secs"][:]
        # 1 is the code for 'end dive'
        gc_dive_end = gc_state_time[np.argwhere(gc_state_state == 1)[0]][0] - start_time
    except KeyError as e:
        log_warning(f"Could not variable find {e}")
        gc_state_state = gc_state_time = None
        gc_dive_end = gc_time[-1]

    # Add in turn controller into the mix
    if "tc_start_time" in ncf.variables:
        try:
            gc_roll_pos_ad = np.hstack(
                (gc_roll_pos_ad, ncf.variables["tc_rollAD"], ncf.variables["tc_endAD"])
            )
            gc_roll_time = np.hstack(
                (
                    gc_roll_time,
                    ncf.variables["tc_start_time"][:] - start_time,
                    ncf.variables["tc_end_time"][:] - start_time,
                )
            )

            roll_sort_i = np.argsort(gc_roll_time)
            gc_roll_time = gc_roll_time[roll_sort_i]
            gc_roll_pos_ad = gc_roll_pos_ad[roll_sort_i]

            for ii in range(ncf.variables["tc_start_time"].size):
                gc_moves.append(
                    gc_move(
                        ncf.variables["tc_start_time"][ii] - start_time,
                        ncf.variables["tc_end_time"][ii] - start_time,
                        4,
                    )
                )

        except Exception:
            log_error("Failed to add TC data to roll data", "exc")

    # Convert Roll to engineering units
    roll_ctr = np.zeros(len(gc_roll_pos_ad))
    roll_ctr[np.argwhere(gc_roll_time <= gc_dive_end)] = ncf.variables[
        "log_C_ROLL_DIVE"
    ].getValue()
    roll_ctr[np.argwhere(gc_roll_time > gc_dive_end)] = ncf.variables[
        "log_C_ROLL_CLIMB"
    ].getValue()
    gc_roll_pos = (gc_roll_pos_ad - roll_ctr) * ncf.variables["log_ROLL_CNV"].getValue()

    # Convert pitch to eng units
    gc_pitch_pos = (
        gc_pitch_pos_ad - ncf.variables["log_C_PITCH"].getValue()
    ) * ncf.variables["log_PITCH_CNV"].getValue()

    # Convert VBD to eng units
    gc_vbd_pos = (
        gc_vbd_pos_ad - ncf.variables["log_C_VBD"].getValue()
    ) * ncf.variables["log_VBD_CNV"].getValue()

    eng_time = ncf.variables["time"][:] - ncf.start_time

    def build_dense_motor_vector(motor_pos, motor_time, eng_time):
        """
        Creates dense motor position and time vectors that are all gc reported
        positions, plus interpolated values for the engieering file times
        """

        f = Utils.CopyInterp(
            motor_time, motor_pos, fill_value=(motor_pos[0], motor_pos[-1])
        )

        motor_pos = np.concatenate((motor_pos, f(eng_time)))
        motor_time = np.concatenate((motor_time, eng_time))
        sort_i = np.argsort(motor_time)
        motor_pos = motor_pos[sort_i]
        motor_time = motor_time[sort_i]
        return (motor_pos, motor_time)

    roll_pos, roll_time = build_dense_motor_vector(gc_roll_pos, gc_roll_time, eng_time)
    pitch_pos, pitch_time = build_dense_motor_vector(
        gc_pitch_pos, gc_pitch_time, eng_time
    )
    vbd_pos, vbd_time = build_dense_motor_vector(gc_vbd_pos, gc_vbd_time, eng_time)

    roll_pos_ad, _ = build_dense_motor_vector(gc_roll_pos_ad, gc_roll_time, eng_time)
    pitch_pos_ad, _ = build_dense_motor_vector(gc_pitch_pos_ad, gc_pitch_time, eng_time)
    vbd_pos_ad, _ = build_dense_motor_vector(gc_vbd_pos_ad, gc_vbd_time, eng_time)
    vbd_pos_pot1_ad, _ = build_dense_motor_vector(gc_vbd_pot1_ad, gc_vbd_time, eng_time)
    vbd_pos_pot2_ad, _ = build_dense_motor_vector(gc_vbd_pot2_ad, gc_vbd_time, eng_time)

    return (
        gc_moves,
        roll_time,
        roll_pos,
        pitch_time,
        pitch_pos,
        vbd_time,
        vbd_pos,
        roll_pos_ad,
        pitch_pos_ad,
        vbd_pos_ad,
        vbd_pos_pot1_ad,
        vbd_pos_pot2_ad,
    )


def add_gc_moves(
    fig, gc_moves, data, xaxis="x1", yaxis="y1", convert_to_mins=False, time_range=None
):
    """Add the gc move regions to a figure"""
    show_label = collections.defaultdict(lambda: True)
    max_time = min_time = None
    if time_range is not None:
        max_time = np.nanmax(time_range)
        min_time = np.nanmin(time_range)

    for gc in gc_moves:
        if max_time is not None and not (
            (min_time <= gc.start_time <= max_time)
            or (min_time <= gc.end_time <= max_time)
        ):
            continue

        st = gc.start_time / 60.0 if convert_to_mins else gc.start_time
        et = gc.end_time / 60.0 if convert_to_mins else gc.end_time

        fig.add_trace(
            {
                "type": "scatter",
                "x": (st, st, et, et),
                "y": (
                    np.nanmin(data),
                    np.nanmax(data),
                    np.nanmax(data),
                    np.nanmin(data),
                ),
                "xaxis": xaxis,
                "yaxis": yaxis,
                "fill": "toself",
                "fillcolor": gc_move_colormap[gc.move_type].color,
                "line": {
                    "dash": "solid",
                    # proxy for line opacity - lines are needed for short moves (like roll)
                    "width": 0.25,
                    "color": gc_move_colormap[gc.move_type].color,
                },
                "mode": "lines",
                "legendgroup": f"{gc_move_colormap[gc.move_type].name}_group",
                "name": f"GC {gc_move_colormap[gc.move_type].name}",
                "showlegend": show_label[gc_move_colormap[gc.move_type].name],
                "text": f"GC {gc_move_colormap[gc.move_type].name}, Start {gc.start_time / 60.0:.3f} mins, End {gc.end_time / 60.0:.3f} mins<br>Duration {gc.end_time-gc.start_time:.2f} secs",
                "hoverinfo": "text",
            }
        )
        show_label[gc_move_colormap[gc.move_type].name] = False


gc_move_color = collections.namedtuple("gc_movecolor", ("color", "name"))
gc_move_colormap = {
    1: gc_move_color("rgba(255, 0, 255, 0.25)", "VBD"),  # Magenta
    2: gc_move_color("rgba(0, 128, 0, 0.25)", "Pitch"),  # Green
    3: gc_move_color("rgba(0, 0, 255, 0.25)", "VBD/Pitch"),  # Blue
    4: gc_move_color("rgba(218, 165, 32, 0.40)", "Roll"),  # Goldenrod
    5: gc_move_color("rgba(255, 0, 0, 0.25)", "VBD/Roll"),  # Red
    6: gc_move_color("rgba(0, 128, 0, 0.25)", "Pitch/Roll"),  # Green
    7: gc_move_color("rgba(0, 0, 0, 0.25)", "VBD/Pitch/Roll"),  # Black
}

motor_move = collections.namedtuple("motor_move", ["name", "units"])

gc_move = collections.namedtuple("gc_move", ["start_time", "end_time", "move_type"])
gc_move_depth = collections.namedtuple(
    "gc_move_depth", ["start_depth", "end_depth", "move_type", "duration"]
)


def collect_timeouts(dive_nc_file, instr_cls):
    timeouts = 0
    timeouts_times = []

    for profile in ("", "_a", "_b", "_c", "_d", "_truck"):
        timeouts_str = f"{instr_cls}_timeouts{profile}"
        if timeouts_str in dive_nc_file.variables:
            timeouts += dive_nc_file.variables[timeouts_str].getValue()
        timeouts_times_str = f"{instr_cls}_timeouts_times{profile}"
        if timeouts_times_str in dive_nc_file.variables:
            timeouts_times += [
                float(x)
                for x in dive_nc_file.variables[timeouts_times_str][:]
                .tobytes()
                .decode()
                .rstrip()
                .rstrip(",")
                .split(",")
            ]
    return (timeouts, np.array(timeouts_times))


run_t = collections.namedtuple("run_t", ("run_value", "run_length", "run_index"))


def find_identical_runs(arr):
    """Finds runs of identical values in an array
    Input:
    numpy array

    Return:
    List of tuples of value, length and index
    """
    if not isinstance(arr, np.ndarray):
        return []
    if arr.ndim != 1 or not arr.size:
        return []

    runs = []
    current_run_value = None
    current_run_length = None
    current_run_start = None

    for ii, val in enumerate(arr):
        if current_run_value is None:
            current_run_value = val
            current_run_length = 1
            current_run_start = ii
            continue

        if current_run_value == val:
            current_run_length += 1
        else:
            runs.append(run_t(current_run_value, current_run_length, current_run_start))
            current_run_value = val
            current_run_length = 1
            current_run_start = ii

    # Add the last run
    runs.append(run_t(current_run_value, current_run_length, current_run_start))
    return runs


def coalesce_short_runs(run_list, min_len):
    """Given a list of run tuples, coalesce short runs into the
    immediate run
    """

    tmp_run_list = copy.deepcopy(run_list)

    new_run = []

    while tmp_run_list:
        current_run_value, current_run_length, current_run_index = tmp_run_list.pop(0)
        while tmp_run_list:
            if (
                tmp_run_list[0].run_length > min_len
                and tmp_run_list[0].run_value != current_run_value
            ):
                break
            _, tmp_len, _ = tmp_run_list.pop(0)
            current_run_length += tmp_len
        new_run.append(run_t(current_run_value, current_run_length, current_run_index))
    return new_run


def add_sample_range_overlay(time_var, max_depth_i, start_time, fig, f_depth):
    """Add sample grid overlays and sample stats traces to a plot"""

    if time_var is None:
        log_warning("time_var is none - skipping range overlay")
        return

    time_dive = time_var[:max_depth_i]
    time_climb = time_var[max_depth_i:]

    min_x = np.iinfo(np.int32).max
    max_x = np.iinfo(np.int32).min
    bin_width = None
    for ttime, name, color in (
        (
            time_dive,
            "Dive samples",
            "steelblue",
        ),
        (time_climb, "Climb samples", "skyblue"),
    ):
        if ttime.size < 2:
            continue

        # Generate the samples/meter trace
        depth = f_depth(ttime)
        max_depth = np.nanmax(depth)
        bin_width = 5.0
        bin_edges = np.arange(
            -bin_width / 2.0,
            max_depth + bin_width / 2.0 + 0.01,
            bin_width,
        )
        bin_centers = np.arange(0.0, max_depth + 0.01, bin_width)
        bin_centers = np.concatenate((bin_centers, bin_centers[:-1][::-1]))

        # Do this to ensure everything is caught in the binned statistic
        bin_edges[0] = -20.0
        bin_edges[-1] = max_depth + 50.0
        _, n_obs, *_ = NetCDFUtils.bindata(depth, ttime, bin_edges)
        meta = n_obs / bin_width
        min_x = np.nanmin(np.hstack((min_x, n_obs)))
        max_x = np.nanmax(np.hstack((max_x, n_obs)))
        fig.add_trace(
            {
                "type": "scatter",
                "x": n_obs,
                "y": bin_centers,
                "meta": meta,
                "xaxis": "x10",
                "line": {
                    "dash": "solid",
                    # proxy for line opacity
                    # "width": 1,
                    "color": color,
                },
                "mode": "lines",
                "name": f"{name} stats",
                "visible": "legendonly",
                "hovertemplate": f"{name} {bin_width}m grid<br>%{{x:d}} samples<br>%{{y:.1f}} meters<br>%{{meta:.2f}} samples/m<extra></extra>",
                "hoverinfo": "text",
                "zorder": -9,
            }
        )

    if bin_width is not None:
        fig.update_layout(
            {
                # Not visible - no good way to control the bottom margin so there is room for this
                "xaxis10": {
                    "title": f"Samples per {bin_width}m",
                    "showgrid": False,
                    "overlaying": "x1",
                    "side": "bottom",
                    "anchor": "free",
                    "position": 0.05,
                    "visible": False,
                    "range": [min_x, max_x],
                }
            }
        )

    return

    # This method of detecting the sampling grid is too error prone to be of use
    # Preserving it here in case the alternate strategy of processing the science and
    # scicon files proves too brittle

    # Note - this bucketing assumes
    # 1) Sample intervals are no greater then 360 seconds
    # 2) Typical sampling on even seconds
    # if time_var.size < 4:
    #     return

    # time_var = time_var[1:]
    # time_dive = time_var[:max_depth_i]
    # time_climb = time_var[max_depth_i:]
    # time_diff_dive = np.digitize(np.diff(time_dive), np.arange(360) + 0.5)
    # time_diff_climb = np.digitize(np.diff(time_climb), np.arange(360) + 0.5)

    # # color_map = ("LightGrey", "DarkGrey")
    # color_map = ("lightgrey", "grey", "darkgrey")

    # for ttime, time_diff, name in (
    #     (time_dive, time_diff_dive, "Dive sample grid"),
    #     (time_climb, time_diff_climb, "Climb sample grid"),
    # ):
    #     if time_dive.size < 2:
    #         continue

    #     # Find and plot the sample grid
    #     tmp_runs = find_identical_runs(time_diff)

    #     print("Full runs")
    #     for run in tmp_runs:
    #         print(run)
    #     runs = tmp_runs
    #     print("Collapsed runs")
    #     runs = coalesce_short_runs(tmp_runs, 1)
    #     for run in runs:
    #         print(run)
    #     show_label = collections.defaultdict(lambda: True)

    #     for ii, (run_value, run_length, run_index) in enumerate(
    #         runs[:: 1 if "Dive" in name else -1]
    #     ):
    #         color = color_map[ii % len(color_map)]
    #         start_range_time = ttime[run_index]
    #         start_range_depth = f_depth(start_range_time)
    #         end_range_time = ttime[run_index + run_length]
    #         end_range_depth = f_depth(end_range_time)

    #         # Sample calcs for the grid
    #         samples_tot = run_length
    #         samples_per_meter = float(samples_tot) / np.abs(
    #             start_range_depth - end_range_depth
    #         )

    #         tag = f"{run_value} secs"
    #         fig.add_trace(
    #             {
    #                 "type": "scatter",
    #                 "x": [0.0, 0.0, 1.0, 1.0],
    #                 "y": [
    #                     start_range_depth,
    #                     end_range_depth,
    #                     end_range_depth,
    #                     start_range_depth,
    #                 ],
    #                 "xaxis": "x11",
    #                 "fill": "toself",
    #                 "fillcolor": color,
    #                 "opacity": 0.50,
    #                 "line": {
    #                     "dash": "solid",
    #                     # proxy for line opacity
    #                     "width": 0.25,
    #                     "color": color,
    #                 },
    #                 "mode": "lines",
    #                 "legendgroup": f"{name}_group",
    #                 "name": name,
    #                 "showlegend": show_label[name],
    #                 "visible": "legendonly",
    #                 "text": f"{name}:{tag}<br>Start:{(start_range_time - start_time)/6.0:.2f} mins, End:Start:{(end_range_time - start_time)/6.0:.2f} mins<br>{samples_tot} samples, {samples_per_meter:.2f} samples per meter:",
    #                 "hoverinfo": "text",
    #                 "zorder": -10,
    #             }
    #         )
    #         show_label[name] = False

    # fig.update_layout(
    #     {
    #         "xaxis11": {
    #             "title": "Samples grid",
    #             "showgrid": False,
    #             "overlaying": "x1",
    #             "side": "bottom",
    #             "anchor": "free",
    #             "position": 0.05,
    #             "visible": False,
    #             "range": [0.0, 1.0],
    #         }
    #     }
    # )


def add_timeout_overlays(
    timeout,
    timeouts_times,
    fig,
    f_depth,
    instrument_time,
    max_depth_sample_index,
    max_depth,
    start_time,
    dive_color,
    climb_color,
):
    """Add timeout overlays to a plot"""
    timeouts_times_dive = timeouts_times[
        timeouts_times < instrument_time[max_depth_sample_index]
    ]
    timeouts_depth_dive = f_depth(timeouts_times_dive)
    timeouts_times_climb = timeouts_times[
        timeouts_times >= instrument_time[max_depth_sample_index]
    ]
    timeouts_depth_climb = f_depth(timeouts_times_climb)

    show_label = collections.defaultdict(lambda: True)
    for timeouts_times, timeouts_depth, name, tag, color in (
        (
            timeouts_times_dive,
            timeouts_depth_dive,
            "timeouts_dive",
            "Dive timeout",
            dive_color,
        ),
        (
            timeouts_times_climb,
            timeouts_depth_climb,
            "timeouts_climb",
            "Climb timeout",
            climb_color,
        ),
    ):
        if timeouts_depth is None:
            continue
        for t_d, t_t in zip(timeouts_depth, timeouts_times, strict=True):
            fig.add_trace(
                {
                    "type": "scatter",
                    "x": [0.0, 0.0, 1.0, 1.0],
                    "y": [
                        t_d,
                        t_d + (0.001 * max_depth),
                        t_d + (0.001 * max_depth),
                        t_d,
                    ],
                    "xaxis": "x12",
                    "fill": "toself",
                    "fillcolor": color,
                    "line": {
                        "dash": "solid",
                        "width": 0.25,
                        "color": color,
                    },
                    "mode": "lines",
                    "legendgroup": f"{name}_group",
                    "name": f"{tag}s",
                    "showlegend": show_label[name],
                    "visible": "legendonly",
                    "text": f"{tag} {(t_t - start_time)/60.0:.2f} mins ({t_t:.3f} epoch secs)",
                    "hoverinfo": "text",
                }
            )
            show_label[name] = False
    fig.update_layout(
        {
            "xaxis12": {
                "title": "Samples grid",
                "showgrid": False,
                "overlaying": "x1",
                "side": "bottom",
                "anchor": "free",
                "position": 0.05,
                "visible": False,
                "range": [0.0, 1.0],
            }
        }
    )


def interp_missing_depth(sg_time, sg_depth):
    sg_depth_good_b = np.logical_not(np.isnan(sg_depth))
    if len(np.squeeze(np.nonzero(sg_depth_good_b))) < 2:
        log_warning("No non-nan depth points - skipping interpolation")
    else:
        sg_depth = Utils.interp1d(
            sg_time[sg_depth_good_b],
            sg_depth[sg_depth_good_b],
            sg_time,
            kind="linear",
        )
    return sg_depth


def Nsquared(ds: netCDF4.Dataset) -> NDArray[np.float64] | None:
    if not all(
        ii in ds.variables
        for ii in (
            "conservative_temperature",
            "absolute_salinity",
            "ctd_depth",
            "avg_latitude",
        )
    ):
        log_warning("Not all needed vars available for buoy freq")
        return None
    try:
        CT = ds.variables["conservative_temperature"][:]
        SA = ds.variables["absolute_salinity"][:]
        ctd_depth = ds.variables["ctd_depth"][:]
        latitude = ds.variables["avg_latitude"][:]

        good_pts_b = np.logical_and.reduce(
            (
                np.logical_not(np.isnan(CT)),
                np.logical_not(np.isnan(SA)),
                np.logical_not(np.isnan(ctd_depth)),
            )
        )

        # Notes from the API indicate that the axis argument for gsw.Nsquared is important to
        # know which way the density gradiant descends - probably doesn't matter for the 1-d case,
        # but to be sure - split the dive up and calc for the single cast
        max_depth_i = np.argmax(ctd_depth[good_pts_b])
        bin_width = 5.0  # Make a parameter

        max_depth = np.floor(np.nanmax(ctd_depth[good_pts_b]))
        bin_centers = np.arange(0.0, max_depth + 0.01, bin_width)
        # This is actually bin edges, so one more point then actual bins
        bin_edges = np.arange(
            -bin_width / 2.0,
            max_depth + bin_width / 2.0 + 0.01,
            bin_width,
        )
        # Do this to ensure everything is caught in the binned statistic
        bin_edges[0] = -20.0
        bin_edges[-1] = max_depth + 50.0

        SA_down = SA[good_pts_b][:max_depth_i]
        CT_down = CT[good_pts_b][:max_depth_i]
        ctd_depth_down = ctd_depth[good_pts_b][:max_depth_i]

        # N2_down = gsw.Nsquared(SA_down, CT_down, ctd_depth_down)[0]

        SA_up = SA[good_pts_b][max_depth_i:]
        CT_up = CT[good_pts_b][max_depth_i:]
        ctd_depth_up = ctd_depth[good_pts_b][max_depth_i:]

        # direction = -1

        # N2_up = gsw.Nsquared(
        #    SA_up[::direction], CT_up[::direction], ctd_depth_up[::direction]
        # )[0][::direction]

        SA_down_binned, _ = NetCDFUtils.bindata(ctd_depth_down, SA_down, bin_edges)
        CT_down_binned, _ = NetCDFUtils.bindata(ctd_depth_down, CT_down, bin_edges)
        SA_up_binned, _ = NetCDFUtils.bindata(ctd_depth_up, SA_up, bin_edges)
        CT_up_binned, _ = NetCDFUtils.bindata(ctd_depth_up, CT_up, bin_edges)

        N2_down_binned, N2_down_binned_p = gsw.Nsquared(
            SA_down_binned,
            CT_down_binned,
            gsw.p_from_z(-bin_centers, np.ones(np.shape(bin_centers)[0]) * latitude),
        )

        N2_up_binned, N2_up_binned_p = gsw.Nsquared(
            SA_up_binned,
            CT_up_binned,
            gsw.p_from_z(-bin_centers, np.ones(np.shape(bin_centers)[0]) * latitude),
        )

        # N2 = np.hstack((N2_down, N2_up))

        # Get back on original grid

        # Needed for interpolator
        N2_down_binned[np.isnan(N2_down_binned)] = 0.0
        N2_up_binned[np.isnan(N2_up_binned)] = 0.0

        f_down = scipy.interpolate.PchipInterpolator(
            -gsw.z_from_p(
                N2_down_binned_p, np.ones(np.shape(N2_down_binned_p)[0]) * latitude
            ),
            N2_down_binned,
        )
        f_up = scipy.interpolate.PchipInterpolator(
            -gsw.z_from_p(
                N2_up_binned_p, np.ones(np.shape(N2_up_binned_p)[0]) * latitude
            ),
            N2_up_binned,
        )

        max_depth_all_i = np.argmax(ctd_depth)
        N2_binned = np.hstack(
            (f_down(ctd_depth[:max_depth_all_i]), f_up(ctd_depth[max_depth_all_i:]))
        )

        return N2_binned
    except Exception:
        log_error("Failed to compute Nsquared", "exc")
        return None
