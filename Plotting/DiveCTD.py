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

"""Plots CTD data"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import pathlib
import typing
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import BaseOpts

import BaseOptsType
import MakeDiveProfiles
import PlotUtils
import PlotUtilsPlotly
import QC
import Utils
from BaseLog import log_debug, log_error, log_info, log_warning
from Plotting import add_arguments, plotdivesingle


@dataclass
class CTDVars:
    """Class for returning CTD vars for plotting routines"""

    binned_profile: bool = False
    ctd_depth_m_v: npt.NDArray[np.float64] | None = None
    ctd_time_v: npt.NDArray[np.float64] | None = None
    bin_width: float = 0.0
    aa4831_temp_dive: npt.NDArray[np.float64] | None = None
    aa4831_temp_climb: npt.NDArray[np.float64] | None = None
    optode_name: str | None = None
    aa4831_depth_dive: npt.NDArray[np.float64] | None = None
    aa4831_depth_climb: npt.NDArray[np.float64] | None = None
    point_num_aa4831_dive: npt.NDArray[np.float64] | None = None
    point_num_aa4831_climb: npt.NDArray[np.float64] | None = None
    qc_tag: str = ""
    depth_dive: npt.NDArray[np.float64] | None = None
    depth_climb: npt.NDArray[np.float64] | None = None
    time_dive: npt.NDArray[np.float64] | None = None
    time_climb: npt.NDArray[np.float64] | None = None
    temp_dive: npt.NDArray[np.float64] | None = None
    temp_climb: npt.NDArray[np.float64] | None = None
    salinity_dive: npt.NDArray[np.float64] | None = None
    salinity_climb: npt.NDArray[np.float64] | None = None
    point_num_ctd_dive: npt.NDArray[np.float64] | None = None
    point_num_ctd_climb: npt.NDArray[np.float64] | None = None
    conductivity_dive: npt.NDArray[np.float64] | None = None
    conductivity_climb: npt.NDArray[np.float64] | None = None
    conductivity: npt.NDArray[np.float64] | None = None
    surface_depth: float = 0.0
    min_salinity: float | None = None
    max_salinity: float | None = None
    min_temperature: float | None = None
    max_temperature: float | None = None
    is_legato: bool = False


def load_ctd_vars(dive_nc_file, temp_name, salinity_name, conductivity_name):
    """Loads CTD vars for plotting routines"""
    ctd_vars = CTDVars()

    ctd_vars.binned_profile = "profile_data_point" in dive_nc_file.dimensions

    if "ctd_depth" in dive_nc_file.variables and "ctd_time" in dive_nc_file.variables:
        ctd_vars.ctd_depth_m_v = dive_nc_file.variables["ctd_depth"][:]
        ctd_vars.ctd_time_v = dive_nc_file.variables["ctd_time"][:]
    elif ctd_vars.binned_profile:
        # SimpleNetCDF binned product
        ctd_vars.ctd_depth_m_v = dive_nc_file.variables["depth"][:]
        ctd_vars.ctd_time_v = dive_nc_file.variables["time"][:]
        ctd_vars.bin_width = np.round(
            np.average(np.diff(ctd_vars.ctd_depth_m_v[0, :])), decimals=1
        )
    else:
        log_info("Could not load ctd_depth nc varible for plot_ctd_data - skipping")
        return None

    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = None

    ctd_vars.aa4831_temp_dive = ctd_vars.aa4831_temp_climb = ctd_vars.optode_name = None

    if "aa4831_temp" in dive_nc_file.variables:
        ctd_vars.optode_name = "aa4831"
    elif "aa4330_temp" in dive_nc_file.variables:
        ctd_vars.optode_name = "aa4330"

    is_scicon = True
    if "aa4831_temp" in dive_nc_file.variables:
        ctd_vars.optode_name = "aa4831"
        optode_temp_name = "aa4831_temp"
    elif "eng_aa4831_Temp" in dive_nc_file.variables:
        ctd_vars.optode_name = "aa4831"
        optode_temp_name = "eng_aa4831_Temp"
        is_scicon = False
    elif "aa4330_temp" in dive_nc_file.variables:
        ctd_vars.optode_name = "aa4330"
        optode_temp_name = "aa4330_temp"
    elif "eng_aa4330_Temp" in dive_nc_file.variables:
        ctd_vars.optode_name = "aa4330"
        optode_temp_name = "eng_aa4330_Temp"
        is_scicon = False
    elif "codaTODO_temp" in dive_nc_file.variables:
        ctd_vars.optode_name = "codaTODO"
        optode_temp_name = "codaTODO_temp"
        is_scicon = True
    elif "eng_codaTODO_temp" in dive_nc_file.variables:
        ctd_vars.optode_name = "codaTODO"
        optode_temp_name = "eng_codaTODO_temp"
        is_scicon = False

    if ctd_vars.optode_name is not None:
        try:
            sg_time = dive_nc_file.variables["time"][:]
            aa4831_temp = dive_nc_file.variables[optode_temp_name][:]
            if is_scicon:
                aa4831_time = dive_nc_file.variables[f"{ctd_vars.optode_name}_time"][:]
            else:
                aa4831_time = sg_time

            depth = dive_nc_file.variables["depth"][:]

            depth_f = scipy.interpolate.interp1d(
                sg_time, depth, kind="linear", bounds_error=False, fill_value=0.0
            )
            aa4831_depth = depth_f(aa4831_time)
            max_depth_sample_index = np.nanargmax(aa4831_depth)

            # Create dive and climb vectors
            ctd_vars.aa4831_depth_dive = aa4831_depth[0:max_depth_sample_index]
            ctd_vars.aa4831_depth_climb = aa4831_depth[max_depth_sample_index:]

            ctd_vars.aa4831_temp_dive = aa4831_temp[0:max_depth_sample_index]
            ctd_vars.aa4831_temp_climb = aa4831_temp[max_depth_sample_index:]

            ctd_vars.aa4831_time_dive = (
                aa4831_time[0:max_depth_sample_index] - start_time
            ) / 60.0
            ctd_vars.aa4831_time_climb = (
                aa4831_time[max_depth_sample_index:] - start_time
            ) / 60.0

            ctd_vars.point_num_aa4831_dive = np.arange(0, max_depth_sample_index)
            ctd_vars.point_num_aa4831_climb = np.arange(
                max_depth_sample_index, len(aa4831_temp)
            )

        except Exception:
            log_error("Error processing optode temp", "exc")

    if "sg_cal_sg_ct_type" in dive_nc_file.variables:
        ctd_vars.is_legato = dive_nc_file.variables["sg_cal_sg_ct_type"].getValue() == 4
    else:
        ctd_vars.is_legato = False

    if not ctd_vars.is_legato:
        # The range of the raw plot is constrained by the range of the QC_GOOD plot for
        # SBECT.  For legato, let the bounds be different for each plot
        ctd_vars.max_salinity = ctd_vars.min_salinity = ctd_vars.max_temperature = (
            ctd_vars.min_temperature
        ) = None

    # Preliminaries
    temp = salinity = None

    if temp_name in dive_nc_file.variables and salinity_name in dive_nc_file.variables:
        try:
            # MakeDiveProfiles ensures that for temperature and salinity that bad_qc
            # points are set to NaN
            temp = dive_nc_file.variables[temp_name][:]
            salinity = dive_nc_file.variables[salinity_name][:]
            if conductivity_name in dive_nc_file.variables:
                ctd_vars.conductivity = dive_nc_file.variables[conductivity_name][:]
            else:
                ctd_vars.conductivity = None
            # ctd_vars.qc_tag = ""
            if "temperature_qc" in dive_nc_file.variables and "raw" not in temp_name:
                temp_qc = QC.decode_qc(dive_nc_file.variables["temperature_qc"])
                temp = np.ma.array(
                    temp,
                    mask=np.logical_not(
                        QC.find_qc(temp_qc, QC.only_good_qc_values, mask=True)
                    ),
                )
                ctd_vars.qc_tag = " - QC_GOOD"

            if "salinity_qc" in dive_nc_file.variables and "raw" not in salinity_name:
                salinity_qc = QC.decode_qc(dive_nc_file.variables["salinity_qc"])
                salinity = np.ma.array(
                    salinity,
                    mask=np.logical_not(
                        QC.find_qc(salinity_qc, QC.only_good_qc_values, mask=True)
                    ),
                )
                ctd_vars.qc_tag = " - QC_GOOD"

            if (
                "conductivity_qc" in dive_nc_file.variables
                and "raw" not in conductivity_name
            ):
                conductivity_qc = QC.decode_qc(
                    dive_nc_file.variables["conductivity_qc"]
                )
                conductivity = np.ma.array(
                    ctd_vars.conductivity,
                    mask=np.logical_not(
                        QC.find_qc(conductivity_qc, QC.only_good_qc_values, mask=True)
                    ),
                )

        except Exception:
            log_info("Could not load nc varibles for plot_ctd_data - skipping", "exc")
            return None
    else:
        log_warning(
            "Could not find both %s and %s nc variables - skipping"
            % (temp_name, salinity_name)
        )
        return None

    # Remove the surface observations to clean up the raw plot
    # ctd_vars.surface_depth = 2.0
    # ctd_vars.surface_depth = 0.0
    if ctd_vars.binned_profile:
        if not start_time:
            start_time = ctd_vars.ctd_time_v[0, 0]
        ctd_vars.depth_dive = ctd_vars.ctd_depth_m_v[0, :]
        ctd_vars.depth_climb = ctd_vars.ctd_depth_m_v[1, :]
        ctd_vars.time_dive = (ctd_vars.ctd_time_v[0, :] - start_time) / 60.0
        ctd_vars.time_climb = (ctd_vars.ctd_time_v[1, :] - start_time) / 60.0
        ctd_vars.temp_dive = temp[0, :]
        ctd_vars.temp_climb = temp[1, :]
        ctd_vars.salinity_dive = salinity[0, :]
        ctd_vars.salinity_climb = salinity[1, :]
        if conductivity is not None:
            ctd_vars.conductivity_dive = conductivity[0, :]
            ctd_vars.conductivity_climb = conductivity[1, :]
    else:
        if not start_time:
            start_time = ctd_vars.ctd_time_v[0]
        if "raw" in temp_name and ctd_vars.surface_depth > 0.0:
            dive_start = np.amin(
                np.where(ctd_vars.ctd_depth_m_v > ctd_vars.surface_depth)
            )
            dive_end = np.amax(
                np.where(ctd_vars.ctd_depth_m_v > ctd_vars.surface_depth)
            )
        else:
            dive_start = 0
            dive_end = len(ctd_vars.ctd_depth_m_v)

        log_debug("dive_start = %d, dive_end = %d" % (dive_start, dive_end))

        # Find the deepest sample
        max_depth_sample_index = np.nanargmax(ctd_vars.ctd_depth_m_v)

        # Create dive and climb vectors
        ctd_vars.depth_dive = ctd_vars.ctd_depth_m_v[dive_start:max_depth_sample_index]
        ctd_vars.depth_climb = ctd_vars.ctd_depth_m_v[max_depth_sample_index:dive_end]

        ctd_vars.time_dive = (
            ctd_vars.ctd_time_v[dive_start:max_depth_sample_index] - start_time
        ) / 60.0
        ctd_vars.time_climb = (
            ctd_vars.ctd_time_v[max_depth_sample_index:dive_end] - start_time
        ) / 60.0

        ctd_vars.temp_dive = temp[dive_start:max_depth_sample_index]
        ctd_vars.temp_climb = temp[max_depth_sample_index:dive_end]

        ctd_vars.salinity_dive = salinity[dive_start:max_depth_sample_index]
        ctd_vars.salinity_climb = salinity[max_depth_sample_index:dive_end]

        ctd_vars.point_num_ctd_dive = np.arange(dive_start, max_depth_sample_index)
        ctd_vars.point_num_ctd_climb = np.arange(max_depth_sample_index, dive_end)

        if ctd_vars.conductivity is not None:
            ctd_vars.conductivity_dive = ctd_vars.conductivity[
                dive_start:max_depth_sample_index
            ]
            ctd_vars.conductivity_climb = ctd_vars.conductivity[
                max_depth_sample_index:dive_end
            ]

    if ctd_vars.is_legato:
        ctd_vars.max_salinity = ctd_vars.min_salinity = ctd_vars.max_temperature = (
            ctd_vars.min_temperature
        ) = None

    if not ctd_vars.min_salinity:
        ctd_vars.min_salinity = np.nanmin(salinity) - (
            0.05 * abs(np.nanmax(salinity) - np.nanmin(salinity))
        )
    if not ctd_vars.max_salinity:
        ctd_vars.max_salinity = np.nanmax(salinity) + (
            0.05 * abs(np.nanmax(salinity) - np.nanmin(salinity))
        )
    if not ctd_vars.min_temperature:
        ctd_vars.min_temperature = np.nanmin(temp) - (
            0.05 * abs(np.nanmax(temp) - np.nanmin(temp))
        )
    if not ctd_vars.max_temperature:
        ctd_vars.max_temperature = np.nanmax(temp) + (
            0.05 * abs(np.nanmax(temp) - np.nanmin(temp))
        )

    return ctd_vars


@plotdivesingle
def plot_CTD(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots CTD data and Optode Temp (if present)"""

    if "temperature" not in dive_nc_file.variables or not generate_plots:
        return ([], [])

    ret_figs = []
    ret_plots = []

    for temp_name, salinity_name, conductivity_name in (
        ("temperature", "salinity", "conductivity"),
        ("temperature_raw", "salinity_raw", "conductivity_raw"),
    ):
        ctd_vars = load_ctd_vars(
            dive_nc_file, temp_name, salinity_name, conductivity_name
        )
        if ctd_vars is None:
            continue

        fig = plotly.graph_objects.Figure()

        # Plot Temp, Salinity and Conductivity vs depth
        fig.add_trace(
            {
                "y": ctd_vars.depth_dive,
                "x": ctd_vars.salinity_dive,
                "meta": ctd_vars.time_dive,
                "customdata": ctd_vars.point_num_ctd_dive,
                "name": "Salinity Dive",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "DarkBlue",
                    #'line':{'width':1, 'color':'LightSlateGrey'}
                },
                "hovertemplate": "%{x:.2f} psu<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "y": ctd_vars.depth_climb,
                "x": ctd_vars.salinity_climb,
                "meta": ctd_vars.time_climb,
                "customdata": ctd_vars.point_num_ctd_climb,
                "name": "Salinity Climb",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "DarkGreen",
                    #'line':{'width':1, 'color':'LightSlateGrey'}
                },
                "hovertemplate": "%{x:.2f} psu<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
            }
        )

        fig.add_trace(
            {
                "y": ctd_vars.depth_dive,
                "x": ctd_vars.temp_dive,
                "meta": ctd_vars.time_dive,
                "customdata": ctd_vars.point_num_ctd_dive,
                "name": "Temp Dive",
                "type": "scatter",
                "xaxis": "x2",
                "yaxis": "y2",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "DarkMagenta",
                    #'size':10,'line':{'width':1, 'color':'DarkSlateGrey'}
                },
                "hovertemplate": "%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "y": ctd_vars.depth_climb,
                "x": ctd_vars.temp_climb,
                "meta": ctd_vars.time_climb,
                "customdata": ctd_vars.point_num_ctd_climb,
                "name": "Temp Climb",
                "type": "scatter",
                "xaxis": "x2",
                "yaxis": "y2",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "DarkRed",
                    #'size':10, 'line':{'width':1, 'color':'DarkSlateGrey'}
                },
                "hovertemplate": "%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
            }
        )

        if ctd_vars.conductivity is not None:
            fig.add_trace(
                {
                    "y": ctd_vars.depth_dive,
                    "x": ctd_vars.conductivity_dive,
                    "meta": ctd_vars.time_dive,
                    "customdata": ctd_vars.point_num_ctd_dive,
                    "name": "Conductivity Dive",
                    "type": "scatter",
                    "xaxis": "x3",
                    "yaxis": "y1",
                    "mode": "markers",
                    "marker": {
                        "symbol": "triangle-down",
                        "color": "LightSlateGrey",
                    },
                    "hovertemplate": "Conductivity Dive<br>%{x:.4f} S/m<br>%{y:.2f}"
                    + "meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    "visible": "legendonly",
                }
            )

            fig.add_trace(
                {
                    "y": ctd_vars.depth_climb,
                    "x": ctd_vars.conductivity_climb,
                    "meta": ctd_vars.time_climb,
                    "customdata": ctd_vars.point_num_ctd_climb,
                    "name": "Conductivity Climb",
                    "type": "scatter",
                    "xaxis": "x3",
                    "yaxis": "y1",
                    "mode": "markers",
                    "marker": {
                        "symbol": "triangle-up",
                        "color": "DarkSlateGrey",
                    },
                    "hovertemplate": "Conductivity Climb<br>%{x:.4f} S/m<br>%{y:.2f}"
                    + " meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    "visible": "legendonly",
                }
            )

        if ctd_vars.aa4831_temp_dive is not None:
            fig.add_trace(
                {
                    "y": ctd_vars.aa4831_depth_dive,
                    "x": ctd_vars.aa4831_temp_dive,
                    "meta": ctd_vars.aa4831_time_dive,
                    "customdata": ctd_vars.point_num_aa4831_dive,
                    "name": f"{ctd_vars.optode_name} Temp Dive",
                    "type": "scatter",
                    "xaxis": "x2",
                    "yaxis": "y2",
                    "mode": "markers",
                    "marker": {
                        "symbol": "triangle-down",
                        "color": "Cyan",
                    },
                    "hovertemplate": f"{ctd_vars.optode_name} Temp Dive"
                    + "<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    "visible": "legendonly",
                }
            )

        if ctd_vars.aa4831_temp_climb is not None:
            fig.add_trace(
                {
                    "y": ctd_vars.aa4831_depth_climb,
                    "x": ctd_vars.aa4831_temp_climb,
                    "meta": ctd_vars.aa4831_time_climb,
                    "customdata": ctd_vars.point_num_aa4831_climb,
                    "name": f"{ctd_vars.optode_name} Temp Climb",
                    "type": "scatter",
                    "xaxis": "x2",
                    "yaxis": "y2",
                    "mode": "markers",
                    "marker": {
                        "symbol": "triangle-up",
                        "color": "DarkCyan",
                    },
                    "hovertemplate": f"{ctd_vars.optode_name} Temp Climb"
                    + "<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    "visible": "legendonly",
                }
            )

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = "%s<br>CTD Temperature%s and Salinity%s vs Depth%s%s%s" % (
            mission_dive_str,
            " RAW" if "raw" in temp_name else "",
            " RAW" if "raw" in salinity_name else "",
            ctd_vars.qc_tag if "raw" not in temp_name else "",
            " - below %.2fm" % ctd_vars.surface_depth
            if ctd_vars.surface_depth > 0.0
            else "",
            f"- binned {ctd_vars.bin_width:.1f} m" if ctd_vars.binned_profile else "",
        )
        fig.update_layout(
            {
                "xaxis": {
                    "title": "Salinity (PSU)",
                    "showgrid": False,
                    "range": [ctd_vars.min_salinity, ctd_vars.max_salinity],
                },
                "yaxis": {
                    "title": "Depth (m)",
                    #'autorange' : 'reversed',
                    "range": [
                        max(
                            np.nanmax(ctd_vars.depth_dive)
                            if len(ctd_vars.depth_dive) > 0
                            else 0,
                            np.nanmax(ctd_vars.depth_climb)
                            if len(ctd_vars.depth_climb) > 0
                            else 0,
                        ),
                        0,
                    ],
                },
                "xaxis2": {
                    "title": "Temperature (C)",
                    #'titlefont': {'color': 'rgb(148, 103, 189)'},
                    #  'tickfont': {color: 'rgb(148, 103, 189)'},
                    "overlaying": "x1",
                    "side": "top",
                    "range": [ctd_vars.min_temperature, ctd_vars.max_temperature],
                },
                # Not visible - no good way to control the bottom margin so there is room for this
                "xaxis3": {
                    "title": "Conductivity (S/m)",
                    "showgrid": False,
                    "overlaying": "x1",
                    "side": "bottom",
                    "anchor": "free",
                    "position": 0.05,
                    "visible": False,
                },
                "yaxis2": {
                    "title": "Depth (m)",
                    "overlaying": "y1",
                    "side": "right",
                    #'autorange' : 'reversed',
                    "range": [
                        max(
                            np.nanmax(ctd_vars.depth_dive)
                            if len(ctd_vars.depth_dive) > 0
                            else 0,
                            np.nanmax(ctd_vars.depth_climb)
                            if len(ctd_vars.depth_climb) > 0
                            else 0,
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
                },
            }
        )

        # Instrument cal date
        if "sg_cal_calibcomm" in dive_nc_file.variables:
            sg_cal_calib_str = (
                dive_nc_file.variables["sg_cal_calibcomm"][:].tobytes().decode("utf-8")
            )
            l_annotations = [
                {
                    "text": sg_cal_calib_str,
                    "showarrow": False,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.0,
                    "y": -0.08,
                }
            ]

            # CT Corrections
            if (
                "raw" not in temp_name
                and "sg_cal_sbect_modes" in dive_nc_file.variables
                and "not installed" not in sg_cal_calib_str
                and not ctd_vars.is_legato
            ):
                l_annotations.append(
                    {
                        "text": "sbect modes:%d"
                        % dive_nc_file.variables["sg_cal_sbect_modes"].getValue(),
                        "showarrow": False,
                        "xref": "paper",
                        "yref": "paper",
                        "x": 1.0,
                        "y": -0.04,
                    }
                )

            fig.update_layout({"annotations": tuple(l_annotations)})

        fig.update_xaxes(automargin=True)

        ret_figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts,
                "dv%04d%s_ctd"
                % (
                    dive_nc_file.dive_number,
                    "" if temp_name == "temperature" else "_raw",
                ),
                fig,
            )
        )

    return (ret_figs, ret_plots)


