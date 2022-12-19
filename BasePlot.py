#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2022 by University of Washington.  All rights reserved.
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
"""Routines for driving the individual plotting routines
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import cProfile
import os
import pdb
import pstats
import sys
import time
import typing
import traceback
import warnings

import plotly
import numpy as np

import BaseOpts
import CommLog
import MakeDiveProfiles
import Plotting
import PlotUtils
import Utils

from BaseLog import BaseLogger, log_error, log_info, log_critical, log_debug
from CalibConst import getSGCalibrationConstants

DEBUG_PDB = "darwin" in sys.platform


def get_dive_plots(base_opts: BaseOpts.BaseOptions) -> dict:
    """Loads up the dictionary of selected dive plots"""
    return {x: Plotting.dive_plot_funcs[x] for x in base_opts.dive_plots}


def get_mission_plots(base_opts: BaseOpts.BaseOptions) -> dict:
    """Loads up the dictionary of selected mission plots"""
    return {x: Plotting.mission_plot_funcs[x] for x in base_opts.mission_plots}


def plot_dives(
    base_opts: BaseOpts.BaseOptions, dive_plot_dict: dict, dive_nc_file_names: list
) -> tuple[list:list]:
    """
    Create per-dive related plots

    Input:
        base_opts - basestation options object
        dive_plot_dict - dictionary of plot names and functions to apply
        dive_nc_file_name - list of fully qualified pathnames to the dive ncfs
    Returns:
        tuple
            list of figures created

            list of filenames created
    """
    figs = []
    output_files = []
    for dive_nc_file_name in dive_nc_file_names:
        for plot_name, plot_func in dive_plot_dict.items():
            log_debug(f"Trying Dive Plot :{plot_name}")
            try:
                dive_ncf = Utils.open_netcdf_file(dive_nc_file_name)
                fig_list, file_list = plot_func(base_opts, dive_ncf)
            except:
                log_error(f"{plot_name} failed {dive_nc_file_name}", "exc")
            else:
                for figure in fig_list:
                    figs.append(figure)
                for file_name in file_list:
                    output_files.append(file_name)
    return (figs, output_files)


def plot_mission(
    base_opts: BaseOpts.BaseOptions, mission_plot_dict: dict, mission_str: list
) -> tuple[list:list]:
    """
    Create per-dive related plots

    Input:
        base_opts - basestation options object
        mission_plot_dict - dictionary of plot names and functions to apply
    Returns:
        tuple
            list of figures created
            list of filenames created
    """
    figs = []
    output_files = []
    for plot_name, plot_func in mission_plot_dict.items():
        log_debug(f"Trying Mission Plot :{plot_name}")
        try:
            fig_list, file_list = plot_func(base_opts, mission_str)
        except:
            log_error(f"{plot_name} failed", "exc")
        else:
            for figure in fig_list:
                figs.append(figure)
            for file_name in file_list:
                output_files.append(file_name)
    return (figs, output_files)


def get_mission_str(base_opts: BaseOpts.BaseOptions, calib_consts: dict) -> str:
    """Constructs a mission title string"""
    if not calib_consts:
        mission_title = "UNKNOWN"
    else:
        mission_title = Utils.ensure_basename(calib_consts["mission_title"])
    return f"SG{'%03d' % base_opts.instrument_id} {mission_title}"


def main():
    """Basestation CLI entry point for per-dive or whole mission plotting

    Returns:
        0 for success (although there may have been individual errors in
            file processing), unless return_base_opts is True, in which case
            the base_opts object is returned
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    base_opts = BaseOpts.BaseOptions(
        "Basestation CLI for creating Seaglider plots",
        additional_arguments={
            "netcdf_files": BaseOpts.options_t(
                None,
                ("BasePlot",),
                ("netcdf_files",),
                str,
                {
                    "help": "List of per-dive netcdf files to process (all in mission_dir)",
                    "nargs": "*",
                    "option_group": "plotting",
                },
            ),
        },
    )
    BaseLogger(base_opts)
    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    required_plotly_version = "4.9.0"
    if Utils.normalize_version(plotly.__version__) < Utils.normalize_version(
        required_plotly_version
    ):
        msg = "plotly %s or greater required (loaded %s)" % (
            required_plotly_version,
            plotly.__version__,
        )
        log_critical(msg)
        raise RuntimeError(msg)

    Utils.check_versions()

    if PlotUtils.setup_plot_directory(base_opts):
        return 1

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if not base_opts.instrument_id:
        (comm_log, _, _, _, _) = CommLog.process_comm_log(
            os.path.join(base_opts.mission_dir, "comm.log"),
            base_opts,
        )
        if comm_log:
            base_opts.instrument_id = comm_log.get_instrument_id()

    if not base_opts.instrument_id:
        _, tail = os.path.split(base_opts.mission_dir[:-1])
        if tail[-5:-3] != "sg":
            log_error("Can't figure out the instrument id - bailing out")
            return 1
        try:
            base_opts.instrument_id = int(tail[:-3])
        except:
            log_error("Can't figure out the instrument id - bailing out")
            return 1

    old_err = np.geterr()
    np.seterr(invalid="warn")

    for plot_type in base_opts.plot_types:
        if plot_type == "dives":
            if not base_opts.netcdf_files:
                dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(
                    base_opts
                )
            else:
                dive_nc_file_names = []
                for ncf_file_name in base_opts.netcdf_files:
                    dive_nc_file_names.append(
                        os.path.join(base_opts.mission_dir, ncf_file_name)
                    )
            plot_dict = get_dive_plots(base_opts)
            plot_dives(base_opts, plot_dict, dive_nc_file_names)
        elif plot_type == "mission":
            sg_calib_file_name = os.path.join(
                base_opts.mission_dir, "sg_calib_constants.m"
            )
            calib_consts = getSGCalibrationConstants(sg_calib_file_name)
            mission_str = get_mission_str(base_opts, calib_consts)
            plot_dict = get_mission_plots(base_opts)
            plot_mission(base_opts, plot_dict, mission_str)
        else:
            log_error(f"Internal error - unknown plot_type {plot_type}")

    np.seterr(**old_err)
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

    warnings.filterwarnings("error")

    try:
        if "--profile" in sys.argv:
            sys.argv.remove("--profile")
            profile_file_name = (
                os.path.splitext(os.path.split(sys.argv[0])[1])[0]
                + "_"
                + time.strftime(
                    "%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())
                ).replace(" ", "_")
                + ".prof"
            )
            # Generate line timings
            retval = cProfile.run("main()", profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.strip_dirs()
            stats.sort_stats("time", "calls")
            stats.sort_stats("cumulative")
            stats.print_stats()
        else:
            retval = main()
    except SystemExit:
        pass
    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting", "exc")

    sys.exit(retval)
