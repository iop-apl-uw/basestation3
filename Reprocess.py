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

"""
Rebuilds per-dive nc files from log and eng files (no comm.log or dat/asc processing)
"""

import cProfile
import glob
import os
import pdb
import pstats
import shutil
import sys
import time
import traceback

import BaseDB
import BaseDotFiles
import BaseNetCDF
import BaseOpts
import BaseOptsType
import BasePlot
import FileMgr
import FlightModel
import MakeDiveProfiles
import MakeKML
import MakeMissionProfile
import MakeMissionTimeSeries
import PlotUtils
import QC
import Sensors
import TraceArray
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)
from CalibConst import getSGCalibrationConstants

DEBUG_PDB = False


def main(cmdline_args: list[str] = sys.argv[1:]):
    """Command line driver for reprocessing per-dive and other nc files

    Returns:
        0 - success
        1 - failure
    """
    # These functions reset large blocks of global variables being used in other modules that
    # assume an initial value on first load, then are updated throughout the run.  The call
    # here sets back to the initial state to handle multiple runs under pytest
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    FlightModel.set_globals()

    base_opts = BaseOpts.BaseOptions(
        "Command line driver for reprocessing per-dive and other nc files",
        additional_arguments={
            "dive_specs": BaseOptsType.options_t(
                "",
                ("Reprocess",),
                ("dive_specs",),
                str,
                {
                    "help": "dive numbers to reprocess - either single dive nums or a range in the form X:Y",
                    "nargs": "*",
                },
            ),
            "called_from_fm": BaseOptsType.options_t(
                False,
                ("Reprocess",),
                ("--called_from_fm",),
                bool,
                {
                    "help": "Indicates the caller was FlightModel.py",
                    "action": "store_true",
                },
            ),
        },
        cmdline_args=cmdline_args,
    )

    BaseLogger(base_opts, include_time=True)  # initializes BaseLog

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    Utils.check_versions()

    # Reset priority
    if base_opts.nice:
        try:
            os.nice(base_opts.nice)
        except Exception:
            log_error("Setting nice to %d failed" % base_opts.nice)

    ret_val = 0

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if base_opts.mission_dir:
        base_path = os.path.expanduser(base_opts.mission_dir)
    else:
        log_error('You must specify --mission_dir"')
        return 1

    full_dive_list = []  # all available dives we have data files for
    dive_list = []  # dives we want to MDP
    all_dive_nc_file_names = []  # all available nc files
    dive_nc_file_names = []  # those we actually MDPd

    if os.path.isdir(base_path):
        # Include only valid dive files
        glob_expr = (
            "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].log",
            "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].eng",
            "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].nc",
            # "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].nc.gz"
        )
        for g in glob_expr:
            nc_match = g.find(".nc") > 0
            for match in glob.glob(os.path.join(base_path, g)):
                log_debug(f"Found dive file {match}")
                if nc_match:
                    all_dive_nc_file_names.append(match)
                # match = match.replace('.nc.gz', '.nc')
                head, _ = os.path.splitext(os.path.abspath(match))
                full_dive_list.append(head)

            full_dive_list = sorted(Utils.unique(full_dive_list))

        if len(base_opts.dive_specs):
            expanded_dive_nums = []
            for dive_num in base_opts.dive_specs:
                strs = dive_num.split(":", 1)
                if len(strs) == 2:
                    expanded_dive_nums.extend(
                        list(range(int(strs[0]), int(strs[1]) + 1))
                    )
                else:
                    expanded_dive_nums.append(int(dive_num))

            for dive_num in expanded_dive_nums:
                # Include only valid dive files
                glob_expr = (
                    "p[0-9][0-9][0-9]%04d.log" % dive_num,
                    "p[0-9][0-9][0-9]%04d.eng" % dive_num,
                    "p[0-9][0-9][0-9]%04d.nc" % dive_num,
                    # "p*%s.nc.gz" % dive_num,
                )
                for g in glob_expr:
                    for match in glob.glob(os.path.join(base_path, g)):
                        log_debug(f"Found dive file {match}")
                        # match = match.replace('.nc.gz', '.nc')
                        head, _ = os.path.splitext(os.path.abspath(match))
                        dive_list.append(head)
                dive_list = sorted(Utils.unique(dive_list))
            log_info(f"Reprocessing dives {dive_list}")
        else:
            log_info(f"Making profiles for all dives in {base_path}")
            dive_list = full_dive_list
    else:
        log_error(f"Directory {base_path} does not exist -- exiting")

    sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")
    calib_consts = getSGCalibrationConstants(
        sg_calib_file_name, ignore_fm_tags=not base_opts.ignore_flight_model
    )
    if not calib_consts:
        log_warning(f"Could not process {sg_calib_file_name}")
        return 1

    try:
        instrument_id = int(calib_consts["id_str"])
    except Exception:
        # base_opts always supplies a default (0)
        instrument_id = int(base_opts.instrument_id)
    else:
        if not base_opts.instrument_id:
            base_opts.instrument_id = instrument_id
    if instrument_id == 0:
        log_warning("Unable to determine instrument id; assuming 0")

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    FileMgr.logger_init(init_dict)

    # Any initialization from the extensions
    BaseDotFiles.process_extensions(("init_extension",), base_opts, init_dict=init_dict)

    # Initialze the netCDF tables
    BaseNetCDF.init_tables(init_dict)

    # Find any associated logger eng files for each dive in dive_list
    logger_eng_files = FileMgr.find_dive_logger_eng_files(
        dive_list, base_opts, instrument_id, init_dict
    )

    if (
        base_opts.backup_flight
        and not base_opts.skip_flight_model
        and not base_opts.called_from_fm
    ):
        flight_dir = os.path.join(base_opts.mission_dir, "flight")
        flight_dir_backup = os.path.join(
            base_opts.mission_dir, f"flight_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        if os.path.exists(flight_dir):
            log_info(f"Backing up {flight_dir} to {flight_dir_backup}")
            try:
                shutil.move(flight_dir, flight_dir_backup)
            except Exception:
                log_error(
                    "Failed to move %s to %s - profiles will use existing flight model data"
                    % (flight_dir, flight_dir_backup),
                    "exc",
                )

    # Now, create the profiles
    dives_processed = []  # MDP succeeded
    dives_not_processed = []  # MDP failed
    nc_files_created = []

    for dive_path in dive_list:
        log_debug(f"Processing {dive_path}")
        head, _ = os.path.splitext(os.path.abspath(dive_path))
        if base_opts.target_dir:
            _, base = os.path.split(os.path.abspath(dive_path))
            outhead = os.path.join(base_opts.target_dir, base)
        else:
            outhead = head

        log_info(f"Head = {head}")

        eng_file_name = head + ".eng"
        log_file_name = head + ".log"
        dive_num = FileMgr.get_dive(eng_file_name)

        base_opts.make_dive_profiles = True
        nc_dive_file_name = outhead + ".nc"

        sg_calib_file_name, _ = os.path.split(os.path.abspath(dive_path))
        sg_calib_file_name = os.path.join(sg_calib_file_name, "sg_calib_constants.m")

        dive_num = FileMgr.get_dive(eng_file_name)
        log_info("Dive number = %d" % dive_num)
        log_debug(f"logger_eng_files = {logger_eng_files[dive_path]}")

        try:
            (temp_ret_val, nc_file_created) = MakeDiveProfiles.make_dive_profile(
                base_opts.force,
                dive_num,
                eng_file_name,
                log_file_name,
                sg_calib_file_name,
                base_opts,
                nc_dive_file_name,
                logger_eng_files=logger_eng_files[dive_path],
            )
        except KeyboardInterrupt:
            log_info("Interrupted by user - bailing out")
            ret_val = 1
            break
        except Exception:
            log_error("Error processing dive %d - skipping" % dive_num, "exc")
            temp_ret_val = 1

        TraceArray.trace_results_stop()  # Just in case we bailed out...no harm if closed
        QC.qc_log_stop()
        # Even if the processing failed, we may get a netcdf files out
        if nc_file_created:
            nc_files_created.append(nc_file_created)
        if temp_ret_val == 1:
            ret_val = 1
            dives_not_processed.append(dive_num)
        elif temp_ret_val == 2:
            log_info("Skipped processing dive %d" % dive_num)
        else:
            dives_processed.append(dive_num)
            # If MDP does nothing (success w/o force option for example), it returns None
            # - don't add to list
            if nc_file_created:
                dive_nc_file_names.append(nc_file_created)
                if not base_opts.called_from_fm:
                    BaseDB.loadDB(base_opts, nc_file_created, run_dive_plots=False)

        del temp_ret_val

    log_info(f"Dives processed = {dives_processed}")
    log_info(f"Dives failed to process = {dives_not_processed}")

    if not base_opts.called_from_fm:
        # Now update other related files for each file we processed
        dive_nc_file_names = sorted(Utils.unique(dive_nc_file_names))

        # Now update all composite files using all available nc files
        all_dive_nc_file_names.extend(dive_nc_file_names)
        all_dive_nc_file_names = sorted(Utils.unique(all_dive_nc_file_names))
        if len(all_dive_nc_file_names):
            if not base_opts.skip_flight_model:
                flight_t0 = time.time()
                log_info(
                    f"Started FLIGHT processing {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(flight_t0))}"
                )
                fm_nc_files_created = []
                try:
                    FlightModel.main(base_opts, sg_calib_file_name, fm_nc_files_created)
                except Exception:
                    log_error("Flight model failed", "exc")
                    if DEBUG_PDB:
                        _, _, tb = sys.exc_info()
                        traceback.print_exc()
                        pdb.post_mortem(tb)
                else:
                    fm_nc_files_created = list(set(fm_nc_files_created))
                    log_info(f"FM files updated {fm_nc_files_created}")
                    nc_files_created = list(set(nc_files_created + fm_nc_files_created))
                    del fm_nc_files_created
                    if not base_opts.called_from_fm:
                        for ncf in nc_files_created:
                            BaseDB.loadDB(base_opts, ncf, run_dive_plots=False)
                    all_dive_nc_file_names.extend(nc_files_created)
                    all_dive_nc_file_names = sorted(
                        Utils.unique(all_dive_nc_file_names)
                    )
                    dive_nc_file_names.extend(nc_files_created)
                    dive_nc_file_names = sorted(Utils.unique(dive_nc_file_names))
                flight_tend = time.time()
                log_info(
                    f"Finished FLIGHT processing {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(flight_tend))} took {flight_tend - flight_t0:.2f} secs"
                )
            else:
                log_info(
                    "Skipping FLIGHT processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )

            if base_opts.reprocess_dive_extensions:
                BaseDotFiles.process_extensions(
                    ("dive",),
                    base_opts,
                    sg_calib_file_name=sg_calib_file_name,
                    dive_nc_file_names=all_dive_nc_file_names,
                    nc_files_created=nc_files_created,
                    # processed_other_files=processed_other_files,  # Output list for extension created files
                    # known_mailer_tags=known_mailer_tags,
                    # known_ftp_tags=known_ftp_tags,
                    # processed_file_names=processed_file_names,
                )

            if base_opts.make_mission_profile:
                log_info(
                    "Started MMP processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                MakeMissionProfile.make_mission_profile(
                    all_dive_nc_file_names, base_opts
                )
                log_info(
                    "Finished MMP processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
            else:
                log_info(
                    "Skipping MMP processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )

            if base_opts.make_mission_timeseries:
                log_info(
                    "Started MMT processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                MakeMissionTimeSeries.make_mission_timeseries(
                    all_dive_nc_file_names, base_opts
                )
                log_info(
                    "Finished MMT processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
            else:
                log_info(
                    "Skipping MMT processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )

            if not base_opts.skip_kml:
                log_info(
                    "Started KML processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                MakeKML.main(base_opts, calib_consts, [])
                log_info(
                    "Finished KML processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
            else:
                log_info(
                    "Skipping KML processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )

            if base_opts.reprocess_mission_extensions:
                BaseDotFiles.process_extensions(
                    ("missionearly",),
                    base_opts,
                    sg_calib_file_name=sg_calib_file_name,
                    dive_nc_file_names=all_dive_nc_file_names,
                    nc_files_created=nc_files_created,
                    # processed_other_files=processed_other_files,  # Output list for extension created files
                    # known_mailer_tags=known_mailer_tags,
                    # known_ftp_tags=known_ftp_tags,
                    # processed_file_names=processed_file_names,
                )

            if base_opts.reprocess_plots:
                log_info(
                    "Started PLOT processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                if PlotUtils.setup_plot_directory(base_opts):
                    log_error(
                        "Failed to setup plot directory - not plots being generated"
                    )

                plot_dict = BasePlot.get_dive_plots(base_opts)
                BasePlot.plot_dives(base_opts, plot_dict, dive_nc_file_names)
                mission_str = BasePlot.get_mission_str(base_opts, calib_consts)
                plot_dict = BasePlot.get_mission_plots(base_opts)
                BasePlot.plot_mission(base_opts, plot_dict, mission_str)

                log_info(
                    "Finished PLOT processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
            else:
                log_info(
                    "Skipping PLOT processing "
                    + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )

            if base_opts.reprocess_mission_extensions:
                BaseDotFiles.process_extensions(
                    ("global", "mission"),
                    base_opts,
                    sg_calib_file_name=sg_calib_file_name,
                    dive_nc_file_names=all_dive_nc_file_names,
                    nc_files_created=nc_files_created,
                    # processed_other_files=processed_other_files,  # Output list for extension created files
                    # known_mailer_tags=known_mailer_tags,
                    # known_ftp_tags=known_ftp_tags,
                    # processed_file_names=processed_file_names,
                )

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    return ret_val


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove("--profile")
            profile_filename = (
                os.path.splitext(os.path.split(sys.argv[0])[1])[0]
                + "_"
                + Utils.ensure_basename(
                    time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                + ".cprof"
            )
            # Generate line timings
            retval = cProfile.run("main()", filename=profile_filename)
            stats = pstats.Stats(profile_filename)
            stats.sort_stats("time", "calls")
            stats.print_stats()
        else:
            retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
