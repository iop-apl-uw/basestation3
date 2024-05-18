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

"""Routines for analysis based plots for reduced TS profiles"""

import os
import pdb
import stat
import sys
import time
import traceback

import numpy as np
import plotly.graph_objects
import seawater
import xarray as xr

import BaseOpts
import PlotUtilsPlotly
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
)

# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False


#
# Plots/Analysis
#
def plot_ts_profile(profile_file, dive_num, base_opts):
    """Plot a text version of a reduced TS profile"""
    with open(profile_file, "r") as fi:
        for ll in fi.readlines():
            if ll.startswith("%first_bin_depth"):
                first_bin_depth = float(ll.split(":")[1])
            elif ll.startswith("%bin_width"):
                bin_width = float(ll.split(":")[1])

    data = np.genfromtxt(profile_file, comments="%", names=("temperature", "salinity"))

    depth = np.arange(first_bin_depth, bin_width * len(data["temperature"]), bin_width)

    return plot_ts_profile_core(
        bin_width, depth, data["temperature"], data["salinity"], dive_num, base_opts
    )


def plot_ncdf_profile(ncf_file, dive_num, base_opts):
    """Plot a text version of a reduced TS profile"""

    ds = xr.open_dataset(ncf_file)

    return plot_ts_profile_core(
        np.diff(ds["depth"])[0],
        ds["depth"],
        ds["temperature"][0],
        ds["salinity"][0],
        ds["dive_number"],
        base_opts,
    )


