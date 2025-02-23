#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025  University of Washington.
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

"""Main plot for glider engineering data"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import contextlib
import typing

import numpy as np
import plotly.graph_objects
import scipy.interpolate

if typing.TYPE_CHECKING:
    import scipy

    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
import Utils
from BaseLog import log_error, log_warning
from Plotting import plotdivesingle


def clock_compass(heading):
    """
    Do the clock arithmatic for the compass headings to ensure it is in the 0-360 degree range

    Input:
        Heading in degrees

    Returns:
        Headings in 0 - 360 range
    """
    over_i_v = [i for i in range(len(heading)) if heading[i] >= 360.0]
    heading[over_i_v] -= 360.0
    under_i_v = [i for i in range(len(heading)) if heading[i] < 0]
    heading[under_i_v] += 360.0
    return heading


@plotdivesingle
def plot_diveplot(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots most of the glider engineering data"""
    # pylint: disable=unused-argument

    # TODO: Make Hovertips show AD counts as well as eng units

    # Preliminaries
    if "gc_st_secs" not in dive_nc_file.variables or not generate_plots:
        return ([], [])

    try:
        start_time = dive_nc_file.start_time
        eng_time = (dive_nc_file.variables["time"][:] - start_time) / 60.0

        (
            gc_moves,
            gc_roll_time,
            gc_roll_pos,
            gc_pitch_time,
            gc_pitch_pos,
            gc_vbd_time,
            gc_vbd_pos,
            gc_roll_pos_ad,
            gc_pitch_pos_ad,
            gc_vbd_pos_ad,
        ) = PlotUtils.extract_gc_moves(dive_nc_file)

        apogee_time = None
        if gc_pitch_pos is not None:
            eng_pitch_pos = gc_pitch_pos * 10.0
            eng_pitch_time = gc_pitch_time / 60.0
            with contextlib.suppress(ValueError):
                apogee_time = min(eng_pitch_time[eng_pitch_pos > 0])
        elif "eng_pitchCtl" in dive_nc_file.variables:
            eng_pitch_pos = dive_nc_file.variables["eng_pitchCtl"][:] * 10.0
            eng_pitch_time = eng_time
            with contextlib.suppress(ValueError):
                apogee_time = min(eng_pitch_time[eng_pitch_pos > 0])
        else:
            log_error("Pitch position not available")
            eng_pitch_pos = eng_pitch_time = None

        # TODO - Something is wrong here - either use eng_roll_pos or gc_roll_pos variable
        if gc_roll_pos is not None:
            # eng_roll_pos = gc_roll_pos
            eng_roll_time = gc_roll_time / 60.0
        elif "eng_rollCtl" in dive_nc_file.variables:
            # eng_roll_pos = dive_nc_file.variables["eng_rollCtl"][:]
            eng_roll_time = eng_time
        else:
            log_error("Roll position not available")
            # eng_roll_pos = eng_roll_time = None

        if gc_vbd_pos is not None:
            eng_vbd_pos = gc_vbd_pos / 10.0
            eng_vbd_time = gc_vbd_time / 60.0
        elif "eng_vbdCC" in dive_nc_file.variables:
            eng_vbd_pos = dive_nc_file.variables["eng_vbdCtl"][:] / 10.0
            eng_vbd_time = eng_time
        else:
            log_error("VBD position not available")
            eng_vbd_pos = eng_vbd_time = None

        glider_id = dive_nc_file.glider
        mission_name = (
            dive_nc_file.variables["sg_cal_mission_title"][:].tobytes().decode("utf-8")
        )
        dive_number = dive_nc_file.dive_number
        start_time_string = dive_nc_file.time_coverage_start

        mag_var = dive_nc_file.variables["magnetic_variation"].getValue()
        heading = clock_compass(dive_nc_file.variables["eng_head"][:] + mag_var)

        errband = float(dive_nc_file.variables["log_HEAD_ERRBAND"].getValue())

        tmp = float(
            dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
            .tobytes()
            .decode("utf-8")
            .split(",")[0]
        )
        desired_heading = clock_compass(np.zeros(len(eng_time)) + tmp)
        desired_heading_plus_errband = clock_compass(
            np.zeros(len(eng_time)) + tmp + errband
        )
        desired_heading_minus_errband = clock_compass(
            np.zeros(len(eng_time)) + tmp - errband
        )

        desired_pitch = float(
            dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
            .tobytes()
            .decode("utf-8")
            .split(",")[2]
        )

        eng_pitch_ang = dive_nc_file.variables["eng_pitchAng"][:]
        eng_roll_ang = dive_nc_file.variables["eng_rollAng"][:]

        # CTD time base
        ctd_time = None
        with contextlib.suppress(KeyError):
            ctd_time = (dive_nc_file.variables["ctd_time"][:] - start_time) / 60.0

        vert_speed_gsm = horz_speed_gsm = glide_angle_gsm = None
        try:
            horz_speed_gsm = dive_nc_file.variables["horz_speed_gsm"][:]
            vert_speed_gsm = dive_nc_file.variables["vert_speed_gsm"][:]
            glide_angle_gsm = dive_nc_file.variables["glide_angle_gsm"][:]
        except KeyError:
            pass

        vert_speed_hdm = horz_speed_hdm = buoy = glide_angle = None
        try:
            vert_speed_hdm = dive_nc_file.variables["vert_speed"][:]
            horz_speed_hdm = dive_nc_file.variables["horz_speed"][:]
            buoy = dive_nc_file.variables["buoyancy"][:] / 10.0
            glide_angle = dive_nc_file.variables["glide_angle"][:]
        except KeyError:
            pass

        if (
            "density" in dive_nc_file.variables
            and "log_MASS" in dive_nc_file.variables
            and "log_RHO" in dive_nc_file.variables
        ):
            eng_density = np.interp(
                eng_vbd_time, ctd_time, dive_nc_file.variables["density"][:]
            )

            mass = dive_nc_file.variables["log_MASS"].getValue()
            rho = dive_nc_file.variables["log_RHO"].getValue()
            vol = mass / rho + eng_vbd_pos * 10
            buoy_veh = (-mass + vol * eng_density / 1000) / 10
        else:
            buoy_veh = None

        ctd_depth = None
        if "legato_pressure" in dive_nc_file.variables:
            # In this case, ctd_depth is derived from the legato, not the truck
            # so we show it as well
            with contextlib.suppress(KeyError):
                ctd_depth = dive_nc_file.variables["ctd_depth"][:]

        aux_depth_name = None
        if "auxB_press" in dive_nc_file.variables:
            aux_depth_name = "auxB"
        if "auxCompass_press" in dive_nc_file.variables:
            aux_depth_name = "auxCompass"

        if aux_depth_name:
            aux_depth = dive_nc_file.variables[f"{aux_depth_name}_depth"][:]
            aux_time = dive_nc_file.variables[f"{aux_depth_name}_time"][:]

        # Depth time base
        try:
            depth = dive_nc_file.variables["depth"][:]
        except KeyError:
            try:
                depth = dive_nc_file.variables["eng_depth"][:] / 100.0
            except KeyError:
                log_warning("No depth variable found")
                return ([], [])

        depth_time = dive_nc_file.variables["time"][:]
    except Exception:
        log_error("Could not process diveplot", "exc")
        return ([], [])

    if not apogee_time:
        apogee_time = depth_time[np.argmax(depth)]

    # Data conversions
    dz_dt = Utils.ctr_1st_diff(-depth * 100, depth_time - start_time)
    if max(depth) > 5000:
        zscl = 100
    elif max(depth) > 2000:
        zscl = 50
    elif max(depth) > 1000:
        zscl = 20
    elif max(depth) > 500:
        zscl = 10
    elif max(depth) > 300:
        zscl = 5
    elif max(depth) > 200:
        zscl = 3
    elif max(depth) > 100:
        zscl = 2
    else:
        zscl = 1

    depth = (depth * -1.0) / zscl
    if ctd_depth is not None:
        ctd_depth = (ctd_depth * -1.0) / zscl
    depth_time = (depth_time - start_time) / 60.0

    if aux_depth_name:
        aux_depth = (aux_depth * -1.0) / zscl
        aux_time = (aux_time - start_time) / 60.0

    fig = plotly.graph_objects.Figure()

    show_label = collections.defaultdict(lambda: True)

    for gc in gc_moves:
        fig.add_trace(
            {
                "type": "scatter",
                "x": (gc[0] / 60.0, gc[0] / 60.0, gc[1] / 60.0, gc[1] / 60.0),
                "y": (-100.0, 80.0, 80.0, -100.0),
                "xaxis": "x1",
                "yaxis": "y1",
                "fill": "toself",
                "fillcolor": PlotUtils.gc_move_colormap[gc[2]].color,
                "line": {
                    "dash": "solid",
                    # proxy for line opacity - lines are needed for short moves (like pitch)
                    "width": 0.25,
                    "color": PlotUtils.gc_move_colormap[gc[2]].color,
                },
                "mode": "lines",  # lines are needed for short moves (like pitch)
                "legendgroup": f"{PlotUtils.gc_move_colormap[gc[2]].name}_group",
                "name": f"GC {PlotUtils.gc_move_colormap[gc[2]].name}",
                "showlegend": show_label[PlotUtils.gc_move_colormap[gc[2]].name],
                "text": f"GC {PlotUtils.gc_move_colormap[gc[2]].name}, Start {gc[0] / 60.0:.2f}mins, End {gc[1] / 60.0:.2f}mins",
                "hoverinfo": "text",
            }
        )
        show_label[PlotUtils.gc_move_colormap[gc[2]].name] = False

    # Depth traces
    valid_i = np.logical_not(np.isnan(depth))
    fig.add_trace(
        {
            "y": depth[valid_i],
            "x": depth_time[valid_i],
            "meta": (depth * zscl)[valid_i],
            "name": f"Depth ({zscl:.0f}m)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            # "mode": "lines",
            "mode": "lines+markers",
            "marker": {"symbol": "cross", "size": 3},
            "line": {"dash": "solid", "color": "DarkRed"},
            "hovertemplate": "Depth<br>%{meta:.1f} meters<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    if aux_depth_name:
        valid_i = np.logical_not(np.isnan(aux_depth))
        fig.add_trace(
            {
                "y": aux_depth[valid_i],
                "x": aux_time[valid_i],
                "meta": (aux_depth * zscl)[valid_i],
                "name": f"{aux_depth_name} Depth ({zscl:.0f}m)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                # "mode": "lines",
                "visible": "legendonly",
                "mode": "lines+markers",
                "marker": {"symbol": "cross", "size": 3},
                "line": {"dash": "solid", "color": "darkviolet"},
                "hovertemplate": f"{aux_depth_name} Depth"
                + "<br>%{meta:.1f} meters<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    if ctd_depth is not None:
        valid_i = np.logical_not(np.isnan(ctd_depth))
        fig.add_trace(
            {
                "y": ctd_depth[valid_i],
                "x": ctd_time[valid_i],
                "meta": (ctd_depth * zscl)[valid_i],
                "name": f"Legato Depth ({zscl:.0f}m)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                # "mode": "lines",
                "visible": "legendonly",
                "mode": "lines+markers",
                "marker": {"symbol": "cross", "size": 3},
                "line": {"dash": "solid", "color": "OrangeRed"},
                "hovertemplate": "Legato Depth<br>%{meta:.1f} meters<br>%{x:.2f} mins<br><extra></extra>",
            }
        )
    # End Depth traces

    # Vehicle attitude from compass and pressure
    valid_i = np.logical_not(np.isnan(dz_dt))
    fig.add_trace(
        {
            "y": dz_dt[valid_i],
            "x": depth_time[valid_i],
            # "legendgroup": "attitude",
            "name": "Vert Speed dz/dt (cm/s)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "DarkBlue"},
            "hovertemplate": "Vert Speed dz/dt<br>%{y:.2f} cm/sec<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    valid_i = np.logical_not(np.isnan(eng_pitch_ang))
    fig.add_trace(
        {
            "y": eng_pitch_ang[valid_i],
            "x": eng_time[valid_i],
            # "legendgroup": "attitude",
            "name": "Pitch Up (deg)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Green"},
            "hovertemplate": "Pitch Up<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": [desired_pitch, desired_pitch, -desired_pitch, -desired_pitch],
            "x": [eng_time[0], apogee_time, apogee_time + 1, eng_time[-1]],
            # "legendgroup": "attitude",
            "name": "Pitch desired (deg)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "dot", "color": "Green"},
            "hovertemplate": "Pitch desired<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    valid_i = np.logical_not(np.isnan(eng_pitch_pos))
    temp_dict = {
        "y": eng_pitch_pos[valid_i],
        "x": eng_pitch_time[valid_i],
        # "legendgroup": "motorpositions",
        "name": "Pitch pos (mm)",
        "type": "scatter",
        "xaxis": "x1",
        "yaxis": "y1",
        #'mode':'lines', 'line':{'dash':'longdash', 'color':Green'}
        "mode": "lines",
        "line": {"dash": "solid", "color": "LightGreen"},
    }
    if gc_pitch_pos_ad is not None:
        temp_dict["customdata"] = gc_pitch_pos_ad
        temp_dict["hovertemplate"] = (
            "Pitch pos<br>%{y:.2f} mm<br>%{customdata:.1f} AD<br>%{x:.2f} mins<br><extra></extra>"
        )
    else:
        temp_dict["hovertemplate"] = (
            "Pitch pos<br>%{y:.2f} mm<br>%{x:.2f} mins<br><extra></extra>"
        )

    fig.add_trace(temp_dict)
    del temp_dict

    valid_i = np.logical_not(np.isnan(eng_roll_ang))
    fig.add_trace(
        {
            "y": eng_roll_ang[valid_i],
            "x": eng_time[valid_i],
            # "legendgroup": "attitude",
            "name": "Vehicle Roll (deg)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Goldenrod"},
            "hovertemplate": "Vehicle Roll<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    temp_dict = {
        "y": gc_roll_pos,
        "x": eng_roll_time,
        # "legendgroup": "motorpositions",
        "name": "Roll pos (deg)",
        "type": "scatter",
        "xaxis": "x1",
        "yaxis": "y1",
        "mode": "lines",
        "line": {"dash": "solid", "color": "LightGoldenrodYellow"},
    }
    if gc_roll_pos_ad is not None:
        temp_dict["customdata"] = gc_roll_pos_ad
        temp_dict["hovertemplate"] = (
            "Roll pos<br>%{y:.2f} deg<br>%{customdata:.1f} AD<br>%{x:.2f} mins<br><extra></extra>"
        )
    else:
        temp_dict["hovertemplate"] = (
            "Roll pos<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>"
        )

    fig.add_trace(temp_dict)
    del temp_dict

    # End Vehicle attitude from compass and pressure

    # Glide Slope Model Output
    if vert_speed_gsm is not None:
        valid_i = np.logical_not(np.isnan(vert_speed_gsm))
        fig.add_trace(
            {
                "y": vert_speed_gsm[valid_i],
                "x": ctd_time[valid_i],
                # "legendgroup": "GSM",
                "name": "Vert Speed GSM (cm/s)",
                "visible": "legendonly",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "solid", "color": "LightBlue"},
                "hovertemplate": "Vert Speed GSM<br>%{y:.2f} cm/sec<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    if horz_speed_gsm is not None:
        valid_i = np.logical_not(np.isnan(horz_speed_gsm))
        fig.add_trace(
            {
                "y": horz_speed_gsm[valid_i],
                "x": ctd_time[valid_i],
                # "legendgroup": "GSM",
                "name": "Horiz Speed GSM (cm/s)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "solid", "color": "Cyan"},
                "hovertemplate": "Horiz Speed GSM<br>%{y:.2f} cm/sec<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    if glide_angle_gsm is not None:
        valid_i = np.logical_not(np.isnan(glide_angle_gsm))
        fig.add_trace(
            {
                "y": glide_angle_gsm[valid_i],
                "x": ctd_time[valid_i],
                # "legendgroup": "GSM",
                "name": "Glide Angle GSM (deg)",
                "visible": "legendonly",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "solid", "color": "Violet"},
                "hovertemplate": "Glide Angle GSM<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
            }
        )
    # End Glide Slope Model Output

    # Hydro Model Output
    if vert_speed_hdm is not None:
        valid_i = np.logical_not(np.isnan(vert_speed_hdm))
        fig.add_trace(
            {
                "y": vert_speed_hdm[valid_i],
                "x": ctd_time[valid_i],
                # "legendgroup": "HDM",
                "name": "Vert Speed HDM (cm/s)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "solid", "color": "Blue"},
                "hovertemplate": "Vert Speed HDM<br>%{y:.2f} cm/sec<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    if horz_speed_hdm is not None:
        valid_i = np.logical_not(np.isnan(horz_speed_hdm))
        fig.add_trace(
            {
                "y": horz_speed_hdm[valid_i],
                "x": ctd_time[valid_i],
                # "legendgroup": "HDM",
                "name": "Horiz Speed HDM (cm/s)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "solid", "color": "DarkCyan"},
                "hovertemplate": "Horiz Speed HDM<br>%{y:.2f} cm/sec<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    if glide_angle is not None:
        valid_i = np.logical_not(np.isnan(glide_angle))
        fig.add_trace(
            {
                "y": glide_angle[valid_i],
                "x": ctd_time[valid_i],
                # "legendgroup": "HDM",
                "name": "Glide Angle HDM (deg)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "solid", "color": "Magenta"},
                "hovertemplate": "Glide Angle HDM<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    if buoy is not None:
        valid_i = np.logical_not(np.isnan(buoy))
        fig.add_trace(
            {
                "y": buoy[valid_i],
                "x": ctd_time[valid_i],
                "meta": buoy[valid_i] * 10.0,
                # "legendgroup": "HDM",
                "name": "Buoyancy HDM (10 g)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "solid", "color": "DarkMagenta"},
                "hovertemplate": "Buoyancy HDM<br>%{meta:.2f} g<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    if buoy_veh is not None:
        valid_i = np.logical_not(np.isnan(buoy_veh))
        fig.add_trace(
            {
                "y": buoy_veh[valid_i],
                "x": eng_vbd_time[valid_i],
                "meta": buoy_veh[valid_i] * 10.0,
                # "legendgroup": "HDM",
                "name": "Buoyancy (veh) (10 g)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "dot", "color": "DarkMagenta"},
                "hovertemplate": "Buoyancy (veh)<br>%{meta:.2f} g<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    valid_i = np.logical_not(np.isnan(eng_vbd_pos))
    temp_dict = {
        "y": eng_vbd_pos[valid_i],
        "x": eng_vbd_time[valid_i],
        "meta": eng_vbd_pos[valid_i] * 10,
        # "legendgroup": "motorpositions",
        "name": "VBD pos (10 cc)",
        "type": "scatter",
        "xaxis": "x1",
        "yaxis": "y1",
        "mode": "lines",
        "line": {"dash": "solid", "color": "Black"},
    }
    if gc_vbd_pos_ad is not None:
        temp_dict["customdata"] = gc_vbd_pos_ad
        temp_dict["hovertemplate"] = (
            "VBD pos<br>%{meta:.2f} cc<br>%{customdata:.1f} AD<br>%{x:.2f} mins<br><extra></extra>"
        )
    else:
        temp_dict["hovertemplate"] = (
            "VBD pos<br>%{meta:.2f} cc<br>%{x:.2f} mins<br><extra></extra>"
        )

    fig.add_trace(temp_dict)
    del temp_dict

    fig.add_trace(
        {
            "y": heading,
            "x": eng_time,
            "name": "Heading (deg true)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y2",
            "mode": "markers",
            "marker": {"symbol": "cross", "color": "DarkRed", "size": 3},
            "hovertemplate": "Heading<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": desired_heading,
            "x": eng_time,
            "name": "Desired Heading (deg true)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y2",
            "mode": "lines",
            "line": {"dash": "longdash", "color": "DarkRed"},
            "hovertemplate": "Desired Head<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": desired_heading_plus_errband,
            "x": eng_time,
            "name": "Desired Head+ErrBand (deg true)",
            "type": "scatter",
            "legendgroup": "HeadErrBand",
            "visible": "legendonly",
            "xaxis": "x1",
            "yaxis": "y2",
            "mode": "lines",
            "line": {"dash": "longdash", "color": "orangered"},
            "hovertemplate": "DHead+ErrBand<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": desired_heading_minus_errband,
            "x": eng_time,
            "name": "Desired Head-ErrBand (deg true)",
            "type": "scatter",
            "visible": "legendonly",
            "legendgroup": "HeadErrBand",
            "xaxis": "x1",
            "yaxis": "y2",
            "mode": "lines",
            "line": {"dash": "longdash", "color": "orangered"},
            "hovertemplate": "DHead-ErrBand<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    # NEWHEAD - if present
    try:
        newhead_heading = dive_nc_file.variables["gc_msg_NEWHEAD_heading"][:]
        newhead_time = (
            dive_nc_file.variables["gc_msg_NEWHEAD_secs"][:] - start_time
        ) / 60.0
    except KeyError:
        pass
    except Exception:
        log_error("Unexpected problem with NEWHEAD variables", "exc")
    else:
        fig.add_trace(
            {
                "y": newhead_heading,
                "x": newhead_time,
                "name": "Newhead (deg true)",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y2",
                "visible": "legendonly",
                "mode": "markers",
                "marker": {"symbol": "cross", "color": "#301934", "size": 3},
                "hovertemplate": "NewHeading<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    try:
        glider_id = int(glider_id)
        glider_id = "SG%03d" % glider_id
    except Exception:
        pass

    traces = []
    for d in fig.data:
        traces.append(d["name"])

    ctlTraces = {}
    ctlTraces["pitch"] = [
        "GC Pitch",
        "Pitch Up (deg)",
        "Pitch desired (deg)",
        "Pitch pos (mm)",
    ]
    ctlTraces["roll"] = ["GC Roll", "Vehicle Roll (deg)", "Roll pos (deg)"]
    ctlTraces["VBD"] = [
        "GC VBD",
        "Buoyancy HDM (10 g)",
        "Buoyancy (veh) (10 g)",
        "VBD pos (10 cc)",
    ]
    ctlTraces["HDM"] = [
        "Horiz Speed HDM (cm/s)",
        "Vert Speed HDM (cm/s)",
        "Glide Angle HDM (deg)",
        "Buoyancy HDM (10 g)",
    ]
    ctlTraces["GSM"] = [
        "Horiz Speed GSM (cm/s)",
        "Vert Speed GSM (cm/s)",
        "Glide Angle GSM (deg)",
    ]

    buttons = [
        dict(
            args2=[{"visible": True}],
            args=[{"visible": "legendonly"}],
            label="All",
            method="restyle",
            visible=True,
        )
    ]

    for c in ctlTraces:
        buttons.append(
            dict(
                args2=[
                    {"visible": True},
                    [i for i, x in enumerate(traces) if x in ctlTraces[c]],
                ],
                args=[
                    {"visible": "legendonly"},
                    [i for i, x in enumerate(traces) if x in ctlTraces[c]],
                ],
                label=c,
                method="restyle",
                visible=True,
            )
        )

    fig.update_layout(
        updatemenus=[
            dict(
                type="buttons",
                direction="left",
                buttons=buttons,
                x=1.1,
                y=1.07,
                visible=True,
                showactive=False,
            ),
        ]
    )

    title_text = "%s %s dive %d started %s" % (
        glider_id,
        mission_name,
        dive_number,
        start_time_string,
    )
    fig.update_layout(
        {
            "xaxis": {
                "title": "Time (minutes)",
                "showgrid": True,
                #'range' : [depth_time[0], depth_time[-1]],
                "range": [0, depth_time[-1]],
                "tick0": 0,  # Minutes
                "dtick": 30,  # Minutes
            },
            "yaxis": {  #'title' : 'Depth (m)',
                #'autorange' : 'reversed',
                "range": [-100.0, 80.0],
                "nticks": 19,
            },
            "yaxis2": {
                "title": "(+) Heading (Degrees True)",  # TOD - add color here color='r',
                "overlaying": "y1",
                "side": "right",
                #'autorange' : 'reversed',
                "range": [0, 360],
                "nticks": 19,
            },
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "t": 150,
            },
            "legend": {
                "x": 1.05,
                "y": 1,
                # Adjust click behavior - swaps from the default
                # "itemclick": "toggleothers",
                # "itemdoubleclick": "toggle",
            },
        }
    )

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts, "dv%04d_diveplot" % (dive_nc_file.dive_number), fig
        ),
    )
