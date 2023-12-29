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

"""Plots legato corrections """

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing

import gsw
import plotly.graph_objects
import scipy
import seawater

import numpy as np

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
import QC

from BaseLog import log_error
from Plotting import plotdivesingle


@plotdivesingle
def plot_legato_corrections(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plot showing results for legato thermal-inertia correction"""
    if not generate_plots:
        return ([], [])

    try:
        if "legato_temp" in dive_nc_file.variables:
            legato_temp = dive_nc_file.variables["legato_temp"][:]
            legato_cond = dive_nc_file.variables["legato_conduc"][:] / 10.0
            legato_time = dive_nc_file.variables["legato_time"][:]
        elif "eng_rbr_temp" in dive_nc_file.variables:
            legato_temp = dive_nc_file.variables["eng_rbr_temp"][:]
            legato_cond = dive_nc_file.variables["eng_rbr_conduc"][:] / 10.0
            legato_time = dive_nc_file.variables["time"][:]
        else:
            return ([], [])
    except Exception:
        log_error("Could not load legato data found", "exc")
        return ([], [])

    legato_raw_valid_i = np.logical_and.reduce(
        (
            np.logical_not(np.isnan(legato_temp)),
            np.logical_not(np.isnan(legato_cond)),
            np.logical_not(np.isnan(legato_time)),
        )
    )

    try:
        corr_temperature = dive_nc_file.variables["temperature"][:]
        corr_temperature_qc = QC.decode_qc(dive_nc_file.variables["temperature_qc"][:])
        temperature_good_i = QC.find_qc(corr_temperature_qc, QC.only_good_qc_values)
        corr_salinity = dive_nc_file.variables["salinity"][:]
        corr_salinity_qc = QC.decode_qc(dive_nc_file.variables["salinity_qc"][:])
        salinity_good_i = QC.find_qc(corr_salinity_qc, QC.only_good_qc_values)
        # Use ctd_pressure since it has already been through the legato pressure despiker
        ctd_press = dive_nc_file.variables["ctd_pressure"][:]
        ctd_time = dive_nc_file.variables["ctd_time"][:]
        start_time = dive_nc_file.start_time
    except Exception:
        log_error("Could not load corrected temperature or salinity", "exc")
        return ([], [])

    ctd_time = (ctd_time - start_time) / 60.0
    legato_time = (legato_time - start_time) / 60.0

    if not base_opts.use_gsw:
        legato_salinity = seawater.salt(
            legato_cond / (seawater.constants.c3515 / 10.0), legato_temp, ctd_press
        )
    else:
        legato_salinity = gsw.SP_from_C(legato_cond * 10.0, legato_temp, ctd_press)

    fig = plotly.graph_objects.Figure()

    fig.add_trace(
        {
            "name": "Legato Raw Salinity",
            "x": legato_time[legato_raw_valid_i],
            "y": legato_salinity[legato_raw_valid_i],
            "yaxis": "y1",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3, "color": "DarkBlue"},
            "hovertemplate": "Raw Salin<br>%{x:.2f} min<br>%{y:.2f} PSU<extra></extra>",
        }
    )
    fig.add_trace(
        {
            "name": "Legato Raw Temp",
            "x": legato_time[legato_raw_valid_i],
            "y": legato_temp[legato_raw_valid_i],
            "yaxis": "y2",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3, "color": "DarkMagenta"},
            "hovertemplate": "Raw Temp<br>%{x:.2f} min<br>%{y:.3f} C<extra></extra>",
        }
    )
    fig.add_trace(
        {
            "name": "Legato Corr Salinity",
            "x": ctd_time[salinity_good_i],
            "y": corr_salinity[salinity_good_i],
            "yaxis": "y1",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3, "color": "DarkGreen"},
            "hovertemplate": "Corr Salin<br>%{x:.2f} min<br>%{y:.2f} PSU<extra></extra>",
        }
    )
    fig.add_trace(
        {
            "name": "Legato Corr Temp",
            "x": ctd_time[temperature_good_i],
            "y": corr_temperature[temperature_good_i],
            "yaxis": "y2",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3, "color": "DarkRed"},
            "hovertemplate": "Corr Temp<br>%{x:.2f} min<br>%{y:.3f} C<extra></extra>",
        }
    )

    # # Highlight differnces
    # changed_points = np.squeeze(
    #     np.nonzero(
    #         np.abs(corr_salinity[salinity_good_i] - legato_salinity[salinity_good_i])
    #         > 0.000001
    #     )
    # )
    # fig.add_trace(
    #     {
    #         "name": "salinity differences",
    #         "x": ctd_time[changed_points],
    #         "y": corr_salinity[changed_points],
    #         "mode": "markers",
    #         "marker": {"symbol": "circle"},
    #         "visible": True,
    #         "hovertemplate": "Diff in salinity<br>%{x:.2f} mins<br>%{y:.2f} PSU<extra></extra>",
    #     }
    # )

    # changed_points = np.squeeze(
    #     np.nonzero(
    #         np.abs(
    #             corr_temperature[temperature_good_i] - legato_temp[temperature_good_i]
    #         )
    #         > 0.0001
    #     )
    # )
    # fig.add_trace(
    #     {
    #         "name": "temperature differences",
    #         "x": ctd_time[changed_points],
    #         "y": corr_temperature[changed_points],
    #         "yaxis": "y2",
    #         "mode": "markers",
    #         "marker": {"symbol": "circle"},
    #         "visible": True,
    #         "hovertemplate": "Diff in temperature<br>%{x:.2f} mins<br>%{y:.3f} C<extra></extra>",
    #     }
    # )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = (
        "%s<br>Legato Raw Temp/Salinity and Corrected Temp/Salinity vs Time"
        % (mission_dive_str,)
    )

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
                "domain": [0.1, 0.9],
            },
            "yaxis": {
                "title": "Conductivity (PSU)",
                "showgrid": True,
                "autorange": "reversed",
            },
            "yaxis2": {
                "title": "Temperature (C)",
                "showgrid": False,
                "side": "right",
                "overlaying": "y1",
                # "autorange": "reversed",
                "anchor": "x",
            },
            "margin": {
                "t": 150,
            },
            "legend": {
                "x": 1.05,
                "y": 1,
            },
            # "width": std_width,
            # "height": std_height,
        }
    )

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_legato_corr_compare" % dive_nc_file.dive_number,
            fig,
        ),
    )