@add_arguments(
    additional_arguments={
        "ctd_series_divesback": BaseOptsType.options_t(
            10,
            ("Base", "BasePlot", "Reprocess"),
            ("--ctd_series_divesback",),
            int,
            {
                "help": "How many dives to include in the CTD series plot",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
        "enable_ctd_series": BaseOptsType.options_t(
            False,
            ("Base", "BasePlot", "Reprocess"),
            ("--enable_ctd_series",),
            bool,
            {
                "help": "Turn on the experimental CTD series plot",
                "section": "plotting",
                "option_group": "plotting",
                "action": "store_true",
            },
        ),
    }
)
@plotdivesingle
def plot_CTD_series(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots CTD data and Optode Temp (if present) as a annimation"""

    if (
        "temperature" not in dive_nc_file.variables
        or not generate_plots
        or not base_opts.enable_ctd_series
    ):
        return ([], [])

    ret_figs = []
    ret_plots = []

    nc_file_names = list(
        map(
            pathlib.Path,
            MakeDiveProfiles.collect_nc_perdive_files(base_opts),
        )
    )
    nc_files = [dive_nc_file]

    for nc_filename in nc_file_names:
        dive_num = int(nc_filename.name[4:8])
        if (
            dive_num > dive_nc_file.dive_number
            or dive_num <= dive_nc_file.dive_number - base_opts.ctd_series_divesback
        ):
            continue
        nc_file = Utils.open_netcdf_file(nc_filename)
        if nc_file:
            nc_files.append(nc_file)

    for temp_name, salinity_name, conductivity_name in (
        ("temperature", "salinity", "conductivity"),
        ("temperature_raw", "salinity_raw", "conductivity_raw"),
    ):
        fig = None
        frames = []
        n_frames = 0
        dive_nums = []

        for nc_file in nc_files:
            ctd_vars = load_ctd_vars(
                nc_file, temp_name, salinity_name, conductivity_name
            )
            if ctd_vars is None:
                continue

            # Create the figures
            if not fig:
                fig = plotly.graph_objects.Figure()

                n_traces = 0

                # Plot Temp, Salinity and Conductivity vs depth
                fig.add_trace(
                    {
                        "y": ctd_vars.depth_dive,
                        "x": ctd_vars.salinity_dive,
                        "meta": ctd_vars.time_dive,
                        "customdata": ctd_vars.point_num_ctd_dive,
                        "name": "Salinity Dive",
                        "type": "scatter",
                        "xaxis": "x1",
                        "yaxis": "y1",
                        "mode": "markers",
                        "marker": {
                            "symbol": "triangle-down",
                            "color": "DarkBlue",
                            #'line':{'width':1, 'color':'LightSlateGrey'}
                        },
                        "hovertemplate": "%{x:.2f} psu<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    }
                )
                fig.add_trace(
                    {
                        "y": ctd_vars.depth_climb,
                        "x": ctd_vars.salinity_climb,
                        "meta": ctd_vars.time_climb,
                        "customdata": ctd_vars.point_num_ctd_climb,
                        "name": "Salinity Climb",
                        "type": "scatter",
                        "xaxis": "x1",
                        "yaxis": "y1",
                        "mode": "markers",
                        "marker": {
                            "symbol": "triangle-up",
                            "color": "DarkGreen",
                            #'line':{'width':1, 'color':'LightSlateGrey'}
                        },
                        "hovertemplate": "%{x:.2f} psu<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    }
                )
                n_traces += 2
                fig.add_trace(
                    {
                        "y": ctd_vars.depth_dive,
                        "x": ctd_vars.temp_dive,
                        "meta": ctd_vars.time_dive,
                        "customdata": ctd_vars.point_num_ctd_dive,
                        "name": "Temp Dive",
                        "type": "scatter",
                        "xaxis": "x2",
                        "yaxis": "y2",
                        "mode": "markers",
                        "marker": {
                            "symbol": "triangle-down",
                            "color": "DarkMagenta",
                            #'size':10,'line':{'width':1, 'color':'DarkSlateGrey'}
                        },
                        "hovertemplate": "%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    }
                )
                fig.add_trace(
                    {
                        "y": ctd_vars.depth_climb,
                        "x": ctd_vars.temp_climb,
                        "meta": ctd_vars.time_climb,
                        "customdata": ctd_vars.point_num_ctd_climb,
                        "name": "Temp Climb",
                        "type": "scatter",
                        "xaxis": "x2",
                        "yaxis": "y2",
                        "mode": "markers",
                        "marker": {
                            "symbol": "triangle-up",
                            "color": "DarkRed",
                            #'size':10, 'line':{'width':1, 'color':'DarkSlateGrey'}
                        },
                        "hovertemplate": "%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    }
                )
                n_traces += 2
                if ctd_vars.conductivity is not None:
                    fig.add_trace(
                        {
                            "y": ctd_vars.depth_dive,
                            "x": ctd_vars.conductivity_dive,
                            "meta": ctd_vars.time_dive,
                            "customdata": ctd_vars.point_num_ctd_dive,
                            "name": "Conductivity Dive",
                            "type": "scatter",
                            "xaxis": "x3",
                            "yaxis": "y1",
                            "mode": "markers",
                            "marker": {
                                "symbol": "triangle-down",
                                "color": "LightSlateGrey",
                            },
                            "hovertemplate": "Conductivity Dive<br>%{x:.4f} S/m<br>%{y:.2f}"
                            + "meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                            "visible": "legendonly",
                        }
                    )

                    fig.add_trace(
                        {
                            "y": ctd_vars.depth_climb,
                            "x": ctd_vars.conductivity_climb,
                            "meta": ctd_vars.aa4831_time_climb,
                            "customdata": ctd_vars.point_num_ctd_climb,
                            "name": "Conductivity Climb",
                            "type": "scatter",
                            "xaxis": "x3",
                            "yaxis": "y1",
                            "mode": "markers",
                            "marker": {
                                "symbol": "triangle-up",
                                "color": "DarkSlateGrey",
                            },
                            "hovertemplate": "Conductivity Climb<br>%{x:.4f} S/m<br>%{y:.2f}"
                            + " meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                            "visible": "legendonly",
                        }
                    )
                    n_traces += 2

                if ctd_vars.aa4831_temp_dive is not None:
                    fig.add_trace(
                        {
                            "y": ctd_vars.aa4831_depth_dive,
                            "x": ctd_vars.aa4831_temp_dive,
                            "meta": ctd_vars.time_dive,
                            "customdata": ctd_vars.point_num_aa4831_dive,
                            "name": f"{ctd_vars.optode_name} Temp Dive",
                            "type": "scatter",
                            "xaxis": "x2",
                            "yaxis": "y2",
                            "mode": "markers",
                            "marker": {
                                "symbol": "triangle-down",
                                "color": "Cyan",
                            },
                            "hovertemplate": f"{ctd_vars.optode_name} Temp Dive"
                            + "<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                            "visible": "legendonly",
                        }
                    )
                    n_traces += 1

                if ctd_vars.aa4831_temp_climb is not None:
                    fig.add_trace(
                        {
                            "y": ctd_vars.aa4831_depth_climb,
                            "x": ctd_vars.aa4831_temp_climb,
                            "meta": ctd_vars.aa4831_time_climb,
                            "customdata": ctd_vars.point_num_aa4831_climb,
                            "name": f"{ctd_vars.optode_name} Temp Climb",
                            "type": "scatter",
                            "xaxis": "x2",
                            "yaxis": "y2",
                            "mode": "markers",
                            "marker": {
                                "symbol": "triangle-up",
                                "color": "DarkCyan",
                            },
                            "hovertemplate": f"{ctd_vars.optode_name} Temp Climb"
                            + "<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                            "visible": "legendonly",
                        }
                    )
                    n_traces += 1

                continue
            data_l = [
                plotly.graph_objects.Scatter(
                    {
                        "y": ctd_vars.depth_dive,
                        "x": ctd_vars.salinity_dive,
                        "meta": ctd_vars.time_dive,
                        "customdata": ctd_vars.point_num_ctd_dive,
                    }
                ),
                plotly.graph_objects.Scatter(
                    {
                        "y": ctd_vars.depth_climb,
                        "x": ctd_vars.salinity_climb,
                        "meta": ctd_vars.time_climb,
                        "customdata": ctd_vars.point_num_ctd_climb,
                    }
                ),
                plotly.graph_objects.Scatter(
                    {
                        "y": ctd_vars.depth_dive,
                        "x": ctd_vars.temp_dive,
                        "meta": ctd_vars.time_dive,
                        "customdata": ctd_vars.point_num_ctd_dive,
                    }
                ),
                plotly.graph_objects.Scatter(
                    {
                        "y": ctd_vars.depth_climb,
                        "x": ctd_vars.temp_climb,
                        "meta": ctd_vars.time_climb,
                        "customdata": ctd_vars.point_num_ctd_climb,
                    }
                ),
            ]
            # TODO - Need to address missing traces for some dives and not others - probably
            # use an empty list for the missing traces
            if ctd_vars.conductivity is not None:
                data_l.append(
                    plotly.graph_objects.Scatter(
                        {
                            "y": ctd_vars.depth_dive,
                            "x": ctd_vars.conductivity_dive,
                            "meta": ctd_vars.time_dive,
                            "customdata": ctd_vars.point_num_ctd_dive,
                        }
                    ),
                )
                data_l.append(
                    plotly.graph_objects.Scatter(
                        {
                            "y": ctd_vars.depth_climb,
                            "x": ctd_vars.conductivity_climb,
                            "meta": ctd_vars.time_climb,
                            "customdata": ctd_vars.point_num_ctd_climb,
                        }
                    ),
                )

            if ctd_vars.aa4831_temp_dive is not None:
                data_l.append(
                    plotly.graph_objects.Scatter(
                        {
                            "y": ctd_vars.aa4831_depth_dive,
                            "x": ctd_vars.aa4831_temp_dive,
                            "meta": ctd_vars.aa4831_time_climb,
                            "customdata": ctd_vars.point_num_aa4831_dive,
                        }
                    )
                )

            if ctd_vars.aa4831_temp_climb is not None:
                data_l.append(
                    plotly.graph_objects.Scatter(
                        {
                            "y": ctd_vars.aa4831_depth_climb,
                            "x": ctd_vars.aa4831_temp_climb,
                            "meta": ctd_vars.aa4831_time_climb,
                            "customdata": ctd_vars.point_num_aa4831_climb,
                        }
                    )
                )

            frames.append(
                plotly.graph_objects.Frame(
                    data=data_l,
                    traces=[k for k in range(n_traces)],
                    name=f"{nc_file.dive_number}",
                )
            )
            dive_nums.append(f"{nc_file.dive_number}")
            n_frames += 1

        # Finally, update the figure
        mission_dive_str = PlotUtils.get_mission_dive(
            dive_nc_file, dives_str=f"Dives {dive_nums[0]} - {dive_nums[-1]}"
        )
        title_text = "%s<br>CTD Temperature%s and Salinity%s vs Depth%s%s%s" % (
            mission_dive_str,
            " RAW" if "raw" in temp_name else "",
            " RAW" if "raw" in salinity_name else "",
            ctd_vars.qc_tag if "raw" not in temp_name else "",
            " - below %.2fm" % ctd_vars.surface_depth
            if ctd_vars.surface_depth > 0.0
            else "",
            f"- binned {ctd_vars.bin_width:.1f} m" if ctd_vars.binned_profile else "",
        )
        fig.update_layout(
            {
                "xaxis": {
                    "title": "Salinity (PSU)",
                    "showgrid": False,
                    "range": [ctd_vars.min_salinity, ctd_vars.max_salinity],
                },
                "yaxis": {
                    "title": "Depth (m)",
                    #'autorange' : 'reversed',
                    "range": [
                        max(
                            np.nanmax(ctd_vars.depth_dive)
                            if len(ctd_vars.depth_dive) > 0
                            else 0,
                            np.nanmax(ctd_vars.depth_climb)
                            if len(ctd_vars.depth_climb) > 0
                            else 0,
                        ),
                        0,
                    ],
                },
                "xaxis2": {
                    "title": "Temperature (C)",
                    #'titlefont': {'color': 'rgb(148, 103, 189)'},
                    #  'tickfont': {color: 'rgb(148, 103, 189)'},
                    "overlaying": "x1",
                    "side": "top",
                    "range": [
                        ctd_vars.min_temperature,
                        ctd_vars.max_temperature,
                    ],
                },
                # Not visible - no good way to control the bottom margin so there is room for this
                "xaxis3": {
                    "title": "Conductivity (S/m)",
                    "showgrid": False,
                    "overlaying": "x1",
                    "side": "bottom",
                    "anchor": "free",
                    "position": 0.05,
                    "visible": False,
                },
                "yaxis2": {
                    "title": "Depth (m)",
                    "overlaying": "y1",
                    "side": "right",
                    #'autorange' : 'reversed',
                    "range": [
                        max(
                            np.nanmax(ctd_vars.depth_dive)
                            if len(ctd_vars.depth_dive) > 0
                            else 0,
                            np.nanmax(ctd_vars.depth_climb)
                            if len(ctd_vars.depth_climb) > 0
                            else 0,
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
            sg_cal_calib_str = (
                dive_nc_file.variables["sg_cal_calibcomm"][:].tobytes().decode("utf-8")
            )
            l_annotations = [
                {
                    "text": sg_cal_calib_str,
                    "showarrow": False,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.0,
                    "y": -0.08,
                }
            ]

            # CT Corrections
            if (
                "raw" not in temp_name
                and "sg_cal_sbect_modes" in dive_nc_file.variables
                and "not installed" not in sg_cal_calib_str
                and not ctd_vars.is_legato
            ):
                l_annotations.append(
                    {
                        "text": "sbect modes:%d"
                        % dive_nc_file.variables["sg_cal_sbect_modes"].getValue(),
                        "showarrow": False,
                        "xref": "paper",
                        "yref": "paper",
                        "x": 1.0,
                        "y": -0.04,
                    }
                )

            fig.update_layout({"annotations": tuple(l_annotations)})

        fig.update_xaxes(automargin=True)

        fig.update(frames=frames)
        updatemenus = [
            {
                "buttons": [
                    {
                        "args": [
                            None,
                            {
                                "frame": {"duration": 500, "redraw": True},
                                "fromcurrent": True,
                                "transition": {
                                    "duration": 300,
                                    "easing": "quadratic-in-out",
                                },
                            },
                        ],
                        "label": "Play",
                        "method": "animate",
                    },
                    {
                        "args": [
                            None,
                            {
                                "frame": {"duration": 0, "redraw": False},
                                "mode": "immediate",
                                "transition": {"duration": 0},
                            },
                        ],
                        "label": "Pause",
                        "method": "animate",
                    },
                ],
                "direction": "left",
                "pad": {"r": 10, "t": 87},
                "showactive": False,
                "type": "buttons",
                "x": 0.1,
                "xanchor": "right",
                "y": 0,
                "yanchor": "top",
            }
        ]

        sliders = [
            {
                "steps": [
                    {
                        "method": "animate",
                        "args": [
                            [dive_nums[k]],
                            {
                                "mode": "immediate",
                                "frame": {"duration": 400, "redraw": True},
                                "transition": {"duration": 0},
                            },
                        ],
                        "label": dive_nums[k],
                    }
                    for k in range(n_frames)
                ],
                "active": n_frames - 1,
                "transition": {"duration": 300, "easing": "cubic-in-out"},
                "currentvalue": {
                    "font": {"size": 15},
                    "prefix": "Dive:",
                    "visible": True,
                    "xanchor": "right",
                },
                "pad": {"b": 10, "t": 50},
                "len": 0.9,
                "x": 0.1,
                "y": 0,
            }
        ]
        fig.update_layout(updatemenus=updatemenus, sliders=sliders)

        ret_figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts,
                "dv%04d%s_ctd_series"
                % (
                    dive_nc_file.dive_number,
                    "" if temp_name == "temperature" else "_raw",
                ),
                fig,
            )
        )

    return (ret_figs, ret_plots)
