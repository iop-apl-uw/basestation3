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

"""Plots motor GC data over whole mission"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import pdb
import sys
import time
import traceback
import typing

import plotly
import plotly.subplots

import numpy as np
import pandas as pd

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import BaseOptsType
import PlotUtilsPlotly
import Utils

from BaseLog import log_info, log_error
from Plotting import plotmissionsingle, add_arguments


# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False


@add_arguments(
    additional_arguments={
        "max_vbd_effic": BaseOptsType.options_t(
            1.0,
            ("Base", "BasePlot", "Reprocess"),
            ("--max_vbd_effic",),
            float,
            {
                "help": "Set the maximum VBD efficiency to plot",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
        "max_vbd_pump_rate": BaseOptsType.options_t(
            -20.0,
            ("Base", "BasePlot", "Reprocess"),
            ("--max_vbd_pump_rate",),
            float,
            {
                "help": "Set the maximum VBD pump rate in AD/sec (negative is pump)",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
    }
)
@plotmissionsingle
def mission_motors(
    base_opts: BaseOpts.BaseOptions,
    mission_str: list,
    dive=None,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots mission motor GC data"""

    if not generate_plots:
        return ([], [])

    log_info("Starting mission_motors")

    if dbcon == None:
        conn = Utils.open_mission_database(base_opts, ro=True)
        if not conn:
            log_error("Could not open mission database")
            return ([], [])
        log_info("mission_motors db opened (ro)")
    else:
        conn = dbcon

    file_list = []
    figs_list = []

    try:
        # capacity 10V and 24V are normalized battery availability

        df = pd.read_sql_query(
            "SELECT dive,roll_rate,roll_i,pitch_rate,pitch_i,vbd_rate,vbd_i,vbd_secs,depth,vbd_eff,pitch_volts,roll_volts,vbd_volts from gc",
            conn,
        ).sort_values("dive")
    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_error("Could not fetch needed columns", "exc")
        if dbcon == None:
            conn.close()
            log_info("mission_motors db closed")

        return ([], [])

    if dbcon == None:
        conn.close()
        log_info("mission_motors db closed")

    rdf = df[df["roll_rate"] != 0]
    pdf = df[df["pitch_rate"] != 0]
    vdf = df[df["vbd_rate"] != 0]

    fig = plotly.subplots.make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        {
            "x": rdf["dive"],
            "y": rdf["roll_i"],
            "name": "roll current",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "Cyan",
            },
            "hovertemplate": "Dive %{x:.0f}<br>Roll current %{y:.2f} A<br><extra></extra>",
        },
        secondary_y=False,
    )
    fig.add_trace(
        {
            "x": rdf["dive"],
            "y": rdf["roll_rate"],
            "name": "roll rate",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "Magenta",
            },
            "hovertemplate": "Dive %{x:.0f}<br>Roll rate %{y:.2f} AD/s<br><extra></extra>",
        },
        secondary_y=True,
    )
    fig.add_trace(
        {
            "x": pdf["dive"],
            "y": pdf["pitch_i"],
            "name": "pitch current",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "DarkBlue",
            },
            "hovertemplate": "Dive %{x:.0f}<br>Pitch current %{y:.2f} A<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": pdf["dive"],
            "y": pdf["pitch_rate"],
            "name": "pitch rate",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "Red",
            },
            "hovertemplate": "Dive %{x:.0f}<br>Pitch rate %{y:.2f} AD/s<br><extra></extra>",
        },
        secondary_y=True,
    )

    fig.update_layout(
        {
            "xaxis": {
                "title": "dive",
                "showgrid": True,
            },
            "yaxis": {
                "title": "current(A)",
                "showgrid": True,
            },
            "yaxis2": {
                "title": "rate(AD/s)",
                "showgrid": False,
            },
            "title": {
                "text": "pitch and roll motor diagnostics",
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "t": 100,
                "b": 25,
            },
        }
    )

    figs_list.append(fig)
    file_list.append(
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_pitch_roll_motors",
            fig,
        )
    )

    fig = plotly.subplots.make_subplots(specs=[[{"secondary_y": True}]])

    pumpdf = vdf[vdf["vbd_rate"] < 0]
    bleeddf = vdf[vdf["vbd_rate"] > 0]

    pumpdf_vbd_rate = pumpdf["vbd_rate"].to_numpy()
    pumpdf_vbd_rate[pumpdf_vbd_rate < base_opts.max_vbd_pump_rate] = np.nan

    fig.add_trace(
        {
            "x": pumpdf["dive"],
            "y": pumpdf["vbd_i"],
            "meta": pumpdf["depth"],
            "name": "Pump Current",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "Blue",
            },
            "hovertemplate": "Dive %{x:.0f}<br>Current %{y:.2f}A<br>Depth %{meta[0]:.2f} m<extra></extra>",
        },
        secondary_y=False,
    )
    fig.add_trace(
        {
            "x": pumpdf["dive"],
            "y": pumpdf_vbd_rate,
            "meta": pumpdf["depth"],
            "name": "Pump Rate",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "Red",
            },
            "hovertemplate": "Dive %{x:.0f}<br>Rate %{y:.2f} AD/s<br>Depth %{meta:.2f} m<extra></extra>",
        },
        secondary_y=True,
    )
    fig.add_trace(
        {
            "x": bleeddf["dive"],
            "y": bleeddf["vbd_rate"],
            "meta": pumpdf["depth"],
            "name": "Bleed Rate",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "Magenta",
            },
            "hovertemplate": "Dive %{x:.0f}<br>Rate %{y:.2f} AD/s<br>Depth %{meta:.2f} m<extra></extra>",
        },
        secondary_y=True,
    )

    fig.update_layout(
        {
            "xaxis": {
                "title": "Dive",
                "showgrid": True,
            },
            "yaxis": {
                "title": "Current (A)",
                "showgrid": True,
            },
            "yaxis2": {
                "title": "Rate (AD/s)",
                "showgrid": False,
            },
            "title": {
                "text": "Pump and Bleed Diagnostics",
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "t": 100,
                "b": 25,
            },
        }
    )

    figs_list.append(fig)
    file_list.append(
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_vbd_motors",
            fig,
        )
    )

    fig = plotly.graph_objects.Figure()

    pumpdf_vbd_eff = pumpdf["vbd_eff"].to_numpy()
    pumpdf_vbd_eff[pumpdf_vbd_eff > base_opts.max_vbd_effic] = np.nan

    fig.add_trace(
        {
            "x": pumpdf["dive"],
            "y": pumpdf_vbd_eff,
            "meta": np.stack((pumpdf["depth"], pumpdf["vbd_secs"]), axis=-1),
            "name": "VBD Efficiency",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "color": pumpdf["depth"],
                "colorbar": {
                    "title": "depth",
                    "len": 0.8,
                },
                "colorscale": "Jet",
            },
            "hovertemplate": "VBD Efficiency<br>Dive %{x:.0f}<br>%{y:.2f} Efficiency<br>Depth %{meta[0]:.2f} m<br>%{meta[1]:.1f} secs<extra></extra>",
        }
    )

    fig.update_layout(
        {
            "xaxis": {
                "title": "Dive",
                "showgrid": True,
            },
            "yaxis": {
                "title": "Efficiency",
                "showgrid": True,
            },
            "title": {
                "text": "VBD Efficiency",
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "t": 100,
                "b": 25,
            },
        }
    )

    figs_list.append(fig)
    file_list.append(
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_vbd_effic",
            fig,
        )
    )

    return (figs_list, file_list)
