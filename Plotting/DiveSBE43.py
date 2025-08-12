#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025, 2025  University of Washington.
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

"""Plots sbe43 data"""

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
def plot_sbe43(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots sbe43 data and sat O2"""

    if not generate_plots:
        return ([], [])
    is_scicon = False
    if "sbe43_time" in dive_nc_file.variables:
        is_scicon = True
    elif "sbe43" in "".join(dive_nc_file.variables):
        pass
    else:
        return ([], [])

    sbe43_correctedO2 = None
    o2_qc_good = False

    # TODO - fix this universally - start_time or start of data UNLESS in binned profile
    # - then just give up.
    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = None

    binned_profile = "profile_data_point" in dive_nc_file.dimensions

    sat_O2 = sbe43_correctedO2 = None
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
                return ([], [])
        # Interpolate around missing depth observations
        sg_depth = PlotUtils.interp_missing_depth(sg_time, sg_depth)

        if binned_profile:
            bin_width = np.round(np.average(np.diff(sg_depth[0, :])), decimals=1)
        if "sbe43_dissolved_oxygen" in dive_nc_file.variables:
            sbe43_correctedO2 = dive_nc_file.variables["sbe43_dissolved_oxygen"][:]
        else:
            log_warning("Did not find corrected sbe43 O2")

        if is_scicon and not binned_profile:
            sbe43_instrument_O2_time = dive_nc_file.variables["sbe43_time"][:]

            if "dissolved_oxygen_sat" in dive_nc_file.variables:
                sat_O2 = dive_nc_file.variables["dissolved_oxygen_sat"]
                sat_O2_time = find_matching_time(dive_nc_file, sat_O2)
                sat_O2 = sat_O2[:]

            f = scipy.interpolate.interp1d(
                sg_time, sg_depth, kind="linear", bounds_error=False, fill_value=0.0
            )
            sbe43_instrument_O2_depth = f(sbe43_instrument_O2_time)
            if sat_O2 is not None:
                sat_O2_depth = f(sat_O2_time)
        else:
            # Truck
            sbe43_instrument_O2_time = sg_time
            sat_O2_depth = sbe43_instrument_O2_depth = sg_depth
            sat_O2_time = sg_time
            if "dissolved_oxygen_sat" in dive_nc_file.variables:
                sat_O2 = dive_nc_file.variables["dissolved_oxygen_sat"][:]
    except Exception:
        log_warning("Could not load oxygen data", "exc")

    if sbe43_correctedO2 is not None:
        if "sbe43_dissolved_oxygen_qc" in dive_nc_file.variables:
            sbe43_correctedO2_qc = QC.decode_qc(
                dive_nc_file.variables["sbe43_dissolved_oxygen_qc"][:]
            )
            sbe43_correctedO2 = np.ma.array(
                sbe43_correctedO2,
                mask=np.logical_not(
                    QC.find_qc(sbe43_correctedO2_qc, QC.only_good_qc_values, mask=True)
                ),
            )
            o2_qc_good = True
        else:
            log_warning("Did not find corrected sbe43 O2 qc")
            o2_qc_good = False

    if binned_profile:
        # Create dive and climb vectors
        depth_dive = sbe43_instrument_O2_depth[0, :]
        depth_climb = sbe43_instrument_O2_depth[1, :]

        if not start_time:
            start_time = sbe43_instrument_O2_time[0, 0]
        sbe43_instrument_O2_time_dive = (
            sbe43_instrument_O2_time[0, :] - start_time
        ) / 60.0
        sbe43_instrument_O2_time_climb = (
            sbe43_instrument_O2_time[1, :] - start_time
        ) / 60.0

        if sbe43_correctedO2 is not None:
            sbe43_correctedO2_dive = sbe43_correctedO2[0, :]
            sbe43_correctedO2_climb = sbe43_correctedO2[1, :]

        if sat_O2 is not None:
            sat_O2_depth_dive = sat_O2_depth[0, :]
            sat_O2_depth_climb = sat_O2_depth[1, :]

            sat_O2_dive = sat_O2[0, :]
            sat_O2_climb = sat_O2[1, :]

            sat_O2_time_dive = (sat_O2_time[0, :] - start_time) / 60.0
            sat_O2_time_climb = (sat_O2_time[1, :] - start_time) / 60.0
    else:
        # Find the deepest sample
        max_depth_sample_index = np.argmax(sbe43_instrument_O2_depth)

        # Create dive and climb vectors
        depth_dive = sbe43_instrument_O2_depth[0:max_depth_sample_index]
        depth_climb = sbe43_instrument_O2_depth[max_depth_sample_index:]

        if not start_time:
            start_time = sbe43_instrument_O2_time[0]
        sbe43_instrument_O2_time_dive = (
            sbe43_instrument_O2_time[0:max_depth_sample_index] - start_time
        ) / 60.0
        sbe43_instrument_O2_time_climb = (
            sbe43_instrument_O2_time[max_depth_sample_index:] - start_time
        ) / 60.0

        if sbe43_correctedO2 is not None:
            sbe43_correctedO2_dive = sbe43_correctedO2[0:max_depth_sample_index]
            sbe43_correctedO2_climb = sbe43_correctedO2[max_depth_sample_index:]

        if sat_O2 is not None:
            max_depth_sample_index = np.argmax(sat_O2_depth)
            sat_O2_depth_dive = sat_O2_depth[0:max_depth_sample_index]
            sat_O2_depth_climb = sat_O2_depth[max_depth_sample_index:]

            sat_O2_dive = sat_O2[0:max_depth_sample_index]
            sat_O2_climb = sat_O2[max_depth_sample_index:]

            sat_O2_time_dive = (
                sat_O2_time[0:max_depth_sample_index] - start_time
            ) / 60.0
            sat_O2_time_climb = (
                sat_O2_time[max_depth_sample_index:] - start_time
            ) / 60.0

    fig = plotly.graph_objects.Figure()

    if o2_qc_good:
        qc_tag = "- QC_GOOD"
    else:
        qc_tag = ""

    if sbe43_correctedO2 is not None:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": sbe43_correctedO2_dive,
                "meta": sbe43_instrument_O2_time_dive,
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
                "x": sbe43_correctedO2_climb,
                "meta": sbe43_instrument_O2_time_climb,
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

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = "%s\nOxygen vs Depth (%scorrected for salinity and depth%s)%s" % (
        mission_dive_str,
        "" if sbe43_correctedO2 is not None else "not ",
        " - QC_GOOD" if o2_qc_good else "",
        f" - binned {bin_width:.1f} m" if binned_profile else "",
    )
    output_name = f"dv{dive_nc_file.dive_number:04d}_sbe43"

    fig.update_layout(
        {
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
    )

    # Instrument cal date

    if "sg_cal_calibcomm_oxygen" in dive_nc_file.variables:
        cal_text = (
            dive_nc_file.variables["sg_cal_calibcomm_oxygen"][:].tobytes().decode()
        )
    elif "sg_cal_calibcomm_sbe43" in dive_nc_file.variables:
        cal_text = (
            dive_nc_file.variables["sg_cal_calibcomm_sbe43"][:].tobytes().decode()
        )
    else:
        cal_text = ""

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
                            "y": -0.08,
                        }
                    ]
                )
            }
        )
    return ([fig], PlotUtilsPlotly.write_output_files(base_opts, output_name, fig))
