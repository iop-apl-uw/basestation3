#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023  University of Washington.
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

# fmt: off
""" Plots mission energy consumption and projections
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import pdb
import sys
import sqlite3
import pandas
import time
import traceback
import typing

import plotly
import BaseDB
from datetime import datetime

import numpy as np
import pandas as pd

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils

from BaseLog import log_info, log_error
from Plotting import plotmissionsingle


# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False

# TODO - Tune up colors
# TODO - test with RevB board
# TODO - fix for split voltage

line_type = collections.namedtuple("line_type", ("dash", "color"))

line_lookup = {
    "VBD_pump": line_type("solid", "magenta"),
    "Pitch_motor": line_type("solid", "green"),
    "Roll_motor": line_type("solid", "red"),
    "Iridium": line_type("solid", "black"),
    "Transponder_ping": line_type("solid", "orange"),
    "GPS": line_type("dash", "green"),
    "Compass": line_type("dash", "magenta"),
    "RAFOS": line_type("solid", "goldenrod"),
    "Transponder": line_type("solid", "maroon"),
    "Compass2": line_type("dash", "turquoise"),
    "network": line_type("dash", "purple"),
    "STM32Mainboard": line_type("dash", "black"),
    "SciCon": line_type("solid", "DarkMagenta"),
    "SBE_CT": line_type("dash", "yellow"),
    "TMICL": line_type("dash", "LightGreen"),
}


@plotmissionsingle
def mission_energy(
        base_opts: BaseOpts.BaseOptions, mission_str: list, dive=None, generate_plots=True, dbcon=None
) -> tuple[list, list]:
    """Plots mission energy consumption and projections"""
    log_info(f"Starting mission_energy {dive}")

    if dbcon == None:
        conn = Utils.open_mission_database(base_opts)
        log_info("mission_energy db opened")
    else:
        conn = dbcon

    if not conn:
        log_error("Could not open mission database")
        return ([], [])
    #l_annotations = []

    if dive is None:
        clause = ''
    else:
        clause = f"WHERE dive <= {dive}"

    #res = conn.cursor().execute('PRAGMA table_info(dives)')
    #unused columns = [i[1] for i in res]

    try:
        # capacity 10V and 24V are normalized battery availability
        fg_df = pd.read_sql_query(
            f"SELECT dive,fg_kJ_used_10V,fg_kJ_used_24V,fg_batt_capacity_10V,fg_batt_capacity_24V,fg_ah_used_10V,fg_ah_used_24V,log_FG_AHR_10Vo,log_FG_AHR_24Vo FROM dives {clause} ORDER BY dive ASC", 
            conn,
        ).sort_values("dive")
    except pandas.errors.DatabaseError as exc:
        if "no such column:" in repr(exc):
            missing_col = repr(exc).split("no such column:")[1].split('"')[0]
            log_error(f"Could not fetch {missing_col} - skipping mission_energy plot")
        else:
            log_error("Failed database call", "exc")
        if dbcon == None:
            try:
                conn.commit()
            except Exception as e:
                conn.rollback()
                log_error(f"Failed commit, MissionEnergy {e}", "exc")

            log_info("mission_energy db closed")
            conn.close()

        return ([], [])

    try:
        batt_df = pd.read_sql_query(
            f"SELECT dive,batt_capacity_10V,batt_capacity_24V,batt_Ahr_cap_10V,batt_Ahr_cap_24V,batt_ah_10V,batt_ah_24V,batt_volts_10V,batt_volts_24V,batt_kJ_used_10V,batt_kJ_used_24V,time_seconds_on_surface,time_seconds_diving,log_gps_time AS dive_end FROM dives {clause} ORDER BY dive ASC", 
            conn,
        ).sort_values("dive")

        start = pd.read_sql_query(
            "SELECT dive,log_gps2_time FROM dives ORDER BY dive ASC LIMIT 1",
            conn,
        )["log_gps2_time"].iloc()[0]

        start_t = pd.read_sql_query(
            "SELECT dive,log_gps2_time FROM dives ORDER BY dive",
            conn,
        )["log_gps2_time"]

        batt_df["batt_Ahr_cap_24V"].iloc()[-1]
        if batt_df["batt_Ahr_cap_24V"].iloc()[-1] is None or batt_df["batt_Ahr_cap_24V"].iloc()[-1] == 0:
            univolt = "10V"
        elif batt_df["batt_Ahr_cap_10V"].iloc()[-1] == 0:
            univolt = "24V"
        else:
            univolt = None

        batt_df["dive_time"] = (
            batt_df["time_seconds_on_surface"] + batt_df["time_seconds_diving"]
        )

        scenario_t = collections.namedtuple(
            "scenario_type",
            ["type_str", "dive_col", "cap_col", "dive_time", "dive_end"],
        )

        scenarios = []
        if univolt:
            scenarios.append(
                scenario_t(
                    "Modeled",
                    batt_df["dive"],
                    batt_df[f"batt_capacity_{univolt}"],
                    batt_df["dive_time"],
                    batt_df["dive_end"],
                )
            )
        else:
            scenarios.append(
                scenario_t(
                    "Modeled_10V",
                    batt_df["dive"],
                    batt_df["batt_capacity_10V"],
                    batt_df["dive_time"],
                    batt_df["dive_end"],
                )
            )
            scenarios.append(
                scenario_t(
                    "Modeled_24V",
                    batt_df["dive"],
                    batt_df["batt_capacity_24V"],
                    batt_df["dive_time"],
                    batt_df["dive_end"],
                )
            )

            # TODO - comment below
            #
            # scenarios.append(
            #     scenario_t(
            #         "Fuel_Gauge",
            #         batt_df["dive"],
            #         fg_df[f"fg_batt_capacity_{univolt}"],
            #         batt_df["dive_time"],
            #     )
            # )

        #y_offset = -0.08
        for type_str, dive_col, cap_col, dive_time, dive_end in scenarios:
            dives_remaining, days_remaining, end_date = Utils.estimate_endurance(
                base_opts,
                dive_col.to_numpy(),
                cap_col.to_numpy(),
                dive_time.to_numpy(),
                dive_end.to_numpy(),
            )

            p_dives_back = (
                base_opts.mission_energy_dives_back
                if dive_col.to_numpy()[-1] >= base_opts.mission_energy_dives_back
                else dive_col.to_numpy()[-1]
            )

            batt_est_str = f"Based on {type_str} for the last {p_dives_back} dives: {dives_remaining} dives remaining ({days_remaining:.01f} days at curr rate) to {100*base_opts.mission_energy_reserve_percent:.0f}% reserve. Estimated end date {end_date} "
            # y_offset += -0.02
            # l_annotations.append(
            #     {
            #         "text": batt_est_str,
            #         "showarrow": False,
            #         "xref": "paper",
            #         "yref": "paper",
            #         "x": 0.0,
            #         "y": y_offset,
            #     }
            # )
            
            end_t = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%SZ").timestamp()
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              f"energy_dives_remain_{type_str}", 
                              float(dives_remaining), conn)
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              f"energy_dives_total_{type_str}", 
                              float(dives_remaining + dive_col.to_numpy()[-1]), conn)
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              f"energy_days_remain_{type_str}", 
                              days_remaining, conn);
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              f"energy_days_total_{type_str}", 
                              (end_t - start)/86400, conn);
            BaseDB.addValToDB(base_opts, 
                              int(batt_df["dive"].to_numpy()[-1]), 
                              f"energy_end_time_{type_str}", 
                              end_t, conn)
            BaseDB.addValToDB(base_opts, 
                              int(batt_df["dive"].to_numpy()[-1]), 
                              f"energy_dives_back_{type_str}", 
                              float(p_dives_back), conn);

        p_dives_back = (
            base_opts.mission_energy_dives_back
            if fg_df["dive"].to_numpy()[-1] >= base_opts.mission_energy_dives_back
            else fg_df["dive"].to_numpy()[-1]
        )
        days_df_modeled = pd.read_sql_query(
            f"SELECT dive,energy_days_total_Modeled FROM dives {clause} ORDER BY dive ASC", 
            conn,
        ).sort_values("dive")


        # TODO Using the polyfit on the normalized battery capacity for the fuel guage yields
        # roughly 10% less dives then next calc (taken directly from the current matlab code)
        used_to_date = (
            (fg_df["log_FG_AHR_24Vo"].to_numpy()[-1] if fg_df["log_FG_AHR_24Vo"].to_numpy()[-1] is not None else 0)
            + fg_df["log_FG_AHR_10Vo"].to_numpy()[-1]
        )
        days_df_fg = None
        fg_est_str = ""

        if used_to_date > 0.0:
            if fg_df["fg_ah_used_24V"].to_numpy()[-1] is not None:
                avg_use = (
                    np.sum(fg_df["fg_ah_used_24V"].to_numpy()[-p_dives_back:])
                    + np.sum(fg_df["fg_ah_used_10V"].to_numpy()[-p_dives_back:])
                ) / float(p_dives_back)
            else:
                avg_use = (
                    np.sum(fg_df["fg_ah_used_10V"].to_numpy()[-p_dives_back:])
                ) / float(p_dives_back)

            log_info(f"avg_use:{avg_use}")

            p_dives_back = (
                base_opts.mission_energy_dives_back
                if batt_df["dive"].to_numpy()[-1] >= base_opts.mission_energy_dives_back
                else batt_df["dive"].to_numpy()[-1]
            )

            batt_cap = max(
                batt_df["batt_Ahr_cap_24V"].to_numpy()[-1] if batt_df["batt_Ahr_cap_24V"].to_numpy()[-1] is not None else 0,
                batt_df["batt_Ahr_cap_10V"].to_numpy()[-1],
            )
            dives_remaining = (
                batt_cap * (1.0 - base_opts.mission_energy_reserve_percent) - used_to_date
            ) / avg_use
            secs_remaining = dives_remaining * np.mean(
                batt_df["dive_time"].to_numpy()[-p_dives_back:]
            )
            end_date = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(batt_df["dive_end"].to_numpy()[-1] + secs_remaining),
            )
            days_remaining = secs_remaining / (24.0 * 3600.0)
            log_info(
                f"Used to date:{used_to_date:.2f} avg_use:{avg_use:.2f} batt_cap:{batt_cap:.2f} dives_remaining:{dives_remaining:.0f}, days_remaining:{days_remaining:.2f}"
            )
            fg_est_str = f"Based on Fuel Gauge for the last {p_dives_back} dives: {dives_remaining:.0f} dives remaining ({days_remaining:.01f} days at current rate) to {100*base_opts.mission_energy_reserve_percent:.0f}% reserve. Estimated end date {end_date} "
            # y_offset += -0.02
            # l_annotations.append(
            #     {
            #         "text": fg_est_str,
            #         "showarrow": False,
            #         "xref": "paper",
            #         "yref": "paper",
            #         "x": 0.0,
            #         "y": y_offset,
            #     }
            # )

            end_t = datetime.strptime(end_date, "%Y-%m-%dT%H:%M:%SZ").timestamp()
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              "energy_dives_remain_FG", 
                              dives_remaining, conn)
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              "energy_dives_total_FG", 
                              dives_remaining + int(dive_col.to_numpy()[-1]), conn)
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              "energy_days_remain_FG", 
                              days_remaining, conn);
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              "energy_end_time_FG", 
                              end_t, conn)
            BaseDB.addValToDB(base_opts, 
                              int(dive_col.to_numpy()[-1]), 
                              "energy_days_total_FG", 
                              (end_t - start)/86400,conn)

            days_df_fg = pd.read_sql_query(
                f"SELECT dive,energy_days_total_FG FROM dives {clause} ORDER BY dive ASC", 
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

        if dbcon == None:
            try:
                conn.commit()
            except Exception as e:
                conn.rollback()
                log_error(f"Failed commit, MissionEnergy {e}", "exc")

            log_info("mission_energy db closed")
            conn.close()

        if not generate_plots:
            return ([], [])

        fig = plotly.graph_objects.Figure()

        if np.std(batt_df["batt_volts_10V"]):
            fig.add_trace(
                {
                    "name": "Min Volts Observed - LV Pack",
                    "x": batt_df["dive"],
                    "y": batt_df["batt_volts_10V"],
                    "yaxis": "y2",
                    "mode": "lines",
                    "line": {"dash": "dash", "width": 1, "color": "Cyan"},
                    "hovertemplate": "Min LV Volts<br>Dive %{x:.0f}<br>%{y:.2f} volts<extra></extra>",
                }
            )
        if np.std(batt_df["batt_volts_24V"]):
            fig.add_trace(
                {
                    "name": "Min Volts Observed - HV Pack",
                    "x": batt_df["dive"],
                    "y": batt_df["batt_volts_24V"],
                    "yaxis": "y2",
                    "mode": "lines",
                    "line": {"dash": "dash", "width": 1, "color": "DarkCyan"},
                    "hovertemplate": "Min HV Volts<br>Dive %{x:.0f}<br>%{y:.2f} volts<extra></extra>",
                }
            )

        for energy_joules_df, energy_tag in (
            (device_joules_df, "device_"),
            (sensor_joules_df, "sensor_"),
        ):
            for energy_col in energy_joules_df.columns.to_list():
                if energy_col.startswith(energy_tag):
                    energy_name = energy_col.removeprefix(energy_tag).removesuffix(
                        "_joules"
                    )
                    # A little convoluted, but if a db column is uninitialized, the database NULL gets
                    # converted to a nan, which is treated as non-zero
                    tmp_j = energy_joules_df[energy_col].to_numpy()
                    if np.count_nonzero(tmp_j[~np.isnan(tmp_j)]) == 0:
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
                            } if energy_name in line_lookup else {
                                "dash": "dot",
                                "color": "LightGray",
                                "width": 1,
                            },
                            "hovertemplate": energy_name
                            + "<br>Dive %{x:.0f}<br> Energy used %{y:.2f} kJ<extra></extra>",
                        }
                    )


        if days_df_fg is not None:
            fig.add_trace(
                {
                    "name": "Mission days (FG)",
                    "x": days_df_fg["dive"],
                    "y": days_df_fg["energy_days_total_FG"],
                    "customdata": np.squeeze(
                        np.dstack(
                            (days_df_fg["energy_days_total_FG"], (start_t - start) / 86400)
                        )
                    ),
                    "yaxis": "y3",
                    "mode": "lines",
                    "line": {"dash": "dot", "width": 1, "color": "DarkBlue"},
                    "hovertemplate": "Mission Days (FG)<br>Dive %{x:.0f}<br>Mission days %{customdata[0]:.1f}<br>Mission day %{customdata[1]:.1f}<extra></extra>",
                }
            )
        fig.add_trace(
            {
                "name": "Mission days (model)",
                "x": days_df_modeled["dive"],
                "y": days_df_modeled["energy_days_total_Modeled"],
                "customdata": np.squeeze(
                    np.dstack(
                        (days_df_modeled["energy_days_total_Modeled"], (start_t - start) / 86400)
                    )
                ),
                "yaxis": "y3",
                "mode": "lines",
                "line": {"dash": "dot", "width": 1, "color": "DarkGrey"},
                "hovertemplate": "Mission days (model)<br>Dive %{x:.0f}<br>Mission days %{customdata[0]:.1f}<br>Mission day %{customdata[1]:.1f}<extra></extra>",
            }
        )        
        if univolt:
            fig.add_trace(
                {
                    "name": "Fuel Gauge",
                    "x": fg_df["dive"],
                    "y": (fg_df["fg_kJ_used_24V"] if fg_df["fg_kJ_used_24V"] is not None else 0) + fg_df["fg_kJ_used_10V"],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {"width": 1, "color": "DarkBlue"},
                    "hovertemplate": "Fuel Gauge<br>Dive %{x:.0f}<br> Energy used %{y:.2f} kJ<extra></extra>",
                }
            )

            fig.add_trace(
                {
                    "name": "Modeled",
                    "x": batt_df["dive"],
                    "y": batt_df["batt_kJ_used_10V"] + (batt_df["batt_kJ_used_24V"] if batt_df["batt_kJ_used_24V"] is not None else 0),
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
                    "y": fg_df["fg_kJ_used_10V"],
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {"width": 1, "color": "LightBlue"},
                    "hovertemplate": "Fuel Gauge 10V<br>Dive %{x:.0f}<br>Energy used %{y:.2f} kJ<extra></extra>",
                }
            )
            if fg_df["fg_kJ_used_24V"][-1] is not None:
                fig.add_trace(
                    {
                        "name": "24V Fuel Gauge",
                        "x": fg_df["dive"],
                        "y": fg_df["fg_kJ_used_24V"],
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
            if batt_df["batt_kJ_used_24V"][-1] is not None:
                fig.add_trace(
                    {
                        "name": "Modeled Use 24V",
                        "x": batt_df["dive"],
                        "y": batt_df["batt_kJ_used_24V"],
                        "yaxis": "y1",
                        "mode": "lines",
                        "line": {"width": 1, "color": "DarkGrey"},
                        "hovertemplate": "Modeled Use 24V<br>Dive %{x:.0f}<br>Energy Used %{y:.2f} kJ<extra></extra>",
                    }
                )

        title_text = f"{mission_str}<br>Energy Consumption and Endurance"

        fig.update_layout(
            {
                "xaxis": {
                    #"title": "Dive Number",
                    "title": f"Dive Number<br>{batt_est_str}<br>{fg_est_str}",
                    "showgrid": True,
                    # "side": "top"
                    "domain": [0.0, 0.925],
                },
                "yaxis": {
                    "title": "energy (kJ)",
                    "showgrid": True,
                    # Fixed ratio
                    # "scaleanchor": "x",
                    # "scaleratio": (plot_lon_max - plot_lon_min)
                    # / (plot_lat_max - plot_lat_min),
                    # Fixed ratio
                },
                "yaxis2": {
                    "title": "volts",
                    "showgrid": False,
                    "overlaying": "y1",
                    "side": "right",
                    "position": 0.925,
                },
                "yaxis3": {
                    "title": "Mission Days",
                    "overlaying": "y1",
                    "anchor": "free",
                    "side": "right",
                    "position": 1,
                    "showgrid": False,
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
                    "b": 125 if univolt else 175,
                    #"b": 250,
                },
                "legend": {
                    "x": 1.075,
                    "y": 1,
                }
                #"annotations": tuple(l_annotations),
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
        log_error("Could not fetch needed columns", "exc")
        if dbcon == None:
            try:
                conn.commit()
            except Exception as e:
                conn.rollback()
                log_error(f"Failed commit, MissionEnergy {e}", "exc")
            conn.close()
            log_info("mission_energy db closed")

        return ([], [])
# fmt: on
