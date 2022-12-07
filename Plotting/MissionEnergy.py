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

""" Plots mission energy consumption and projections
"""
import collections
import pdb
import sys
import traceback

import plotly

import numpy as np
import pandas as pd


import BaseOpts
import PlotUtilsPlotly
import Utils

from BaseLog import log_info, log_error
from Plotting import plotmissionsingle


DEBUG_PDB = "darwin" in sys.platform

line_type = collections.namedtuple("line_type", ("dash", "color"))

line_lookup = {
    "VBD_pump": line_type("solid", "magenta"),
    "Pitch_motor": line_type("solid", "green"),
    "Roll_motor": line_type("solid", "red"),
    "Iridium": line_type("solid", "black"),
    "Transponder_ping": line_type("solid", "orange"),
    "GPS": line_type("dash", "green"),
    "Compass": line_type("dash", "magenta"),
    # "RAFOS" :
    # "Transponder" :
    # "Compass2" :
    # "network" :
    "STM32Mainboard": line_type("dash", "black"),
}

# pylint: disable=unused-argument
@plotmissionsingle
def mission_energy(base_opts: BaseOpts.BaseOptions) -> tuple[list, list]:
    """Plots mission energy consumption and projections"""
    log_info("Starting mission_energy")

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    try:
        fg_df = pd.read_sql_query(
            "SELECT dive,fg_low_voltage_kJ_used,fg_high_voltage_kJ_used,capacity_10V,capacity_24V from dives",
            conn,
        ).sort_values("dive")

        # Find the device and sensor columnns for power consumption
        df = pd.read_sql_query("PRAGMA table_info(dives)", conn)

        device_joule_cols = df[
            np.logical_and(
                df["name"].str.endswith("_joules"), df["name"].str.startswith("device_")
            )
        ]["name"].to_list()

        device_joules_df = pd.read_sql_query(
            f"SELECT dive,{','.join(device_joule_cols)} from dives", conn
        ).sort_values("dive")

        # RevE
        if "device_Fast_joules" in device_joule_cols:
            device_joules_df["device_STM32Mainboard_joules"] = (
                device_joules_df["device_Core_joules"]
                + device_joules_df["device_Fast_joules"]
                + device_joules_df["device_Slow_joules"]
                + device_joules_df["device_LPSleep_joules"]
            )
            device_joules_df.drop(
                columns=[
                    "device_Core_joules",
                    "device_Fast_joules",
                    "device_Slow_joules",
                    "device_LPSleep_joules",
                ],
                inplace=True,
            )

        sensor_joule_cols = df[
            np.logical_and(
                df["name"].str.endswith("_joules"), df["name"].str.startswith("sensor_")
            )
        ]["name"].to_list()

        sensor_joules_df = pd.read_sql_query(
            f"SELECT dive,{','.join(sensor_joule_cols)} from dives", conn
        ).sort_values("dive")

        fig = plotly.graph_objects.Figure()

        for device_col in device_joules_df.columns.to_list():
            if device_col.startswith("device_"):
                device_name = device_col.removeprefix("device_").removesuffix("_joules")
                # If there is no data at all - don't plot
                if len(np.nonzero(device_joules_df[device_col].to_numpy())[0]) == 0:
                    continue
                fig.add_trace(
                    {
                        "name": device_name,
                        "x": device_joules_df["dive"],
                        "y": device_joules_df[device_col] / 1000.0,
                        "yaxis": "y1",
                        # "mode": "lines+markers",
                        "mode": "lines",
                        # "line": {"dash": "dash", "color": "Blue"},
                        "line": {
                            "dash": line_lookup[device_name].dash,
                            "color": line_lookup[device_name].color,
                            "width": 1,
                        },
                        # "marker": {"symbol": "cross", "size": 3, "color": "LightBlue"},
                        # "hovertemplate": "Raw Salin<br>%{x:.2f} min<br>%{y:.2f} PSU<extra></extra>",
                    }
                )

        fig.add_trace(
            {
                "name": "10V Fuel Gauge",
                "x": fg_df["dive"],
                "y": fg_df["fg_low_voltage_kJ_used"],
                "yaxis": "y1",
                "mode": "lines+markers",
                "line": {"width": 1},
                "marker": {"symbol": "cross", "size": 3, "color": "LightBlue"},
                # "hovertemplate": "Raw Salin<br>%{x:.2f} min<br>%{y:.2f} PSU<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "name": "24V Fuel Gauge",
                "x": fg_df["dive"],
                "y": fg_df["fg_high_voltage_kJ_used"],
                "yaxis": "y1",
                "mode": "lines+markers",
                "line": {"width": 1},
                "marker": {"symbol": "cross", "size": 3, "color": "DarkBlue"},
                # "hovertemplate": "Raw Salin<br>%{x:.2f} min<br>%{y:.2f} PSU<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "name": "Fuel Gauge Sum",
                "x": fg_df["dive"],
                "y": fg_df["fg_high_voltage_kJ_used"] + fg_df["fg_low_voltage_kJ_used"],
                "yaxis": "y1",
                "mode": "lines+markers",
                "line": {"width": 1},
                "marker": {"symbol": "cross", "size": 3, "color": "DarkBlue"},
                # "hovertemplate": "Raw Salin<br>%{x:.2f} min<br>%{y:.2f} PSU<extra></extra>",
            }
        )

        # TODO - add mission string creation for all plots and feed into routines
        mission_str = ""
        title_text = f"{mission_str}<br>Energy Consumption"

        fig.update_layout(
            {
                "xaxis": {
                    "title": "Dive Number",
                    "showgrid": True,
                    # "side": "top"
                },
                "yaxis": {
                    "title": "energy (kJ)",
                    "showgrid": True,
                },
                "title": {
                    "text": title_text,
                    "xanchor": "center",
                    "yanchor": "top",
                    "x": 0.5,
                    "y": 0.95,
                },
                "margin": {
                    "t": 100,
                    "b": 125,
                },
            },
        )
        return (
            [fig],
            PlotUtilsPlotly.write_output_files(
                base_opts,
                "eng_mission_energy",
                fig,
            ),
        )

    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_error("Could not fetch needed columns")
        return ([], [])

    return ([], [])
