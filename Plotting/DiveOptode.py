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

"""Plots optode data"""

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
from BaseLog import log_warning
from Plotting import plotdivesingle


def find_matching_time(ncf, nc_var):
    """Given a variable from the netcdf file, locate the matching time vector"""
    dim = nc_var.dimensions
    for k, v in ncf.variables.items():
        if v.dimensions == dim and k.endswith("_time"):
            return ncf.variables[k][:]
    return None


@plotdivesingle
def plot_optode(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots optode data and sat O2"""

    if not generate_plots:
        return ([], [])
    optode_type = None
    is_scicon = False
    if "aa4831_time" in dive_nc_file.variables:
        optode_type = "4831"
        is_scicon = True
    elif "aa4330_time" in dive_nc_file.variables:
        optode_type = "4330"
        is_scicon = True
    elif "aa3830_time" in dive_nc_file.variables:
        optode_type = "3830"
        is_scicon = True
    elif "aa4831" in "".join(dive_nc_file.variables):
        optode_type = "4831"
    elif "aa4330" in "".join(dive_nc_file.variables):
        optode_type = "4330"
    elif "aa3830" in "".join(dive_nc_file.variables):
        optode_type = "3830"
    if optode_type is None:
        return ([], [])

    optode_correctedO2 = None
    o2_qc_good = False

    # TODO - fix this universally - start_time or start of data UNLESS in binned profile
    # - then just give up.
    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = None

    binned_profile = "profile_data_point" in dive_nc_file.dimensions

    sat_O2 = sat_O2_depth = optode_instrument_O2 = optode_correctedO2 = (
        optode_instrument_temp
    ) = None
    min_temp = max_temp = None
    try:
        sg_time = dive_nc_file.variables["time"][:]
        sg_depth = None
        try:
            sg_depth = dive_nc_file.variables["depth"][:]
        except KeyError:
            try:
                sg_depth = dive_nc_file.variables["eng_depth"][:] / 100.0
            except KeyError:
                log_warning("No depth variable found")
        # Interpolate around missing depth observations
        sg_depth = PlotUtils.interp_missing_depth(sg_time, sg_depth)

        if binned_profile:
            bin_width = np.round(np.average(np.diff(sg_depth[0, :])), decimals=1)
        if f"aanderaa{optode_type}_dissolved_oxygen" in dive_nc_file.variables:
            optode_correctedO2 = dive_nc_file.variables[
                f"aanderaa{optode_type}_dissolved_oxygen"
            ][:]
        else:
            log_warning("Did not find corrected optode O2")

        if is_scicon and not binned_profile:
            optode_instrument_O2_time = dive_nc_file.variables[f"aa{optode_type}_time"][
                :
            ]

            if f"aa{optode_type}_O2" in dive_nc_file.variables:
                optode_instrument_O2 = dive_nc_file.variables[f"aa{optode_type}_O2"][:]

            if f"aa{optode_type}_temp" in dive_nc_file.variables:
                optode_instrument_temp = dive_nc_file.variables[
                    f"aa{optode_type}_temp"
                ][:]

            if "dissolved_oxygen_sat" in dive_nc_file.variables:
                sat_O2 = dive_nc_file.variables["dissolved_oxygen_sat"]
                sat_O2_time = find_matching_time(dive_nc_file, sat_O2)
                sat_O2 = sat_O2[:]

            f = scipy.interpolate.interp1d(
                sg_time, sg_depth, kind="linear", bounds_error=False, fill_value=0.0
            )
            optode_instrument_O2_depth = f(optode_instrument_O2_time)
            if sat_O2 is not None:
                sat_O2_depth = f(sat_O2_time)
        else:
            # Truck
            optode_instrument_O2_time = sg_time
            sat_O2_depth = optode_instrument_O2_depth = sg_depth
            sat_O2_time = sg_time
            if "dissolved_oxygen_sat" in dive_nc_file.variables:
                sat_O2 = dive_nc_file.variables["dissolved_oxygen_sat"][:]
            if f"eng_aa{optode_type}_O2" in dive_nc_file.variables:
                optode_instrument_O2 = dive_nc_file.variables[
                    f"eng_aa{optode_type}_O2"
                ][:]
            if f"eng_aa{optode_type}_temp" in dive_nc_file.variables:
                optode_instrument_temp = dive_nc_file.variables[
                    f"eng_aa{optode_type}_temp"
                ][:]
    except Exception:
        log_warning("Could not load oxygen data", "exc")

    if optode_instrument_temp is not None:
        min_temp = np.nanmin(optode_instrument_temp) - (
            0.05
            * abs(np.nanmax(optode_instrument_temp) - np.nanmin(optode_instrument_temp))
        )
        max_temp = np.nanmax(optode_instrument_temp) + (
            0.05
            * abs(np.nanmax(optode_instrument_temp) - np.nanmin(optode_instrument_temp))
        )

    if optode_correctedO2 is not None:
        if f"aanderaa{optode_type}_dissolved_oxygen_qc" in dive_nc_file.variables:
            optode_correctedO2_qc = QC.decode_qc(
                dive_nc_file.variables[f"aanderaa{optode_type}_dissolved_oxygen_qc"][:]
            )
            optode_correctedO2 = np.ma.array(
                optode_correctedO2,
                mask=np.logical_not(
                    QC.find_qc(optode_correctedO2_qc, QC.only_good_qc_values, mask=True)
                ),
            )
            o2_qc_good = True
        else:
            log_warning("Did not find corrected optode O2 qc")
            o2_qc_good = False

    drift_gain = None
    drift_gain_var = f"aanderaa{optode_type}_drift_gain"
    try:
        drift_gain = dive_nc_file.variables[drift_gain_var].getValue()
    except Exception:
        log_warning(f"Could not find {drift_gain_var} - drift gain not set?")

    max_depth_sample_index = None
    if binned_profile:
        # Create dive and climb vectors
        depth_dive = optode_instrument_O2_depth[0, :]
        depth_climb = optode_instrument_O2_depth[1, :]

        if optode_instrument_O2 is not None:
            optode_instrument_O2_dive = optode_instrument_O2[0, :]
            optode_instrument_O2_climb = optode_instrument_O2[1, :]

        if not start_time:
            start_time = optode_instrument_O2_time[0, 0]
        optode_instrument_O2_time_dive = (
            optode_instrument_O2_time[0, :] - start_time
        ) / 60.0
        optode_instrument_O2_time_climb = (
            optode_instrument_O2_time[1, :] - start_time
        ) / 60.0

        if optode_correctedO2 is not None:
            optode_correctedO2_dive = optode_correctedO2[0, :]
            optode_correctedO2_climb = optode_correctedO2[1, :]

        if sat_O2 is not None:
            sat_O2_depth_dive = sat_O2_depth[0, :]
            sat_O2_depth_climb = sat_O2_depth[1, :]

            sat_O2_dive = sat_O2[0, :]
            sat_O2_climb = sat_O2[1, :]

            sat_O2_time_dive = (sat_O2_time[0, :] - start_time) / 60.0
            sat_O2_time_climb = (sat_O2_time[1, :] - start_time) / 60.0
    else:
        # Find the deepest sample
        max_depth_sample_index = np.argmax(optode_instrument_O2_depth)

        # Create dive and climb vectors
        depth_dive = optode_instrument_O2_depth[0:max_depth_sample_index]
        depth_climb = optode_instrument_O2_depth[max_depth_sample_index:]

        if optode_instrument_O2 is not None:
            optode_instrument_O2_dive = optode_instrument_O2[0:max_depth_sample_index]
            optode_instrument_O2_climb = optode_instrument_O2[max_depth_sample_index:]

        if optode_instrument_temp is not None:
            optode_instrument_temp_dive = optode_instrument_temp[
                0:max_depth_sample_index
            ]
            optode_instrument_temp_climb = optode_instrument_temp[
                max_depth_sample_index:
            ]

        if not start_time:
            start_time = optode_instrument_O2_time[0]
        optode_instrument_O2_time_dive = (
            optode_instrument_O2_time[0:max_depth_sample_index] - start_time
        ) / 60.0
        optode_instrument_O2_time_climb = (
            optode_instrument_O2_time[max_depth_sample_index:] - start_time
        ) / 60.0

        # For samples and timeout plots
        f_depth = scipy.interpolate.PchipInterpolator(
            optode_instrument_O2_time,
            optode_instrument_O2_depth,
            extrapolate=True,
        )
        max_depth = np.nanmax(
            np.hstack(
                (
                    [] if sat_O2_depth is None else sat_O2_depth,
                    []
                    if optode_instrument_O2_depth is None
                    else optode_instrument_O2_depth,
                )
            )
        )

        if optode_correctedO2 is not None:
            optode_correctedO2_dive = optode_correctedO2[0:max_depth_sample_index]
            optode_correctedO2_climb = optode_correctedO2[max_depth_sample_index:]

        if sat_O2 is not None:
            max_depth_satO2_index = np.argmax(sat_O2_depth)
            sat_O2_depth_dive = sat_O2_depth[0:max_depth_satO2_index]
            sat_O2_depth_climb = sat_O2_depth[max_depth_satO2_index:]

            sat_O2_dive = sat_O2[0:max_depth_satO2_index]
            sat_O2_climb = sat_O2[max_depth_satO2_index:]

            sat_O2_time_dive = (
                sat_O2_time[0:max_depth_satO2_index] - start_time
            ) / 60.0
            sat_O2_time_climb = (
                sat_O2_time[max_depth_satO2_index:] - start_time
            ) / 60.0

    fig = plotly.graph_objects.Figure()

    if optode_instrument_O2 is not None:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": optode_instrument_O2_dive,
                "meta": optode_instrument_O2_time_dive,
                "name": "Instrument Reported O2 Dive",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "Green",
                },
                "hovertemplate": "Inst Reported O2 Dive<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                # $\mu$M/kg
            }
        )
        fig.add_trace(
            {
                "y": depth_climb,
                "x": optode_instrument_O2_climb,
                "meta": optode_instrument_O2_time_climb,
                "name": "Instrument Reported O2 Climb",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Goldenrod",
                },
                "hovertemplate": "Inst Reported O2 Climb<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )
    if o2_qc_good:
        qc_tag = "- QC_GOOD"
    else:
        qc_tag = ""

    if optode_correctedO2 is not None:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": optode_correctedO2_dive,
                "meta": optode_instrument_O2_time_dive,
                "name": f"Corrected O2 dive {qc_tag}",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "Magenta",
                },
                "hovertemplate": "Corrected O2 Dive<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                # $\mu$M/kg
            }
        )
        fig.add_trace(
            {
                "y": depth_climb,
                "x": optode_correctedO2_climb,
                "meta": optode_instrument_O2_time_climb,
                "name": f"Corrected O2 climb {qc_tag}",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Red",
                },
                "hovertemplate": "Corrected O2 Climb<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )

    if sat_O2 is not None:
        fig.add_trace(
            {
                "y": sat_O2_depth_dive,
                "x": sat_O2_dive,
                "meta": sat_O2_time_dive,
                "name": "Sat O2 dive",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "Blue",
                },
                "hovertemplate": "Sat O2 Dive<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "y": sat_O2_depth_climb,
                "x": sat_O2_climb,
                "meta": sat_O2_time_climb,
                "name": "Sat O2 climb",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Cyan",
                },
                "hovertemplate": "Sat O2 Climb<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )

    if optode_instrument_temp is not None:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": optode_instrument_temp_dive,
                "meta": optode_instrument_O2_time_dive,
                "name": "Instrument Reported Temp Dive",
                "type": "scatter",
                "xaxis": "x2",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "LightGrey",
                },
                "hovertemplate": "Inst Reported Temp Dive<br>%{x:.2f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                "visible": "legendonly",
            }
        )
        fig.add_trace(
            {
                "y": depth_climb,
                "x": optode_instrument_temp_climb,
                "meta": optode_instrument_O2_time_climb,
                "name": "Instrument Reported Temp Climb",
                "type": "scatter",
                "xaxis": "x2",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "DarkGrey",
                },
                "hovertemplate": "Inst Reported Temp Climb<br>%{x:.2f} C<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                "visible": "legendonly",
            }
        )

    # Only for time series plots
    timeouts = None
    if max_depth_sample_index is not None:
        timeouts, timeouts_times = PlotUtils.collect_timeouts(
            dive_nc_file, f"aa{optode_type}"
        )

        if timeouts:
            PlotUtils.add_timeout_overlays(
                timeouts,
                timeouts_times,
                fig,
                f_depth,
                optode_instrument_O2_time,
                max_depth_sample_index,
                max_depth,
                start_time,
                "Green",  # To match instrument O2 trace
                "Goldenrod",  # To match instrument O2 trace
            )

        PlotUtils.add_sample_range_overlay(
            optode_instrument_O2_time,
            max_depth_sample_index,
            start_time,
            fig,
            f_depth,
        )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = "%s\nOxygen vs Depth (%scorrected for salinity and depth%s)%s" % (
        mission_dive_str,
        "" if optode_correctedO2 is not None else "not ",
        " - QC_GOOD" if o2_qc_good else "",
        f" - binned {bin_width:.1f} m" if binned_profile else "",
    )
    output_name = "dv%04d_aa%s" % (dive_nc_file.dive_number, optode_type)

    update_dict = {
        "xaxis": {
            "title": r"Dissolved Oxygen (umol/kg)",
            "showgrid": True,
            "side": "top",
            # "range": [min_salinity, max_salinity],
        },
        "yaxis": {
            "title": "Depth (m)",
            "showgrid": True,
            "autorange": "reversed",
            # "range": [
            #     max(
            #         depth_dive.max() if len(depth_dive) > 0 else 0,
            #         depth_climb.max() if len(depth_climb) > 0 else 0,
            #     ),
            #     0,
            # ],
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

    if min_temp is not None:
        update_dict["xaxis2"] = {
            "title": r"Temperature (C)",
            "overlaying": "x1",
            "side": "bottom",
            "range": [min_temp, max_temp],
        }

    fig.update_layout(update_dict)

    # Instrument cal date

    if "sg_cal_calibcomm_oxygen" in dive_nc_file.variables:
        cal_text = (
            dive_nc_file.variables["sg_cal_calibcomm_oxygen"][:].tobytes().decode()
        )
    elif "sg_cal_calibcomm_optode" in dive_nc_file.variables:
        cal_text = (
            dive_nc_file.variables["sg_cal_calibcomm_optode"][:].tobytes().decode()
        )
    else:
        cal_text = ""

    if drift_gain is not None:
        cal_text += f" Drift Gain:{drift_gain:.2f}"

    if timeouts:
        cal_text += f" Timeouts:{timeouts:d}"

    if cal_text:
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
                            "y": -0.14,
                        }
                    ]
                )
            }
        )
    return ([fig], PlotUtilsPlotly.write_output_files(base_opts, output_name, fig))
