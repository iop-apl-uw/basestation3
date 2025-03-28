#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024  University of Washington.
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

""" Plots volume estimates
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import sqlite3
import typing

import pandas as pd
import plotly

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils
from BaseLog import log_error, log_info, log_warning
from Plotting import plotmissionsingle


# pylint: disable=unused-argument
@plotmissionsingle
def mission_volume(
    base_opts: BaseOpts.BaseOptions,
    mission_str: list,
    dive=None,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots various estimates for volmax"""

    if not generate_plots:
        return ([], [])

    if dbcon is None:
        conn = Utils.open_mission_database(base_opts, ro=True)
        if not conn:
            log_error("Could not open mission database")
            return ([], [])
        log_info("mission_volume db opened (ro)")
    else:
        conn = dbcon

    cur = conn.cursor()
    res = cur.execute("PRAGMA table_info(dives)")
    columns = [i[1] for i in res]

    fig = plotly.graph_objects.Figure()
    volmax_df = None
    if "implied_volmax" in columns:
        try:
            volmax_df = pd.read_sql_query(
                "SELECT dive,implied_volmax from dives",
                conn,
            ).sort_values("dive")
        except (pd.io.sql.DatabaseError, sqlite3.OperationalError):
            log_warning("Could not load implied volmax", "exc")

    regressed_volmax_df = None
    if "vert_vel_regress_volmax" in columns:
        try:
            regressed_volmax_df = pd.read_sql_query(
                "SELECT dive,vert_vel_regress_volmax from dives",
                conn,
            ).sort_values("dive")
        except (pd.io.sql.DatabaseError, sqlite3.OperationalError):
            log_warning("Could not load implied volmax", "exc")

    volmax_GSM_df = None
    if "implied_volmax_GSM" in columns:
        try:
            volmax_GSM_df = pd.read_sql_query(
                "SELECT dive,implied_volmax_GSM from dives",
                conn,
            ).sort_values("dive")
        except (pd.io.sql.DatabaseError, sqlite3.OperationalError):
            log_warning("Could not load implied volmax GSM", "exc")

    glider_df = None
    if "implied_volmax_glider" in columns:
        try:
            glider_df = pd.read_sql_query(
                "SELECT dive,implied_volmax_glider from dives",
                conn,
            ).sort_values("dive")
        except (sqlite3.OperationalError, pd.io.sql.DatabaseError):
            log_warning("Could not load implied volmax from the glider estimate", "exc")

    flight_df = None
    if "implied_volmax_fm" in columns:
        try:
            flight_df = pd.read_sql_query(
                "SELECT dive,implied_volmax_fm from dives",
                conn,
            ).sort_values("dive")
        except (sqlite3.OperationalError, pd.io.sql.DatabaseError):
            log_warning(
                "Could not load implied volmax from the flight model estimate", "exc"
            )

    if dbcon is None:
        conn.close()
        log_info("mission_volume db closed")

    if volmax_df is not None:
        fig.add_trace(
            {
                "name": "Basestation Volmax",
                "x": volmax_df["dive"],
                "y": volmax_df["implied_volmax"],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "DarkCyan",
                    "width": 1,
                },
                "hovertemplate": "Basestation Volmax estimate<br>Dive %{x:.0f}<br>volmax %{y:.0f} cc<extra></extra>",
            }
        )
    if regressed_volmax_df is not None:
        fig.add_trace(
            {
                "name": "Basestation Regressed Volmax",
                "x": regressed_volmax_df["dive"],
                "y": regressed_volmax_df["vert_vel_regress_volmax"],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "DarkMagenta",
                    "width": 1,
                },
                "hovertemplate": "Basestation Regressed Volmax estimate<br>Dive %{x:.0f}<br>volmax %{y:.0f} cc<extra></extra>",
            }
        )
    if volmax_GSM_df is not None:
        fig.add_trace(
            {
                "name": "GSM Volmax",
                "x": volmax_GSM_df["dive"],
                "y": volmax_GSM_df["implied_volmax_GSM"],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "darkgoldenrod",
                    "width": 1,
                },
                "hovertemplate": "GSM Volmax estimate<br>Dive %{x:.0f}<br>volmax %{y:.0f} cc<extra></extra>",
            }
        )
    if glider_df is not None:
        fig.add_trace(
            {
                "name": "Glider On Board Volmax",
                "x": glider_df["dive"],
                "y": glider_df["implied_volmax_glider"],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "DarkBlue",
                    "width": 1,
                },
                "hovertemplate": "Glider Volmax estimate<br>Dive %{x:.0f}<br>volmax %{y:.0f} cc<extra></extra>",
            }
        )

    if flight_df is not None:
        fig.add_trace(
            {
                "name": "Flight Model Volmax",
                "x": flight_df["dive"],
                "y": flight_df["implied_volmax_fm"],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "Dark Green",
                    "width": 1,
                },
                "hovertemplate": "FM Volmax estimate<br>Dive %{x:.0f}<br>volmax %{y:.0f} cc<extra></extra>",
            }
        )

    title_text = f"{mission_str}<br>Volmax Estimates"

    fig.update_layout(
        {
            "xaxis": {
                "title": "Dive",
                "showgrid": True,
            },
            "yaxis": {
                "title": "Volmax (cc)",
                "showgrid": True,
                "tickformat": "d",
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
            "eng_mission_volmax",
            fig,
        ),
    )
