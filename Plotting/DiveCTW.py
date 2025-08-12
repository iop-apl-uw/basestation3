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

"""Plots gliders course through the water"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import contextlib
import typing

import numpy as np
import plotly.graph_objects

if typing.TYPE_CHECKING:
    import scipy

    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
import Utils
from BaseLog import log_debug, log_error, log_warning
from Plotting import plotdivesingle


@plotdivesingle
def plot_CTW(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots the glider course through the water"""
    # TODO create roll to right and left vectors
    # TODO add new traces that overlay exiting traces with low alpha circles
    # TODO see grouped_legend.py for how to group things into one trace
    # TODO add relevant text to plot (or legand)

    if not generate_plots:
        return ([], [])

    # Preliminaries
    try:
        # start_time = dive_nc_file.start_time
        time_gps = dive_nc_file.variables["log_gps_time"][:]
        start_time = time_gps[1]
        #        ctd_time = (dive_nc_file.variables["ctd_time"][:] - start_time) / 60.0
        #        ctd_depth = dive_nc_file.variables["ctd_depth"][:]
        #        north_disp = dive_nc_file.variables["north_displacement"][:]
        #        east_disp = dive_nc_file.variables["east_displacement"][:]

        sg_time = (dive_nc_file.variables["time"][:] - start_time) / 60.0
        sg_depth = dive_nc_file.variables["depth"][:]
        # Interpolate around missing depth observations
        sg_depth = PlotUtils.interp_missing_depth(sg_time, sg_depth)

        north_disp_gsm = dive_nc_file.variables["north_displacement_gsm"][:]
        east_disp_gsm = dive_nc_file.variables["east_displacement_gsm"][:]

        lats_gsm = dive_nc_file.variables["latitude_gsm"][:]
        lons_gsm = dive_nc_file.variables["longitude_gsm"][:]
        lat_gps = dive_nc_file.variables["log_gps_lat"][:]
        lon_gps = dive_nc_file.variables["log_gps_lon"][:]

        mhead = [
            float(s)
            for s in dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
            .tobytes()
            .decode("utf-8")
            .split(",")
        ]
        errband = float(dive_nc_file.variables["log_HEAD_ERRBAND"].getValue())
        if "log_gps_magvar" in dive_nc_file.variables:
            magvar = dive_nc_file.variables["log_gps_magvar"][:][0]
        elif "magnetic_variation" in dive_nc_file.variables:
            # Vendor Basestation
            magvar = dive_nc_file.variables["magnetic_variation"].getValue()
        else:
            log_error("Could not find the magvar for plot_CTW")
            magvar = -1.0
    except KeyError as e:
        log_error(f"Unable to load {e} - skipping plot_CTW")
        return ([], [])
    except Exception:
        log_error("Problems in plot_CTW", "exc")
        return ([], [])

    ctd_time = ctd_depth = north_disp = east_disp = lats = lons = None

    with contextlib.suppress(KeyError):
        ctd_time = (dive_nc_file.variables["ctd_time"][:] - start_time) / 60.0
        ctd_depth = dive_nc_file.variables["ctd_depth"][:]
        north_disp = dive_nc_file.variables["north_displacement"][:]
        east_disp = dive_nc_file.variables["east_displacement"][:]
        lats = dive_nc_file.variables["latitude"][:]
        lons = dive_nc_file.variables["longitude"][:]

    # In the event there is no CTD columns, the assumption is the GSM model
    # was computed against the truck time grid
    if ctd_time is None:
        ctd_time = sg_time
        ctd_depth = sg_depth

    x = y = None
    if lats is not None and lons is not None:
        x = lats.copy()
        y = lons.copy()
        x[0] = 0
        y[0] = 0
        for i in range(len(x)):
            (_, _, x[i], y[i]) = Utils.rangeBearing(lats[0], lons[0], lats[i], lons[i])

    x_gsm = lats_gsm.copy()
    y_gsm = lons_gsm.copy()
    x_gsm[0] = 0
    y_gsm[0] = 0
    for i in range(len(x_gsm)):
        (_, _, x_gsm[i], y_gsm[i]) = Utils.rangeBearing(
            lats_gsm[0], lons_gsm[0], lats_gsm[i], lons_gsm[i]
        )

    desired_head = mhead[0]

    disp = north_disp_cum = east_disp_cum = None
    if north_disp is not None and east_disp is not None:
        north_disp_cum = np.cumsum(north_disp)
        east_disp_cum = np.cumsum(east_disp)
        disp = np.sqrt(north_disp_cum[-1] ** 2 + east_disp_cum[-1] ** 2)

        log_debug(
            f"Total displacement {disp} (m) desired heading {desired_head:f} (deg), magvar {magvar:f} (deg)"
        )

    north_disp_gsm_cum = np.cumsum(north_disp_gsm)
    east_disp_gsm_cum = np.cumsum(east_disp_gsm)
    disp_gsm = np.sqrt(north_disp_gsm_cum[-1] ** 2 + east_disp_gsm_cum[-1] ** 2)
    log_debug(
        f"Total displacement (GSM) {disp_gsm} (m) desired heading {desired_head:f} (deg), magvar {magvar:f} (deg)"
    )

    # Check for AD2CP output
    north_disp_cum_ttw = None
    east_disp_cum_ttw = None
    north_disp_cum_ttw_ocn = None
    east_disp_cum_ttw_ocn = None
    if (
        "ad2cp_inv_glider_uttw" in dive_nc_file.variables
        and "ad2cp_inv_glider_vttw" in dive_nc_file.variables
    ):
        # import pdb

        # pdb.set_trace()
        try:
            ttw_time = dive_nc_file.variables["ad2cp_inv_glider_time"][:]
            dive_i = np.logical_and(ttw_time >= time_gps[1], ttw_time <= time_gps[2])

            ttw_dive_time_diff = np.hstack(
                (ttw_time[dive_i][0] - time_gps[1], np.diff(ttw_time[dive_i]))
            )
            ttw_dive_time = (ttw_time[dive_i] - time_gps[1]) / 60.0
            uttw = dive_nc_file.variables["ad2cp_inv_glider_uttw"][:]
            vttw = dive_nc_file.variables["ad2cp_inv_glider_vttw"][:]
            uocn = dive_nc_file.variables["ad2cp_inv_glider_uocn"][:]
            vocn = dive_nc_file.variables["ad2cp_inv_glider_vocn"][:]

            north_disp_cum_ttw = np.cumsum(vttw[dive_i] * ttw_dive_time_diff)
            east_disp_cum_ttw = np.cumsum(uttw[dive_i] * ttw_dive_time_diff)
            north_disp_cum_ttw_ocn = np.cumsum(
                (vttw[dive_i] + vocn[dive_i]) * ttw_dive_time_diff
            )
            east_disp_cum_ttw_ocn = np.cumsum(
                (uttw[dive_i] + uocn[dive_i]) * ttw_dive_time_diff
            )

            # ttw_time = dive_nc_file.variables["ad2cp_inv_glider_time"][:]
            # ttw_time = (ttw_time[1:] - ttw_time[1]) / 60.0
        except Exception:
            log_warning("Problems in plot_CTW ADCP intput", "exc")
    # _, gc_roll_time, gc_roll_pos, gc_pitch_time, gc_pitch_pos, gc_vbd_time, gc_vbd_pos = extract_gc_moves(dive_nc_file)

    fig = plotly.graph_objects.Figure()

    if north_disp_cum is not None and east_disp_cum is not None:
        fig.add_trace(
            {
                "y": north_disp_cum,
                "x": east_disp_cum,
                "meta": ctd_time,
                "name": "Course Through Water HDM",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "circle",
                    "color": "DarkBlue",
                    "size": 2,
                    #'line':{'width':1, 'color':'LightSlateGrey'}
                },
                "hovertemplate": "CTW HDM<br>Northward %{y:.1f} m<br>Eastward %{x:.1f} m<br>%{meta:.2f} mins<extra></extra>",
            }
        )

    fig.add_trace(
        {
            "y": north_disp_gsm_cum,
            "x": east_disp_gsm_cum,
            "meta": ctd_time,
            "name": "Course Through Water GSM",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "circle",
                "color": "DarkGreen",
                "size": 2,
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            "hovertemplate": "CTW GSM<br>Northward %{y:.1f} m<br>Eastward %{x:.1f} m<br>%{meta:.2f} mins<extra></extra>",
        }
    )

    if north_disp_cum_ttw is not None and east_disp_cum_ttw is not None:
        fig.add_trace(
            {
                "y": north_disp_cum_ttw,
                "x": east_disp_cum_ttw,
                "meta": ttw_dive_time,
                "name": "Course Through Water AD2CP",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "circle",
                    # "color": "DarkGrey",
                    "color": "Magenta",
                    "size": 2,
                    #'line':{'width':1, 'color':'LightSlateGrey'}
                },
                "hovertemplate": "CTW AD2CP<br>Northward %{y:.1f} m<br>Eastward %{x:.1f} m<br>%{meta:.2f} mins<extra></extra>",
                # "visible": "legendonly",  # For now
            }
        )

    if lats is not None and lons is not None:
        customdata = np.squeeze(
            np.dstack(
                (
                    np.transpose(ctd_time),
                    np.transpose(ctd_depth),
                    np.transpose(lats),
                    np.transpose(lons),
                )
            )
        )

        hovertemplate = "COG HDM<br>lat %{customdata[2]:.4f}, lon %{customdata[3]:.4f}<br>time %{customdata[0]:.2f} min, depth %{customdata[1]:.2f} m<extra></extra>"

        fig.add_trace(
            {
                "y": y,
                "x": x,
                "meta": ctd_time,
                "name": "Course Over Ground HDM",
                "type": "scatter",
                "mode": "markers",
                "customdata": customdata,
                "marker": {
                    "symbol": "circle",
                    "color": "Cyan",
                    "size": 2,
                    #'line':{'width':1, 'color':'LightSlateGrey'}
                },
                "hovertemplate": hovertemplate,
            }
        )

    customdata = np.squeeze(
        np.dstack(
            (
                np.transpose(ctd_time),
                np.transpose(ctd_depth),
                np.transpose(lats_gsm),
                np.transpose(lons_gsm),
            )
        )
    )

    hovertemplate = "COG GSM<br>lat %{customdata[2]:.4f}, lon %{customdata[3]:.4f}<br>time %{customdata[0]:.2f} min, depth %{customdata[1]:.2f} m<extra></extra>"

    fig.add_trace(
        {
            "y": y_gsm,
            "x": x_gsm,
            "meta": ctd_time,
            "name": "Course Over Ground GSM",
            "type": "scatter",
            "mode": "markers",
            "customdata": customdata,
            "marker": {
                "symbol": "circle",
                "color": "steelblue",
                "size": 2,
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            "visible": True if lats is None or lons is None else "legendonly",
            "hovertemplate": hovertemplate,
        }
    )

    if north_disp_cum_ttw_ocn is not None:
        fig.add_trace(
            {
                "y": north_disp_cum_ttw_ocn,
                "x": east_disp_cum_ttw_ocn,
                "meta": ttw_dive_time,
                "name": "Course Over Ground AD2CP",
                "type": "scatter",
                "mode": "markers",
                "customdata": customdata,
                "marker": {
                    "symbol": "circle",
                    # "color": "Grey",
                    "color": "Orange",
                    "size": 2,
                    #'line':{'width':1, 'color':'LightSlateGrey'}
                },
                "hovertemplate": "COG AD2CP<br>Northward %{y:.1f} m<br>Eastward %{x:.1f} m<br>%{meta:.2f} mins<extra></extra>",
                # "visible": "legendonly",  # For now
            }
        )

    fig.add_trace(
        {
            "y": (0,),
            "x": (0,),
            "name": "GPS2",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "star",
                "color": "Red",
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            "hovertemplate": f"GPS2: {lat_gps[1]:.4f}, {lon_gps[1]:.4f}<extra></extra>",
        }
    )

    if y is not None and x is not None:
        gps_y = (y[-1],)
        gps_x = (x[-1],)
    else:
        gps_y = (y_gsm[-1],)
        gps_x = (x_gsm[-1],)

    fig.add_trace(
        {
            "y": gps_y,
            "x": gps_x,
            "name": "GPSEND",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "Red",
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            # "hovertemplate": f"GPSE: {Utils.dd2ddmm(lat_gps[2]):.2f}, {Utils.dd2ddmm(lon_gps[2]):.2f}",
            "hovertemplate": f"GPSE: {lat_gps[2]:.4f}, {lon_gps[2]:.4f}<br>{(time_gps[2] - start_time)/60.0:.4f} mins<extra></extra>",
        }
    )

    def roll_heading(deg):
        if deg >= 360.0:
            deg -= 360.0
        if deg < 0:
            deg += 360.0
        return deg

    # Add heading cone
    def line_end(deg, disp):
        deg = roll_heading(deg)
        return (np.sin(np.radians(deg)) * disp, np.cos(np.radians(deg)) * disp)

    # TODO - need annotations in the legend
    heading_list = [(desired_head, "head", "Red")]
    if np.abs(errband) < 180.0:
        heading_list.append(
            (roll_heading(desired_head + errband), "head+errband", "Black")
        )
        heading_list.append(
            (roll_heading(desired_head - errband), "head-errband", "Black")
        )

    for head, head_label, head_color in heading_list:
        if disp is not None:
            head_x, head_y = line_end(head + magvar, disp * 1.1)
        else:
            head_x, head_y = line_end(head + magvar, disp_gsm * 1.1)
        log_debug(f"head:{head:f} x:{head_x:f} y:{head_y:f}")
        # fig.add_shape(
        #     plotly.graph_objects.layout.Shape(
        #         name="Desired Heading",
        #         type="line",
        #         x0=0,
        #         y0=0,
        #         x1=x,
        #         y1=y,
        #         line=dict(
        #             color="Red" if head == desired_head else "Black",
        #             width=1,
        #             dash="solid",
        #         ),
        #     )
        # )
        fig.add_trace(
            {
                "name": f"{head_label} {head:.2f} deg mag",
                "y": [0, head_y],
                "x": [0, head_x],
                "type": "scatter",
                "mode": "lines",
                "line": {"dash": "solid", "color": head_color},
                "hovertemplate": f"{head:.2f} deg mag<extra></extra>",
            }
        )
    # Needed to get the origin for the lines to be 0,0 on the plot
    # fig.update_shapes(dict(xref="x", yref="y"))

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = f"{mission_dive_str}<br>Course through water and over ground"

    if np.nanmax(np.absolute(north_disp_gsm_cum)) > np.nanmax(
        np.absolute(east_disp_gsm_cum)
    ):
        xconstrain_key = "scaleanchor"
        xconstrain_value = "y"
        yconstrain_key = "constrain"
        yconstrain_value = "domain"
    else:
        xconstrain_key = "constrain"
        xconstrain_value = "domain"
        yconstrain_key = "scaleanchor"
        yconstrain_value = "x"

    fig.update_layout(
        {
            "xaxis": {
                "title": "Eastward Displacment (m)",
                "showgrid": True,
                #'range' : [min_salinity, max_salinity],
                xconstrain_key: xconstrain_value,
            },
            "yaxis": {
                "title": "Northward Displacment (m)",
                #'range' : [max(depth_dive.max() if len(depth_dive) > 0 else 0, depth_climb.max() if len(depth_climb) > 0 else 0), 0]
                yconstrain_key: yconstrain_value,
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
            "legend": {
                "x": 1.05,
                "y": 1,
            },
        }
    )

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts, "dv%04d_ctw" % (dive_nc_file.dive_number,), fig
        ),
    )
