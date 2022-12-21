#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

""" Plots volume estimates
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import pdb
import sys
import traceback
import typing

import plotly

import pandas as pd

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils

from BaseLog import log_error, log_warning
from Plotting import plotmissionsingle


# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False


@plotmissionsingle
def mission_volume(
    base_opts: BaseOpts.BaseOptions, mission_str: list
) -> tuple[list, list]:
    """Plots various estimates for volmax"""

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    fig = plotly.graph_objects.Figure()
    df = None
    try:
        df = pd.read_sql_query(
            "SELECT dive,implied_volmax from dives",
            conn,
        ).sort_values("dive")
    except:
        log_error("Could not fetch needed columns", "exc")
        return ([], [])

    glider_df = None
    try:
        glider_df = pd.read_sql_query(
            "SELECT dive,implied_volmax_glider from dives",
            conn,
        ).sort_values("dive")
    except pd.io.sql.DatabaseError:
        log_warning("Could not load implied volmax from the glider estimate", "exc")

    flight_df = None
    try:
        flight_df = pd.read_sql_query(
            "SELECT dive,implied_volmax_fm from dives",
            conn,
        ).sort_values("dive")
    except pd.io.sql.DatabaseError:
        log_warning(
            "Could not load implied volmax from the flight model estimate", "exc"
        )

    fig.add_trace(
        {
            "name": "Basestation volmax",
            "x": df["dive"],
            "y": df["implied_volmax"],
            "yaxis": "y1",
            "mode": "lines",
            "line": {
                "dash": "solid",
                "color": "DarkMagenta",
                "width": 1,
            },
            "hovertemplate": "Basestation volmax estimate<br>Dive %{x:.0f}<br>volmax %{y:.0f} cc<extra></extra>",
        }
    )
    if glider_df is not None:
        fig.add_trace(
            {
                "name": "Glider volmax",
                "x": glider_df["dive"],
                "y": glider_df["implied_volmax_glider"],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "DarkBlue",
                    "width": 1,
                },
                "hovertemplate": "Glider volmax estimate<br>Dive %{x:.0f}<br>volmax %{y:.0f} cc<extra></extra>",
            }
        )

    if flight_df is not None:
        fig.add_trace(
            {
                "name": "Flight Model volmax",
                "x": flight_df["dive"],
                "y": flight_df["implied_volmax_fm"],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "Dark Green",
                    "width": 1,
                },
                "hovertemplate": "FM volmax estimate<br>Dive %{x:.0f}<br>volmax %{y:.0f} cc<extra></extra>",
            }
        )

    title_text = f"{mission_str}<br>Volmax estimates"

    fig.update_layout(
        {
            "xaxis": {
                "title": "Dive Number",
                "showgrid": True,
            },
            "yaxis": {
                "title": "volmax (cc)",
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
