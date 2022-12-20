#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

"""Main plot for glider engineering data """

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import typing

import numpy as np
import scipy.interpolate
import plotly.graph_objects

if typing.TYPE_CHECKING:
    import BaseOpts
    import scipy

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
    base_opts: BaseOpts.BaseOptions, dive_nc_file: scipy.io._netcdf.netcdf_file
) -> tuple[list, list]:
    """Plots most of the glider engineering data"""
    # pylint: disable=unused-argument

    # TODO: Make Hovertips show AD counts as well as eng units

    # Preliminaries
    if "gc_st_secs" not in dive_nc_file.variables:
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
        ) = PlotUtils.extract_gc_moves(dive_nc_file)

        if gc_pitch_pos is not None:
            eng_pitch_pos = gc_pitch_pos * 10.0
            eng_pitch_time = gc_pitch_time / 60.0
        elif "eng_pitchCtl" in dive_nc_file.variables:
            eng_pitch_pos = dive_nc_file.variables["eng_pitchCtl"][:] * 10.0
            eng_pitch_time = eng_time
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
        start_time_string = dive_nc_file.time_coverage_start.decode()

        mag_var = dive_nc_file.variables["magnetic_variation"].getValue()
        heading = clock_compass(dive_nc_file.variables["eng_head"][:] + mag_var)

        tmp = float(
            dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
            .tobytes()
            .decode("utf-8")
            .split(",")[0]
        )
        desired_heading = clock_compass(np.zeros(len(eng_time)) + tmp)

        eng_pitch_ang = dive_nc_file.variables["eng_pitchAng"][:]
        eng_roll_ang = dive_nc_file.variables["eng_rollAng"][:]

        # CTD time base
        ctd_time = None
        try:
            ctd_time = (dive_nc_file.variables["ctd_time"][:] - start_time) / 60.0
        except KeyError:
            pass

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

        ctd_depth = None
        if "legato_pressure" in dive_nc_file.variables:
            # In this case, ctd_depth is derived from the legato, not the truck
            # so we show it as well
            try:
                ctd_depth = dive_nc_file.variables["ctd_depth"][:]
            except KeyError:
                pass

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
    except:
        log_error("Could not process diveplot", "exc")
        return ([], [])

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

    # Depth traces
    fig.add_trace(
        {
            "y": depth,
            "x": depth_time,
            "meta": depth * zscl,
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
        fig.add_trace(
            {
                "y": aux_depth,
                "x": aux_time,
                "meta": aux_depth * zscl,
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
        fig.add_trace(
            {
                "y": ctd_depth,
                "x": ctd_time,
                "meta": ctd_depth * zscl,
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
    fig.add_trace(
        {
            "y": dz_dt,
            "x": depth_time,
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

    fig.add_trace(
        {
            "y": eng_pitch_ang,
            "x": eng_time,
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
            "y": eng_roll_ang,
            "x": eng_time,
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

    # End Vehicle attitude from compass and pressure

    # Glide Slope Model Output
    if vert_speed_gsm is not None:
        fig.add_trace(
            {
                "y": vert_speed_gsm,
                "x": ctd_time,
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
        fig.add_trace(
            {
                "y": horz_speed_gsm,
                "x": ctd_time,
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
        fig.add_trace(
            {
                "y": glide_angle_gsm,
                "x": ctd_time,
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
        fig.add_trace(
            {
                "y": vert_speed_hdm,
                "x": ctd_time,
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
        fig.add_trace(
            {
                "y": horz_speed_hdm,
                "x": ctd_time,
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
        fig.add_trace(
            {
                "y": glide_angle,
                "x": ctd_time,
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
        fig.add_trace(
            {
                "y": buoy,
                "x": ctd_time,
                "meta": buoy * 10.0,
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
    # End Hydro Model Output

    # Motor positions
    fig.add_trace(
        {
            "y": eng_pitch_pos,
            "x": eng_pitch_time,
            # "legendgroup": "motorpositions",
            "name": "Pitch pos (mm)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            #'mode':'lines', 'line':{'dash':'longdash', 'color':Green'}
            "mode": "lines",
            "line": {"dash": "solid", "color": "LightGreen"},
            "hovertemplate": "Pitch pos<br>%{y:.2f} mm<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": gc_roll_pos,
            "x": eng_roll_time,
            # "legendgroup": "motorpositions",
            "name": "Roll pos (deg)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "LightGoldenrodYellow"},
            "hovertemplate": "Roll pos<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": eng_vbd_pos,
            "x": eng_vbd_time,
            "meta": eng_vbd_pos * 10,
            # "legendgroup": "motorpositions",
            "name": "VBD pos (10 cc)",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Black"},
            "hovertemplate": "VBD pos<br>%{meta:.2f} cc<br>%{x:.2f} mins<br><extra></extra>",
        }
    )
    # End Motor Positions

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
            "hovertemplate": "Heading<br>%{y:.2f} deg<br>%{x:.2f} mins<br><extra></extra>",
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
    except:
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
    except:
        pass

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