def plot_ts_profile_core(bin_width, depth, temperature, salinity, dive_num, base_opts):
    """Core plotting routine"""
    ret_val = []

    fig = plotly.graph_objects.Figure()

    fig.add_trace(
        {
            "y": depth,
            "x": salinity,
            "name": "Salinity",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "DarkBlue",
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            "hovertemplate": "%{x:.2f} psu<br>%{y:.2f} meters<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "y": depth,
            "x": temperature,
            "name": "Temp",
            "type": "scatter",
            "xaxis": "x2",
            "yaxis": "y2",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "DarkMagenta",
                #'size':10,'line':{'width':1, 'color':'DarkSlateGrey'}
            },
            "hovertemplate": "%{x:.2f} C<br>%{y:.2f} meters<extra></extra>",
        }
    )

    title_text = (
        f"Raw/Uncorrect CTD Temperature and Salinity vs Depth<br>Binned to {bin_width}m"
    )
    fig.update_layout(
        {
            "xaxis": {
                "title": "Salinity (PSU)",
                "showgrid": False,
                # "range": [np.min(data["salinity"]), np.max(data["salinity"])],
            },
            "yaxis": {
                "title": "Depth (m)",
                #'autorange' : 'reversed',
                "range": [
                    depth.max(),
                    0,
                ],
            },
            "xaxis2": {
                "title": "Temperature (C)",
                #'titlefont': {'color': 'rgb(148, 103, 189)'},
                #  'tickfont': {color: 'rgb(148, 103, 189)'},
                "overlaying": "x1",
                "side": "top",
                # "range": [np.min(data["temperature"]), np.max(data["temperature"])],
            },
            "yaxis2": {
                "title": "Depth (m)",
                "overlaying": "y1",
                "side": "right",
                #'autorange' : 'reversed',
                "range": [
                    max(depth),
                    0,
                ],
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

    ret_val.append(
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_reduced_ctd" % (dive_num,),
            fig,
        )
    )

    # TS plot

    temperature_dive = temperature
    salinity_dive = salinity
    depth_dive = depth

    # Countour the density
    min_salinity = np.nanmin(salinity) - (
        0.05 * abs(np.nanmax(salinity) - np.nanmin(salinity))
    )
    max_salinity = np.nanmax(salinity) + (
        0.05 * abs(np.nanmax(salinity) - np.nanmin(salinity))
    )

    min_temperature = np.nanmin(temperature) - (
        0.05 * abs(np.nanmax(temperature) - np.nanmin(temperature))
    )
    max_temperature = np.nanmax(temperature) + (
        0.05 * abs(np.nanmax(temperature) - np.nanmin(temperature))
    )

    fig = plotly.graph_objects.Figure()

    # plt.xlim(xmax = max_salinity, xmin = min_salinity)
    # plt.ylim(ymax = max_temperature, ymin = min_temperature)

    sgrid = np.linspace(min_salinity, max_salinity)
    tgrid = np.linspace(min_temperature, max_temperature)

    (Sg, Tg) = np.meshgrid(sgrid, tgrid)
    Pg = np.zeros((len(Sg), len(Tg)))
    sigma_grid = seawater.dens(Sg, Tg, Pg) - 1000.0

    # What a hack - this intermediate step is needed for plot.ly
    tg = Tg[:, 0][:]
    sg = Sg[0, :][:]

    fig.add_trace(
        {
            "x": sg,
            "y": tg,
            "z": sigma_grid[:],
            "type": "contour",
            "contours_coloring": "none",
            "showscale": False,
            "showlegend": True,
            "name": "Density",
            "contours": {
                "showlabels": True,
            },
            "hoverinfo": "skip",
        }
    )

    cmin = np.nanmin(depth)
    cmax = np.nanmax(depth)

    sigma_dive = (
        seawater.dens(salinity_dive, temperature_dive, np.zeros(len(temperature_dive)))
        - 1000.0
    )
    # sigma_climb = (
    #     seawater.dens(
    #         salinity_climb, temperature_climb, np.zeros(len(temperature_climb))
    #     )
    #     - 1000.0
    # )

    fig.add_trace(
        {
            "y": temperature_dive,
            "x": salinity_dive,
            "customdata": sigma_dive,
            # Not sure where this came from - previous version had this for dive and no
            # meta for climb.  Might have been to address the sometimes mis-matched color bars
            # "meta": {"colorbar": depth_dive,},
            "meta": depth_dive,
            "name": "Dive",
            "type": "scatter",
            "xaxis": "x1",
            "yaxis": "y1",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": depth_dive,
                "colorbar": {
                    "title": "Depth(m)",
                    "len": 0.8,
                },
                "colorscale": "jet",
                "reversescale": True,
                "cmin": cmin,
                "cmax": cmax,
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            "hovertemplate": "Dive<br>%{x:.2f} psu<br>%{y:.3f} C<br>%{customdata:.2f}"
            " sigma-t<br>%{meta:.2f} meters<extra></extra>",
        }
    )

    # fig.add_trace(
    #     {
    #         "y": temperature_climb,
    #         "x": salinity_climb,
    #         "meta": depth_climb,
    #         "customdata": np.squeeze(
    #             np.dstack(
    #                 (np.transpose(sigma_climb), np.transpose(point_num_ctd_climb))
    #             )
    #         ),
    #         "name": "Climb",
    #         "type": "scatter",
    #         "xaxis": "x1",
    #         "yaxis": "y1",
    #         "mode": "markers",
    #         "marker": {
    #             "symbol": "triangle-up",
    #             "color": depth_climb,
    #             "colorbar": {
    #                 "title": "Depth(m)",
    #                 "len": 0.7 if freeze_pt is not None else 0.8,
    #             },
    #             "colorscale": "jet",
    #             "reversescale": True,
    #             "cmin": cmin,
    #             "cmax": cmax,
    #             #'line':{'width':1, 'color':'LightSlateGrey'}
    #         },
    #         "hovertemplate": "Climb<br>%{x:.2f} psu<br>%{y:.3f} C<br>%{customdata[0]:.2f}"
    #         + " sigma-t<br>%{customdata[1]:d} point_num<br>%{meta:.2f} meters<extra></extra>",
    #     }
    # )

    title_text = (
        f"Raw/Uncorrect CTD Temperature and Salinity vs Depth<br>Binned to {bin_width}m"
    )

    # aspect_ratio = (max_salinity - min_salinity) / (max_temperature - min_temperature)

    fig.update_layout(
        {
            "xaxis": {
                "title": "Salinity (PSU)",
                "showgrid": True,
                "range": [min_salinity, max_salinity],
            },
            "yaxis": {
                "title": "Temperature (C)",
                "range": [min_temperature, max_temperature],
                #'scaleanchor' : 'x1',
                #'scaleratio' : aspect_ratio,
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

    ret_val.append(
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_reduced_ts" % (dive_num,),
            fig,
        )
    )

    return ret_val


def load_additional_arguments():
    """Defines and extends arguments related to this extension.
    Called by BaseOpts when the extension is set to be loaded
    """
    return (
        # Add this module to these options defined in BaseOpts
        [
            "save_svg",
            "save_png",
            "save_jpg",
            "save_webp",
            "compress_div",
            "full_html",
            "plot_directory",
            "mission_dir",
            "netcdf_filename",
        ],
        # Option groups
        {},
        # Additional arguments
        {},
    )


# pylint: disable=unused-argument
def main(
    instrument_id=None,
    base_opts=None,
    sg_calib_file_name=None,
    dive_nc_file_names=None,
    nc_files_created=None,
    processed_other_files=None,
    known_mailer_tags=None,
    known_ftp_tags=None,
    processed_file_names=None,
):
    """Basestation extension for plotting X3 compressed TS profiles

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    if base_opts is None:
        add_to_arguments, _, _ = load_additional_arguments()

        base_opts = BaseOpts.BaseOptions(
            "Basestation extension for plotting X3 compressed or network cdf TS profiles",
            add_to_arguments=add_to_arguments,
            additional_arguments={
                "profile_filenames": BaseOpts.options_t(
                    None,
                    ("MakePlotTSProfile",),
                    ("profile_filenames",),
                    BaseOpts.FullPath,
                    {
                        "help": "Name of TS profile file(s) or network cdf (.ncdf) files to plot",
                        "nargs": "+",
                        "action": BaseOpts.FullPathAction,
                    },
                ),
            },
        )

    BaseLogger(base_opts)  # initializes BaseLog

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    log_debug(f"processed_other_files {processed_other_files}")
    Utils.check_versions()

    profile_file_names = []
    ncdf_file_names = []

    if hasattr(base_opts, "profile_filenames") and base_opts.profile_filenames:
        processed_other_files = base_opts.profile_filenames

    if processed_other_files is not None:
        for ff in processed_other_files:
            if ff.endswith(".npro"):
                # While the glider can produce reduced profile up or down,
                # only plot the downcast.
                if os.path.split(ff)[1][10:11] == "a":
                    profile_file_names.append(ff)
            elif ff.endswith(".ncdf"):
                ncdf_file_names.append(ff)
    else:
        log_info("No profiles specified to plot")
        return 0

    if profile_file_names or ncdf_file_names:
        if profile_file_names:
            # These files come from the scicon profile sub-directory
            pd = os.path.split(os.path.split(profile_file_names[0])[0])[0]
        else:
            pd = os.path.split(ncdf_file_names[0])[0]
        pd = os.path.join(pd, "plots")

        if not base_opts.plot_directory:
            base_opts.plot_directory = pd
        if not os.path.exists(base_opts.plot_directory):
            try:
                os.mkdir(base_opts.plot_directory)
            except Exception:
                log_error(f"Could not create {base_opts.plot_directory}", "exc")
                log_info("Bailing out")
                return 1

        if not os.path.exists(base_opts.plot_directory):
            try:
                os.mkdir(base_opts.plot_directory)
                # Ensure that MoveData can move it as pilot if not run as the glider account
                os.chmod(
                    base_opts.plot_directory,
                    stat.S_IRUSR
                    | stat.S_IWUSR
                    | stat.S_IXUSR
                    | stat.S_IRGRP
                    | stat.S_IXGRP
                    | stat.S_IWGRP
                    | stat.S_IROTH
                    | stat.S_IXOTH,
                )
            except Exception:
                log_error(f"Could not create {base_opts.plot_directory}", "exc")
                log_info("Bailing out")
                return 1

        for profile_file_name in profile_file_names:
            log_info(f"Processing {profile_file_name}")
            dive_num = int(os.path.split(profile_file_name)[1][6:10])
            try:
                plots = plot_ts_profile(profile_file_name, dive_num, base_opts)
                if processed_other_files is not None and plots is not None:
                    for p in plots:
                        processed_other_files.append(p)

            except KeyboardInterrupt:
                log_error("Interupted by operator")
                break
            except Exception:
                log_error(
                    "Error in plotting vertical velocity for %s - skipping"
                    % profile_file_name,
                    "exc",
                )

        for ncdf_file_name in ncdf_file_names:
            log_info(f"Processing {ncdf_file_name}")
            # dive_num = int(os.path.split(ncdf_file_name)[1][4:8])
            try:
                plots = plot_ncdf_profile(ncdf_file_name, None, base_opts)
                if processed_other_files is not None and plots is not None:
                    for p in plots:
                        processed_other_files.append(p)

            except KeyboardInterrupt:
                log_error("Interupted by operator")
                break
            except Exception:
                log_error(
                    "Error in plotting vertical velocity for %s - skipping"
                    % ncdf_file_name,
                    "exc",
                )

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    return 0


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        retval = main()
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
