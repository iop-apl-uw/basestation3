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

"""Plots legaot pressure data """

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing

import numpy as np
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
import QC
from BaseLog import log_error
from Plotting import plotdivesingle


@plotdivesingle
def plot_legato_pressure(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
) -> tuple[list, list]:
    """Plots the raw legato pressure, the ctd_pressure (smoothed) and locations for the
    interpolated points
    """

    if (
        "legato_pressure" not in dive_nc_file.variables
        and "eng_rbr_pressure" not in dive_nc_file.variables
    ) or not generate_plots:
        return ([], [])

    try:
        legato_time = dive_nc_file.variables["legato_time"][:]
        legato_pressure = dive_nc_file.variables["legato_pressure"][:]
    except:
        try:
            legato_time = dive_nc_file.variables["time"][:]
            legato_pressure = dive_nc_file.variables["eng_rbr_pressure"][:]
        except:
            log_error(
                "Could not legato pressure in scicon or on truck - skipping plot", "exc"
            )
            return ([], [])

    try:
        ctd_time = dive_nc_file.variables["ctd_time"][:]
        ctd_pressure = dive_nc_file.variables["ctd_pressure"][:]
        ctd_pressure_qc = QC.decode_qc(dive_nc_file.variables["ctd_pressure_qc"][:])
        sg_pressure = dive_nc_file.variables["pressure"][:]
        sg_time = dive_nc_file.variables["time"][:]
    except:
        log_error("Could not find needed variables - skipping plot", "exc")
        return ([], [])

    aux_pressure_name = None
    if "auxB_press" in dive_nc_file.variables:
        aux_pressure_name = "auxB"
    if "auxCompass_press" in dive_nc_file.variables:
        aux_pressure_name = "auxCompass"

    if aux_pressure_name:
        aux_pressure = dive_nc_file.variables[f"{aux_pressure_name}_press"][:]
        aux_time = dive_nc_file.variables[f"{aux_pressure_name}_time"][:]

    try:
        start_time = dive_nc_file.start_time
    except KeyError:
        start_time = None

    if start_time:
        legato_dive_time = (legato_time - start_time) / 60.0
        ctd_dive_time = (ctd_time - start_time) / 60.0
        sg_dive_time = (sg_time - start_time) / 60.0
        if aux_pressure_name:
            aux_time = (aux_time - start_time) / 60.0

    fig = plotly.graph_objects.Figure()

    fig.add_trace(
        {
            "name": "legato pressure",
            "x": legato_dive_time,
            "y": legato_pressure,
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3},
            "hovertemplate": "Pressure from Legato<br>%{x:.2f} mins<br>%{y:.2f} dbar<extra></extra>",
        }
    )

    bad_points = np.nonzero(ctd_pressure_qc == QC.QC_INTERPOLATED)[0]

    fig.add_trace(
        {
            "name": "legato pressure spikes",
            "x": legato_dive_time[bad_points],
            "y": legato_pressure[bad_points],
            "mode": "markers",
            "marker": {"symbol": "circle"},
            "visible": True,
            "hovertemplate": "Despiker detected bad points<br>%{x:.2f} mins<br>%{y:.2f} dbar<extra></extra>",
        }
    )

    legato_dp_dt = np.diff(legato_pressure) / np.diff(legato_time)

    fig.add_trace(
        {
            "name": "legato dp/dt",
            "x": legato_dive_time[1:],
            "y": legato_dp_dt,
            "yaxis": "y2",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3},
            "visible": "legendonly",
            "hovertemplate": "Legato dp/dt<br>%{x:.2f} mins<br>%{y:.2f} dbar/sec<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "name": "ctd_pressure",
            "x": ctd_dive_time,
            "y": ctd_pressure,
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3},
            "visible": True,
            "hovertemplate": "Smoothed legato pressure<br>%{x:.2f} mins<br>%{y:.2f} dbar<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "name": "truck_pressure",
            "x": sg_dive_time,
            "y": sg_pressure,
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3},
            "visible": True,
            "hovertemplate": "Truck pressure<br>%{x:.2f} mins<br>%{y:.2f} dbar<extra></extra>",
        }
    )

    if aux_pressure_name:
        fig.add_trace(
            {
                "name": f"{aux_pressure_name}_pressure",
                "x": aux_time,
                "y": aux_pressure,
                "mode": "lines+markers",
                "line": {"width": 1},
                "marker": {"symbol": "cross", "size": 3},
                "visible": True,
                "hovertemplate": f"{aux_pressure_name} pressure"
                + "<br>%{x:.2f} mins<br>%{y:.2f} dbar<extra></extra>",
            }
        )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = "%s<br>Legato Raw and Smoothed Pressure vs Depth" % (mission_dive_str,)

    fig.update_layout(
        {
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "xaxis": {
                "title": "Time Into Dive (min)",
                "showgrid": True,
            },
            "yaxis": {
                "title": "Pressure",
                "showgrid": True,
                "autorange": "reversed",
            },
            "yaxis2": {
                "title": "dz/dt",
                "showgrid": False,
                "side": "right",
                "overlaying": "y1",
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
            "dv%04d_legato_smoothed" % dive_nc_file.dive_number,
            fig,
        ),
    )
