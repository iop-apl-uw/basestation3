#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2025  University of Washington.
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

"""Plots Temperature vs Salinity"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing

import numpy as np
import plotly.graph_objects
import scipy
import seawater

if typing.TYPE_CHECKING:
    import BaseOpts

import MakeDiveProfiles
import PlotUtils
import PlotUtilsPlotly
import QC
import Utils
from BaseLog import log_info, log_warning
from Plotting import plotdivesingle


@plotdivesingle
def plot_TS(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots TS Data"""

    if "temperature" not in dive_nc_file.variables or not generate_plots:
        return ([], [])

    ret_plots = []
    ret_figs = []

    if "sg_cal_sg_ct_type" in dive_nc_file.variables:
        is_legato = dive_nc_file.variables["sg_cal_sg_ct_type"].getValue() == 4
    else:
        is_legato = False

    binned_profile = "profile_data_point" in dive_nc_file.dimensions

    if not is_legato:
        # The range of the raw plot is constrained by the range of the QC_GOOD plot for
        # SBECT.  For legato, let the bounds be different for each plot
        max_salinity = min_salinity = max_temperature = min_temperature = None

    # Order matters here
    for temp_name, salinity_name in (
        ("temperature", "salinity"),
        ("temperature_raw", "salinity_raw"),
    ):
        # Preliminaries
        pressure = freeze_pt = None
        good_mask = None

        try:
            temperature = dive_nc_file.variables[temp_name][:]
            salinity = dive_nc_file.variables[salinity_name][:]

            if "raw" not in temp_name:
                if (
                    "temperature_qc" in dive_nc_file.variables
                    and "salinity_qc" in dive_nc_file.variables
                ):
                    temperature_qc = QC.decode_qc(
                        dive_nc_file.variables["temperature_qc"]
                    )
                    salinity_qc = QC.decode_qc(dive_nc_file.variables["salinity_qc"])
                    good_mask = np.logical_and(
                        QC.find_qc(temperature_qc, QC.only_good_qc_values, mask=True),
                        QC.find_qc(salinity_qc, QC.only_good_qc_values, mask=True),
                    )
                    if not good_mask.any():
                        log_warning(
                            "No good data points found for CTD QC Data - skipping"
                        )
                        continue

                    temperature = temperature[good_mask]
                    salinity = salinity[good_mask]
                    qc_tag = " - QC_GOOD"
                else:
                    log_warning("qc variables for temperature or salinity missing")
                    qc_tag = ""

            if (
                binned_profile
                and "sg_data_point" in dive_nc_file.variables[temp_name].dimensions
            ):
                ctd_depth_m_v = dive_nc_file.variables["depth"][:]
                bin_width = np.round(
                    np.average(np.diff(ctd_depth_m_v[0, :])), decimals=1
                )
            else:
                ctd_depth_m_v = dive_nc_file.variables["ctd_depth"][:]

            if good_mask is not None:
                ctd_depth_m_v = ctd_depth_m_v[good_mask]

            if (
                "log_USE_ICE" in dive_nc_file.variables
                and dive_nc_file.variables["log_USE_ICE"].getValue() > 0
            ) or base_opts.plot_freeze_pt:
                if "sg_data_point" in dive_nc_file.variables[temp_name].dimensions:
                    pressure = dive_nc_file.variables["pressure"][:]
                else:
                    pressure = dive_nc_file.variables["ctd_pressure"][:]
                if good_mask is not None:
                    pressure = pressure[good_mask]

            if base_opts.use_gsw:
                if "avg_longitude" in dive_nc_file.variables:
                    avg_longitude = dive_nc_file.variables["avg_longitude"].getValue()
                else:
                    # Older basestations didn't calcuate this value
                    avg_longitude = MakeDiveProfiles.avg_longitude(
                        dive_nc_file.variables["log_gps_lon"][1],
                        dive_nc_file.variables["log_gps_lon"][2],
                    )
                avg_latitude = dive_nc_file.variables["avg_latitude"].getValue()

        except KeyError as e:
            log_warning(f"Could not find variable {str(e)} - skipping plot_ts")
            continue
        except Exception:
            log_info("Could not load nc varibles for plot_ts - skipping", "exc")
            continue

        if binned_profile:
            # Create dive and climb vectors
            depth_dive = ctd_depth_m_v[0, :]
            depth_climb = ctd_depth_m_v[1, :]

            temperature_dive = temperature[0, :]
            temperature_climb = temperature[1, :]

            salinity_dive = salinity[0, :]
            salinity_climb = salinity[1, :]
        else:
            # Find the deepest sample
            max_depth_sample_index = np.nanargmax(ctd_depth_m_v)

            # Create dive and climb vectors
            depth_dive = ctd_depth_m_v[0:max_depth_sample_index]
            depth_climb = ctd_depth_m_v[max_depth_sample_index:]

            temperature_dive = temperature[0:max_depth_sample_index]
            temperature_climb = temperature[max_depth_sample_index:]

            salinity_dive = salinity[0:max_depth_sample_index]
            salinity_climb = salinity[max_depth_sample_index:]

            point_num_ctd_dive = np.arange(0, max_depth_sample_index)
            point_num_ctd_climb = np.arange(max_depth_sample_index, len(ctd_depth_m_v))

        if pressure is not None:
            if not base_opts.use_gsw:
                freeze_pt = seawater.fp(salinity, pressure)
            else:
                freeze_pt = Utils.fp(salinity, pressure, avg_longitude, avg_latitude)

            freeze_pt_dive = freeze_pt[0:max_depth_sample_index]
            freeze_pt_climb = freeze_pt[max_depth_sample_index:]

        if is_legato:
            max_salinity = min_salinity = max_temperature = min_temperature = None

        # Countour the density
        if not min_salinity:
            min_salinity = np.nanmin(salinity) - (
                0.05 * abs(np.nanmax(salinity) - np.nanmin(salinity))
            )
        if not max_salinity:
            max_salinity = np.nanmax(salinity) + (
                0.05 * abs(np.nanmax(salinity) - np.nanmin(salinity))
            )

        if freeze_pt is not None:
            temp = np.concatenate((temperature, freeze_pt))
        else:
            temp = temperature

        if not min_temperature:
            min_temperature = np.nanmin(temp) - (
                0.05 * abs(np.nanmax(temp) - np.nanmin(temp))
            )
        if not max_temperature:
            max_temperature = np.nanmax(temperature) + (
                0.05 * abs(np.nanmax(temperature) - np.nanmin(temperature))
            )

        fig = plotly.graph_objects.Figure()

        # plt.xlim(xmax = max_salinity, xmin = min_salinity)
        # plt.ylim(ymax = max_temperature, ymin = min_temperature)

        sgrid = np.linspace(min_salinity, max_salinity)
        tgrid = np.linspace(min_temperature, max_temperature)

        (Sg, Tg) = np.meshgrid(sgrid, tgrid)
        Pg = np.zeros((len(Sg), len(Tg)))
        if not base_opts.use_gsw:
            sigma_grid = seawater.dens(Sg, Tg, Pg) - 1000.0
        else:
            sigma_grid = Utils.density(Sg, Tg, Pg, avg_longitude, avg_latitude) - 1000.0

        # What a hack - this intermediate step is needed for plot.ly
        tg = Tg[:, 0][:]
        sg = Sg[0, :][:]

        fig.add_trace(
            {
                "x": sg,
                "y": tg,
                "z": sigma_grid[:],
                "type": "contour",
                "contours_coloring": "none",
                "showscale": False,
                "showlegend": True,
                "name": "Density",
                "contours": {
                    "showlabels": True,
                },
                "hoverinfo": "skip",
            }
        )

        if freeze_pt is not None:
            fig.add_trace(
                {
                    "y": freeze_pt_dive,
                    "x": salinity_dive,
                    "name": "Freeze Point Dive",
                    "type": "scatter",
                    "xaxis": "x1",
                    "yaxis": "y1",
                    "mode": "markers",
                    "marker": {"symbol": "triangle-down", "color": "LightGrey"},
                    "hoverinfo": "skip",
                }
            )

            fig.add_trace(
                {
                    "y": freeze_pt_climb,
                    "x": salinity_climb,
                    "name": "Freeze Point Dive",
                    "type": "scatter",
                    "xaxis": "x1",
                    "yaxis": "y1",
                    "mode": "markers",
                    "marker": {"symbol": "triangle-up", "color": "DarkGrey"},
                    "hoverinfo": "skip",
                }
            )

        cmin = np.nanmin(ctd_depth_m_v)
        cmax = np.nanmax(ctd_depth_m_v)

        if not base_opts.use_gsw:
            sigma_dive = (
                seawater.dens(
                    salinity_dive, temperature_dive, np.zeros(len(temperature_dive))
                )
                - 1000.0
            )
            sigma_climb = (
                seawater.dens(
                    salinity_climb, temperature_climb, np.zeros(len(temperature_climb))
                )
                - 1000.0
            )
        else:
            sigma_dive = (
                Utils.density(
                    salinity_dive,
                    temperature_dive,
                    np.zeros(len(temperature_dive)),
                    avg_longitude,
                    avg_latitude,
                )
                - 1000.0
            )
            sigma_climb = (
                Utils.density(
                    salinity_climb,
                    temperature_climb,
                    np.zeros(len(temperature_climb)),
                    avg_longitude,
                    avg_latitude,
                )
                - 1000.0
            )

        fig.add_trace(
            {
                "y": temperature_dive,
                "x": salinity_dive,
                "customdata": np.squeeze(
                    np.dstack(
                        (np.transpose(sigma_dive), np.transpose(point_num_ctd_dive))
                    )
                ),
                # Not sure where this came from - previous version had this for dive and no
                # meta for climb.  Might have been to address the sometimes mis-matched color bars
                # "meta": {"colorbar": depth_dive,},
                "meta": depth_dive,
                "name": "Dive",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": depth_dive,
                    "colorbar": {
                        "title": "Depth(m)",
                        "len": 0.7 if freeze_pt is not None else 0.8,
                    },
                    "colorscale": "jet",
                    "reversescale": True,
                    "cmin": cmin,
                    "cmax": cmax,
                    #'line':{'width':1, 'color':'LightSlateGrey'}
                },
                "hovertemplate": "Dive<br>%{x:.2f} psu<br>%{y:.3f} C<br>%{customdata[0]:.2f}"
                " sigma-t<br>%{customdata[1]:d} point_num<br>%{meta:.2f} meters<extra></extra>",
            }
        )

        fig.add_trace(
            {
                "y": temperature_climb,
                "x": salinity_climb,
                "meta": depth_climb,
                "customdata": np.squeeze(
                    np.dstack(
                        (np.transpose(sigma_climb), np.transpose(point_num_ctd_climb))
                    )
                ),
                "name": "Climb",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": depth_climb,
                    "colorbar": {
                        "title": "Depth(m)",
                        "len": 0.7 if freeze_pt is not None else 0.8,
                    },
                    "colorscale": "jet",
                    "reversescale": True,
                    "cmin": cmin,
                    "cmax": cmax,
                    #'line':{'width':1, 'color':'LightSlateGrey'}
                },
                "hovertemplate": "Climb<br>%{x:.2f} psu<br>%{y:.3f} C<br>%{customdata[0]:.2f}"
                + " sigma-t<br>%{customdata[1]:d} point_num<br>%{meta:.2f} meters<extra></extra>",
            }
        )

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = "%s<br>CTD Temperature%s and Salinity%s vs Depth%s%s" % (
            mission_dive_str,
            " RAW" if "raw" in temp_name else "",
            " RAW" if "raw" in salinity_name else "",
            qc_tag if "raw" not in temp_name else "",
            f" - binned {bin_width:.1f} m" if binned_profile else "",
        )

        # aspect_ratio = (max_salinity - min_salinity) / (max_temperature - min_temperature)

        fig.update_layout(
            {
                "xaxis": {
                    "title": "Salinity (PSU)",
                    "showgrid": True,
                    "range": [min_salinity, max_salinity],
                },
                "yaxis": {
                    "title": "Temperature (C)",
                    "range": [min_temperature, max_temperature],
                    #'scaleanchor' : 'x1',
                    #'scaleratio' : aspect_ratio,
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
                        "y": -0.08,
                    }
                )

            fig.update_layout({"annotations": tuple(l_annotations)})

        ret_figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts,
                "dv%04d_ts%s"
                % (dive_nc_file.dive_number, "_raw" if "raw" in temp_name else ""),
                fig,
            )
        )

    return (ret_figs, ret_plots)
