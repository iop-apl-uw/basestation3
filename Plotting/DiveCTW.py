#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022, 2023 by University of Washington.  All rights reserved.
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

"""Plots gliders course through the water """

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing

import numpy as np
import plotly.graph_objects

if typing.TYPE_CHECKING:
    import BaseOpts
    import scipy

import PlotUtils
import PlotUtilsPlotly
from BaseLog import log_error, log_debug
from Plotting import plotdivesingle


@plotdivesingle
def plot_CTW(
    base_opts: BaseOpts.BaseOptions, dive_nc_file: scipy.io._netcdf.netcdf_file
) -> tuple[list, list]:
    """Plots the glider course through the water"""
    # TODO create roll to right and left vectors
    # TODO add new traces that overlay exiting traces with low alpha circles
    # TODO see grouped_legend.py for how to group things into one trace
    # TODO add relevant text to plot (or legand)

    # Preliminaries
    try:
        start_time = dive_nc_file.start_time
        ctd_time = (dive_nc_file.variables["ctd_time"][:] - start_time) / 60.0
        north_disp = dive_nc_file.variables["north_displacement"][:]
        east_disp = dive_nc_file.variables["east_displacement"][:]
        north_disp_gsm = dive_nc_file.variables["north_displacement_gsm"][:]
        east_disp_gsm = dive_nc_file.variables["east_displacement_gsm"][:]
        mhead = [
            float(s)
            for s in dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
            .tobytes()
            .decode("utf-8")
            .split(",")
        ]
        errband = float(dive_nc_file.variables["log_HEAD_ERRBAND"].getValue())
        if "log_gps_magvar" in dive_nc_file.variables:
            magvar = dive_nc_file.variables["log_gps_magvar"][:][0]
        elif "magnetic_variation" in dive_nc_file.variables:
            # Vendor Basestation
            magvar = dive_nc_file.variables["magnetic_variation"].getValue()
        else:
            log_error("Could not find the magvar for plot_CTW", "exc")
    except:
        log_error("Problems in plot_CTW", "exc")
        return ([], [])

    desired_head = mhead[0]
    north_disp_cum = np.cumsum(north_disp)
    east_disp_cum = np.cumsum(east_disp)

    north_disp_gsm_cum = np.cumsum(north_disp_gsm)
    east_disp_gsm_cum = np.cumsum(east_disp_gsm)

    disp = np.sqrt(north_disp_cum[-1] ** 2 + east_disp_cum[-1] ** 2)

    log_debug(
        f"Total displacement {disp} (m) desired heading {desired_head:f} (deg), magvar {magvar:f} (deg)"
    )

    # _, gc_roll_time, gc_roll_pos, gc_pitch_time, gc_pitch_pos, gc_vbd_time, gc_vbd_pos = extract_gc_moves(dive_nc_file)

    fig = plotly.graph_objects.Figure()

    fig.add_trace(
        {
            "y": north_disp_cum,
            "x": east_disp_cum,
            "meta": ctd_time,
            "name": "Course Through Water HDM",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "circle",
                "color": "DarkBlue",
                "size": 2,
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            "hovertemplate": "CTW HDM<br>Northward %{y:.1f} m<br>Eastward %{x:.1f} m<br>%{meta:.2f} mins<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": north_disp_gsm_cum,
            "x": east_disp_gsm_cum,
            "meta": ctd_time,
            "name": "Course Through Water GSM",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "circle",
                "color": "DarkGreen",
                "size": 2,
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            "hovertemplate": "CTW GSM<br>Northward %{y:.1f} m<br>Eastward %{x:.1f} m<br>%{meta:.2f} mins<extra></extra>",
        }
    )

    def roll_heading(deg):
        if deg >= 360.0:
            deg -= 360.0
        if deg < 0:
            deg += 360.0
        return deg

    # Add heading cone
    def line_end(deg, disp):
        deg = roll_heading(deg)
        return (np.sin(np.radians(deg)) * disp, np.cos(np.radians(deg)) * disp)

    # TODO - need annotations in the legend
    for head, head_label, head_color in (
        (desired_head, "head", "Red"),
        (roll_heading(desired_head + errband), "head+errband", "Black"),
        (roll_heading(desired_head - errband), "head-errband", "Black"),
    ):
        x, y = line_end(head + magvar, disp * 1.1)
        log_debug(f"head:{head:f} x:{x:f} y:{y:f}")
        # fig.add_shape(
        #     plotly.graph_objects.layout.Shape(
        #         name="Desired Heading",
        #         type="line",
        #         x0=0,
        #         y0=0,
        #         x1=x,
        #         y1=y,
        #         line=dict(
        #             color="Red" if head == desired_head else "Black",
        #             width=1,
        #             dash="solid",
        #         ),
        #     )
        # )
        fig.add_trace(
            {
                "name": f"{head_label} {head:.2f} deg mag",
                "y": [0, y],
                "x": [0, x],
                "type": "scatter",
                "mode": "lines",
                "line": {"dash": "solid", "color": head_color},
                "hovertemplate": f"{head:.2f} deg mag<extra></extra>",
            }
        )
    # Needed to get the origin for the lines to be 0,0 on the plot
    # fig.update_shapes(dict(xref="x", yref="y"))

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = f"{mission_dive_str}<br>Course through Water"

    if np.nanmax(np.absolute(north_disp_gsm_cum)) > np.nanmax(
        np.absolute(east_disp_gsm_cum)
    ):
        xconstrain_key = "scaleanchor"
        xconstrain_value = "y"
        yconstrain_key = "constrain"
        yconstrain_value = "domain"
    else:
        xconstrain_key = "constrain"
        xconstrain_value = "domain"
        yconstrain_key = "scaleanchor"
        yconstrain_value = "x"

    fig.update_layout(
        {
            "xaxis": {
                "title": "Eastward Displacment Through Water (m)",
                "showgrid": True,
                #'range' : [min_salinity, max_salinity],
                xconstrain_key: xconstrain_value,
            },
            "yaxis": {
                "title": "Northward Displacment Through Water (m)",
                #'range' : [max(depth_dive.max() if len(depth_dive) > 0 else 0, depth_climb.max() if len(depth_climb) > 0 else 0), 0]
                yconstrain_key: yconstrain_value,
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
            base_opts, "dv%04d_ctw" % (dive_nc_file.dive_number,), fig
        ),
    )
