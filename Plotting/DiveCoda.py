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


@plotdivesingle
def plot_coda(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots coda data and sat O2"""

    if not generate_plots:
        return ([], [])
    is_scicon = False
    if "codaTODO_time" in dive_nc_file.variables:
        is_scicon = True
    elif "codaTODO" in "".join(dive_nc_file.variables):
        pass
    else:
        return ([], [])

    codatodo_correctedO2 = None
    o2_qc_good = False

    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = None

    codatodo_instrument_sat_O2 = codatodo_instrument_compensated_O2 = (
        codatodo_instrument_uncompensated_O2
    ) = codatodo_correctedO2 = None
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
        if "codaTODO_dissolved_oxygen" in dive_nc_file.variables:
            codatodo_correctedO2 = dive_nc_file.variables["codaTODO_dissolved_oxygen"][
                :
            ]
        else:
            log_warning("Did not find corrected codatodo O2")

        if is_scicon:
            codatodo_instrument_O2_time = dive_nc_file.variables["codaTODO_time"][:]
            if "codaTODO_compensated_O2" in dive_nc_file.variables:
                codatodo_instrument_compensated_O2 = dive_nc_file.variables[
                    "codaTODO_compensated_O2"
                ][:]

            if "codaTODO_uncompensated_O2" in dive_nc_file.variables:
                codatodo_instrument_uncompensated_O2 = dive_nc_file.variables[
                    "codaTODO_uncompensated_O2"
                ][:]

            if "codaTODO_O2_sat" in dive_nc_file.variables:
                codatodo_instrument_sat_O2 = dive_nc_file.variables["codaTODO_O2_sat"][
                    :
                ]

            f = scipy.interpolate.interp1d(
                sg_time, sg_depth, kind="linear", bounds_error=False, fill_value=0.0
            )
            codatodo_instrument_O2_depth = f(codatodo_instrument_O2_time)
        else:
            # Truck
            codatodo_instrument_O2_time = sg_time
            if "eng_codatodo_O2_sat" in dive_nc_file.variables:
                codatodo_instrument_sat_O2 = dive_nc_file.variables[
                    "eng_codatodo_O2_sat"
                ][:]
            if "eng_codatodo_compensated_O2" in dive_nc_file.variables:
                codatodo_instrument_compensated_O2 = dive_nc_file.variables[
                    "eng_codatodo_compensated_O2"
                ][:]
            if "eng_codatodo_uncompensated_O2" in dive_nc_file.variables:
                codatodo_instrument_uncompensated_O2 = dive_nc_file.variables[
                    "eng_codatodo_uncompensated_O2"
                ][:]
            codatodo_instrument_O2_depth = sg_depth
    except Exception:
        log_warning("Could not load oxygen data", "exc")

    if codatodo_correctedO2 is not None:
        if "codaTODO_dissolved_oxygen_qc" in dive_nc_file.variables:
            codatodo_correctedO2_qc = QC.decode_qc(
                dive_nc_file.variables["codaTODO_dissolved_oxygen_qc"][:]
            )
            codatodo_correctedO2 = np.ma.array(
                codatodo_correctedO2,
                mask=np.logical_not(
                    QC.find_qc(
                        codatodo_correctedO2_qc, QC.only_good_qc_values, mask=True
                    )
                ),
            )
            o2_qc_good = True
        else:
            log_warning("Did not find corrected optode O2 qc")
            o2_qc_good = False

    # Find the deepest sample
    max_depth_sample_index = np.argmax(codatodo_instrument_O2_depth)

    # Create dive and climb vectors
    depth_dive = codatodo_instrument_O2_depth[0:max_depth_sample_index]
    depth_climb = codatodo_instrument_O2_depth[max_depth_sample_index:]

    if codatodo_instrument_compensated_O2 is not None:
        codatodo_instrument_compensated_O2_dive = codatodo_instrument_compensated_O2[
            0:max_depth_sample_index
        ]
        codatodo_instrument_compensated_O2_climb = codatodo_instrument_compensated_O2[
            max_depth_sample_index:
        ]

    if codatodo_instrument_uncompensated_O2 is not None:
        codatodo_instrument_uncompensated_O2_dive = (
            codatodo_instrument_uncompensated_O2[0:max_depth_sample_index]
        )
        codatodo_instrument_uncompensated_O2_climb = (
            codatodo_instrument_uncompensated_O2[max_depth_sample_index:]
        )

    if codatodo_instrument_sat_O2 is not None:
        codatodo_instrument_sat_O2_dive = codatodo_instrument_sat_O2[
            0:max_depth_sample_index
        ]
        codatodo_instrument_sat_O2_climb = codatodo_instrument_sat_O2[
            max_depth_sample_index:
        ]

    if codatodo_correctedO2 is not None:
        codatodo_correctedO2_dive = codatodo_correctedO2[0:max_depth_sample_index]
        codatodo_correctedO2_climb = codatodo_correctedO2[max_depth_sample_index:]

    if not start_time:
        start_time = codatodo_instrument_O2_time[0]
    codatodo_instrument_O2_time_dive = (
        codatodo_instrument_O2_time[0:max_depth_sample_index] - start_time
    ) / 60.0
    codatodo_instrument_O2_time_climb = (
        codatodo_instrument_O2_time[max_depth_sample_index:] - start_time
    ) / 60.0

    fig = plotly.graph_objects.Figure()

    if codatodo_instrument_compensated_O2 is not None:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": codatodo_instrument_compensated_O2_dive,
                "meta": codatodo_instrument_O2_time_dive,
                "name": "Instrument Reported Compensated O2 Dive",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "Green",
                },
                "hovertemplate": "Inst Reported Compensated O2 Dive<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "y": depth_climb,
                "x": codatodo_instrument_compensated_O2_climb,
                "meta": codatodo_instrument_O2_time_climb,
                "name": "Instrument Reported Compensated O2 Climb",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Goldenrod",
                },
                "hovertemplate": "Inst Reported Compensated O2 Climb<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )

    if codatodo_instrument_uncompensated_O2 is not None:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": codatodo_instrument_uncompensated_O2_dive,
                "meta": codatodo_instrument_O2_time_dive,
                "name": "Instrument Reported Uncompensated O2 Dive",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "DarkMagenta",
                },
                "hovertemplate": "Inst Reported Uncompensated O2 Dive<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "y": depth_climb,
                "x": codatodo_instrument_uncompensated_O2_climb,
                "meta": codatodo_instrument_O2_time_climb,
                "name": "Instrument Reported Uncompensated O2 Climb",
                "type": "scatter",
                "xaxis": "x1",
                "yaxis": "y1",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Black",
                },
                "hovertemplate": "Inst Reported Uncompensated O2 Climb<br>%{x:.2f} umol/kg<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
            }
        )

    if o2_qc_good:
        qc_tag = "- QC_GOOD"
    else:
        qc_tag = ""

    if codatodo_correctedO2 is not None:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": codatodo_correctedO2_dive,
                "meta": codatodo_instrument_O2_time_dive,
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
                "x": codatodo_correctedO2_climb,
                "meta": codatodo_instrument_O2_time_climb,
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

    if codatodo_instrument_sat_O2 is not None:
        fig.add_trace(
            {
                "y": depth_dive,
                "x": codatodo_instrument_sat_O2_dive,
                "meta": codatodo_instrument_O2_time_dive,
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
                "y": depth_climb,
                "x": codatodo_instrument_sat_O2_climb,
                "meta": codatodo_instrument_O2_time_climb,
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
    title_text = "%s\nOxygen vs Depth (%scorrected for salinity and depth%s)" % (
        mission_dive_str,
        "" if codatodo_correctedO2 is not None else "not ",
        " - QC_GOOD" if o2_qc_good else "",
    )
    output_name = "dv%04d_codatodo" % dive_nc_file.dive_number

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

    if "sg_cal_calibcomm_codaTODO" in dive_nc_file.variables:
        cal_text = (
            dive_nc_file.variables["sg_cal_calibcomm_codaTODO"][:].tobytes().decode()
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
