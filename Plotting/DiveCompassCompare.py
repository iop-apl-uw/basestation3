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

"""Plots comparision of compass output """

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import typing

import gsw
import numpy as np
import plotly.graph_objects
import scipy
import seawater

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
import Utils
from BaseLog import log_warning, log_info, log_debug, log_error
from Plotting import plotdivesingle


def plot_compass_compare(
    dive_nc_file,
    second_compass_tag,
    second_compass_time,
    second_compass_heading,
    second_compass_pitch,
    second_compass_roll,
    second_compass_press,
    base_opts,
    flip_roll=False,
    flip_pitch=False,
    flip_heading=False,
):
    """Compares roll/pitch/heading of the truck compass with a secondary compass"""
    # Preliminaries
    try:
        start_time = dive_nc_file.start_time
        glider_id = dive_nc_file.glider
        mission_name = (
            dive_nc_file.variables["sg_cal_mission_title"][:].tobytes().decode("utf-8")
        )
        dive_number = dive_nc_file.dive_number
        start_time_string = dive_nc_file.time_coverage_start

        gc_secs = dive_nc_file.variables["gc_st_secs"][:]
        gc_secs = np.concatenate((np.array((0.0,)), gc_secs, np.array((2000000000.0,))))

        gc_moves = PlotUtils.extract_gc_moves(dive_nc_file)[0]

        # SG eng time base
        eng_time = (dive_nc_file.variables["time"][:] - start_time) / 60.0
        heading = dive_nc_file.variables["eng_head"][:]
        eng_pitch_ang = dive_nc_file.variables["eng_pitchAng"][:]
        eng_roll_ang = dive_nc_file.variables["eng_rollAng"][:]

        # Second compass output
        second_compass_time = (
            dive_nc_file.variables[second_compass_time][:] - start_time
        ) / 60.0
        second_compass_heading = dive_nc_file.variables[second_compass_heading][:]
        if flip_heading:
            second_compass_heading += 180
            second_compass_heading[second_compass_heading >= 360.0] -= 360.0
        second_compass_pitch_ang = dive_nc_file.variables[second_compass_pitch][:]
        if flip_pitch:
            second_compass_pitch_ang = -1.0 * second_compass_pitch_ang
        second_compass_roll_ang = dive_nc_file.variables[second_compass_roll][:]
        if flip_roll:
            second_compass_roll_ang = -1.0 * second_compass_roll_ang
        if second_compass_press not in dive_nc_file.variables:
            log_info("No second compass pressure column specified - skipping")
            second_compass_pressure = None
        else:
            second_compass_pressure = dive_nc_file.variables[second_compass_press][:]

        gps_lat = dive_nc_file.variables["log_gps_lat"][:]

        # Depth time base
        depth = None
        try:
            depth = dive_nc_file.variables["depth"][:]
        except KeyError:
            try:
                depth = dive_nc_file.variables["eng_depth"][:] / 100.0
            except KeyError:
                log_warning("No depth variable found")
        depth_time = dive_nc_file.variables["time"][:]
    except:
        log_error("Could not process compass_compare", "exc")
        return ([], [])

    if second_compass_pressure is None:
        second_compass_depth = None
    else:
        try:
            if not base_opts.use_gsw:
                second_compass_depth = seawater.dpth(
                    second_compass_pressure, np.mean((gps_lat[1], gps_lat[2]))
                )
            else:
                second_compass_depth = -1.0 * gsw.z_from_p(
                    second_compass_pressure, np.mean((gps_lat[1], gps_lat[2])), 0.0, 0.0
                )
        except:
            log_error("Failed to correct second compass pressure for lat", "exc")
            second_compass_depth = None

    # Data conversions
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
                    "color": PlotUtils.gc_move_colormap[gc[2]].color,
                },
                "mode": "none",  # no outter lines and ponts
                "legendgroup": f"{PlotUtils.gc_move_colormap[gc[2]].name}_group",
                "name": f"GC {PlotUtils.gc_move_colormap[gc[2]].name}",
                "showlegend": show_label[PlotUtils.gc_move_colormap[gc[2]].name],
                "text": f"GC {PlotUtils.gc_move_colormap[gc[2]].name}, Start {gc[0] / 60.0:.2f}mins, End {gc[1] / 60.0:.2f}mins",
                "hoverinfo": "text",
            }
        )
        show_label[PlotUtils.gc_move_colormap[gc[2]].name] = False

    # Compute RMS for heading, roll and pitch differences

    # Filter out points outside the truck compass time and steep pitch angles
    filter_i_v = [
        ii
        for ii in range(len(second_compass_time))
        if second_compass_time[ii] >= eng_time[0]
        and second_compass_time[ii] <= eng_time[-1]
        and np.fabs(second_compass_pitch_ang[ii]) < 70.0
    ]

    log_debug(min(filter_i_v), max(filter_i_v))

    num_pts = len(second_compass_time[filter_i_v])

    ##DEBUG    compass_diff_v = second_compass_heading[1:] - second_compass_heading[:-1]
    ##DEBUG    hemi_i_v = filter(lambda i: compass_diff_v[i] >  180.0,xrange(len(compass_diff_v)))
    ##DEBUG    compass_diff_v[hemi_i_v] -= 360.0;
    ##DEBUG    hemi_i_v = filter(lambda i: compass_diff_v[i] < -180.0,xrange(len(compass_diff_v)))
    ##DEBUG    compass_diff_v[hemi_i_v] += 360.0;
    ##DEBUG    for ii in range(len(compass_diff_v)):
    ##DEBUG        if fabs(compass_diff_v[ii] > 20):
    ##DEBUG            log_debug("%d %f" % (ii, compass_diff_v[ii]))

    # Wrong way - doesn't handle the 0/360 crossing correctly
    # head_interp = Utils.interp1d(eng_time, heading, second_compass_time[filter_i_v],kind='linear')

    # Interpolate heading, dealing with 0/360 crossing
    x = np.cos(np.radians(heading))
    y = np.sin(np.radians(heading))
    x1 = Utils.interp1d(eng_time, x, second_compass_time[filter_i_v], kind="linear")
    y1 = Utils.interp1d(eng_time, y, second_compass_time[filter_i_v], kind="linear")
    head_interp = np.mod(np.degrees(np.arctan2(y1, x1)), 360)

    delta_head_v = head_interp - second_compass_heading[filter_i_v]
    hemi_i_v = [i for i in range(num_pts) if delta_head_v[i] > 180.0]
    delta_head_v[hemi_i_v] -= 360.0
    hemi_i_v = [i for i in range(num_pts) if delta_head_v[i] < -180.0]
    delta_head_v[hemi_i_v] += 360.0
    log_debug(
        "heading_diff min:%f max:%f mean:%f"
        % (np.min(delta_head_v), np.max(delta_head_v), np.mean(delta_head_v))
    )
    head_rms = np.sqrt(np.mean(delta_head_v**2.0))
    head_diff_mean = np.mean(delta_head_v)

    large_diff_i_v = [
        ii for ii in range(num_pts) if np.fabs(delta_head_v[ii]) > head_rms * 3
    ]
    log_debug(delta_head_v[large_diff_i_v])
    log_debug(large_diff_i_v)
    log_debug(second_compass_pitch_ang[large_diff_i_v])

    pitch_interp = Utils.interp1d(
        eng_time, eng_pitch_ang, second_compass_time[filter_i_v], kind="linear"
    )
    pitch_rms = np.sqrt(
        np.mean((pitch_interp - second_compass_pitch_ang[filter_i_v]) ** 2.0)
    )
    pitch_diff_mean = np.mean(pitch_interp - second_compass_pitch_ang[filter_i_v])

    roll_interp = Utils.interp1d(
        eng_time, eng_roll_ang, second_compass_time[filter_i_v], kind="linear"
    )
    roll_rms = np.sqrt(
        np.mean((roll_interp - second_compass_roll_ang[filter_i_v]) ** 2.0)
    )
    roll_diff_mean = np.mean(roll_interp - second_compass_roll_ang[filter_i_v])

    # l_annotations = [
    #     {
    #         "text": f"Heading Differnce Mean:{head_diff_mean:.2f} deg RMS:{head_rms:.3f} deg",
    #         "showarrow": False,
    #         "xref": "paper",
    #         "yref": "paper",
    #         "align": "left",
    #         "xanchor": "left",
    #         "valign": "top",
    #         "x": 0,
    #         "y": -0.04,
    #     },
    #     {
    #         "text": f"Pitch Differnce Mean:{pitch_diff_mean:.2f} deg RMS:{pitch_rms:.3f} deg",
    #         "showarrow": False,
    #         "xref": "paper",
    #         "yref": "paper",
    #         "align": "left",
    #         "xanchor": "left",
    #         "valign": "top",
    #         "x": 0,
    #         "y": -0.06,
    #     },
    #     {
    #         "text": f"Roll Differnce Mean:{roll_diff_mean:.2f} deg RMS:{roll_rms:.3f} deg",
    #         "showarrow": False,
    #         "xref": "paper",
    #         "yref": "paper",
    #         "align": "left",
    #         "xanchor": "left",
    #         "valign": "top",
    #         "x": 0,
    #         "y": -0.08,
    #     },
    # ]
    # fig.update_layout({"annotations": tuple(l_annotations)})

    rms_line = (
        f"Heading Difference Mean:{head_diff_mean:.2f} deg RMS:{head_rms:.3f} deg<br>"
        f"Pitch Difference Mean:{pitch_diff_mean:.2f} deg RMS:{pitch_rms:.3f} deg<br>"
        f"Roll Difference Mean:{roll_diff_mean:.2f} deg RMS:{roll_rms:.3f} deg"
    )

    depth = (depth * -1.0) / zscl
    depth_time = (depth_time - start_time) / 60.0

    fig.add_trace(
        {
            "y": depth,
            "x": depth_time,
            "meta": depth * zscl,
            "name": f"Depth ({zscl:.0f}m) - truck",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines+markers",
            "marker": {"symbol": "cross", "size": 3},
            "line": {"dash": "solid", "color": "Black"},
            "hovertemplate": "Depth truck<br>%{meta:.2f} meters<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    if second_compass_depth is not None:
        second_compass_depth = (second_compass_depth * -1.0) / zscl
        fig.add_trace(
            {
                "y": second_compass_depth,
                "x": second_compass_time,
                "meta": second_compass_depth * zscl,
                "name": f"Depth ({zscl:.0f}m) - {second_compass_tag}",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "lines+markers",
                "marker": {"symbol": "cross", "size": 3},
                "line": {"dash": "solid", "color": "Magenta"},
                "hovertemplate": "Depth "
                + second_compass_tag
                + "<br>%{meta:.2f} meters<br>%{x:.2f} mins<br><extra></extra>",
            }
        )

    fig.add_trace(
        {
            "y": eng_pitch_ang,
            "x": eng_time,
            "name": "Pitch Up (deg) - truck",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "LightGreen"},
            "hovertemplate": "Pitch up - truck<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": second_compass_pitch_ang,
            "x": second_compass_time,
            "name": f"Pitch Up (deg) - {second_compass_tag}",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "DarkGreen"},
            "hovertemplate": "Pitch up - "
            + second_compass_tag
            + "<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": eng_roll_ang,
            "x": eng_time,
            "name": "Roll (deg) - truck",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Blue"},
            "hovertemplate": "Roll - truck<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": second_compass_roll_ang,
            "x": second_compass_time,
            "name": f"Roll (deg) - {second_compass_tag}",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "DarkBlue"},
            "hovertemplate": "Roll - "
            + second_compass_tag
            + "<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": heading,
            "x": eng_time,
            "name": "Heading (deg) - truck ",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y2",
            "mode": "markers",
            "marker": {"symbol": "cross", "color": "DarkRed", "size": 3},
            "hovertemplate": "Heading - truck<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": second_compass_heading,
            "x": second_compass_time,
            "name": f"Heading (deg) - {second_compass_tag}",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y2",
            "mode": "markers",
            "marker": {"symbol": "cross", "color": "Orange", "size": 3},
            "hovertemplate": "Heading - "
            + second_compass_tag
            + "<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    try:
        glider_id = int(glider_id)
        glider_id = "SG%03d" % glider_id
    except:
        pass

    title_text = (
        "%s %s dive %d started %s<br>Comparision of truck compass and %s output"
        % (
            glider_id,
            mission_name,
            dive_number,
            start_time_string,
            second_compass_tag,
        )
    )
    fig.update_layout(
        {
            "xaxis": {
                "title": "Time (minutes)<br>" + rms_line,
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
            },
        }
    )

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_truck_%s_compass_compare"
            % (dive_nc_file.dive_number, second_compass_tag.lower()),
            fig,
        ),
    )


