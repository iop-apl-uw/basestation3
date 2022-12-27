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

from BaseLog import log_error
from Plotting import plotmissionsingle


# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False


@plotmissionsingle
def mission_int_sensors(
    base_opts: BaseOpts.BaseOptions, mission_str: list
) -> tuple[list, list]:
    """Plots internal pressure, RH, temp"""

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    fig = plotly.graph_objects.Figure()
    df = None
    try:
        df = pd.read_sql_query(
            "SELECT dive,log_HUMID,log_INTERNAL_PRESSURE,log_TEMP from dives",
            conn,
        ).sort_values("dive")
    except:
        log_error("Could not fetch needed columns", "exc")
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

    fig.add_trace(
        {
            "name": "Temperature",
            "x": df["dive"],
            "y": df["log_TEMP"],
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
    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_int_sensors",
            fig,
        ),
    )
