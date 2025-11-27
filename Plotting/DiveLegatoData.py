#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025  University of Washington.
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

"""Plots raw legato data"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

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
from Plotting import plotdivesingle


@plotdivesingle
def plot_legato_data(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots raw legato columns along with optode temp (if available)"""

    if (
        "legato_temp" not in dive_nc_file.variables
        and "eng_rbr_temp" not in dive_nc_file.variables
    ) or not generate_plots:
        return ([], [])

    if "legato_temp" in dive_nc_file.variables:
        temp = dive_nc_file.variables["legato_temp"][:]
        cond_temp = dive_nc_file.variables["legato_conducTemp"][:]
        conductivity = dive_nc_file.variables["legato_conduc"][:] / 10.0
        legato_time = dive_nc_file.variables["legato_time"][:]
    else:
        temp = dive_nc_file.variables["eng_rbr_temp"][:]
        cond_temp = dive_nc_file.variables["eng_rbr_conducTemp"][:]
        conductivity = dive_nc_file.variables["eng_rbr_conduc"][:] / 10.0
        legato_time = dive_nc_file.variables["time"][:]

    if base_opts.plot_legato_use_glider_pressure:
        glider_pressure = dive_nc_file.variables["pressure"][:]
        glider_t = dive_nc_file.variables["time"][:]
        press_f = scipy.interpolate.interp1d(
            glider_t, glider_pressure, kind="linear", bounds_error=False, fill_value=0.0
        )
        pressure = press_f(legato_time)
    else:
        if "legato_pressure" in dive_nc_file.variables:
            pressure = dive_nc_file.variables["legato_pressure"][:]
        else:
            pressure = dive_nc_file.variables["eng_rbr_pressure"][:]

    log_gps_lat = dive_nc_file.variables["log_gps_lat"][:]

    if not base_opts.use_gsw:
        depth = seawater.dpth(pressure, log_gps_lat[0])
    else:
        depth = -1.0 * gsw.z_from_p(pressure, log_gps_lat[0], 0.0, 0.0)

    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = legato_time[0]

    if "aa4831_temp" in dive_nc_file.variables:
        aa4831_temp = dive_nc_file.variables["aa4831_temp"][:]
        aa4831_time = dive_nc_file.variables["aa4831_time"][:]
        depth_f = scipy.interpolate.interp1d(
            legato_time, depth, kind="linear", bounds_error=False, fill_value=0.0
        )
        aa4831_depth = depth_f(aa4831_time)
        max_depth_sample_index = np.argmax(aa4831_depth)

        # Create dive and climb vectors
        aa4831_depth_dive = aa4831_depth[0:max_depth_sample_index]
        aa4831_depth_climb = aa4831_depth[max_depth_sample_index:]

        aa4831_temp_dive = aa4831_temp[0:max_depth_sample_index]
        aa4831_temp_climb = aa4831_temp[max_depth_sample_index:]
    else:
        aa4831_temp_dive = aa4831_temp_climb = None

    # Filter bad points - note, this includes NaNs which are common
    # in the legato on truck case
    temp_mask = (temp >= -4.0) & (temp <= 40.0)
    cond_mask = (conductivity >= 0.0) & (conductivity <= 40.0)
    depth_mask = (depth >= 0.0) & (depth <= 1090.0)

    mask = cond_mask & temp_mask & depth_mask

    depth = depth[mask]
    temp = temp[mask]
    cond_temp = cond_temp[mask]
    conductivity = conductivity[mask]
    pressure = pressure[mask]
    legato_time = legato_time[mask]

    # Find the deepest sample
    max_depth_sample_index = np.argmax(depth)

    # Create dive and climb vectors
    depth_dive = depth[0:max_depth_sample_index]
    depth_climb = depth[max_depth_sample_index:]

    temp_dive = temp[0:max_depth_sample_index]
    temp_climb = temp[max_depth_sample_index:]

    cond_temp_dive = cond_temp[0:max_depth_sample_index]
    cond_temp_climb = cond_temp[max_depth_sample_index:]

    conductivity_dive = conductivity[0:max_depth_sample_index]
    conductivity_climb = conductivity[max_depth_sample_index:]

    if not base_opts.use_gsw:
        salinity = seawater.salt(
            conductivity / (seawater.constants.c3515 / 10.0), temp, pressure
        )
    else:
        salinity = gsw.SP_from_C(conductivity * 10.0, temp, pressure)

    salinity_dive = salinity[0:max_depth_sample_index]
    salinity_climb = salinity[max_depth_sample_index:]

    time_dive = (legato_time[0:max_depth_sample_index] - legato_time[0]) / 60.0
    time_climb = (legato_time[max_depth_sample_index:] - legato_time[0]) / 60.0

    # For samples and timeout plots
    sg_good_pts = np.logical_and(
        np.logical_not(np.isnan(dive_nc_file.variables["time"][:])),
        np.logical_not(np.isnan(dive_nc_file.variables["depth"][:])),
    )
    f_depth = scipy.interpolate.PchipInterpolator(
        dive_nc_file.variables["time"][sg_good_pts],
        dive_nc_file.variables["depth"][sg_good_pts],
        extrapolate=True,
    )
    max_depth = np.nanmax(depth)

    fig = plotly.graph_objects.Figure()

    # Plot Temp and Salinity vs depth

    fig.add_trace(
        {
            "y": depth_dive,
            "x": salinity_dive,
            "meta": time_dive,
            "name": "Legato Raw Salinity Dive",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "DarkBlue",
            },
            "hovertemplate": "Legato Salin Dive<br>%{x:.2f} psu<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
        }
    )
    fig.add_trace(
        {
            "y": depth_climb,
            "x": salinity_climb,
            "meta": time_climb,
            "name": "Legato Raw Salinity Climb",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "DarkGreen",
            },
            "hovertemplate": "Legato Salin Climb<br>%{x:.2f} psu<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": depth_dive,
            "x": conductivity_dive,
            "meta": time_dive,
            "name": "Legato Raw Conductivity Dive",
            "type": "scatter",
            "xaxis": "x3",
            "yaxis": "y1",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "LightSlateGrey",
            },
            "hovertemplate": "Legato Cond Dive<br>%{x:.4f} S/m<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            "visible": "legendonly",
        }
    )
    fig.add_trace(
        {
            "y": depth_climb,
            "x": conductivity_climb,
            "meta": time_climb,
            "name": "Legato Raw Conductivity Climb",
            "type": "scatter",
            "xaxis": "x3",
            "yaxis": "y1",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "DarkSlateGrey",
            },
            "hovertemplate": "Legato Cond Climb<br>%{x:.4f} S/m<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            "visible": "legendonly",
        }
    )

    fig.add_trace(
        {
            "y": depth_dive,
            "x": temp_dive,
            "meta": time_dive,
            "name": "Legato Raw Temp Dive",
            "type": "scatter",
            "xaxis": "x2",
            "yaxis": "y2",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "DarkMagenta",
            },
            "hovertemplate": "Legato Temp Dive<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
        }
    )
    fig.add_trace(
        {
            "y": depth_climb,
            "x": temp_climb,
            "meta": time_climb,
            "name": "Legato Raw Temp Climb",
            "type": "scatter",
            "xaxis": "x2",
            "yaxis": "y2",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "DarkRed",
            },
            "hovertemplate": "Legato Temp Climb<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": depth_dive,
            "x": cond_temp_dive,
            "meta": time_dive,
            "name": "Legato Raw Conduc Temp Dive",
            "type": "scatter",
            "xaxis": "x2",
            "yaxis": "y2",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "goldenrod",
            },
            "hovertemplate": "Legato Conduc Temp Dive<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            "visible": "legendonly",
        }
    )
    fig.add_trace(
        {
            "y": depth_climb,
            "x": cond_temp_climb,
            "meta": time_climb,
            "name": "Legato Raw Conduc Temp Climb",
            "type": "scatter",
            "xaxis": "x2",
            "yaxis": "y2",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "darkgoldenrod",
            },
            "hovertemplate": "Legato Conduc Temp Climb<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            "visible": "legendonly",
        }
    )

    if aa4831_temp_dive is not None:
        fig.add_trace(
            {
                "y": aa4831_depth_dive,
                "x": aa4831_temp_dive,
                "meta": time_dive,
                "name": "aa4831 Temp Dive",
                "type": "scatter",
                "xaxis": "x2",
                "yaxis": "y2",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "Cyan",
                },
                "hovertemplate": "aa4831 Temp Dive<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                "visible": "legendonly",
            }
        )

    if aa4831_temp_climb is not None:
        fig.add_trace(
            {
                "y": aa4831_depth_climb,
                "x": aa4831_temp_climb,
                "meta": time_climb,
                "name": "aa4831 Temp Climb",
                "type": "scatter",
                "xaxis": "x2",
                "yaxis": "y2",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "DarkCyan",
                },
                "hovertemplate": "aa4831 Temp Climb<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                "visible": "legendonly",
            }
        )

    timeouts, timeouts_times = PlotUtils.collect_timeouts(
        dive_nc_file,
        "legato",
    )

    if timeouts:
        PlotUtils.add_timeout_overlays(
            timeouts,
            timeouts_times,
            fig,
            f_depth,
            legato_time,
            max_depth_sample_index,
            max_depth,
            start_time,
            "DarkMagenta",  # To match insturment dive trace
            "DarkRed",  # To match instrument climb trace
        )

    PlotUtils.add_sample_range_overlay(
        legato_time,
        max_depth_sample_index,
        start_time,
        fig,
        f_depth,
    )

    # fig.update_yaxes(autorange="reversed")

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = "%s<br>Legato Raw Temperature and Salinity vs Depth" % (
        mission_dive_str,
    )
    fig.update_layout(
        {
            "xaxis": {
                "title": "Salinity (PSU)",
                "showgrid": False,
            },
            "yaxis": {
                "title": "Depth (m)",
                "range": [
                    max(
                        depth_dive.max() if len(depth_dive) > 0 else 0,
                        depth_climb.max() if len(depth_climb) > 0 else 0,
                    ),
                    0,
                ],
                "domain": (0.1, 1.0),
            },
            "xaxis2": {
                "title": "Temperature (C)",
                "overlaying": "x1",
                "side": "top",
            },
            "xaxis3": {
                "title": "Conductivity (S/m)",
                "showgrid": False,
                "overlaying": "x1",
                "side": "bottom",
                "anchor": "free",
                "position": 0.05,
            },
            "yaxis2": {
                # Interfers with other legend items
                # "title": "Depth (m)",
                "overlaying": "y1",
                "side": "right",
                #'autorange' : 'reversed',
                "range": [
                    max(
                        depth_dive.max() if len(depth_dive) > 0 else 0,
                        depth_climb.max() if len(depth_climb) > 0 else 0,
                    ),
                    0,
                ],
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
                # "b": 150,
            },
        }
    )

    # Instrument cal date
    if "sg_cal_calibcomm" in dive_nc_file.variables:
        cal_text = (
            dive_nc_file.variables["sg_cal_calibcomm"][:].tobytes().decode("utf-8")
        )
        # if timeouts:
        #    cal_text += f" Timeouts:{timeouts:d}"

        fig.update_layout(
            {
                "annotations": tuple(
                    [
                        {
                            "text": cal_text,
                            "showarrow": False,
                            "xref": "paper",
                            "yref": "paper",
                            "x": 0.0,
                            "y": -0.08,
                        }
                    ]
                )
            }
        )

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_legato" % dive_nc_file.dive_number,
            fig,
        ),
    )
