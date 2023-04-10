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

""" Plots internal pressure and RH
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing

import plotly

import pandas as pd

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils
import BaseDB

from BaseLog import log_error, log_info
from Plotting import plotmissionsingle


@plotmissionsingle
def mission_int_sensors(
    base_opts: BaseOpts.BaseOptions, mission_str: list, dive=None, generate_plots=True
) -> tuple[list, list]:
    """Plots internal pressure, RH, temp"""
    log_info("Starting mission_int_sensors")
    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    if dive == None:
        clause = ""
    else:
        clause = f"WHERE dive <= {dive}"

    fig = plotly.graph_objects.Figure()
    df = None
    try:
        df = pd.read_sql_query(
            f"SELECT dive,log_HUMID,log_INTERNAL_PRESSURE from dives {clause} ORDER BY dive ASC",
            conn,
        ).sort_values("dive")
    except:
        log_error("Could not fetch needed columns", "exc")
        conn.close()
        return ([], [])

    df_int_temperature = None
    try:
        df_int_temperature = pd.read_sql_query(
            f"SELECT dive,log_TEMP from dives {clause} ORDER BY dive ASC",
            conn,
        ).sort_values("dive")
    except pd.errors.DatabaseError as e:
        if e.args[0].endswith("no such column: log_TEMP"):
            pass
        else:
            log_error("Unexpected error fetching log_TEMP", "exc")

    for v in ["log_INTERNAL_PRESSURE", "log_HUMID"]:
        m, b = Utils.dive_var_trend(base_opts, df["dive"].to_numpy(), df[v].to_numpy())
        BaseDB.addValToDB(base_opts, df["dive"].to_numpy()[-1], f"{v}_slope", m)

    if not generate_plots:
        log_info("Returning")
        conn.close()
        return ([], [])

    fig.add_trace(
        {
            "name": "Internl Pressure",
            "x": df["dive"],
            "y": df["log_INTERNAL_PRESSURE"],
            "yaxis": "y1",
            "mode": "lines",
            "line": {
                "dash": "solid",
                "color": "DarkMagenta",
                "width": 1,
            },
            "hovertemplate": "Internal Pressure<br>Dive %{x:.0f}<br>pressure %{y:.2f} psia<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "name": "Relative Humidity",
            "x": df["dive"],
            "y": df["log_HUMID"],
            "yaxis": "y2",
            "mode": "lines",
            "line": {
                "dash": "solid",
                "color": "DarkBlue",
                "width": 1,
            },
            "hovertemplate": "Relative Humidity<br>Dive %{x:.0f}<br>RH %{y:.2f} percent<extra></extra>",
        }
    )
    if df_int_temperature is not None:
        fig.add_trace(
            {
                "name": "Temperature",
                "x": df_int_temperature["dive"],
                "y": df_int_temperature["log_TEMP"],
                "yaxis": "y3",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "Red",
                    "width": 1,
                },
                "hovertemplate": "Temperature<br>Dive %{x:.0f}<br>T %{y:.2f}C<extra></extra>",
            }
        )

    title_text = f"{mission_str}<br>Internal Sensors"

    fig.update_layout(
        {
            "xaxis": {
                "title": "Dive Number",
                "showgrid": True,
                "domain": [0.0, 0.9],
            },
            "yaxis": {
                "title": "Internal Pressure (psia)",
                "showgrid": True,
                "tickformat": ".02f",
                "position": 0.0,
            },
            "yaxis2": {
                "title": "Relative Humidity",
                "overlaying": "y1",
                "side": "right",
                "showgrid": False,
                "tickformat": ".02f",
                "position": 0.9,
            },
            "yaxis3": {
                "title": "Temperature (C)",
                "overlaying": "y1",
                "anchor": "free",
                "side": "right",
                "position": 1,
                "showgrid": False,
            },
            "legend": {
                "x": 1.05,
                "y": 1,
            },
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "b": 120,
            },
        },
    )
    conn.close()
    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_int_sensors",
            fig,
        ),
    )
