#! /usr/bin/env python

##
## Copyright (c) 2006, 2007, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2020 by University of Washington.  All rights reserved.
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

"""Routines for analysis based plots from netCDF data
"""

import cProfile
import pstats
import os
import re
import stat
import sys
import time

import plotly.graph_objects
import numpy as np

from BaseLog import (
    BaseLogger,
    log_warning,
    log_error,
    log_info,
    log_debug,
    log_critical,
)
from BaseNetCDF import nc_sg_cal_prefix
import BaseOpts
from MakeDiveProfiles import sg_config_constants
import HydroModel

import MakeDiveProfiles
import Utils
import PlotUtils
import PlotUtilsPlotly
import Conf

#
# Plots/Analysis
#
def plot_ts_profile(profile_file, dive_num, plot_conf):

    with open(profile_file, "r") as fi:
        for ll in fi.readlines():
            if ll.startswith("%first_bin_depth"):
                first_bin_depth = float(ll.split(":")[1])
            elif ll.startswith("%bin_width"):
                bin_width = float(ll.split(":")[1])

    data = np.genfromtxt(profile_file, comments="%", names=("temperature", "salinity"))

    depth = np.arange(first_bin_depth, bin_width * len(data["temperature"]), bin_width)

    fig = plotly.graph_objects.Figure()

    fig.add_trace(
        {
            "y": depth,
            "x": data["salinity"],
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
            "x": data["temperature"],
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
                "range": [depth.max(), 0,],
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
                "range": [max(depth), 0,],
            },
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {"t": 150,},
        }
    )

    return PlotUtilsPlotly.write_output_files(
        plot_conf, "dv%04d_ts_profile" % (dive_num,), fig,
    )

    return ret_list


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
    """Basestation extension for running analysis and creating associated plots

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    if base_opts is None:
        base_opts = BaseOpts.BaseOptions(sys.argv, "g", usage="%prog [Options] ")
    BaseLogger("MakePlot2", base_opts)  # initializes BaseLog

    args = base_opts.get_args()  # positional argument

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    log_info(f"other_files {processed_file_names}")
    Utils.check_versions()

    plot_conf = Conf.conf(PlotUtils.make_plot_section, PlotUtils.make_plot_default_dict)
    if plot_conf.parse_conf_file(base_opts.config_file_name) > 2:
        log_error(
            f"Count not process {base_opts.config_file_name} - continuing with defaults"
        )
    plot_conf.dump_conf_vars()

    if plot_conf.plot_directory is None and base_opts.mission_dir is not None:
        plot_conf.plot_directory = os.path.join(base_opts.mission_dir, "plots")

    if sg_calib_file_name is None and base_opts.mission_dir is not None:
        sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")

    profile_file_names = []
    if not base_opts.mission_dir and len(args) == 1:
        profile_file_names = [os.path.expanduser(args[0])]
        if plot_conf.plot_directory is None:
            plot_conf.plot_directory = os.path.split(
                os.path.split(profile_file_names[0])[0]
            )[0]
        if sg_calib_file_name is None:
            sg_calib_file_name = os.path.join(
                plot_conf.plot_directory, "sg_calib_constants.m"
            )
    elif processed_file_names is not None:
        for ff in processed_file_names:
            if ff.endswith(".profile"):
                # Only the down casts are good at the moment
                if os.path.split(ff)[1][10:11] == "a":
                    profile_file_names.append(ff)

    if profile_file_names:
        if not os.path.exists(plot_conf.plot_directory):
            try:
                os.mkdir(plot_conf.plot_directory)
            except:
                log_error(f"Could not create {plot_conf.plot_directory}", "exc")
                log_info("Bailing out")
                return 1

        if not os.path.exists(plot_conf.plot_directory):
            try:
                os.mkdir(plot_conf.plot_directory)
                # Ensure that MoveData can move it as pilot if not run as the glider account
                os.chmod(
                    plot_conf.plot_directory,
                    stat.S_IRUSR
                    | stat.S_IWUSR
                    | stat.S_IXUSR
                    | stat.S_IRGRP
                    | stat.S_IXGRP
                    | stat.S_IWGRP
                    | stat.S_IROTH
                    | stat.S_IXOTH,
                )
            except:
                log_error(f"Could not create {plot_conf.plot_directory}", "exc")
                log_info("Bailing out")
                return 1

        for profile_file_name in profile_file_names:
            log_info(f"Processing {profile_file_name}")
            dive_num = int(os.path.split(profile_file_name)[1][6:10])
            try:
                plots = plot_ts_profile(profile_file_name, dive_num, plot_conf)
                if processed_other_files is not None and plots is not None:
                    for p in plots:
                        processed_other_files.append(p)

            except KeyboardInterrupt:
                log_error("Interupted by operator")
                break
            except:
                log_error(
                    "Error in plotting vertical velocity for %s - skipping"
                    % profile_file_name,
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
        if "--profile" in sys.argv:
            sys.argv.remove("--profile")
            profile_file_name = (
                os.path.splitext(os.path.split(sys.argv[0])[1])[0]
                + "_"
                + Utils.ensure_basename(
                    time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                + ".cprof"
            )
            # Generate line timings
            retval = cProfile.run("main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats("time", "calls")
            stats.print_stats()
        else:
            retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
