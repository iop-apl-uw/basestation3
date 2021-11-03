#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2012, 2016, 2019, 2020, 2021 by University of Washington.  All rights reserved.
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

"""Routines for creating mission profile from a Seaglider's dive profiles
"""

import cProfile
import os
import pstats
import sys
import time

import Utils
import BaseOpts
from BaseLog import BaseLogger, log_info, log_error, log_warning, log_critical
import MakeDiveProfiles
import Sensors
import BaseNetCDF


def main():
    """Command line driver for creating mission profiles from single dive netCDF files

    All netCDF files of the form pXXXYYYY.nc (where XXX is the glider ID and
    YYYY is the dive number) from the mission directory are processed to create
    the mission profile.  The name of the profile may be optionally specified on
    the command line as a fully qualified path.  If no output file is specified,
    the output file is created in the mission directory with a standard name of
    the form:

        sgXXX_(mission_title)_BINWIDTHm_WHICHHALF_profile.nc

    where XXX is the glider id and (mission_title) is the is the contents of the
    mission_title field in the sg_calib_contants.m file, also located in the
    specified directory, BINWIDTH is the specified bin width in meters and
    WHICHHALF refers to which of the dive half profiles are included in each
    profile up, down, up_and_down (treated as seperate profiles) or combine
    (combine the down and up halfs)

    Returns:
        0 - success
        1 - failure

    Raises:
        None - all exceptions are caught and logged
    """
    base_opts = BaseOpts.BaseOptions(
        "Command line driver for creating mission profiles from single dive netCDF files"
    )
    BaseLogger(base_opts)  # initializes BaseLog

    # Reset priority
    if base_opts.nice:
        try:
            os.nice(base_opts.nice)
        except:
            log_error("Setting nice to %d failed" % base_opts.nice)

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    # logger_init(init_dict)

    # Initialze the netCDF tables
    BaseNetCDF.init_tables(init_dict)

    # Collect up the possible files
    dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)

    (ret_val, _) = MakeDiveProfiles.make_mission_profile(dive_nc_file_names, base_opts)

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
