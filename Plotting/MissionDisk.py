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

""" Plots disk stats
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
def mission_disk(
    base_opts: BaseOpts.BaseOptions, mission_str: list
) -> tuple[list, list]:
    """Plots disk stats """

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    res = conn.cursor().execute('PRAGMA table_info(dives)')
    columns = [i[1] for i in res]

    qcols = list(filter(lambda x: x.startswith("SD_") or x.endswith("_FREEKB"), columns))

    if len(qcols) == 0:
        return ([], [])

    qstr = ",".join(qcols);

    fig = plotly.graph_objects.Figure()
    df = None
    try:
        df = pd.read_sql_query(
            f"SELECT dive,{qstr} from dives",
            conn,
        ).sort_values("dive")
    except:
        log_error("Could not fetch needed columns", "exc")
        return ([], [])

    y_offset = -0.08

    l_annotations = []

    if "SD_free" in df.columns:
        fig.add_trace(
            {
                "name": "SD free kB",
                "x": df["dive"],
                "y": df["SD_free"],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "red",
                    "width": 1,
                },
            }
        )

        m,b = np.polyfit(df["dive"].to_numpy(), df["SD_free"].to_numpy(), 1)

        y_offset += -0.02
        l_annotations.append(
            {
                "text": f"based on SD free, {-b/m:.0f} dives until full",
                "showarrow": False,
                "xref": "paper",
                "yref": "paper",
                "x": 0.0,
                "y": y_offset,
            }
        )   

    if "SD_files" in df.columns:
        fig.add_trace(
            {
                "name": "SD file count",
                "x": df["dive"],
                "y": df["SD_files"],
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "blue",
                    "width": 1,
                },
            }
        )

    if "SD_dirs" in df.columns:
        fig.add_trace(
            {
                "name": "SD dir count",
                "x": df["dive"],
                "y": df["SD_dirs"],
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "cyan",
                    "width": 1,
                },
            }
        )

    for v in list(df.columns.values):
        if not v.endswith("FREEKB"):
            continue
        
        nm = v.replace('log_', '')
        fig.add_trace(
            {
                "name": nm,
                "x": df["dive"],
                "y": df[v],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "width": 1,
                },
            }
        )

        m,b = np.polyfit(df["dive"].to_numpy(), df[v].to_numpy(), 1)

        y_offset += -0.02
        l_annotations.append(
            {
                "text": f"based on {nm}, {-b/m:.0f} dives until full",
                "showarrow": False,
                "xref": "paper",
                "yref": "paper",
                "x": 0.0,
                "y": y_offset,
            }
        )   



    fig.update_layout(
        {
            "xaxis": {
                "title": "Dive Number",
                "showgrid": True,
            },
            "yaxis": {
                "title": "free space (kB)",
                "showgrid": True,
                "tickformat": ".0f",
            },
            "yaxis2": {
                "title": "count",
                "overlaying": "y1",
                "side": "right",
                "showgrid": False,
                "tickformat": ".0f",
            },
            "title": {
                "text": f"{mission_str}<br>Disk usage",
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
                "b": 120,
            },
            "annotations": tuple(l_annotations),
        },
    )
    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_disk",
            fig,
        ),
    )
