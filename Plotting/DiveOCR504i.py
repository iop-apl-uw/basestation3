#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025, 2026  University of Washington.
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

"""Plots Satlantic ocr504i"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import pathlib
import typing

import numpy as np
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
from BaseLog import log_error
from Plotting import plotdivesingle


@plotdivesingle
def plot_ocr504i(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Plots raw output from Satlantic ocr504i"""

    if (
        "ocr504i_time" not in dive_nc_file.variables
        and "eng_ocr504i" not in dive_nc_file.variables
    ) or not generate_plots:
        return ([], [])

    scicon = "ocr504i_time" in dive_nc_file.variables

    # Preliminaries
    ocr504i_color_map_dive = ["Red", "goldenrod", "Blue", "Aqua"]
    ocr504i_color_map_climb = ["DarkRed", "darkgoldenrod", "DarkBlue", "DarkCyan"]
    ocr504i_channel_map = ["412.3 nm", "443.58 nm", "554.47 nm", "PAR"]

    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = None

    binned_profile = "profile_data_point" in dive_nc_file.dimensions
    binned_tag = ""

    chans = [None] * 4
    try:
        for ii in range(4):
            chans[ii] = dive_nc_file.variables[
                "%socr504i_chan%d"
                % ("" if scicon or binned_profile else "eng_", ii + 1)
            ][:]
        depth = dive_nc_file.variables["depth"][:]
        sg_time = dive_nc_file.variables["time"][:]
        # Interpolate around missing depth observations
        depth = PlotUtils.interp_missing_depth(sg_time, depth)

        if binned_profile:
            binned_tag = " - binned %.1f m" % (
                np.round(np.average(np.diff(depth[0, :])), decimals=1),
            )

    except Exception:
        log_error("Could not ocr504i variables", "exc")
        return ([], [])

    if scicon:
        try:
            ocr504i_time = dive_nc_file.variables["ocr504i_time"][:]
        except Exception:
            log_error("Could not ocr504i variables", "exc")
            return ([], [])

        # Interp
        f = scipy.interpolate.interp1d(
            sg_time, depth, kind="linear", bounds_error=False, fill_value=0.0
        )
        depth = f(ocr504i_time)
    else:
        ocr504i_time = sg_time

    chans_dive = [None] * 4
    chans_climb = [None] * 4

    if binned_profile:
        max_depth_sample_index = None
        # Create dive and climb vectors
        depth_dive = depth[0, :]
        depth_climb = depth[1, :]

        if not start_time:
            start_time = sg_time[0, 0]

        time_dive = (ocr504i_time[0, :] - start_time) / 60.0
        time_climb = (ocr504i_time[1, :] - start_time) / 60.0

        for ii in range(4):
            chans_dive[ii] = chans[ii][0, :]
            chans_climb[ii] = chans[ii][1, :]
    else:
        # Find the deepest sample
        max_depth_sample_index = np.argmax(depth)

        # Create dive and climb vectors
        depth_dive = depth[0:max_depth_sample_index]
        depth_climb = depth[max_depth_sample_index:]

        if not start_time:
            start_time = sg_time[0]

        time_dive = (ocr504i_time[0:max_depth_sample_index] - start_time) / 60.0
        time_climb = (ocr504i_time[max_depth_sample_index:] - start_time) / 60.0

        for ii in range(4):
            chans_dive[ii] = chans[ii][0:max_depth_sample_index]
            chans_climb[ii] = chans[ii][max_depth_sample_index:]

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

    # single_units = "\mu$W$/cm^2/nm$"
    # par_units = "$\mu$mol$/m^2/sec$"
    single_units = "uW/cm^2/nm"
    par_units = "umol/m^2/sec"

    for ii in range(3):
        if len(chans_dive[ii]) != 0:
            fig.add_trace(
                {
                    "y": depth_dive,
                    "x": chans_dive[ii],
                    "meta": time_dive,
                    "name": f"{ocr504i_channel_map[ii]} Dive",
                    "type": "scatter",
                    "xaxis": "x1",
                    "yaxis": "y1",
                    "mode": "markers+lines",
                    "marker": {
                        "symbol": "triangle-down",
                        "color": ocr504i_color_map_dive[ii],
                    },
                    "hovertemplate": f"{ocr504i_channel_map[ii]} Dive<br>"
                    + "%{x:.2f} "
                    + single_units
                    + "<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                }
            )
        if len(chans_climb[ii]) != 0:
            fig.add_trace(
                {
                    "y": depth_climb,
                    "x": chans_climb[ii],
                    "meta": time_climb,
                    "name": f"{ocr504i_channel_map[ii]} Climb",
                    "type": "scatter",
                    "xaxis": "x1",
                    "yaxis": "y1",
                    "mode": "markers+lines",
                    "marker": {
                        "symbol": "triangle-up",
                        "color": ocr504i_color_map_climb[ii],
                    },
                    "hovertemplate": f"{ocr504i_channel_map[ii]} Climb<br>"
                    + "%{x:.2f} "
                    + single_units
                    + "<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                }
            )

    if len(chans_dive[3]) != 0:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": chans_dive[3],
                "meta": time_dive,
                "name": f"{ocr504i_channel_map[3]} Dive",
                "type": "scatter",
                "xaxis": "x2",
                "yaxis": "y1",
                "mode": "markers+lines",
                "marker": {
                    "symbol": "triangle-down",
                    "color": ocr504i_color_map_dive[3],
                },
                "hovertemplate": f"{ocr504i_channel_map[3]} Dive<br>"
                + "%{x:.2f} "
                + par_units
                + "<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )

    if len(chans_climb[3]) != 0:
        fig.add_trace(
            {
                "y": depth_climb,
                "x": chans_climb[3],
                "meta": time_climb,
                "name": f"{ocr504i_channel_map[3]} Climb",
                "type": "scatter",
                "xaxis": "x2",
                "yaxis": "y1",
                "mode": "markers+lines",
                "marker": {
                    "symbol": "triangle-up",
                    "color": ocr504i_color_map_climb[3],
                },
                "hovertemplate": f"{ocr504i_channel_map[3]} Climb<br>"
                + "%{x:.2f} "
                + par_units
                + "<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )

        # Only for time series plots
        timeouts = None
        if max_depth_sample_index is not None:
            timeouts, timeouts_times = PlotUtils.collect_timeouts(
                dive_nc_file,
                "ocr504i",
            )

            if timeouts:
                PlotUtils.add_timeout_overlays(
                    timeouts,
                    timeouts_times,
                    fig,
                    f_depth,
                    ocr504i_time,
                    max_depth_sample_index,
                    max_depth,
                    start_time,
                    "Red",  # To match insturment dive trace
                    "DarkRed",  # To match instrument climb trace
                )

            PlotUtils.add_sample_range_overlay(
                base_opts,
                "ocr504i",
                dive_nc_file.dive_number,
                ocr504i_time,
                max_depth_sample_index,
                start_time,
                fig,
                f_depth,
            )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = f"{mission_dive_str}<br>PAR OCR504i Output vs Depth{binned_tag}"
    output_name = "dv%04d_ocr504i" % dive_nc_file.dive_number

    fig.update_layout(
        {
            "xaxis": {
                # "title": r"Single wavelength $\mu$W$/cm^2/nm$",
                "title": f"Single wavelength {single_units}",
                "showgrid": False,
            },
            "yaxis": {
                "title": "Depth (m)",
                "autorange": "reversed",
            },
            "xaxis2": {
                # "title": r"PAR output $\mu$mol$/m^2/sec$",
                "title": f"PAR output {par_units}",
                "overlaying": "x1",
                "side": "top",
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
        }
    )

    updatemenus = [
        dict(
            type="buttons",
            direction="down",
            buttons=list(
                [
                    dict(
                        args=[{"xaxis.type": "linear", "xaxis2.type": "linear"}],
                        label="Linear Scale",
                        method="relayout",
                    ),
                    dict(
                        args=[{"xaxis.type": "log", "xaxis2.type": "log"}],
                        label="Log Scale",
                        method="relayout",
                    ),
                ]
            ),
        ),
    ]
    fig.update_layout(updatemenus=updatemenus)
    return ([fig], PlotUtilsPlotly.write_output_files(base_opts, output_name, fig))
