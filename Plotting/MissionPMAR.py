#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025  University of Washington.
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

"""Plots PMAR stats"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import typing
from dataclasses import dataclass
from typing import Any

import pandas as pd
import plotly

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils
from BaseLog import log_error, log_info
from Plotting import plotmissionsingle


@plotmissionsingle
def mission_pmar_stats(
    base_opts: BaseOpts.BaseOptions,
    mission_str: list,
    dive=None,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots disk stats"""

    plot_details = collections.namedtuple(
        "plot_details",
        (
            "yaxis",
            "color",
            "htext",
        ),
    )

    pmar_stats = {
        "pmar_bufferfull": plot_details("y1", "red", "count"),
        "pmar_writeerrors": plot_details("y1", "magenta", "count"),
        "pmar_datafiles": plot_details("y4", "indigo", "num files"),
        "pmar_datafailedfiles": plot_details("y4", "violet", "num files"),
        "pmar_goodblocks": plot_details("y2", "green", "num blocks"),
        "pmar_motordroppedblocks": plot_details("y2", "cyan", "num blocks"),
        "pmar_clipdroppedblocks": plot_details("y2", "blue", "num blocks"),
        "pmar_totalclip": plot_details("y3", "orange", "clip count"),
        "pmar_totaldespike": plot_details("y3", "darkgoldenrod", "despike count"),
    }

    if not generate_plots:
        return ([], [])

    if dbcon is None:
        conn = Utils.open_mission_database(base_opts, ro=True)
        if not conn:
            log_error("Could not open mission database")
            return ([], [])
        log_info("mission_disk db opened (ro)")
    else:
        conn = dbcon

    res = conn.cursor().execute("PRAGMA table_info(dives)")
    columns = [i[1] for i in res]

    qcols = []
    for col in columns:
        for stat in pmar_stats:
            if col.startswith(stat):
                qcols.append(col)

    if len(qcols) == 0:
        return ([], [])

    qstr = ",".join(qcols)

    df = None
    try:
        df = pd.read_sql_query(
            f"SELECT dive,{qstr} from dives",
            conn,
        ).sort_values("dive")
    except Exception:
        log_error("Could not fetch needed columns", "exc")
        if dbcon is None:
            conn.close()
            log_info("mission_disk db closed")
        return ([], [])

    if dbcon is None:
        conn.close()
        log_info("mission_disk db closed")

    # accum_details = collections.namedtuple(
    #     "accum_details",
    #     (
    #         "stat_name",
    #         "accum",
    #     ),
    # )
    @dataclass
    class accum_details:
        stat_name: str
        accum: Any

    accums = {}
    for profile in ("a", "c", "b", "d"):
        for channel in ("00", "01"):
            for stat in pmar_stats:
                stat_ch = f"{stat}_ch{channel}"
                var_name = f"{stat}_{profile}_ch{channel}"
                if var_name in df:
                    if stat_ch in accums:
                        accums[stat_ch].accum += df[var_name].to_numpy()
                    else:
                        accums[stat_ch] = accum_details(stat, df[var_name].to_numpy())

    fig = plotly.graph_objects.Figure()

    for var_n, var_details in accums.items():
        fig.add_trace(
            {
                "name": var_n,
                "x": df["dive"],
                "y": var_details.accum,
                "yaxis": pmar_stats[var_details.stat_name].yaxis,
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": pmar_stats[var_details.stat_name].color,
                    "width": 1,
                },
                # pmar_stats[var_details.stat].hover_template
                "hovertemplate": "Dive %{x}<br>" + f"{var_n}" + "<br>%{y:.0f} "
                f"{pmar_stats[var_details.stat_name].htext}" + "<extra></extra>",
            }
        )
    fig.update_layout(
        {
            "xaxis": {
                "title": "Dive Number",
                "showgrid": True,
                # "domain": [0.25, 0.8],
                "domain": [0.20, 0.90],
            },
            "yaxis": {
                "title": "bufferfull/writeerrors",
                "showgrid": True,
                # "tickformat": ".0f",
            },
            "yaxis2": {
                "title": "num blocks",
                "overlaying": "y",
                "side": "left",
                "showgrid": False,
                # "tickformat": ".0f",
                "position": 0.10,
            },
            "yaxis3": {
                "title": "clip count/despike count",
                # "autorange": "reversed",
                "overlaying": "y",
                "anchor": "x",
                "side": "right",
                # "position": 1.05,
                "showgrid": False,
            },
            "yaxis4": {
                "title": "num files",
                "overlaying": "y",
                "anchor": "free",
                "side": "right",
                # "position": 0.85,
                "position": 1.0,
                "showgrid": False,
            },
            "title": {
                "text": f"{mission_str}<br>PMAR Stats",
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.85,
            },
            "legend": {
                "x": 1.05,
                "y": 1,
            },
            "margin": {
                "t": 200,
                "b": 120,
            },
            # "annotations": tuple(l_annotations),
        },
    )
    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_pmar_stats",
            fig,
        ),
    )
