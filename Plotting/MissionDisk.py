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

"""Plots disk stats"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing
import warnings

import pandas as pd
import plotly

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import numpy as np

import PlotUtilsPlotly
import Utils
from BaseLog import log_error, log_info
from Plotting import plotmissionsingle


@plotmissionsingle
def mission_disk(
    base_opts: BaseOpts.BaseOptions,
    mission_str: list,
    dive=None,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots disk stats"""

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

    qcols = list(
        filter(
            lambda x: x.startswith("SD_")
            or x.endswith("_FREEKB")
            or x.endswith("_FREE"),
            columns,
        )
    )

    if len(qcols) == 0:
        return ([], [])

    qstr = ",".join(qcols)

    fig = plotly.graph_objects.Figure()
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

    sd_free_est = ""
    sc_free_est = ""

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
                "hovertemplate": "Dive %{x}<br>SD free space %{y:,} kb<extra></extra>",
            }
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=np.RankWarning)
            m, b = np.polyfit(df["dive"].to_numpy(), df["SD_free"].to_numpy(), 1)

        sd_free_est = f"<br>based on SD free, {-b/m:.0f} dives until full"

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
                "hovertemplate": "Dive %{x}<br>SD file count %{y}<extra></extra>",
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
                "hovertemplate": "Dive %{x}<br>SD dir count %{y}<extra></extra>",
            }
        )

    for v in list(df.columns.values):
        if not v.endswith("FREEKB"):
            continue

        nm = v.replace("log_", "")
        sensor_tag = nm
        try:
            if "_" in nm:
                sensor_tag = nm.split("_")[0]
        except Exception:
            pass
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
                "hovertemplate": f"Dive %{{x}}<br>{sensor_tag} free space %{{y:,}} kb<extra></extra>",
            }
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=np.RankWarning)
            m, b = np.polyfit(df["dive"].to_numpy(), df[v].to_numpy(), 1)

        sc_free_est = f"<br>based on {nm}, {-b/m:.0f} dives until full"
        # y_offset += -0.02
        # l_annotations.append(
        #     {
        #         "text": sc_free_est,
        #         "showarrow": False,
        #         "xref": "paper",
        #         "yref": "paper",
        #         "x": 0.0,
        #         "y": y_offset,
        #     }
        # )

    fig.update_layout(
        {
            "xaxis": {
                # "title": "Dive Number",
                "title": f"Dive Number{sd_free_est}{sc_free_est}",
                "showgrid": True,
                "domain": [0, 0.95],
            },
            "yaxis": {
                "title": "free space (kB)",
                "showgrid": True,
                "tickformat": ",.0f",
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
            # "annotations": tuple(l_annotations),
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


pmar_free_color_map = (
    "red",
    "orange",
    "darkgoldenrod",
    "green",
    "blue",
    "indigo",
    "violet",
    # "black",
)


@plotmissionsingle
def mission_pmar_disk(
    base_opts: BaseOpts.BaseOptions,
    mission_str: list,
    dive=None,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots disk stats"""

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

    qcols = list(filter(lambda x: x.startswith("log_PM_FREEKB"), columns))

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

    fig = plotly.graph_objects.Figure()
    fields = [i for i in df if i.startswith("log_PM")]
    for field in fields:
        drive_id = int(field.split("_")[-1])
        fig.add_trace(
            {
                "name": f"PM {drive_id:02d} free kB",
                "x": df["dive"],
                "y": df[field],
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": pmar_free_color_map[drive_id],
                    "width": 1,
                },
                "hovertemplate": "Dive %{x}<br>PM "
                + f"{drive_id:02d}"
                + " free space %{y:,} kb<extra></extra>",
            }
        )
    pm_free_est = ""
    if len(fields) > 1:
        pm_tot = df[fields].sum(axis=1)
        fig.add_trace(
            {
                "name": "PM Total free kB",
                "x": df["dive"],
                "y": pm_tot,
                "yaxis": "y1",
                "mode": "lines",
                "line": {
                    "dash": "solid",
                    "color": "black",
                    "width": 1,
                },
                "hovertemplate": "Dive %{x}<br>PM Total free space %{y:,} kb<extra></extra>",
            }
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=np.RankWarning)
            if df["dive"].to_numpy().size > 20:
                dives_back = -20
            else:
                dives_back = 0
            m, b = np.polyfit(
                df["dive"].to_numpy()[dives_back:], pm_tot.to_numpy()[dives_back:], 1
            )

        pm_free_est = f"<br>based on PM Total free, {-b/m:.0f} dives until full"
        if dives_back:
            pm_free_est += f" (Based on last {np.abs(dives_back):d} dives)"
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=np.RankWarning)
            if df["dive"].to_numpy().size > 20:
                dives_back = -20
            else:
                dives_back = 0
            m, b = np.polyfit(
                df["dive"].to_numpy()[dives_back:],
                df[fields[0]].to_numpy()[dives_back:],
                1,
            )

        pm_free_est = f"<br>based on PM free, {-b/m:.0f} dives until full"
        if dives_back:
            pm_free_est += f" (Based on last {np.abs(dives_back):d} dives)"

    fig.update_layout(
        {
            "xaxis": {
                # "title": "Dive Number",
                "title": f"Dive Number{pm_free_est}",
                "showgrid": True,
                "domain": [0, 0.95],
            },
            "yaxis": {
                "title": "free space (kB)",
                "showgrid": True,
                "tickformat": ",.0f",
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
            # "annotations": tuple(l_annotations),
        },
    )
    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_mission_pmar_disk",
            fig,
        ),
    )
