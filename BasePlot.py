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
import cProfile
import os
import pdb
import pstats
import stat
import sys
import time
import traceback
import warnings

import plotly
import numpy as np

import BaseOpts
import MakeDiveProfiles
import Plotting
import Utils

from BaseLog import BaseLogger, log_error, log_info, log_critical

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
            try:
                fig_list, file_list = plot_func(base_opts, dive_nc_file_name)
            except:
                log_error(f"{plot_name} failed {dive_nc_file_name}", "exc")
            else:
                for figure in fig_list:
                    figs.append(figure)
                for file_name in file_list:
                    output_files.append(file_name)
    return (figs, output_files)


def plot_mission(
    base_opts: BaseOpts.BaseOptions, mission_plot_dict: dict
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
        try:
            fig_list, file_list = plot_func(base_opts)
        except:
            log_error(f"{plot_name} failed", "exc")
        else:
            for figure in fig_list:
                figs.append(figure)
            for file_name in file_list:
                output_files.append(file_name)
    return (figs, output_files)


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

    dive_plot_list = Plotting.dive_plot_funcs.keys()
    mission_plot_list = Plotting.mission_plot_funcs.keys()

    base_opts = BaseOpts.BaseOptions(
        "Basestation CLI for creating Seaglider plots",
        additional_arguments={
            # CONSIDER: this might be best as an option in BaseOpts so Base.py can pick it up
            "dive_plots": BaseOpts.options_t(
                dive_plot_list,
                ("BasePlot",),
                ("--dive_plots",),
                str,
                {
                    "help": "Which dive plots to produce",
                    "section": "baseplot",
                    "choices": list(Plotting.dive_plot_funcs.keys()),
                    # "option_group": "plotting",
                    "subparsers": ("plot_dive",),
                },
            ),
            "netcdf_files": BaseOpts.options_t(
                None,
                ("BasePlot",),
                ("netcdf_files",),
                str,
                {
                    "help": "List of per-dive netcdf files to process (all in mission_dir)",
                    "nargs": "*",
                    # "option_group": "plotting",
                    "subparsers": ("plot_dive",),
                },
            ),
            # CONSIDER: this might be best as an option in BaseOpts so Base.py can pick it up
            "mission_plots": BaseOpts.options_t(
                mission_plot_list,
                ("BasePlot",),
                ("--mission_plots",),
                str,
                {
                    "help": "Which mission plots to produce",
                    "section": "baseplot",
                    "choices": list(Plotting.mission_plot_funcs.keys()),
                    # "option_group": "plotting",
                    "subparsers": ("plot_mission",),
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

    if base_opts.plot_directory is None:
        base_opts.plot_directory = os.path.join(base_opts.mission_dir, "plots")

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
        except:
            log_error(f"Could not create {base_opts.plot_directory}", "exc")
            log_info("Bailing out")
            return 1

    old_err = np.geterr()
    np.seterr(invalid="warn")

    if base_opts.subparser_name == "plot_dive":
        if not base_opts.netcdf_files:
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
        else:
            dive_nc_file_names = []
            for ncf_file_name in base_opts.netcdf_files:
                dive_nc_file_names.append(
                    os.path.join(base_opts.mission_dir, ncf_file_name)
                )
        plot_dict = get_dive_plots(base_opts)
        plot_dives(base_opts, plot_dict, dive_nc_file_names)
    elif base_opts.subparser_name == "plot_mission":
        plot_dict = get_mission_plots(base_opts)
        plot_mission(base_opts, plot_dict)
    else:
        log_error("Internal error - unknown sub-parser")

    # for dive_nc_file_name in dive_nc_file_names:
    #     log_info(f"Processing {dive_nc_file_name}")

    #     try:
    #         dive_nc_file = Utils.open_netcdf_file(dive_nc_file_name, "r")
    #     except:
    #         log_error(f"Unable to open {dive_nc_file_name}", "exc")
    #         log_info("Continuing processing...")
    #         continue

    #     if "processing_error" in dive_nc_file.variables:
    #         log_warning(f"{dive_nc_file_name} is marked as having a processing error")

    #     if "skipped_profile" in dive_nc_file.variables:
    #         log_warning(f"{dive_nc_file_name} is marked as a skipped_profile")

    #     try:
    #         dive_num = dive_nc_file.dive_number
    #     except (AttributeError, KeyError):
    #         log_error(f"No dive_number attribute in {dive_nc_file_name} - skipping")
    #         continue

    #     if (
    #         "gc_st_secs" in dive_nc_file.variables
    #         and "diveplot" in base_opts.makeplot4_plots
    #     ):
    #         try:
    #             figs, plots = plot_diveplot(
    #                 dive_nc_file,
    #                 dive_num,
    #                 base_opts,
    #             )
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)

    #         except KeyboardInterrupt:
    #             log_error("Interupted by operator")
    #             break
    #         except:
    #             if DEBUG_PDB:
    #                 _, _, tb = sys.exc_info()
    #                 traceback.print_exc()
    #                 pdb.post_mortem(tb)
    #             log_error(
    #                 f"Error in plotting diveplot for {dive_nc_file_name} - skipping",
    #                 "exc",
    #             )

    #     # try:
    #     #     head,tail = os.path.split(dive_nc_file_name)
    #     #     qc_file = "%s/p%03d%04d.pckl" % (head, dive_nc_file.glider, dive_nc_file.variables['trajectory'][:][0])
    #     #     plots = plot_qc(dive_nc_file, dive_num, base_opts, qc_file)
    #     #     if(processed_other_files is not None and plots is not None):
    #     #         for p in plots:
    #     #             processed_other_files.append(p)

    #     # except KeyboardInterrupt:
    #     #     log_error('Interupted by operator')
    #     #     break
    #     # except:
    #     # if DEBUG_PDB:
    #     #         _, _, tb = sys.exc_info()
    #     #         traceback.print_exc()
    #     #         pdb.post_mortem(tb)

    #     #     log_error("Error in plotting qc for %s - skipping" % dive_nc_file_name, 'exc')

    #     if (
    #         "auxCompass_time" in dive_nc_file.variables
    #         and "compass_compare" in base_opts.makeplot4_plots
    #     ):
    #         try:
    #             figs, plots = plot_compass_compare(
    #                 dive_nc_file,
    #                 dive_num,
    #                 "auxCompass",
    #                 "auxCompass_time",
    #                 "auxCompass_hdg",
    #                 "auxCompass_pit",
    #                 "auxCompass_rol",
    #                 "auxCompass_press",
    #                 base_opts,
    #             )
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)

    #         except KeyboardInterrupt:
    #             log_error("Interupted by operator")
    #             break
    #         except:
    #             if DEBUG_PDB:
    #                 _, _, tb = sys.exc_info()
    #                 traceback.print_exc()
    #                 pdb.post_mortem(tb)
    #             log_error(
    #                 "Error in plotting plot_compass_compare for auxCompass for %s - skipping"
    #                 % dive_nc_file_name,
    #                 "exc",
    #             )

    #     if (
    #         "auxB_time" in dive_nc_file.variables
    #         and "compass_compare" in base_opts.makeplot4_plots
    #     ):
    #         try:
    #             figs, plots = plot_compass_compare(
    #                 dive_nc_file,
    #                 dive_num,
    #                 "auxB",
    #                 "auxB_time",
    #                 "auxB_hdg",
    #                 "auxB_pit",
    #                 "auxB_rol",
    #                 "auxB_press",
    #                 base_opts,
    #             )
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)
    #         except KeyboardInterrupt:
    #             log_error("Interupted by operator")
    #             break
    #         except:
    #             if DEBUG_PDB:
    #                 _, _, tb = sys.exc_info()
    #                 traceback.print_exc()
    #                 pdb.post_mortem(tb)
    #             log_error(
    #                 "Error in plotting plot_compass_compare for auxB for %s - skipping"
    #                 % dive_nc_file_name,
    #                 "exc",
    #             )

    #     if (
    #         "cp_time" in dive_nc_file.variables
    #         and "compass_compare" in base_opts.makeplot4_plots
    #     ):
    #         try:
    #             figs, plots = plot_compass_compare(
    #                 dive_nc_file,
    #                 dive_num,
    #                 "ADCPCompass",
    #                 "cp_time",
    #                 "cp_heading",
    #                 "cp_pitch",
    #                 "cp_roll",
    #                 "cp_pressure",
    #                 base_opts,
    #             )
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #         except KeyboardInterrupt:
    #             log_error("Interupted by operator")
    #             break
    #         except:
    #             if DEBUG_PDB:
    #                 _, _, tb = sys.exc_info()
    #                 traceback.print_exc()
    #                 pdb.post_mortem(tb)
    #             log_error(
    #                 "Error in plotting plot_compass_compare for ADCP Compass for %s - skipping"
    #                 % dive_nc_file_name,
    #                 "exc",
    #             )

    #     if (
    #         "ad2cp_time" in dive_nc_file.variables
    #         and "compass_compare" in base_opts.makeplot4_plots
    #     ):
    #         try:
    #             figs, plots = plot_compass_compare(
    #                 dive_nc_file,
    #                 dive_num,
    #                 "ADCPCompass",
    #                 "ad2cp_time",
    #                 "ad2cp_heading",
    #                 "ad2cp_pitch",
    #                 "ad2cp_roll",
    #                 "ad2cp_pressure",
    #                 base_opts,
    #                 flip_pitch=True,
    #                 flip_roll=True,
    #                 flip_heading=True,
    #             )
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)
    #         except KeyboardInterrupt:
    #             log_error("Interupted by operator")
    #             break
    #         except:
    #             if DEBUG_PDB:
    #                 _, _, tb = sys.exc_info()
    #                 traceback.print_exc()
    #                 pdb.post_mortem(tb)
    #             log_error(
    #                 "Error in plotting plot_compass_compare for ADCP Compass for %s - skipping"
    #                 % dive_nc_file_name,
    #                 "exc",
    #             )

    #     ### COG
    #     try:
    #         if (
    #             "latitude" in dive_nc_file.variables
    #             and "longitude" in dive_nc_file.variables
    #             and "log_gps_lat" in dive_nc_file.variables
    #             and "COG" in base_opts.makeplot4_plots
    #         ):
    #             figs, plots = plot_COG(dive_nc_file, dive_num, base_opts)
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)
    #     except KeyboardInterrupt:
    #         log_error("Interupted by operator")
    #         break
    #     except:
    #         if DEBUG_PDB:
    #             _, _, tb = sys.exc_info()
    #             traceback.print_exc()
    #             pdb.post_mortem(tb)
    #         log_error(
    #             f"Error in plotting COG for {dive_nc_file_name} - skipping", "exc"
    #         )

    #     ### Displacement
    #     try:
    #         if (
    #             "north_displacement" in dive_nc_file.variables
    #             and "east_displacement" in dive_nc_file.variables
    #             and "CTW" in base_opts.makeplot4_plots
    #         ):
    #             figs, plots = plot_CTW(dive_nc_file, dive_num, base_opts)
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)
    #     except KeyboardInterrupt:
    #         log_error("Interupted by operator")
    #         break
    #     except:
    #         if DEBUG_PDB:
    #             _, _, tb = sys.exc_info()
    #             traceback.print_exc()
    #             pdb.post_mortem(tb)
    #         log_error(
    #             f"Error in plotting COG for {dive_nc_file_name} - skipping", "exc"
    #         )

    #     ### CTD
    #     try:
    #         if (
    #             "temperature" in dive_nc_file.variables
    #             and "ctd_data" in base_opts.makeplot4_plots
    #         ):
    #             figs, plots = plot_ctd_data(dive_nc_file, dive_num, base_opts)
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)
    #     except KeyboardInterrupt:
    #         log_error("Interupted by operator")
    #         break
    #     except:
    #         if DEBUG_PDB:
    #             _, _, tb = sys.exc_info()
    #             traceback.print_exc()
    #             pdb.post_mortem(tb)
    #         log_error(
    #             f"Error in plotting ctd for {dive_nc_file_name} - skipping", "exc"
    #         )

    #     ### TS
    #     if "ts" in base_opts.makeplot4_plots:
    #         try:
    #             # TODO Finish and make work for truck as well as scicon
    #             fig, plots = plot_ts(dive_nc_file, dive_num, base_opts)
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)

    #         except KeyboardInterrupt:
    #             log_error("Interupted by operator")
    #             break
    #         except:
    #             if DEBUG_PDB:
    #                 _, _, tb = sys.exc_info()
    #                 traceback.print_exc()
    #                 pdb.post_mortem(tb)
    #             log_error(
    #                 f"Error in plotting TS for {dive_nc_file_name} - skipping", "exc"
    #             )

    #     ### TMicro
    #     try:
    #         tmicl_present = False
    #         for v in dive_nc_file.variables:
    #             if "tmicl_" in v:
    #                 tmicl_present = True
    #         if tmicl_present and "tmicl_data" in base_opts.makeplot4_plots:
    #             figs, plots = plot_tmicl_data(dive_nc_file, dive_num, base_opts)
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)

    #     except KeyboardInterrupt:
    #         log_error("Interupted by operator")
    #         break
    #     except:
    #         if DEBUG_PDB:
    #             _, _, tb = sys.exc_info()
    #             traceback.print_exc()
    #             pdb.post_mortem(tb)

    #         log_error(
    #             "Error in ploting tmicro for %s - skipping" % dive_nc_file_name, "exc"
    #         )

    #     ### PMAR
    #     try:
    #         pmar_present = False
    #         for v in dive_nc_file.variables:
    #             if "pmar_" in v:
    #                 pmar_present = True
    #         if pmar_present and "pmar_data" in base_opts.makeplot4_plots:
    #             figs, plots = plot_pmar_data(dive_nc_file, dive_num, base_opts)
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)

    #     except KeyboardInterrupt:
    #         log_error("Interupted by operator")
    #         break
    #     except:
    #         if DEBUG_PDB:
    #             _, _, tb = sys.exc_info()
    #             traceback.print_exc()
    #             pdb.post_mortem(tb)
    #         log_error(
    #             "Error in plottting pmar for %s - skipping" % dive_nc_file_name, "exc"
    #         )

    #     ### Optode
    #     try:
    #         optode_type = None
    #         is_scicon = False
    #         if "aa4831_time" in dive_nc_file.variables:
    #             optode_type = "4831"
    #             is_scicon = True
    #         elif "aa4330_time" in dive_nc_file.variables:
    #             optode_type = "4330"
    #             is_scicon = True
    #         elif "aa3830_time" in dive_nc_file.variables:
    #             optode_type = "3830"
    #             is_scicon = True
    #         elif "aa4831" in "".join(dive_nc_file.variables):
    #             optode_type = "4831"
    #         elif "aa4330" in "".join(dive_nc_file.variables):
    #             optode_type = "4330"
    #         elif "aa3830" in "".join(dive_nc_file.variables):
    #             optode_type = "3830"
    #         if optode_type is not None and "optode_data" in base_opts.makeplot4_plots:
    #             log_debug("optode type = %s" % optode_type)
    #             figs, plots = plot_optode_data(
    #                 dive_nc_file,
    #                 dive_num,
    #                 base_opts,
    #                 optode_type,
    #                 scicon=is_scicon,
    #             )
    #             if processed_other_files is not None and plots is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)
    #     except KeyboardInterrupt:
    #         log_error("Interupted by operator")
    #         break
    #     except:
    #         if DEBUG_PDB:
    #             _, _, tb = sys.exc_info()
    #             traceback.print_exc()
    #             pdb.post_mortem(tb)

    #         log_error(
    #             "Error in plotting optode for %s - skipping" % dive_nc_file_name, "exc"
    #         )

    #     # try:
    #     #     # SBE43
    #     #     # TODO - Add truck support
    #     #     if('sbe43_time' in dive_nc_file.variables):
    #     #         plots = plot_sbe43_data(dive_nc_file, dive_num, base_opts, scicon=True)
    #     #         if(processed_other_files is not None and plots is not None):
    #     #             for p in plots:
    #     #                 processed_other_files.append(p)
    #     # except KeyboardInterrupt:
    #     #     log_error('Interupted by operator')
    #     #     break
    #     # except:
    #     # if DEBUG_PDB:
    #     #     _, _, tb = sys.exc_info()
    #     #     traceback.print_exc()
    #     #     pdb.post_mortem(tb)
    #     #     log_error("Error in plotting sbe43 for %s - skipping" % dive_nc_file_name, 'exc')

    #     ### Wetlabs
    #     try:
    #         # The plot routine currently handles only the canonical wlbb2fl instrument (red, blue, and chlorophyll)
    #         wetlabs_type = None
    #         is_scicon = False
    #         for typ in ("wlbb2fl", "wlbbfl2", "wlbb3", "wlfl3"):
    #             if "%s_time" % typ in dive_nc_file.variables:
    #                 wetlabs_type = typ
    #                 is_scicon = True
    #             elif typ in "".join(dive_nc_file.variables):
    #                 wetlabs_type = typ

    #             if wetlabs_type and "wetlabs_data" in base_opts.makeplot4_plots:
    #                 log_debug("wetlabs type = %s" % wetlabs_type)
    #                 figs, plots = plot_wetlabs_data(
    #                     dive_nc_file,
    #                     dive_num,
    #                     base_opts,
    #                     wetlabs_type,
    #                     scicon=is_scicon,
    #                 )
    #                 if processed_other_files is not None:
    #                     for p in plots:
    #                         processed_other_files.append(p)
    #                 if figures is not None and figs is not None:
    #                     for fig in figs:
    #                         figures.append(fig)
    #     except KeyboardInterrupt:
    #         log_error("Interupted by operator")
    #         break
    #     except:
    #         if DEBUG_PDB:
    #             _, _, tb = sys.exc_info()
    #             traceback.print_exc()
    #             pdb.post_mortem(tb)
    #         log_error(
    #             "Error in plotting wetlabs for %s - skipping" % dive_nc_file_name, "exc"
    #         )

    #     # try:
    #     #     # PAR
    #     #     # Add truck support
    #     #     if('qsp2150a_time' in dive_nc_file.variables):
    #     #         plots = plot_par_data(dive_nc_file, dive_num, base_opts, scicon=True)
    #     #         if(processed_other_files is not None):
    #     #             for p in plots:
    #     #                 processed_other_files.append(p)
    #     # except KeyboardInterrupt:
    #     #     log_error('Interupted by operator')
    #     #     break
    #     # except:
    #     # if DEBUG_PDB:
    #     #     _, _, tb = sys.exc_info()
    #     #     traceback.print_exc()
    #     #     pdb.post_mortem(tb)
    #     #     log_error("Error in plotting qsp2150a for %s - skipping" % dive_nc_file_name, 'exc')

    #     try:
    #         if ("ocr504i_time" in dive_nc_file.variables) or (
    #             "eng_ocr504i" in "".join(dive_nc_file.variables)
    #             and "ocr504i_data" in base_opts.makeplot4_plots
    #         ):
    #             figs, plots = plot_ocr504i_data(
    #                 dive_nc_file,
    #                 dive_num,
    #                 base_opts,
    #                 scicon=("ocr504i_time" in dive_nc_file.variables),
    #             )
    #             if processed_other_files is not None:
    #                 for p in plots:
    #                     processed_other_files.append(p)
    #             if figures is not None and figs is not None:
    #                 for fig in figs:
    #                     figures.append(fig)
    #     except KeyboardInterrupt:
    #         log_error("Interupted by operator")
    #         break
    #     except:
    #         if DEBUG_PDB:
    #             _, _, tb = sys.exc_info()
    #             traceback.print_exc()
    #             pdb.post_mortem(tb)
    #         log_error(
    #             "Error in plotting ocr504i for %s - skipping" % dive_nc_file_name, "exc"
    #         )

    #     dive_nc_file.close()

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
