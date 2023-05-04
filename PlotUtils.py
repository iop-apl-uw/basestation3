#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023  University of Washington.
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

""" Utility functions for plotting routines
"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import os
import stat
import time
import typing

import numpy as np
import scipy

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

from BaseLog import log_error, log_warning


#
# Utility Routines
#
def get_mission_dive(dive_nc_file):
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
        glider_id = getattr(dive_nc_file, "glider")
    elif "log_ID" in dive_nc_file.variables:
        glider_id = dive_nc_file.variables["log_ID"].getValue()
    if hasattr(dive_nc_file, "dive_number"):
        dive_num = getattr(dive_nc_file, "dive_number")
    elif "log_DIVE" in dive_nc_file.variables:
        dive_num = dive_nc_file.variables["log_DIVE"].getValue()
    if hasattr(dive_nc_file, "project"):
        mission_title = getattr(dive_nc_file, "project").decode("utf-8")
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

    return f"SG{glider_id:03d} {mission_title} Dive {dive_num:d} Started {start_time}"


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
        except:
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
        return None

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
    gc_roll_pos = gc_roll_pos[sort_i]
    gc_pitch_pos = gc_pitch_pos[sort_i]
    gc_vbd_pos = gc_vbd_pos[sort_i]
    gc_roll_time = np.copy(gc_time)
    gc_pitch_time = np.copy(gc_time)
    gc_vbd_time = np.copy(gc_time)

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

    # Convert Roll to engineering units
    gc_state_state = ncf.variables["gc_state_state"][:]
    gc_state_time = ncf.variables["gc_state_secs"][:]
    # 1 is the code for 'end dive'
    gc_dive_end = gc_state_time[np.argwhere(gc_state_state == 1)[0]][0]
    roll_ctr = np.zeros(len(gc_roll_pos))
    roll_ctr[np.argwhere(gc_roll_time <= gc_dive_end)] = ncf.variables[
        "log_C_ROLL_DIVE"
    ].getValue()
    roll_ctr[np.argwhere(gc_roll_time > gc_dive_end)] = ncf.variables[
        "log_C_ROLL_CLIMB"
    ].getValue()
    gc_roll_pos = (gc_roll_pos - roll_ctr) * ncf.variables["log_ROLL_CNV"].getValue()

    # Convert pitch to eng units
    gc_pitch_pos = (
        gc_pitch_pos - ncf.variables["log_C_PITCH"].getValue()
    ) * ncf.variables["log_PITCH_CNV"].getValue()

    # Convert VBD to eng units
    gc_vbd_pos = (gc_vbd_pos - ncf.variables["log_C_VBD"].getValue()) * ncf.variables[
        "log_VBD_CNV"
    ].getValue()

    eng_time = ncf.variables["time"][:] - ncf.start_time

    def build_dense_motor_vector(motor_pos, motor_time, eng_time):
        """
        Creates dense motor position and time vectors that are all gc reported
        positions, plus interpolated values for the engieering file times
        """
        try:
            f = scipy.interpolate.interp1d(
                motor_time,
                motor_pos,
                kind="previous",
                bounds_error=False,
                # fill_value=0.0,
                fill_value=(motor_pos[0], motor_pos[-1]),
            )
        except NotImplementedError:
            log_warning(
                "Interp1d does not impliment kind previous - failing back to linear"
            )
            f = scipy.interpolate.interp1d(
                motor_time, motor_pos, kind="linear", bounds_error=False, fill_value=0.0
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

    return (gc_moves, roll_time, roll_pos, pitch_time, pitch_pos, vbd_time, vbd_pos)


def add_gc_moves(
    fig,
    gc_moves,
    data,
    xaxis="x1",
    yaxis="y1",
):
    """Add the gc move regions to a figure"""
    show_label = collections.defaultdict(lambda: True)
    for gc in gc_moves:
        fig.add_trace(
            {
                "type": "scatter",
                "x": (
                    gc.start_time,
                    gc.start_time,
                    gc.end_time,
                    gc.end_time,
                ),
                "y": (
                    np.nanmin(data),
                    np.nanmax(data),
                    np.nanmax(data),
                    np.nanmin(data),
                ),
                "xaxis": xaxis,
                "yaxis": yaxis,
                "fill": "toself",
                "fillcolor": gc_move_colormap[gc[2]].color,
                "line": {
                    "dash": "solid",
                    "color": gc_move_colormap[gc[2]].color,
                },
                "mode": "none",  # no outter lines and ponts
                "legendgroup": f"{gc_move_colormap[gc[2]].name}_group",
                "name": f"GC {gc_move_colormap[gc[2]].name}",
                "showlegend": show_label[gc_move_colormap[gc[2]].name],
                "text": f"GC {gc_move_colormap[gc[2]].name}, Start {gc[0] / 60.0:.2f}mins, End {gc[1] / 60.0:.2f}mins",
                "hoverinfo": "text",
            }
        )
        show_label[gc_move_colormap[gc[2]].name] = False


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
    "gc_move_depth", ["start_depth", "end_depth", "move_type"]
)
