#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025, 2026  University of Washington.
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

"""Plots internal pressure and RH"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import typing

import pandas as pd
import plotly.graph_objects

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import BaseDB
import PlotUtilsPlotly
import Utils
from BaseLog import log_error, log_info, log_warning
from Plotting import plotmissionsingle

additional_plot = collections.namedtuple(
    "additional_plot",
    ["df", "trace_name", "col_name", "color", "yaxis", "hovertemplate"],
)


def add_additional_trace(
    fig: plotly.graph_objects.Figure, add_plot: additional_plot
) -> None:
    fig.add_trace(
        {
            "name": add_plot.trace_name,
            "x": add_plot.df["dive"],
            "y": add_plot.df[add_plot.col_name],
            "yaxis": add_plot.yaxis,
            "mode": "lines",
            "line": {
                "dash": "solid",
                "color": add_plot.color,
                "width": 1,
            },
            "visible": "legendonly",
            "hovertemplate": add_plot.hovertemplate,
        }
    )


@plotmissionsingle
def mission_int_sensors(
    base_opts: BaseOpts.BaseOptions,
    mission_str: list,
    dive=None,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots internal pressure, RH, temp"""
    log_info("Starting mission_int_sensors")

    if dbcon is None:
        conn = Utils.open_mission_database(base_opts)
        log_info("mission_int_sensors db opened")
    else:
        conn = dbcon

    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    if dive is None:
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
    except Exception:
        log_error("Could not fetch needed columns", "exc")
        if dbcon is None:
            conn.close()
            log_info("mission_int_sensors db closed")
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
        try:
            if len(df["dive"].to_numpy()) > 0:
                m, b = Utils.dive_var_trend(
                    base_opts, df["dive"].to_numpy(), df[v].to_numpy()
                )
                BaseDB.addValToDB(
                    base_opts, df["dive"].to_numpy()[-1], f"{v}_slope", m, con=conn
                )
        except Exception as exception:
            log_warning(f"Failed slope calculation for {v} {exception} - skipping")

    cols = [x[1] for x in conn.cursor().execute("PRAGMA table_info(dives)").fetchall()]
    add_plots: list[additional_plot] = []
    for col_name, plot_name, color, yaxis, hovertemplate in (
        (
            "log_HUMID_LIMIT",
            "Relative Humidity Limit",
            "black",
            "y2",
            "Relative Humidity Limit<br>Dive %{x:.0f}<br>RH %{y:.2f} percent<extra></extra>",
        ),
        (
            "log_HUMID_MIN",
            "Relative Humidity Min",
            "Cyan",
            "y2",
            "Relative Humidity Min<br>Dive %{x:.0f}<br>RH %{y:.2f} percent<extra></extra>",
        ),
        (
            "log_HUMID_MAX",
            "Relative Humidity Max",
            "DarkBlue",
            "y2",
            "Relative Humidity Max<br>Dive %{x:.0f}<br>RH %{y:.2f} percent<extra></extra>",
        ),
        (
            "log_INTERNAL_PRESSURE_LATCH",
            "Internal Pressure Latch",
            "DarkGrey",
            "y1",
            "InternalPressure Latch<br>Dive %{x:.0f}<br>pressure %{y:.2f} psia<extra></extra>",
        ),
        (
            "log_INTERNAL_PRESSURE_MIN",
            "Internal Pressure Min",
            "#EE82EE",
            "y1",
            "InternalPressure Min<br>Dive %{x:.0f}<br>pressure %{y:.2f} psia<extra></extra>",
        ),
        (
            "log_INTERNAL_PRESSURE_MAX",
            "Internal Pressure Max",
            "DarkMagenta",
            "y1",
            "InternalPressure Max<br>Dive %{x:.0f}<br>pressure %{y:.2f} psia<extra></extra>",
        ),
    ):
        if col_name not in cols:
            continue
        try:
            add_df = pd.read_sql_query(
                f"SELECT dive,{col_name} from dives {clause} ORDER BY dive ASC",
                conn,
            ).sort_values("dive")
        except pd.errors.DatabaseError as e:
            if e.args[0].endswith(f"no such column: log_{col_name}"):
                pass
            else:
                log_error(f"Unexpected error fetching {col_name}", "exc")
        else:
            # Skip empty columns
            if add_df[col_name].isnull().all():
                continue
            add_plots.append(
                additional_plot(
                    add_df, plot_name, col_name, color, yaxis, hovertemplate
                )
            )

    if dbcon is None:
        try:
            conn.commit()
        except Exception as e:
            conn.rollback()
            log_error(f"Failed commit, MissionIntSensors {e}", "exc")

        log_info("mission_int_sensors db closed")
        conn.close()

    if not generate_plots:
        log_info("Returning")
        return ([], [])

    fig.add_trace(
        {
            "name": "Internal Pressure",
            "x": df["dive"],
            "y": df["log_INTERNAL_PRESSURE"],
            "yaxis": "y1",
            "mode": "lines",
            "line": {
                "dash": "solid",
                "color": "magenta",
                "width": 1,
            },
            "hovertemplate": "Internal Pressure<br>Dive %{x:.0f}<br>pressure %{y:.2f} psia<extra></extra>",
        }
    )

    for add_plot in add_plots:
        if "Pressure" not in add_plot.trace_name:
            continue
        add_additional_trace(fig, add_plot)

    fig.add_trace(
        {
            "name": "Relative Humidity",
            "x": df["dive"],
            "y": df["log_HUMID"],
            "yaxis": "y2",
            "mode": "lines",
            "line": {
                "dash": "solid",
                # "color": "DarkBlue",
                "color": "blue",
                "width": 1,
            },
            "hovertemplate": "Relative Humidity<br>Dive %{x:.0f}<br>RH %{y:.2f} percent<extra></extra>",
        }
    )

    for add_plot in add_plots:
        if "Humidity" not in add_plot.trace_name:
            continue
        add_additional_trace(fig, add_plot)

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
                    "color": "olive",
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
    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_int_sensors",
            fig,
        ),
    )
