#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2026  University of Washington.
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

"""Plots comm.log counter values"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import pathlib
import typing

import numpy as np
import pandas as pd
import plotly.graph_objects
import scipy

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils
from BaseLog import log_error, log_info, log_warning
from Plotting import plotmissionsingle


@plotmissionsingle
def mission_commlog(
    base_opts: BaseOpts.BaseOptions,
    mission_str: list,
    dive=None,
    generate_plots=True,
    dbcon=None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Plots disk stats"""

    if not generate_plots:
        return ([], [])

    if dbcon is None:
        conn = Utils.open_mission_database(base_opts, ro=True)
        if not conn:
            log_error("Could not open mission database")
            return ([], [])
        log_info("mission_commlog db opened (ro)")
    else:
        conn = dbcon

    res = conn.cursor().execute("PRAGMA table_info(calls)")
    columns = [i[1] for i in res]
    if not columns:
        log_warning("No calls table - skipping")
        return ([], [])

    fig = plotly.graph_objects.Figure()
    df = None

    try:
        df = pd.read_sql_query(
            "SELECT * FROM calls ORDER BY dive,cycle,call",
            conn,
        )
    except Exception:
        log_error(
            "Could not fetch needed columns - skipping eng_mission_commlog", "exc"
        )
        if dbcon is None:
            conn.close()
            log_info("mission_commlog db closed")

        return ([], [])

    callNum = np.arange(0, len(df["pitch"]))

    dive_nums = df["dive"]
    if len(dive_nums) == 0:
        log_error("No call data found in database - skipping eng_mission_commlog")
        return ([], [])

    # Interpolate over missing dive numbers - may not be needed
    dive_nums_i = list(
        filter(
            lambda i: dive_nums[i] is not None,
            range(len(dive_nums)),
        )
    )
    dive_f = scipy.interpolate.interp1d(
        np.array(dive_nums_i),
        np.array(dive_nums)[dive_nums_i],
        kind="nearest",
        bounds_error=False,
        fill_value=0,
    )

    for ii in callNum:
        if dive_nums[int(ii)] is None:
            dive_nums[int(ii)] = int(dive_f(int(ii)))

    # Select some points on the graph for the dive numbers
    divevals = []
    divetext = []
    if len(callNum) > 7:
        for ii in callNum[:: len(callNum) // 7]:
            divevals.append(ii)
            divetext.append(dive_nums[int(ii)])
    else:
        for ii in callNum:
            divevals.append(ii)
            divetext.append(dive_nums[int(ii)])

    if "pitch" in df.columns:
        fig.add_trace(
            {
                "name": "Pitch/-5 (deg)",
                "x": callNum,
                "y": df["pitch"] / -5,
                "customdata": np.squeeze(
                    np.dstack(
                        (
                            np.transpose(dive_nums),
                            df["pitch"],
                        )
                    )
                ),
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "red",
                    "width": 1,
                },
                "hovertemplate": "Pitch %{customdata[1]:.1f} deg<br>Dive Num %{customdata[0]}<br>Call Num %{x}<extra></extra>",
            }
        )

    if "depth" in df.columns:
        fig.add_trace(
            {
                "name": "Depth (m)",
                "x": callNum,
                "y": df["depth"],
                "customdata": dive_nums,
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "green",
                    "width": 1,
                },
                "hovertemplate": "Depth %{y:.2f} m<br>Dive Num %{customdata}<br>Call Num %{x}<extra></extra>",
            }
        )

    if "intP" in df.columns:
        fig.add_trace(
            {
                "name": "Internal Pressure (psia)",
                "x": callNum,
                "y": df["intP"],
                "customdata": dive_nums,
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "magenta",
                    "width": 1,
                },
                "hovertemplate": "Internal Pressure %{y:.2f} psia<br>Dive Num %{customdata}<br>Call Num %{x}<extra></extra>",
            }
        )

    if "RH" in df.columns:
        fig.add_trace(
            {
                "name": "Relative Humidity/10",
                "x": callNum,
                "y": df["RH"] / 10,
                "customdata": np.squeeze(
                    np.dstack(
                        (
                            np.transpose(dive_nums),
                            df["RH"],
                        )
                    )
                ),
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "yellow",
                    "width": 2,
                },
                "hovertemplate": "RH %{customdata[1]:.2f} deg<br>Dive Num %{customdata[0]}<br>Call Num %{x}<extra></extra>",
            }
        )

    if "temp" in df.columns:
        fig.add_trace(
            {
                "name": "Internal Temperature/2",
                "x": callNum,
                "y": df["temp"] / 2.0,
                "customdata": np.squeeze(
                    np.dstack(
                        (
                            np.transpose(dive_nums),
                            df["temp"],
                        )
                    )
                ),
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "olive",
                    "width": 2,
                },
                "hovertemplate": "IntTemp %{customdata[1]:.2f} C<br>Dive Num %{customdata[0]}<br>Call Num %{x}<extra></extra>",
            }
        )

    if "volts10" in df.columns:
        fig.add_trace(
            {
                "name": "Low Voltage Batt (V)",
                "x": callNum,
                "y": df["volts10"],
                "customdata": dive_nums,
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "blue",
                    "width": 1,
                },
                "hovertemplate": "Low Voltage Batt %{y:.2f} V<br>Dive Num %{customdata}<br>Call Num %{x}<extra></extra>",
            }
        )

    if "volts24" in df.columns:
        fig.add_trace(
            {
                "name": "High Voltage Batt (V)",
                "x": callNum,
                "y": df["volts24"],
                "customdata": dive_nums,
                "yaxis": "y2",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "cyan",
                    "width": 1,
                },
                "hovertemplate": "High Voltage Batt %{y:.2f} V<br>Dive Num %{customdata}<br>Call Num %{x}<extra></extra>",
            }
        )

    colors = ["red", "blue", "green"]
    for i, (a, tag) in enumerate(
        [("pitchAD", "Pitch AD"), ("rollAD", "Roll AD"), ("vbdAD", "VBD AD")]
    ):
        if a in df.columns:
            fig.add_trace(
                {
                    "name": f"{tag} position",
                    "x": callNum,
                    "y": df[a],
                    "customdata": dive_nums,
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {
                        "dash": "dash",
                        "color": colors[i],
                        "width": 1,
                    },
                    "hovertemplate": f"{tag} %{{y:d}}<br>Dive Num %{{customdata}}<br>Call Num %{{x}}<extra></extra>",
                }
            )

    ctd_col_type = collections.namedtuple(
        "ctd_col_type", ("name", "title", "units", "color", "scale")
    )
    ctd_cols = (
        ctd_col_type("density", "Seawater surface desnsity", "sigma-t", "gray", 0.25),
        ctd_col_type("sss", "Seawater surface salinity", "PSU", "DarkGreen", 0.25),
        ctd_col_type("sst", "Seawater surface temperature", "C", "orange", 0.5),
    )
    if all(ii.name in df.columns for ii in ctd_cols):
        good_pts = np.logical_and(
            df["sss"] != 0.0, [ii is not None for ii in df["sss"].to_numpy()]
        )
        if np.nonzero(good_pts)[0].size > 2:
            for ctd_col in ctd_cols:
                fig.add_trace(
                    {
                        "name": f"{ctd_col.title}/{1.0/ctd_col.scale:.0f} ({ctd_col.units})",
                        "x": callNum[good_pts],
                        "y": df[ctd_col.name][good_pts] * ctd_col.scale,
                        "customdata": np.squeeze(
                            np.dstack(
                                (
                                    np.transpose(dive_nums[good_pts]),
                                    df[ctd_col.name][good_pts],
                                )
                            )
                        ),
                        "yaxis": "y2",
                        "mode": "lines+markers",
                        "marker": {"symbol": "cross", "size": 3},
                        "line": {
                            "dash": "solid",
                            "color": ctd_col.color,
                            "width": 1,
                        },
                        "hovertemplate": f"{ctd_col.title} %{{customdata[1]:.2f}} {ctd_col.units}<br>Dive Num %{{customdata[0]}}<br>Call Num %{{x}}<extra></extra>",
                    }
                )

    fig.add_trace(
        {
            "name": "Hidden Trace for Dive Number",
            "x": callNum,
            "y": callNum,
            "xaxis": "x2",
            "yaxis": "y1",
            "mode": "markers",
            "visible": False,
        }
    )

    fig.update_layout(
        {
            "xaxis": {
                "title": "Call number",
                "showgrid": True,
                "domain": [0.0, 0.925],
                # "domain": [0.075, 1.0],
            },
            "xaxis2": {
                "title": "Dive Number",
                "showgrid": False,
                "overlaying": "x1",
                "side": "top",
                "range": [min(callNum), max(callNum)],
                "tickmode": "array",
                "tickvals": divevals,
                "ticktext": divetext,
                # "position": 0.0,
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
                "t": 150,
                "b": 125,
            },
            "legend": {
                "x": 1.075,
                "y": 1,
            },
        },
    )
    if dbcon is None:
        log_info("mission_commlog db closed")
        conn.close()

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_commlog",
            fig,
        ),
    )
