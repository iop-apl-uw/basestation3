#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2014, 2016, 2017, 2018, 2019, 2020, 2021, 2022 by University of Washington.  All rights reserved.
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

"""
Rebuilds per-dive nc files from log and eng files (no comm.log or dat/asc processing)
--make_mission_timeseries and --make_mission_profile flags also honored.
Building KML implied by --make_mission_timeseries or --make_mission_profile

python Reprocess.py --force -v --mission_dir <dir> [<dive numbers>]
where <dive_numbers> can be individual dive numbers, e.g., 45 66, etc.
or can be a range, e.g., 45:66, which will reprocess all the dives between 45 and 66 inclusively
These specifications can be mixed, e.g., 45 77 89:120 452
If no specification is given all the available dives are reprocessed
When building MMP, MMT, KML, etc. these are rebuild from all files
"""

import cProfile
import pstats
import glob
import os
import shutil
import sys
import time

# import NODC
from BaseLog import (
    BaseLogger,
    log_debug,
    log_info,
    log_error,
    log_warning,
    log_critical,
)
from CalibConst import getSGCalibrationConstants
import BaseNetCDF
import BaseOpts
import FileMgr
import FlightModel
import MakeDiveProfiles
import MakeKML
import MakePlot
import MakePlot2
import MakePlot3
import MakePlot4
import QC
import Sensors
import TraceArray
import Utils


