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

"""Plots ctd corrections """

# TODO: This can be removed as of python 3.11
from __future__ import annotations
import collections
import typing

import gsw
import plotly.graph_objects
import scipy
import seawater

import numpy as np

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
import QC

from BaseLog import log_error, log_warning
from Plotting import plotdivesingle

# Experimental option - show the QC for the raw temp and salinity
# This seems more confusing then useful as the start of this QC vector is
# written out early in the QC process, but after some initial QC work has been done.
#
# Leave code turned off for now
f_add_raw_qc = False


@plotdivesingle
def plot_ctd_corrections(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plot showing results for ctd thermal-inertia corrections"""
    if not generate_plots:
        return ([], [])

    # Initial approach based on QC pickle output.  Not needed as same info can be recovered from
    # history attribute

    # qc_file = os.path.join(
    #     base_opts.mission_dir, f"qclog_{dive_nc_file.variables['trajectory'][0]:d}.pckl"
    # )

    # qc_data = QC.load_qc_pickl(qc_file)
    # if qc_data is None:
    #     log_warning(f"Could not load {qc_file} - skipping QC data")

    # qc_data_alt = QC.qc_log_list_from_history(dive_nc_file)

    # if len(qc_data) != len(qc_data_alt):
    #     log_warning("Diff lengths")
    # else:
    #     for ii in range(len(qc_data)):
    #         qc_str, qc_type, qc_points = qc_data[ii]
    #         qc_str_a, qc_type_a, qc_points_a = qc_data_alt[ii]
    #         if qc_str != qc_str_a:
    #             log_info(f"{ii}:{qc_str}{qc_str_a}")
    #         if qc_type != qc_type_a:
    #             log_info(f"{ii}:{qc_type}{qc_type_a}")
    #         if not np.array_equal(qc_points, qc_points_a):
    #             log_info(f"{ii}:{qc_points}{qc_points_a}")

    # qc_data = [x for x in qc_data if "raw " not in x.qc_str]

    qc_data = QC.qc_log_list_from_history(dive_nc_file)

    try:
        if "legato_temp" in dive_nc_file.variables:
            ctd_raw_temp = dive_nc_file.variables["legato_temp"][:]
            ctd_raw_cond = dive_nc_file.variables["legato_conduc"][:] / 10.0
            ctd_raw_time = dive_nc_file.variables["legato_time"][:]
            ctd_type = "Legato"
        elif "eng_rbr_temp" in dive_nc_file.variables:
            ctd_raw_temp = dive_nc_file.variables["eng_rbr_temp"][:]
            ctd_raw_cond = dive_nc_file.variables["eng_rbr_conduc"][:] / 10.0
            ctd_raw_time = dive_nc_file.variables["time"][:]
            ctd_type = "Legato"
        elif "temperature_raw" in dive_nc_file.variables:
            ctd_raw_temp = dive_nc_file.variables["temperature_raw"][:]
            ctd_raw_cond = dive_nc_file.variables["conductivity_raw"][:]
            ctd_raw_time = dive_nc_file.variables["ctd_time"][:]
            ctd_type = "Seabird"
        else:
            return ([], [])

        if f_add_raw_qc:
            raw_temperature_qc_strs = QC.qc_to_str(
                QC.decode_qc(dive_nc_file.variables["temperature_raw_qc"][:]),
                add_str="<br>",
            )
            raw_salinity_qc_strs = QC.qc_to_str(
                QC.decode_qc(dive_nc_file.variables["salinity_raw_qc"][:]),
                add_str="<br>",
            )
        else:
            raw_temperature_qc_strs = ["" for x in range(ctd_raw_temp.size)]
            raw_salinity_qc_strs = ["" for x in range(ctd_raw_cond.size)]

        qc_line = ""
        for raw in ("_raw", ""):
            temperature_qc = QC.decode_qc(
                dive_nc_file.variables[f"temperature{raw}_qc"][:]
            )
            salinity_qc = QC.decode_qc(dive_nc_file.variables[f"salinity{raw}_qc"][:])
            qc_counts = {}
            for qc_val in QC.qc_name_d.keys():
                qc_counts[qc_val] = np.nonzero(
                    np.logical_and(
                        QC.find_qc(temperature_qc, [qc_val], mask=True),
                        QC.find_qc(salinity_qc, [qc_val], mask=True),
                    )
                )[0].size
            raw_str = "Raw" if raw == "_raw" else "Corrected"
            qc_line += f"<br>QC {raw_str} Totals:"
            for qc_val, qc_count in qc_counts.items():
                if qc_count:
                    qc_line += f" {QC.qc_name_d[qc_val]}:{qc_count}"

    except Exception:
        log_error("Could not load ctd data", "exc")
        return ([], [])

    gc_secs = gc_moves = None
    try:
        gc_secs = dive_nc_file.variables["gc_st_secs"][:]
        gc_secs = np.concatenate((np.array((0.0,)), gc_secs, np.array((2000000000.0,))))

        gc_moves = PlotUtils.extract_gc_moves(dive_nc_file)[0]
    except Exception:
        log_warning("Could not extract GC data - skipping", "exc")

    ctd_raw_valid_i = np.logical_and.reduce(
        (
            np.logical_not(np.isnan(ctd_raw_temp)),
            np.logical_not(np.isnan(ctd_raw_cond)),
            np.logical_not(np.isnan(ctd_raw_time)),
        )
    )

    point_num = np.arange(0, ctd_raw_temp.size)
    # These are split into salinity and temp.
    cust_hv_txt = ["", ""]
    cust_data = [None, None]
    qc_pts = [None, None]
    if qc_data:
        for jj in range(2):
            qc_list, qc_pts[jj] = QC.qc_list_to_points_list(
                qc_data, ctd_raw_temp.size, bool(jj)
            )
            tmp_list = [
                np.transpose(point_num),
                np.transpose(raw_salinity_qc_strs if jj else raw_temperature_qc_strs),
            ]
            for ii in range(len(qc_list)):
                tmp_list.append(np.transpose(qc_list[ii]))
                cust_hv_txt[jj] = f"{cust_hv_txt[jj]}%{{customdata[{ii+2}]}}"
            cust_data[jj] = np.dstack((tmp_list))
    else:
        for jj in range(2):
            cust_data[jj] = np.dstack(
                (
                    np.transpose(point_num),
                    np.transpose(
                        np.transpose(
                            raw_salinity_qc_strs if jj else raw_temperature_qc_strs
                        ),
                    ),
                )
            )

    try:
        corr_temperature = dive_nc_file.variables["temperature"][:]
        corr_temperature_qc = QC.decode_qc(dive_nc_file.variables["temperature_qc"][:])
        corr_temperature_qc_strs = QC.qc_to_str(corr_temperature_qc)
        # Display all points in plot - keep this mechanism in case we need to revert
        # temperature_good_i = QC.find_qc(corr_temperature_qc, QC.only_good_qc_values)
        temperature_good_i = np.arange(0, corr_temperature.size)
        corr_salinity = dive_nc_file.variables["salinity"][:]
        corr_salinity_qc = QC.decode_qc(dive_nc_file.variables["salinity_qc"][:])
        corr_salinity_qc_strs = QC.qc_to_str(corr_salinity_qc)
        # salinity_good_i = QC.find_qc(corr_salinity_qc, QC.only_good_qc_values)
        salinity_good_i = np.arange(0, corr_salinity.size)
        # Use ctd_pressure since it has already been through the legato pressure despiker
        ctd_press = dive_nc_file.variables["ctd_pressure"][:]
        ctd_depth = dive_nc_file.variables["ctd_depth"][:]
        ctd_time = dive_nc_file.variables["ctd_time"][:]
        start_time = dive_nc_file.start_time
    except Exception:
        log_error("Could not load corrected temperature or salinity", "exc")
        return ([], [])

    ctd_time = (ctd_time - start_time) / 60.0
    ctd_raw_time = (ctd_raw_time - start_time) / 60.0

    if not base_opts.use_gsw:
        ctd_raw_salinity = seawater.salt(
            ctd_raw_cond / (seawater.constants.c3515 / 10.0), ctd_raw_temp, ctd_press
        )
    else:
        ctd_raw_salinity = gsw.SP_from_C(ctd_raw_cond * 10.0, ctd_raw_temp, ctd_press)

    fig = plotly.graph_objects.Figure()

    rng = np.nanmax(ctd_depth) - np.nanmin(ctd_depth)
    depth_max = np.nanmax(ctd_depth) + (0.05 * rng)
    depth_min = np.nanmin(ctd_depth) - (0.05 * rng)

    if gc_moves is not None:
        show_label = collections.defaultdict(lambda: True)
        # y_min = min(ctd_raw_salinity.min(), corr_salinity.min())
        # y_max = max(ctd_raw_salinity.max(), corr_salinity.max())
        y_min = depth_max
        y_max = depth_min
        for gc in gc_moves:
            fig.add_trace(
                {
                    "type": "scatter",
                    "x": (gc[0] / 60.0, gc[0] / 60.0, gc[1] / 60.0, gc[1] / 60.0),
                    "y": (y_min, y_max, y_max, y_min),
                    "xaxis": "x1",
                    # "yaxis": "y1",
                    "yaxis": "y3",
                    "fill": "toself",
                    "fillcolor": PlotUtils.gc_move_colormap[gc[2]].color,
                    "line": {
                        "dash": "solid",
                        "color": PlotUtils.gc_move_colormap[gc[2]].color,
                    },
                    "mode": "none",  # no outter lines and ponts
                    "legendgroup": f"{PlotUtils.gc_move_colormap[gc[2]].name}_group",
                    "name": f"GC {PlotUtils.gc_move_colormap[gc[2]].name}",
                    "showlegend": show_label[PlotUtils.gc_move_colormap[gc[2]].name],
                    "text": f"GC {PlotUtils.gc_move_colormap[gc[2]].name}, Start {gc[0] / 60.0:.2f}mins, End {gc[1] / 60.0:.2f}mins",
                    "hoverinfo": "text",
                }
            )
            show_label[PlotUtils.gc_move_colormap[gc[2]].name] = False

    # Depth trace
    fig.add_trace(
        {
            "name": "Depth",
            "x": ctd_time,
            "y": ctd_depth,
            "mode": "lines+markers",
            "marker": {"symbol": "cross", "size": 3},
            # "line": {"dash": "solid", "color": "DarkRed"},
            "line": {"dash": "solid", "color": "DarkGrey"},
            "yaxis": "y3",
            "hovertemplate": "Depth<br>%{y:.1f} meters<br>%{x:.2f} mins<br><extra></extra>",
            "visible": "legendonly",
            # "visible": True,
        }
    )

    # Annotate QC'd points
    if qc_pts[0]:
        fig.add_trace(
            {
                "name": "QC Salin/Cond flagged",
                "x": ctd_raw_time[list(qc_pts[0])],
                "y": ctd_raw_salinity[list(qc_pts[0])],
                "mode": "markers",
                "yaxis": "y1",
                "marker": {
                    "symbol": "circle",
                    "color": "Cyan",
                },
                "visible": True,
                "hovertemplate": None,
                "hoverinfo": "skip",
            }
        )

    fig.add_trace(
        {
            "name": f"{ctd_type} Raw Salinity",
            "x": ctd_raw_time[ctd_raw_valid_i],
            "y": ctd_raw_salinity[ctd_raw_valid_i],
            "customdata": np.squeeze(cust_data[0]),
            "yaxis": "y1",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {
                "symbol": "cross",
                "size": 3,
                "color": "DarkBlue",
            },
            "hovertemplate": f"Raw Salin<br>%{{x:.2f}} min<br>%{{y:.2f}} PSU<br>%{{customdata[0]:d}} point_num<br>%{{customdata[1]}}{cust_hv_txt[1]}<extra></extra>",
        }
    )

    if qc_pts[1]:
        fig.add_trace(
            {
                "name": "QC Temp flagged",
                "x": ctd_raw_time[list(qc_pts[1])],
                "y": ctd_raw_temp[list(qc_pts[1])],
                "yaxis": "y2",
                "mode": "markers",
                "marker": {
                    "symbol": "circle",
                    "color": "Cyan",
                },
                "visible": True,
                "hovertemplate": None,
                "hoverinfo": "skip",
            }
        )

    fig.add_trace(
        {
            "name": f"{ctd_type} Raw Temp",
            "x": ctd_raw_time[ctd_raw_valid_i],
            "y": ctd_raw_temp[ctd_raw_valid_i],
            "customdata": np.squeeze(cust_data[1]),
            "yaxis": "y2",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3, "color": "DarkMagenta"},
            "hovertemplate": f"Raw Temp<br>%{{x:.2f}} min<br>%{{y:.3f}} C<br>%{{customdata[0]:d}} point_num<br>%{{customdata[1]}}{cust_hv_txt[0]}<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "name": f"{ctd_type} Corr Salinity",
            "x": ctd_time[salinity_good_i],
            "y": corr_salinity[salinity_good_i],
            "customdata": np.squeeze(
                np.dstack(
                    (
                        np.transpose(np.arange(0, ctd_raw_time.size)[salinity_good_i]),
                        np.transpose(corr_salinity_qc_strs),
                    )
                )
            ),
            "yaxis": "y1",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3, "color": "DarkGreen"},
            "hovertemplate": "Corr Salin<br>%{x:.2f} min<br>%{y:.2f} PSU<br>%{customdata[0]:d} point_num<br>%{customdata[1]}<extra></extra>",
        }
    )
    fig.add_trace(
        {
            "name": f"{ctd_type} Corr Temp",
            "x": ctd_time[temperature_good_i],
            "y": corr_temperature[temperature_good_i],
            "customdata": np.squeeze(
                np.dstack(
                    (
                        np.transpose(
                            np.arange(0, ctd_raw_time.size)[temperature_good_i]
                        ),
                        np.transpose(corr_temperature_qc_strs),
                    )
                )
            ),
            "yaxis": "y2",
            "mode": "lines+markers",
            "line": {"width": 1},
            "marker": {"symbol": "cross", "size": 3, "color": "DarkRed"},
            "hovertemplate": "Corr Temp<br>%{x:.2f} min<br>%{y:.3f} C<br>%{customdata[0]:d} point_num<br>%{customdata[1]}<extra></extra>",
        }
    )

    # # Highlight differnces
    # changed_points = np.squeeze(
    #     np.nonzero(
    #         np.abs(corr_salinity[salinity_good_i] - ctd_raw_salinity[salinity_good_i])
    #         > 0.000001
    #     )
    # )
    # fig.add_trace(
    #     {
    #         "name": "salinity differences",
    #         "x": ctd_time[changed_points],
    #         "y": corr_salinity[changed_points],
    #         "mode": "markers",
    #         "marker": {"symbol": "circle"},
    #         "visible": True,
    #         "hovertemplate": "Diff in salinity<br>%{x:.2f} mins<br>%{y:.2f} PSU<extra></extra>",
    #     }
    # )

    # changed_points = np.squeeze(
    #     np.nonzero(
    #         np.abs(
    #             corr_temperature[temperature_good_i] - ctd_raw_temp[temperature_good_i]
    #         )
    #         > 0.0001
    #     )
    # )
    # fig.add_trace(
    #     {
    #         "name": "temperature differences",
    #         "x": ctd_time[changed_points],
    #         "y": corr_temperature[changed_points],
    #         "yaxis": "y2",
    #         "mode": "markers",
    #         "marker": {"symbol": "circle"},
    #         "visible": True,
    #         "hovertemplate": "Diff in temperature<br>%{x:.2f} mins<br>%{y:.3f} C<extra></extra>",
    #     }
    # )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = f"{mission_dive_str}<br>{ctd_type} Raw Temp/Salinity and Corrected Temp/Salinity vs Time{qc_line}"

    fig.update_layout(
        {
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "xaxis": {
                "title": "Time Into Dive (min)",
                "showgrid": True,
                "domain": [0.1, 0.9],
            },
            "yaxis": {
                "title": "Conductivity (PSU)",
                "showgrid": True,
                "autorange": "reversed",
            },
            "yaxis2": {
                "title": "Temperature (C)",
                "showgrid": False,
                "side": "right",
                "overlaying": "y1",
                # "autorange": "reversed",
                "anchor": "x",
            },
            "yaxis3": {
                "title": "Depth",
                "range": [depth_max, depth_min],
                # "autorange": "reversed",
                "overlaying": "y1",
                "anchor": "free",
                "side": "left",
                "position": 0,
                "showgrid": False,
            },
            "margin": {
                "t": 150,
            },
            "legend": {
                "x": 1.05,
                "y": 1,
            },
            # "width": std_width,
            # "height": std_height,
        }
    )

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_%s_corr_compare" % (dive_nc_file.dive_number, ctd_type.lower()),
            fig,
        ),
    )