@plotdivesingle
def plot_compare_aux(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots comparision of truc with with aux compass"""

    if "auxCompass_time" not in dive_nc_file.variables or not generate_plots:
        return ([], [])
    return plot_compass_compare(
        dive_nc_file,
        "auxCompass",
        "auxCompass_time",
        "auxCompass_hdg",
        "auxCompass_pit",
        "auxCompass_rol",
        "auxCompass_press",
        base_opts,
    )


@plotdivesingle
def plot_compare_auxb(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots comparision of truc with with auxb compass"""
    if "auxB_time" not in dive_nc_file.variables or not generate_plots:
        return ([], [])
    return plot_compass_compare(
        dive_nc_file,
        "auxB",
        "auxB_time",
        "auxB_hdg",
        "auxB_pit",
        "auxB_rol",
        "auxB_press",
        base_opts,
    )


@plotdivesingle
def plot_compare_cp(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots comparision of truck compass with with logdev adcp compass"""
    if "cp_time" not in dive_nc_file.variables or not generate_plots:
        return ([], [])
    return plot_compass_compare(
        dive_nc_file,
        "ADCPCompass",
        "cp_time",
        "cp_heading",
        "cp_pitch",
        "cp_roll",
        "cp_pressure",
        base_opts,
    )


@plotdivesingle
def plot_compare_ad2cp(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots comparision of truck compass with with logdev adcp compass"""
    if "ad2cp_time" not in dive_nc_file.variables or not generate_plots:
        return ([], [])

    return plot_compass_compare(
        dive_nc_file,
        "ADCPCompass",
        "ad2cp_time",
        "ad2cp_heading",
        "ad2cp_pitch",
        "ad2cp_roll",
        "ad2cp_pressure",
        base_opts,
        flip_pitch=base_opts.flip_ad2cp,
        flip_roll=base_opts.flip_ad2cp,
        flip_heading=base_opts.flip_ad2cp,
    )
