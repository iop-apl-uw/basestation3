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
import sqlite3
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

# TODO - Tune up colors
# TODO - test with RevB board

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
    "SciCon": line_type("solid", "DarkMagenta"),
}

# Based on fuel gauge from combined packs over previous 10 dives:
# dives remaining   : 534 (176.4 days at current dive duration)
# projected end date: 02-Jun-2023 04:13:42 (to 15% capacity)
# def estimate_endurace(conn: sqlite3.Connection) -> str:

#     batt_df = pd.read_sql_query(
#         "SELECT dive,batt_kJ_used_10V,batt_kJ_used_24V,time_seconds_diving from dives"
#     )

# if len(batt_df) >= dives_back:
#    batt_df["batt_kJ_used_10V"] + batt_df["batt_kJ_used_24V"],
#    m, b = np.polyfit(, freegb_var, 1)
#    log_debug("Fit for %s: m = %f, b = %f" % (tag, m, b))
#    last_dive = -b / m


# pylint: disable=unused-argument
@plotmissionsingle
def mission_energy(
    base_opts: BaseOpts.BaseOptions, mission_str: list
) -> tuple[list, list]:
    """Plots mission energy consumption and projections"""
    log_info("Starting mission_energy")

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    try:
        # capacity 10V and 24V are normalized battery availability

        fg_df = pd.read_sql_query(
            "SELECT dive,fg_kJ_used_10V,fg_kJ_used_24V from dives",
            conn,
        ).sort_values("dive")

        batt_df = pd.read_sql_query(
            "SELECT dive,batt_capacity_10V,batt_capacity_24V,batt_Ahr_cap_10V,batt_Ahr_cap_24V,batt_ah_10V,batt_ah_24V,batt_volts_10V,batt_volts_24V,batt_kj_used_10V,batt_kj_used_24V from dives",
            conn,
        ).sort_values("dive")

        if (
            batt_df["batt_Ahr_cap_24V"].iloc()[-1] == 0
            or batt_df["batt_Ahr_cap_10V"].iloc()[-1] == 0
        ):
            f_univolt = True
        else:
            f_univolt = False

        # estimate_endurace(conn)

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

        for energy_joules_df, energy_tag in (
            (device_joules_df, "device_"),
            (sensor_joules_df, "sensor_"),
        ):
            for energy_col in energy_joules_df.columns.to_list():
                if energy_col.startswith(energy_tag):
                    energy_name = energy_col.removeprefix(energy_tag).removesuffix(
                        "_joules"
                    )
                    if len(np.nonzero(energy_joules_df[energy_col].to_numpy())[0]) == 0:
                        continue
                    fig.add_trace(
                        {
                            "name": energy_name,
                            "x": energy_joules_df["dive"],
                            "y": energy_joules_df[energy_col] / 1000.0,
                            "yaxis": "y1",
                            "mode": "lines",
                            "line": {
                                "dash": line_lookup[energy_name].dash,
                                "color": line_lookup[energy_name].color,
                                "width": 1,
                            },
                            "hovertemplate": energy_name
                            + "<br>Dive %{x:.0f}<br> Energy used %{y:.2f} kJ<extra></extra>",
                        }
                    )

        if f_univolt:
            fig.add_trace(
                {
                    "name": "Fuel Gauge",
                    "x": fg_df["dive"],
                    "y": fg_df["fg_kJ_used_24V"] + fg_df["fg_kJ_used_10V"],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {"width": 1, "color": "DarkBlue"},
                    "hovertemplate": "Fuel Gauge<br>Dive %{x:.0f}<br> Energy used %{y:.2f} kJ<extra></extra>",
                }
            )
            fig.add_trace(
                {
                    "name": "Modeled Use",
                    "x": batt_df["dive"],
                    "y": batt_df["batt_kJ_used_10V"] + batt_df["batt_kJ_used_24V"],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {"width": 1, "color": "DarkGrey"},
                    "hovertemplate": "Modeled Use<br>Dive %{x:.0f}<br>Energy used %{y:.2f} kJ<extra></extra>",
                }
            )
        else:
            fig.add_trace(
                {
                    "name": "10V Fuel Gauge",
                    "x": fg_df["dive"],
                    "y": fg_df["fg_10V_kJ_used"],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {"width": 1, "color": "LightBlue"},
                    "hovertemplate": "Fuel Gauge 10V<br>Dive %{x:.0f}<br>Energy used %{y:.2f} kJ<extra></extra>",
                }
            )
            fig.add_trace(
                {
                    "name": "24V Fuel Gauge",
                    "x": fg_df["dive"],
                    "y": fg_df["fg_24V_used"],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {"width": 1, "color": "DarkBlue"},
                    "hovertemplate": "Fuel Gauge 24V<br>Dive %{x:.0f}<br>Energy used %{y:.2f} kJ<extra></extra>",
                }
            )
            fig.add_trace(
                {
                    "name": "10V Modeled Use",
                    "x": batt_df["dive"],
                    "y": batt_df["batt_kJ_used_10V"],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {"width": 1, "color": "LightGrey"},
                    "hovertemplate": "Modeled Use 10V<br>Dive %{x:.0f}<br>Energy used %{y:.2f} kJ<extra></extra>",
                }
            )
            fig.add_trace(
                {
                    "name": "Modeled Use 24V",
                    "x": batt_df["dive"],
                    "y": batt_df["batt_kj_used_24V"],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {"width": 1, "color": "DarkGrey"},
                    "hovertemplate": "Modeled Use 24V<br>Dive %{x:.0f}<br>Energy Used %{y:.2f} kJ<extra></extra>",
                }
            )

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