def main():
    """Command line driver for reprocessing per-dive and other nc files

    usage: Reprocess.py [options] --mission_dir <mission_dir> [<dive_numbers>]
    where:
        --mission_dir   - The name of a directory containing the data files

    The following standard options are supported:
        --version             show program's version number and exit
        -h, --help            show this help message and exit
        --base_log=BASE_LOG   basestation log file, records all levels of notifications
        --nice=NICE           processing priority level (niceness)
        -v, --verbose         print status messages to stdout
        -q, --quiet           don't print status messages to stdout
        --debug               log/display debug messages
        -i INSTRUMENT_ID, --instrument_id=INSTRUMENT_ID
                              force instrument (glider) id
        --magcalfile=CALFILE  Reprocess compass headings using calfile (tcm2mat format)
        --gzip_netcdf         gzip netcdf files
        --make_mission_profile       Create the binned product from all dives
        --make_mission_timeseries    Create the composite product from all dives
        --reprocess_plots     Re-run MakePlot* extensions
        --reprocess_flight    Saves Flight directory off

    Note:
        sg_calib_constants must be in the same directory as the file(s) being processed

    Returns:
        0 - success
        1 - failure
    """
    base_opts = BaseOpts.BaseOptions(
        "Command line driver for reprocessing per-dive and other nc files",
        additional_arguments={
            "dive_specs": BaseOpts.options_t(
                None,
                ("Reprocess",),
                ("dive_specs",),
                str,
                {
                    "help": "dive numbers to reprocess - either single dive nums or a range in the form X:Y",
                    "nargs": "*",
                },
            ),
        },
    )

    BaseLogger(base_opts)  # initializes BaseLog

    Utils.check_versions()

    # Reset priority
    if base_opts.nice:
        try:
            os.nice(base_opts.nice)
        except:
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
            "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].nc"
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
    calib_consts = getSGCalibrationConstants(sg_calib_file_name)
    if not calib_consts:
        log_warning(f"Could not process {sg_calib_file_name}")
        return 1

    try:
        instrument_id = int(calib_consts["id_str"])
    except:
        # base_opts always supplies a default (0)
        instrument_id = int(base_opts.instrument_id)
    if instrument_id == 0:
        log_warning("Unable to determine instrument id; assuming 0")

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    FileMgr.logger_init(init_dict)

    # Initialze the netCDF tables
    BaseNetCDF.init_tables(init_dict)

    # Find any associated logger eng files for each dive in dive_list
    logger_eng_files = FileMgr.find_dive_logger_eng_files(
        dive_list, base_opts, instrument_id, init_dict
    )

    if base_opts.reprocess_flight:
        flight_dir = os.path.join(base_opts.mission_dir, "flight")
        flight_dir_backup = os.path.join(
            base_opts.mission_dir, f"flight_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        if os.path.exists(flight_dir):
            log_info(f"Backing up {flight_dir} to {flight_dir_backup}")
            try:
                shutil.move(flight_dir, flight_dir_backup)
            except:
                log_error(
                    "Failed to move %s to %s - profiles will use existing flight model data"
                    % (flight_dir, flight_dir_backup),
                    "exc",
                )

    # Now, create the profiles
    dives_processed = []  # MDP succeeded
    dives_not_processed = []  # MDP failed
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
            (temp_ret_val, _) = MakeDiveProfiles.make_dive_profile(
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
        except:
            log_error("Error processing dive %d - skipping" % dive_num, "exc")
            temp_ret_val = 1

        TraceArray.trace_results_stop()  # Just in case we bailed out...no harm if closed
        QC.qc_log_stop()
        if temp_ret_val == 1:
            ret_val = 1
            dives_not_processed.append(dive_num)
        elif temp_ret_val == 2:
            log_info("Skipped processing dive %d" % dive_num)
        else:
            dives_processed.append(dive_num)
        del temp_ret_val

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    log_info(f"Dives processed = {dives_processed}")
    log_info(f"Dives failed to process = {dives_not_processed}")

    # Now update other related files for each file we processed
    dive_nc_file_names = sorted(Utils.unique(dive_nc_file_names))

    # CONSIDER process .extensions here using something like:
    #
    # from Globals import known_mailer_tags, known_ftp_tags
    # process_extensions('.extensions', ["dive", "global", "mission"], base_opts, sg_calib_file_name, dive_nc_file_names,  \
    #                    dive_nc_file_names, [], Base.known_mailer_tags, Base.known_ftp_tags, None)
    #
    # This would replace the explicit calls to MakePlots

    # Now update all composite files using all available nc files
    all_dive_nc_file_names.extend(dive_nc_file_names)
    all_dive_nc_file_names = sorted(Utils.unique(all_dive_nc_file_names))
    if len(all_dive_nc_file_names):
        if base_opts.reprocess_flight:
            log_info(
                "Started FLIGHT processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
            FlightModel.main(
                instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names
            )
            log_info(
                "Finished FLIGHT processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
        else:
            log_info(
                "Skipping FLIGHT processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )

        if base_opts.make_mission_profile:
            log_info(
                "Started MMP processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
            MakeDiveProfiles.make_mission_profile(all_dive_nc_file_names, base_opts)
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
            MakeDiveProfiles.make_mission_timeseries(all_dive_nc_file_names, base_opts)
            log_info(
                "Finished MMT processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
        else:
            log_info(
                "Skipping MMT processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )

        if base_opts.make_mission_timeseries or base_opts.make_mission_profile:
            log_info(
                "Started KML processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
            MakeKML.main(
                instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names
            )
            log_info(
                "Finished KML processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
        else:
            log_info(
                "Skipping KML processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )

        if base_opts.reprocess_plots:
            log_info(
                "Started PLOT processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
            # MakePlot.main(
            #    instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names
            # )
            MakePlot2.main(
                instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names
            )
            MakePlot3.main(
                instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names
            )
            MakePlot4.main(
                instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names
            )

            log_info(
                "Finished PLOT processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
        else:
            log_info(
                "Skipping PLOT processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )

        # if process_NODC:
        #     log_info(
        #         "Started NODC processing "
        #         + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
        #     )
        #     NODC.process_nc_files(base_opts, all_dive_nc_file_names, enable_ftp=False)
        #     log_info(
        #         "Finished NODC processing "
        #         + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
        #     )
        # else:
        #     log_info(
        #         "Skipping NODC processing "
        #         + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
        #     )

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
