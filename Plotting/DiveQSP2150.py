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

"""Plots the Biospherical QSP2150 PAR sensor (truck).

What the glider logs depends on the sensor's calibration mode (Sensors/qsp2150_ext.py),
so this plot reads the units and description the extension put on the netCDF
variables: qsp_PAR (in-water PAR) when the calibration constants allowed it, else the
column as recorded - labelled "unknown" when no mode was given. There's always a plot
when the dive has QSP2150 data.
"""

from __future__ import annotations

import pathlib
import typing

import numpy as np
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import sqlite3

    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
from BaseLog import log_error, log_warning
from Plotting import plotdivesingle

INSTRUMENT = "qsp"  # the eng prefix - timeouts and sample ranges go by it
RAW_VAR = "eng_qsp_PARuV"
PAR_VAR = "qsp_PAR"


def _attr(var: typing.Any, name: str) -> str:
    """Reads a netCDF variable attribute as text.

    Args:
        var: The netCDF variable.
        name: The attribute.

    Returns:
        The attribute, or "" if the variable doesn't have it.
    """
    value = getattr(var, name, "")
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


@plotdivesingle
def plot_qsp2150(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots: bool = True,
    dbcon: sqlite3.Connection | None = None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Plots QSP2150 PAR vs depth - calibrated if possible, as recorded otherwise.

    Args:
        base_opts: Command line options.
        dive_nc_file: The dive's netCDF file.
        generate_plots: False to skip the plot.
        dbcon: Unused (the plot signature).

    Returns:
        (figures, output files).
    """
    if RAW_VAR not in dive_nc_file.variables or not generate_plots:
        return ([], [])

    try:
        raw_var = dive_nc_file.variables[RAW_VAR]
        raw = raw_var[:]
        depth = dive_nc_file.variables["depth"][:]
        sg_time = dive_nc_file.variables["time"][:]
        depth = PlotUtils.interp_missing_depth(sg_time, depth)
        par_var = dive_nc_file.variables.get(PAR_VAR)
        par = par_var[:] if par_var is not None else None
    except Exception:
        log_error("Could not load the QSP2150 variables", "exc")
        return ([], [])

    raw_units = _attr(raw_var, "units") or "unknown"
    raw_comment = _attr(raw_var, "comment")

    try:
        start_time = dive_nc_file.start_time
    except Exception:
        start_time = sg_time[0]

    max_depth_sample_index = int(np.argmax(depth))
    max_depth = np.nanmax(depth)
    good = np.logical_and(np.isfinite(sg_time), np.isfinite(depth))
    f_depth = scipy.interpolate.PchipInterpolator(sg_time[good], depth[good], extrapolate=True)
    time_dive = (sg_time[:max_depth_sample_index] - start_time) / 60.0
    time_climb = (sg_time[max_depth_sample_index:] - start_time) / 60.0

    fig = plotly.graph_objects.Figure()

    def add_casts(values: np.ndarray, name: str, units: str, xaxis: str, colors: tuple[str, str], visible: typing.Any) -> None:
        for cast, sl, times, symbol, color in (
            ("Dive", slice(0, max_depth_sample_index), time_dive, "triangle-down", colors[0]),
            ("Climb", slice(max_depth_sample_index, None), time_climb, "triangle-up", colors[1]),
        ):
            fig.add_trace(
                {
                    "y": depth[sl],
                    "x": values[sl],
                    "meta": times,
                    "name": f"{name} {cast}",
                    "type": "scatter",
                    "xaxis": xaxis,
                    "yaxis": "y1",
                    "mode": "markers",
                    "visible": visible,
                    "marker": {"symbol": symbol, "color": color},
                    "hovertemplate": f"{name} {cast}<br>%{{x:.4f}} {units}<br>%{{y:.2f}} meters<br>%{{meta:.2f}} mins<extra></extra>",
                }
            )

    layout: dict[str, typing.Any] = {
        "yaxis": {"title": "Depth (m)", "showgrid": True, "autorange": "reversed"},
        "margin": {"t": 150, "b": 110},
    }
    if par is not None:
        par_units = _attr(par_var, "units")
        add_casts(par, "PAR", par_units, "x1", ("Red", "DarkRed"), True)
        add_casts(raw, "As recorded", raw_units, "x2", ("Blue", "DarkBlue"), "legendonly")
        layout["xaxis"] = {"title": f"PAR ({par_units}, in water)", "type": "log", "showgrid": True, "side": "bottom"}
        layout["xaxis2"] = {
            "title": f"As recorded ({raw_units})",
            "type": "log",
            "overlaying": "x1",
            "side": "top",
            "showgrid": False,
        }
        axes = ["xaxis", "xaxis2"]
        subtitle = "QSP2150 PAR"
    else:
        if raw_units == "unknown":
            title = "QSP2150 output as recorded (units unknown - set qsp_mode in sg_calib_constants.m)"
            log_warning("QSP2150 plot: units unknown - no qsp_mode in sg_calib_constants.m")
        else:
            title = f"QSP2150 output as recorded ({raw_units})"
        add_casts(raw, "As recorded", raw_units, "x1", ("Red", "DarkRed"), True)
        layout["xaxis"] = {"title": title, "type": "log", "showgrid": True, "side": "bottom"}
        axes = ["xaxis"]
        subtitle = "QSP2150 output"

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    layout["title"] = {
        "text": f"{mission_dive_str}<br>{subtitle} vs Depth",
        "xanchor": "center",
        "yanchor": "top",
        "x": 0.5,
        "y": 0.95,
    }
    fig.update_layout(layout)
    fig.update_layout(updatemenus=PlotUtilsPlotly.axis_scale_buttons(axes))

    timeouts, timeouts_times = PlotUtils.collect_timeouts(dive_nc_file, INSTRUMENT)
    if timeouts:
        PlotUtils.add_timeout_overlays(
            timeouts,
            timeouts_times,
            fig,
            f_depth,
            sg_time,
            max_depth_sample_index,
            max_depth,
            start_time,
            "Magenta",
            "Red",
        )
    PlotUtils.add_sample_range_overlay(
        base_opts,
        INSTRUMENT,
        dive_nc_file.dive_number,
        sg_time,
        max_depth_sample_index,
        start_time,
        fig,
        f_depth,
    )

    annotations = [PlotUtilsPlotly.add_help_link("dv_qsp2150")]
    cal_text = ""
    if "sg_cal_calibcomm_qsp" in dive_nc_file.variables:
        cal_text = dive_nc_file.variables["sg_cal_calibcomm_qsp"][:].tobytes().decode(errors="replace")
    elif raw_comment:
        cal_text = raw_comment
    if timeouts:
        cal_text += f" Timeouts:{timeouts:d}"
    if cal_text:
        annotations.append(
            {"text": cal_text, "showarrow": False, "xref": "paper", "yref": "paper", "x": 0.0, "y": -0.12, "xanchor": "left"}
        )
    fig.update_layout({"annotations": tuple(annotations)})

    output_name = "dv%04d_qsp2150" % dive_nc_file.dive_number
    return ([fig], PlotUtilsPlotly.write_output_files(base_opts, output_name, fig))
