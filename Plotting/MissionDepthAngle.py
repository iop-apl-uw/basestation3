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

""" Plots surface depth and angle
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
def mission_depthangle(
    base_opts: BaseOpts.BaseOptions, mission_str: list, dive=None
) -> tuple[list, list]:
    """Plots surface depth and angle """

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    fig = plotly.graph_objects.Figure()
    df = None
    try:
        df = pd.read_sql_query(
            "SELECT dive,log__SM_DEPTHo,log__SM_ANGLEo from dives",
            conn,
        ).sort_values("dive")
    except:
        log_error("Could not fetch needed columns", "exc")
        return ([], [])

    fig.add_trace(
        {
            "name": "Surface Maneuver Depth (m)",
            "x": df["dive"],
            "y": df["log__SM_DEPTHo"],
            "yaxis": "y1",
            "mode": "lines",
            "line": {
                "dash": "solid",
                "color": "red",
                "width": 1,
            },
            "hovertemplate": "Surface Depth<br>Dive %{x:.0f}<br>depth %{y:.2f} m<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "name": "Surface Maneuver Angle (deg)",
            "x": df["dive"],
            "y": df["log__SM_ANGLEo"],
            "yaxis": "y2",
            "mode": "lines",
            "line": {
                "dash": "solid",
                "color": "blue",
                "width": 1,
            },
            "hovertemplate": "Surface Angle<br>Dive %{x:.0f}<br>angle %{y:.2f} deg<extra></extra>",
        }
    )

    title_text = f"{mission_str}<br>Surface Maneuver Depth and Angle"

    fig.update_layout(
        {
            "xaxis": {
                "title": "Dive Number",
                "showgrid": True,
            },
            "yaxis": {
                "title": "Surface Maneuver Depth (m)",
                "showgrid": True,
                "tickformat": ".1f",
                'autorange' : 'reversed',
            },
            "yaxis2": {
                "title": "Surface Maneuver Angle (deg)",
                "overlaying": "y1",
                "side": "right",
                "showgrid": False,
                "tickformat": "-.0f",
                'autorange' : 'reversed',
            },
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "legend": {
                "x": 1.05,
                "y": 1,
            },
            "margin": {
                "b": 80,
            },
        },
    )
    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_depthangle",
            fig,
        ),
    )
