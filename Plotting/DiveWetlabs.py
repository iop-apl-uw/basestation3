#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025  University of Washington.
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

"""Plots wetlabs data"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
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


@plotdivesingle
def plot_wetlabs(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots raw or calibrated output for wetlabs pucks"""

    if not generate_plots:
        return ([], [])

    wetlabs_types = []
    varlist = "".join(filter(lambda x: "sg_cal" not in x, dive_nc_file.variables))
    for typ in ("wlbb2fl", "wlbbfl2", "wlbb3", "wlfl3"):
        if "%s_time" % typ in dive_nc_file.variables:
            wetlabs_types.append((typ, True))
        elif typ in varlist:
            wetlabs_types.append((typ, False))

    if not wetlabs_types:
        return ([], [])

    ret_plots = []
    ret_figs = []

    # WETlabs_ext supports saving the raw counts and providing adjusted values
    # In the plots below, we support either all adjusted or all raw data rather than a mix

    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = None

    binned_profile = "profile_data_point" in dive_nc_file.dimensions
    binned_tag = ""

    for wetlabs_type, is_scicon in wetlabs_types:
        try:
            sg_depth = None
            try:
                sg_depth = dive_nc_file.variables["depth"][:]
            except KeyError:
                try:
                    sg_depth = dive_nc_file.variables["eng_depth"][:] / 100.0
                except KeyError:
                    log_warning("No depth variable found")
            sg_time = dive_nc_file.variables["time"][:]
            # Interpolate around missing depth observations
            sg_depth = PlotUtils.interp_missing_depth(sg_time, sg_depth)

            if binned_profile:
                binned_tag = " - binned %.1f m" % (
                    np.round(np.average(np.diff(sg_depth[0, :])), decimals=1),
                )
            # Check for scicon based time
            if is_scicon:
                wl_time = dive_nc_file.variables[f"{wetlabs_type}_time"][:]

                # Interp ctd_depth to determine WL depth
                f = scipy.interpolate.interp1d(
                    sg_time, sg_depth, kind="linear", bounds_error=False, fill_value=0.0
                )
                wetlabs_depth_m_v = f(wl_time)
            else:
                # Truck
                wetlabs_depth_m_v = sg_depth
                wl_time = sg_time
        except Exception:
            log_error("Could not load wetlab variable(s)", "exc")
            return (ret_figs, ret_plots)

        if binned_profile:
            max_depth_sample_index = None
            if not start_time:
                start_time = wl_time[0, 0]

            depth_dive = wetlabs_depth_m_v[0, :]
            depth_climb = wetlabs_depth_m_v[1, :]

            wl_time_dive = (wl_time[0, :] - start_time) / 60.0
            wl_time_climb = (wl_time[1, :] - start_time) / 60.0
        else:
            if not start_time:
                start_time = wl_time[0]

            # Find the deepest sample
            max_depth_sample_index = np.argmax(wetlabs_depth_m_v)

            # Create dive and climb vectors
            depth_dive = wetlabs_depth_m_v[0:max_depth_sample_index]
            depth_climb = wetlabs_depth_m_v[max_depth_sample_index:]

            wl_time_dive = (wl_time[0:max_depth_sample_index] - start_time) / 60.0
            wl_time_climb = (wl_time[max_depth_sample_index:] - start_time) / 60.0

            # For samples and timeout plots
            f_depth = scipy.interpolate.PchipInterpolator(
                wl_time,
                wetlabs_depth_m_v,
                extrapolate=True,
            )
            max_depth = np.nanmax(wetlabs_depth_m_v)

        # Make this one plot for each channel

        # Find the fluoresence channels
        fc = collections.namedtuple("fluor_chan", ["name", "units"])
        fluor_chans = collections.OrderedDict(
            (
                ("sig460nm", fc("CDOM fluorescence", "1e-9")),
                ("sig530nm", fc("Uranine fluorescence", "1e-9")),
                ("sig570nm", fc("Phycoerythrin/Rhodamine fluorescence", "1e-9")),
                ("sig595nm", fc("Phycoerythrin fluorescence", "1e-9")),
                ("sig680nm", fc("Phycocyanin fluorescence", "1e-9")),
                ("sig695nm", fc("Chlorophyll fluorescence", "ug/l")),
            )
        )

        for ff in list(fluor_chans.keys()):
            for vv in ("%s_%s_adjusted", "%s_%s", "eng_%s_%s"):
                var_name = vv % (wetlabs_type, ff)
                if var_name in dive_nc_file.variables:
                    log_debug(f"Found {var_name} in fluor")
                    fluorcount = dive_nc_file.variables[var_name][:]

                    if binned_profile:
                        fluorcount_dive = fluorcount[0, :]
                        fluorcount_climb = fluorcount[1, :]
                    else:
                        fluorcount_dive = fluorcount[0:max_depth_sample_index]
                        fluorcount_climb = fluorcount[max_depth_sample_index:]

                    if "adjusted" in var_name:
                        chan_name = r"%s %s" % (
                            fluor_chans[ff].name,
                            fluor_chans[ff].units,
                        )
                        units = fluor_chans[ff].units
                    else:
                        chan_name = f"{fluor_chans[ff].name} counts"
                        units = "counts"

                    fig = plotly.graph_objects.Figure()

                    fig.add_trace(
                        {
                            "y": depth_dive,
                            "x": fluorcount_dive,
                            "meta": wl_time_dive,
                            "name": f"{chan_name} Dive",
                            "type": "scatter",
                            "xaxis": "x1",
                            "yaxis": "y1",
                            "mode": "markers",
                            "marker": {
                                "symbol": "triangle-down",
                                "color": "Magenta",
                            },
                            "hovertemplate": f"{chan_name}  Dive<br>"
                            + "%{x:.2f} "
                            + units
                            + "<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                        }
                    )
                    fig.add_trace(
                        {
                            "y": depth_climb,
                            "x": fluorcount_climb,
                            "meta": wl_time_climb,
                            "name": f"{chan_name} Climb",
                            "type": "scatter",
                            "xaxis": "x1",
                            "yaxis": "y1",
                            "mode": "markers",
                            "marker": {
                                "symbol": "triangle-up",
                                "color": "Red",
                            },
                            "hovertemplate": f"{chan_name}  Climb<br>"
                            + "%{x:.2f} "
                            + units
                            + "<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                        }
                    )

                    # Only for time series plots
                    timeouts = None
                    if max_depth_sample_index:
                        timeouts, timeouts_times = PlotUtils.collect_timeouts(
                            dive_nc_file,
                            wetlabs_type,
                        )

                        if timeouts:
                            PlotUtils.add_timeout_overlays(
                                timeouts,
                                timeouts_times,
                                fig,
                                f_depth,
                                wl_time,
                                max_depth_sample_index,
                                max_depth,
                                start_time,
                                "Magenta",  # To match insturment dive trace
                                "Red",  # To match instrument climb trace
                            )

                        PlotUtils.add_sample_range_overlay(
                            wl_time,
                            max_depth_sample_index,
                            start_time,
                            fig,
                            f_depth,
                        )

                    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
                    title_text = f"{mission_dive_str}<br>{fluor_chans[ff].name} vs Depth{binned_tag}"
                    output_name = "dv%04d_%s_%s" % (
                        dive_nc_file.dive_number,
                        wetlabs_type,
                        Utils.ensure_basename(fluor_chans[ff].name),
                    )

                    output_name.lower()

                    fig.update_layout(
                        {
                            "xaxis": {
                                "title": chan_name,
                                "showgrid": True,
                                "side": "top",
                                # "range": [min_salinity, max_salinity],
                            },
                            "yaxis": {
                                "title": "Depth (m)",
                                "showgrid": True,
                                "autorange": "reversed",
                                # "range": [
                                #     max(
                                #         depth_dive.max() if len(depth_dive) > 0 else 0,
                                #         depth_climb.max() if len(depth_climb) > 0 else 0,
                                #     ),
                                #     0,
                                # ],
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
                    )

                    if "sg_cal_calibcomm_wetlabs" in dive_nc_file.variables:
                        cal_text = (
                            dive_nc_file.variables["sg_cal_calibcomm_wetlabs"][:]
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
                    break

        # Plot backscatter vs depth
        # Find the backscatter channels
        bs = collections.namedtuple("bs_chan", ["name", "dive_color", "climb_color"])
        bs_chans = collections.OrderedDict(
            (
                ("sig470nm", bs("Blue scattering", "Blue", "DarkBlue")),
                ("sig532nm", bs("Green scattering", "GreenYellow", "DarkGreen")),
                ("sig700nm", bs("Red scattering", "Red", "DarkRed")),
                ("sig880nm", bs("Infrared scattering", "Yellow", "Gold")),
            )
        )

        adjusted = False
        fig = None
        last_dive_color = last_climb_color = None

        for bb in list(bs_chans.keys()):
            for vv in ("%s_%s_adjusted", "%s_%s", "eng_%s_%s"):
                var_name = vv % (wetlabs_type, bb)
                if var_name in dive_nc_file.variables:
                    if not fig:
                        fig = plotly.graph_objects.Figure()
                    log_debug(f"Found {var_name} in back scatter")
                    if "adjusted" in var_name:
                        adjusted = True
                    bscount = dive_nc_file.variables[var_name][:]

                    if binned_profile:
                        bscount_dive = bscount[0, :]
                        bscount_climb = bscount[1, :]
                    else:
                        bscount_dive = bscount[0:max_depth_sample_index]
                        bscount_climb = bscount[max_depth_sample_index:]

                    if adjusted:
                        units = "m 1e-1 sr 1e-1"
                        fmt = ".3g"
                    else:
                        units = "Counts"
                        fmt = ".1f"

                    last_dive_color = bs_chans[bb].dive_color
                    last_climb_color = bs_chans[bb].climb_color

                    fig.add_trace(
                        {
                            "y": depth_dive,
                            "x": bscount_dive,
                            "meta": wl_time_dive,
                            "name": f"{bb[3:]} Dive",
                            "type": "scatter",
                            "xaxis": "x1",
                            "yaxis": "y1",
                            "mode": "markers",
                            "marker": {
                                "symbol": "triangle-down",
                                "color": bs_chans[bb].dive_color,
                            },
                            "hovertemplate": f"{bb[3:]} Dive<br>"
                            + "%{x:"
                            + fmt
                            + "} "
                            + units
                            + "<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                        }
                    )
                    fig.add_trace(
                        {
                            "y": depth_climb,
                            "x": bscount_climb,
                            "meta": wl_time_climb,
                            "name": f"{bb[3:]} Climb",
                            "type": "scatter",
                            "xaxis": "x1",
                            "yaxis": "y1",
                            "mode": "markers",
                            "marker": {
                                "symbol": "triangle-up",
                                "color": bs_chans[bb].climb_color,
                            },
                            "hovertemplate": f"{bb[3:]} Climb<br>"
                            + "%{x:"
                            + fmt
                            + "} "
                            + units
                            + "<br>%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                        }
                    )
                    break

        # If we didn't find backscatter, we're done.
        if not fig:
            return (ret_figs, ret_plots)

        # Only for time series plots
        timeouts = None
        if max_depth_sample_index:
            timeouts, timeouts_times = PlotUtils.collect_timeouts(
                dive_nc_file,
                wetlabs_type,
            )

            if timeouts:
                PlotUtils.add_timeout_overlays(
                    timeouts,
                    timeouts_times,
                    fig,
                    f_depth,
                    wl_time,
                    max_depth_sample_index,
                    max_depth,
                    start_time,
                    last_dive_color,  # To match insturment dive trace
                    last_climb_color,  # To match instrument climb trace
                )

            PlotUtils.add_sample_range_overlay(
                wl_time,
                max_depth_sample_index,
                start_time,
                fig,
                f_depth,
            )

        if adjusted:
            xlabel = r"$m^{-1} sr^{-1}$"
        else:
            xlabel = "Counts"

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = f"{mission_dive_str}<br>Backscattering vs Depth{binned_tag}"
        output_name = "dv%04d_%s_backscatter" % (dive_nc_file.dive_number, wetlabs_type)

        fig.update_layout(
            {
                "xaxis": {
                    "title": xlabel,
                    "showgrid": True,
                    "side": "top",
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
        )

        if "sg_cal_calibcomm_wetlabs" in dive_nc_file.variables:
            cal_text = (
                dive_nc_file.variables["sg_cal_calibcomm_wetlabs"][:].tobytes().decode()
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
