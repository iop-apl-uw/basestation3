#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022, 2023 by University of Washington.  All rights reserved.
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

""" Plots comm.log counter values
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
import numpy as np

from BaseLog import log_error
from Plotting import plotmissionsingle


# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False


@plotmissionsingle
def mission_commlog(
    base_opts: BaseOpts.BaseOptions, mission_str: list, dive=None, generate_plots=True
) -> tuple[list, list]:
    """Plots disk stats"""

    if not generate_plots:
        return ([], [])

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    fig = plotly.graph_objects.Figure()
    df = None
    try:
        df = pd.read_sql_query(
            "SELECT * FROM calls ORDER BY dive,cycle,call",
            conn,
        )
    except:
        log_error("Could not fetch needed columns", "exc")
        return ([], [])


    callNum = np.arange(0, len(df["pitch"]))

    if "pitch" in df.columns:
        fig.add_trace(
            {
                "name": "pitch/-5",
                "x": callNum,
                "y": df["pitch"]/-5,
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "red",
                    "width": 1,
                },
            }
        )

    if "depth" in df.columns:
        fig.add_trace(
            {
                "name": "depth",
                "x": callNum,
                "y": df["depth"],
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "green",
                    "width": 1,
                },
            }
        )

    if "intP" in df.columns:
        fig.add_trace(
            {
                "name": "internal pressure",
                "x": callNum,
                "y": df["intP"],
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "magenta",
                    "width": 1,
                },
            }
        )

    if "RH" in df.columns:
        fig.add_trace(
            {
                "name": "relative humidity/10",
                "x": callNum,
                "y": df["RH"]/10,
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "yellow",
                    "width": 2,
                },
            }
        )

    if "volts10" in df.columns:
        fig.add_trace(
            {
                "name": "low volts",
                "x": callNum,
                "y": df["volts10"],
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "blue",
                    "width": 1,
                },
            }
        )

    if "volts24" in df.columns:
        fig.add_trace(
            {
                "name": "high volts",
                "x": callNum,
                "y": df["volts24"],
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "cyan",
                    "width": 1,
                },
            }
        )

    colors = ["red", "blue", "green"]
    for i, a in enumerate(["pitchAD", "rollAD" ,"vbdAD"]):
    
        if a in df.columns:
            fig.add_trace(
                {
                    "name": a,
                    "x": callNum,
                    "y": df[a],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {
                        "dash": "dash",
                        "color": colors[i],
                        "width": 1,
                    },
                }
            )

    fig.update_layout(
        {
            "xaxis": {
                "title": "Call number",
                "showgrid": True,
                "domain": [0.0, 0.925],
            },
            "yaxis": {
                "title": "AD value",
                "showgrid": True,
            },
            "yaxis2": {
                "title": "value",
                "showgrid": False,
                "overlaying": "y1",
                "side": "right",
                "position": 0.925,
            },

            "title": {
                "text": "CommLog counter line values",
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "t": 100,
                "b": 125,
            },
            "legend": {
                "x": 1.075,
                "y": 1,
            }
        },
    )
    conn.close()

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_commlog",
            fig,
        ),
    )
