#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025, 2026  University of Washington.
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

"""Plots sicence instrument data"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing

import numpy as np
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
import Utils
from BaseLog import log_debug, log_error, log_warning
from Plotting import plotdivesingle

# TODO - hard coded for new - needs to move to a yml file
instrument_meta = {}

instrument_meta["fet"] = {
    "layout": {"xaxis_title": "Volts", "xaxis2_title": "nano amps"},
    "vars": {
        "biasBatt": {
            "xaxis": "x1",
            "yaxis": "y1",
            "color_down": "LightGrey",
            "color_up": "DarkGrey",
            "units": "V",
            "hoverfmt": ".2f",
            "visible": "legendonly",
        },
        "Vrse": {
            "xaxis": "x1",
            "yaxis": "y1",
            "color_down": "Red",
            "color_up": "Magenta",
            "units": "V",
            "hoverfmt": ".4f",
        },
        "Vrsestd": {
            "xaxis": "x1",
            "yaxis": "y1",
            "color_down": "Cyan",
            "color_up": "DarkCyan",
            "units": "V",
            "hoverfmt": ".3g",
            "visible": "legendonly",
        },
        "Vk": {
            "xaxis": "x1",
            "yaxis": "y1",
            "color_down": "orange",
            "color_up": "darkgoldenrod",
            "units": "V",
            "hoverfmt": ".4f",
            "visible": "legendonly",
        },
        "Vkstd": {
            "xaxis": "x1",
            "yaxis": "y1",
            "color_down": "Green",
            "color_up": "DarkGreen",
            "units": "V",
            "hoverfmt": ".3g",
            "visible": "legendonly",
        },
        "Ik": {
            "xaxis": "x2",
            "yaxis": "y1",
            "color_down": "Blue",
            "color_up": "DarkBlue",
            "units": "uI",
            "hoverfmt": ".4f",
            "visible": "legendonly",
        },
        "Ib": {
            "xaxis": "x2",
            "yaxis": "y1",
            "color_down": "olive",
            "color_up": "darkolivegreen",
            "units": "uI",
            "hoverfmt": ".4f",
            "visible": "legendonly",
        },
    },
}


@plotdivesingle
def plot_science(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots calibrated output for science instruments"""

    if not generate_plots:
        return ([], [])

    ret_plots = []
    ret_figs = []

    varlist = "".join(filter(lambda x: "sg_cal" not in x, dive_nc_file.variables))

    for instrument_root, meta in instrument_meta.items():
        instruments = []
        for inst in ("", "1", "2", "3"):
            typ = f"{instrument_root}{inst}"
            if typ in varlist:
                if "%s_time" % typ in dive_nc_file.variables:
                    instruments.append((typ, True))
                elif typ in varlist:
                    instruments.append((typ, False))

        for instrument, is_scicon in instruments:
            var_vals = {}
            tag = "" if is_scicon else "eng_"
            for var_n in meta["vars"]:
                var_name = f"{tag}{instrument}_{var_n}"
                if var_name in dive_nc_file.variables:
                    var_vals[var_n] = dive_nc_file.variables[var_name][:]

            if not var_vals:
                continue

            try:
                start_time = dive_nc_file.start_time
            except Exception:
                start_time = None

            try:
                sg_depth = None
                try:
                    sg_depth = dive_nc_file.variables["depth"][:]
                except KeyError:
                    try:
                        sg_depth = dive_nc_file.variables["eng_depth"][:] / 100.0
                    except KeyError:
                        log_warning("No depth variable found")
                        continue
                sg_time = dive_nc_file.variables["time"][:]
                # Interpolate around missing depth observations
                sg_depth = PlotUtils.interp_missing_depth(sg_time, sg_depth)

                # Check for scicon based time
                if is_scicon:
                    instrument_time = dive_nc_file.variables[f"{instrument}_time"][:]

                    # Interp ctd_depth to determine WL depth
                    f = scipy.interpolate.interp1d(
                        sg_time,
                        sg_depth,
                        kind="linear",
                        bounds_error=False,
                        fill_value=0.0,
                    )
                    instrument_depth_m_v = f(instrument_time)
                else:
                    # Truck
                    instrument_depth_m_v = sg_depth
                    instrument_time = sg_time
            except Exception:
                log_error(f"Could not load {instrument} variable(s)", "exc")
                continue

            if not start_time:
                start_time = instrument_time[0]

            # Find the deepest sample
            max_depth_sample_index = np.argmax(instrument_depth_m_v)

            # Create dive and climb vectors
            depth_dive = instrument_depth_m_v[0:max_depth_sample_index]
            depth_climb = instrument_depth_m_v[max_depth_sample_index:]

            instrument_time_dive = (
                instrument_time[0:max_depth_sample_index] - start_time
            ) / 60.0
            instrument_time_climb = (
                instrument_time[max_depth_sample_index:] - start_time
            ) / 60.0

            # For samples and timeout plots
            sg_good_pts = np.logical_and(
                np.logical_not(np.isnan(sg_time)), np.logical_not(np.isnan(sg_depth))
            )
            f_depth = scipy.interpolate.PchipInterpolator(
                sg_time[sg_good_pts],
                sg_depth[sg_good_pts],
                extrapolate=True,
            )
            max_depth = np.nanmax(instrument_depth_m_v)

            fig = plotly.graph_objects.Figure()

            for var_n, var_val in var_vals.items():
                log_debug(f"Found {var_n} in fluor")

                var_dive = var_val[0:max_depth_sample_index]
                var_climb = var_val[max_depth_sample_index:]

                var_meta = meta["vars"][var_n]

                chan_name = var_n
                units = var_meta["units"]
                hover_fmt = var_meta["hoverfmt"]

                dive_dict = {
                    "y": depth_dive,
                    "x": var_dive,
                    "meta": instrument_time_dive,
                    "name": f"{chan_name} Dive",
                    "type": "scatter",
                    "xaxis": var_meta["xaxis"],
                    "yaxis": var_meta["yaxis"],
                    "mode": "markers",
                    "marker": {
                        "symbol": "triangle-down",
                        "color": var_meta["color_down"],
                    },
                    "hovertemplate": f"{chan_name}  Dive<br>%{{x:{hover_fmt}}} {units}<br>%{{y:.2f}} meters<br>%{{meta:.2f}} mins<extra></extra>",
                }

                if "visible" in var_meta:
                    dive_dict["visible"] = var_meta["visible"]

                fig.add_trace(dive_dict)

                climb_dict = {
                    "y": depth_climb,
                    "x": var_climb,
                    "meta": instrument_time_climb,
                    "name": f"{chan_name} Climb",
                    "type": "scatter",
                    "xaxis": var_meta["xaxis"],
                    "yaxis": var_meta["yaxis"],
                    "mode": "markers",
                    "marker": {
                        "symbol": "triangle-up",
                        "color": var_meta["color_up"],
                    },
                    "hovertemplate": f"{chan_name}  Climb<br>%{{x:{hover_fmt}}} {units}<br>%{{y:.2f}} meters<br>%{{meta:.2f}} mins<extra></extra>",
                }

                if "visible" in var_meta:
                    climb_dict["visible"] = var_meta["visible"]

                fig.add_trace(climb_dict)

            timeouts = None
            if max_depth_sample_index is not None:
                timeouts, timeouts_times = PlotUtils.collect_timeouts(
                    dive_nc_file,
                    instrument,
                )

                if timeouts:
                    PlotUtils.add_timeout_overlays(
                        timeouts,
                        timeouts_times,
                        fig,
                        f_depth,
                        instrument_time,
                        max_depth_sample_index,
                        max_depth,
                        start_time,
                        "Magenta",  # To match insturment dive trace
                        "Red",  # To match instrument climb trace
                    )

                PlotUtils.add_sample_range_overlay(
                    instrument_time,
                    max_depth_sample_index,
                    start_time,
                    fig,
                    f_depth,
                )

            mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
            title_text = f"{mission_dive_str}<br>{instrument} vs Depth"
            output_name = "dv%04d_%s_%s" % (
                dive_nc_file.dive_number,
                instrument,
                Utils.ensure_basename(instrument),
            )

            output_name.lower()

            update_dict = {
                "xaxis": {
                    "title": meta["layout"]["xaxis_title"],
                    "showgrid": True,
                    "side": "bottom",
                },
                "yaxis": {
                    "title": "Depth (m)",
                    "showgrid": True,
                    "autorange": "reversed",
                },
                "title": {
                    "text": title_text,
                    "xanchor": "center",
                    "yanchor": "top",
                    "x": 0.5,
                    "y": 0.95,
                },
                "margin": {
                    "t": 150,
                },
            }

            if "xaxis2_title" in meta["layout"]:
                update_dict["xaxis2"] = {
                    "title": meta["layout"]["xaxis2_title"],
                    "overlaying": "x1",
                    "side": "top",
                    "showgrid": False,
                }

            fig.update_layout(update_dict)

            if f"sg_cal_calibcomm_{instrument}" in dive_nc_file.variables:
                cal_text = (
                    dive_nc_file.variables[f"sg_cal_calibcomm_{instrument}"][:]
                    .tobytes()
                    .decode()
                )
                if timeouts:
                    cal_text += f" Timeouts:{timeouts:d}"

                fig.update_layout(
                    {
                        "annotations": tuple(
                            [
                                {
                                    "text": cal_text,
                                    "showarrow": False,
                                    "xref": "paper",
                                    "yref": "paper",
                                    "x": 0.0,
                                    "y": -0.08,
                                }
                            ]
                        )
                    }
                )

            ret_figs.append(fig)
            ret_plots.extend(
                PlotUtilsPlotly.write_output_files(
                    base_opts,
                    output_name,
                    fig,
                )
            )

    return (ret_figs, ret_plots)
