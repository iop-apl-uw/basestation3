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

import typing

import numpy as np
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
import QC
from BaseLog import log_debug, log_error, log_info, log_warning
from Plotting import plotdivesingle


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

    binned_profile = "profile_data_point" in dive_nc_file.dimensions

    if "ctd_depth" in dive_nc_file.variables and "ctd_time" in dive_nc_file.variables:
        ctd_depth_m_v = dive_nc_file.variables["ctd_depth"][:]
        ctd_time_v = dive_nc_file.variables["ctd_time"][:]
    elif binned_profile:
        # SimpleNetCDF binned product
        ctd_depth_m_v = dive_nc_file.variables["depth"][:]
        ctd_time_v = dive_nc_file.variables["time"][:]
        bin_width = np.round(np.average(np.diff(ctd_depth_m_v[0, :])), decimals=1)
    else:
        log_info("Could not load ctd_depth nc varible for plot_ctd_data - skipping")
        return (ret_figs, ret_plots)

    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = None

    aa4831_temp_dive = aa4831_temp_climb = optode_name = None

    if "aa4831_temp" in dive_nc_file.variables:
        optode_name = "aa4831"
    elif "aa4330_temp" in dive_nc_file.variables:
        optode_name = "aa4330"

    is_scicon = True
    if "aa4831_temp" in dive_nc_file.variables:
        optode_name = "aa4831"
        optode_temp_name = "aa4831_temp"
    elif "eng_aa4831_Temp" in dive_nc_file.variables:
        optode_name = "aa4831"
        optode_temp_name = "eng_aa4831_Temp"
        is_scicon = False
    elif "aa4330_temp" in dive_nc_file.variables:
        optode_name = "aa4330"
        optode_temp_name = "aa4330_temp"
    elif "eng_aa4330_Temp" in dive_nc_file.variables:
        optode_name = "aa4330"
        optode_temp_name = "eng_aa4330_Temp"
        is_scicon = False

    if optode_name is not None:
        try:
            sg_time = dive_nc_file.variables["time"][:]
            aa4831_temp = dive_nc_file.variables[optode_temp_name][:]
            if is_scicon:
                aa4831_time = dive_nc_file.variables[f"{optode_name}_time"][:]
            else:
                aa4831_time = sg_time

            depth = dive_nc_file.variables["depth"][:]

            depth_f = scipy.interpolate.interp1d(
                sg_time, depth, kind="linear", bounds_error=False, fill_value=0.0
            )
            aa4831_depth = depth_f(aa4831_time)
            max_depth_sample_index = np.nanargmax(aa4831_depth)

            # Create dive and climb vectors
            aa4831_depth_dive = aa4831_depth[0:max_depth_sample_index]
            aa4831_depth_climb = aa4831_depth[max_depth_sample_index:]

            aa4831_temp_dive = aa4831_temp[0:max_depth_sample_index]
            aa4831_temp_climb = aa4831_temp[max_depth_sample_index:]

            point_num_aa4831_dive = np.arange(0, max_depth_sample_index)
            point_num_aa4831_climb = np.arange(max_depth_sample_index, len(aa4831_temp))

        except Exception:
            log_error("Error processing optode temp", "exc")

    if "sg_cal_sg_ct_type" in dive_nc_file.variables:
        is_legato = dive_nc_file.variables["sg_cal_sg_ct_type"].getValue() == 4
    else:
        is_legato = False

    if not is_legato:
        # The range of the raw plot is constrained by the range of the QC_GOOD plot for
        # SBECT.  For legato, let the bounds be different for each plot
        max_salinity = min_salinity = max_temperature = min_temperature = None

    for temp_name, salinity_name, conductivity_name in (
        ("temperature", "salinity", "conductivity"),
        ("temperature_raw", "salinity_raw", "conductivity_raw"),
    ):
        # Preliminaries
        temp = salinity = None

        if (
            temp_name in dive_nc_file.variables
            and salinity_name in dive_nc_file.variables
        ):
            try:
                # MakeDiveProfiles ensures that for temperature and salinity that bad_qc
                # points are set to NaN
                temp = dive_nc_file.variables[temp_name][:]
                salinity = dive_nc_file.variables[salinity_name][:]
                if conductivity_name in dive_nc_file.variables:
                    conductivity = dive_nc_file.variables[conductivity_name][:]
                else:
                    conductivity = None
                qc_tag = ""
                if (
                    "temperature_qc" in dive_nc_file.variables
                    and "raw" not in temp_name
                ):
                    temp_qc = QC.decode_qc(dive_nc_file.variables["temperature_qc"])
                    temp = np.ma.array(
                        temp,
                        mask=np.logical_not(
                            QC.find_qc(temp_qc, QC.only_good_qc_values, mask=True)
                        ),
                    )
                    qc_tag = " - QC_GOOD"

                if (
                    "salinity_qc" in dive_nc_file.variables
                    and "raw" not in salinity_name
                ):
                    salinity_qc = QC.decode_qc(dive_nc_file.variables["salinity_qc"])
                    salinity = np.ma.array(
                        salinity,
                        mask=np.logical_not(
                            QC.find_qc(salinity_qc, QC.only_good_qc_values, mask=True)
                        ),
                    )
                    qc_tag = " - QC_GOOD"

                if (
                    "conductivity_qc" in dive_nc_file.variables
                    and "raw" not in conductivity_name
                ):
                    conductivity_qc = QC.decode_qc(
                        dive_nc_file.variables["conductivity_qc"]
                    )
                    conductivity = np.ma.array(
                        conductivity,
                        mask=np.logical_not(
                            QC.find_qc(
                                conductivity_qc, QC.only_good_qc_values, mask=True
                            )
                        ),
                    )

            except Exception:
                log_info(
                    "Could not load nc varibles for plot_ctd_data - skipping", "exc"
                )
                continue
        else:
            log_warning(
                "Could not find both %s and %s nc variables - skipping"
                % (temp_name, salinity_name)
            )
            continue

        fig = plotly.graph_objects.Figure()

        # Remove the surface observations to clean up the raw plot
        # surface_depth = 2.0
        surface_depth = 0.0
        if binned_profile:
            if not start_time:
                start_time = ctd_time_v[0, 0]
            depth_dive = ctd_depth_m_v[0, :]
            depth_climb = ctd_depth_m_v[1, :]
            time_dive = (ctd_time_v[0, :] - start_time) / 60.0
            time_climb = (ctd_time_v[1, :] - start_time) / 60.0
            temp_dive = temp[0, :]
            temp_climb = temp[1, :]
            salinity_dive = salinity[0, :]
            salinity_climb = salinity[1, :]
            if conductivity is not None:
                conductivity_dive = conductivity[0, :]
                conductivity_climb = conductivity[1, :]
        else:
            if not start_time:
                start_time = ctd_time_v[0]
            if "raw" in temp_name and surface_depth > 0.0:
                dive_start = np.amin(np.where(ctd_depth_m_v > surface_depth))
                dive_end = np.amax(np.where(ctd_depth_m_v > surface_depth))
            else:
                dive_start = 0
                dive_end = len(ctd_depth_m_v)

            log_debug("dive_start = %d, dive_end = %d" % (dive_start, dive_end))

            # Find the deepest sample
            max_depth_sample_index = np.nanargmax(ctd_depth_m_v)

            # Create dive and climb vectors
            depth_dive = ctd_depth_m_v[dive_start:max_depth_sample_index]
            depth_climb = ctd_depth_m_v[max_depth_sample_index:dive_end]

            time_dive = (
                ctd_time_v[dive_start:max_depth_sample_index] - start_time
            ) / 60.0
            time_climb = (
                ctd_time_v[max_depth_sample_index:dive_end] - start_time
            ) / 60.0

            temp_dive = temp[dive_start:max_depth_sample_index]
            temp_climb = temp[max_depth_sample_index:dive_end]

            salinity_dive = salinity[dive_start:max_depth_sample_index]
            salinity_climb = salinity[max_depth_sample_index:dive_end]

            point_num_ctd_dive = np.arange(dive_start, max_depth_sample_index)
            point_num_ctd_climb = np.arange(max_depth_sample_index, dive_end)

            if conductivity is not None:
                conductivity_dive = conductivity[dive_start:max_depth_sample_index]
                conductivity_climb = conductivity[max_depth_sample_index:dive_end]

        if is_legato:
            max_salinity = min_salinity = max_temperature = min_temperature = None

        if not min_salinity:
            min_salinity = np.nanmin(salinity) - (
                0.05 * abs(np.nanmax(salinity) - np.nanmin(salinity))
            )
        if not max_salinity:
            max_salinity = np.nanmax(salinity) + (
                0.05 * abs(np.nanmax(salinity) - np.nanmin(salinity))
            )
        if not min_temperature:
            min_temperature = np.nanmin(temp) - (
                0.05 * abs(np.nanmax(temp) - np.nanmin(temp))
            )
        if not max_temperature:
            max_temperature = np.nanmax(temp) + (
                0.05 * abs(np.nanmax(temp) - np.nanmin(temp))
            )

        # Plot Temp, Salinity and Conductivity vs depth
        fig.add_trace(
            {
                "y": depth_dive,
                "x": salinity_dive,
                "meta": time_dive,
                "customdata": point_num_ctd_dive,
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
                "y": depth_climb,
                "x": salinity_climb,
                "meta": time_climb,
                "customdata": point_num_ctd_climb,
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
                "y": depth_dive,
                "x": temp_dive,
                "meta": time_dive,
                "customdata": point_num_ctd_dive,
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
                "y": depth_climb,
                "x": temp_climb,
                "meta": time_climb,
                "customdata": point_num_ctd_climb,
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

        if conductivity is not None:
            fig.add_trace(
                {
                    "y": depth_dive,
                    "x": conductivity_dive,
                    "meta": time_dive,
                    "customdata": point_num_ctd_dive,
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
                    "y": depth_climb,
                    "x": conductivity_climb,
                    "meta": time_climb,
                    "customdata": point_num_ctd_climb,
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

        if aa4831_temp_dive is not None:
            fig.add_trace(
                {
                    "y": aa4831_depth_dive,
                    "x": aa4831_temp_dive,
                    "meta": time_dive,
                    "customdata": point_num_aa4831_dive,
                    "name": f"{optode_name} Temp Dive",
                    "type": "scatter",
                    "xaxis": "x2",
                    "yaxis": "y2",
                    "mode": "markers",
                    "marker": {
                        "symbol": "triangle-down",
                        "color": "Cyan",
                    },
                    "hovertemplate": f"{optode_name} Temp Dive"
                    + "<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    "visible": "legendonly",
                }
            )

        if aa4831_temp_climb is not None:
            fig.add_trace(
                {
                    "y": aa4831_depth_climb,
                    "x": aa4831_temp_climb,
                    "meta": time_climb,
                    "customdata": point_num_aa4831_climb,
                    "name": f"{optode_name} Temp Climb",
                    "type": "scatter",
                    "xaxis": "x2",
                    "yaxis": "y2",
                    "mode": "markers",
                    "marker": {
                        "symbol": "triangle-up",
                        "color": "DarkCyan",
                    },
                    "hovertemplate": f"{optode_name} Temp Climb"
                    + "<br>%{x:.3f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<br>%{customdata:d} point_num<extra></extra>",
                    "visible": "legendonly",
                }
            )

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = "%s<br>CTD Temperature%s and Salinity%s vs Depth%s%s%s" % (
            mission_dive_str,
            " RAW" if "raw" in temp_name else "",
            " RAW" if "raw" in salinity_name else "",
            qc_tag if "raw" not in temp_name else "",
            " - below %.2fm" % surface_depth if surface_depth > 0.0 else "",
            f"- binned {bin_width:.1f} m" if binned_profile else "",
        )
        fig.update_layout(
            {
                "xaxis": {
                    "title": "Salinity (PSU)",
                    "showgrid": False,
                    "range": [min_salinity, max_salinity],
                },
                "yaxis": {
                    "title": "Depth (m)",
                    #'autorange' : 'reversed',
                    "range": [
                        max(
                            np.nanmax(depth_dive) if len(depth_dive) > 0 else 0,
                            np.nanmax(depth_climb) if len(depth_climb) > 0 else 0,
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
                    "range": [min_temperature, max_temperature],
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
                            np.nanmax(depth_dive) if len(depth_dive) > 0 else 0,
                            np.nanmax(depth_climb) if len(depth_climb) > 0 else 0,
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
