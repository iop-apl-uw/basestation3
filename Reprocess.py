#! /usr/bin/env python

## 
## Copyright (c) 2006-2014, 2016, 2017, 2018, 2019 by University of Washington.  All rights reserved.
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

# Rebuilds per-dive nc files from log and eng files (no comm.log or dat/asc processing)
# then builds aux, MMD, MMT, and KML files as directed by flags below

# python Reprocess.py --force -v --mission_dir <dir> [<dive numbers>]
# where <dive_numbers> can be individual dive numbers, e.g., 45 66, etc.
# or can be a range, e.g., 45:66, which will reprocess all the dives between 45 and 66 inclusively
# These specifications can be mixed, e.g., 45 77 89:120 452
# If no specification is given all the available dives are reprocessed
# When building MMP, MMT, KML, etc. these are rebuild from all files

# (re) generate dive nc files
process_MDP = True # make False if MDP succeeded before and you want to skip this step to debug a later step
process_aux = False # if True, also obeys --make_dive_pro, --make_dive_kkyy, --make_dive_bpo

# (re) generate from dive nc files
process_MMP = False # can take a lot of memory for many dives (--make_mission_profile)
process_MMT = False # can take a lot of memory for many dives (--make_mission_timeseries)
process_KML = False 
process_PLOTS = False
process_NODC = False # avoid sending to NODC
process_FLIGHT = False

import os
import sys
import traceback
import string
import time
import re
import shutil
from numpy import *
import math
import BaseOpts
from BaseLog import *
import GPS
from CalibConst import getSGCalibrationConstants
from Utils import *
import pdb
import Sensors
from BaseNetCDF import *
from Enum import *
from FileMgr import *
import glob
import MakeDiveProfiles
try:
    import MakeKML
    KML_available = True
except ImportError:
    KML_available = False # KML not available

try:
    import MakePlot
    PLOTS_available = True
except ImportError:
    PLOTS_available = False
    
try:
    import FlightModel
    FLIGHT_available = True
except ImportError:
    FLIGHT_available = False
    
import NODC

def dump_data_netcdf():
    pass

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
        --institution=INSTITUTION
                              Institution field for the netCDF files
        --disclaimer=DISCLAIMER
                              Disclaimer field for the netCDF files
        -i INSTRUMENT_ID, --instrument_id=INSTRUMENT_ID
                              force instrument (glider) id
        --magcalfile=CALFILE  Reprocess compass headings using calfile (tcm2mat format)
        --gzip_netcdf         gzip netcdf files
        --make_dive_pro       Create the dive profile in text format
        --make_dive_bpo       Create the dive binned profile in text format
        --make_dive_kkyy      Create the dive kkyy output files
        --make_mission_profile       Create the binned product from all dives
        --make_mission_timeseries    Create the composite product from all dives
              
    Note:
        sg_calib_constants must be in the same directory as the file(s) being processed

    Returns:
        0 - success
        1 - failure
    """
    global process_MDP
    global process_aux

    global process_MMP
    global process_MMT
    global process_KML
    global process_PLOTS
    global process_FLIGHT
    global process_NODC

    base_opts = BaseOpts.BaseOptions(sys.argv, 'd',
                                     usage="%prog [Options] [basefile]")
    
    BaseLogger("Reprocess", base_opts) # initializes BaseLog

    Utils.check_versions()
    args = BaseOpts.BaseOptions._args # positional arguments

    if len(args) < 1 and not base_opts.mission_dir:
        print((main.__doc__))
        return 1

    if len(args) == 0:# doing all the dives?
        process_MMT = True
        process_MMP = True
        # See policy below
        # process_KML = True
        # process_NODC = False
    
    # Reset priority
    if(base_opts.nice):
        try:
            os.nice(base_opts.nice)
        except:
            log_error("Setting nice to %d failed" % base_opts.nice)

    # TODO really add options to 'd' in BaseOpts for each of these choices
    # See if any are set True, which case unpack as directed, otherwise provide a set of defaults for Reprocess
    if (base_opts.make_dive_kkyy or base_opts.make_dive_pro or base_opts.make_dive_bpo):
        process_aux = True

    if (base_opts.make_mission_profile):
        process_MMP = True

    if (base_opts.make_mission_timeseries):
        process_MMP = True

    if (process_MMP or process_MMT):
        # We appear to be making all the whole mission products
        # Make the others...
        process_KML  = True
        process_NODC = False 

    if base_opts.reprocess_plots:
        process_PLOTS = True
        
    if base_opts.reprocess_flight:
        process_FLIGHT = True

    ret_val = 0
    
    log_info("Started processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

    if(base_opts.mission_dir):
        base_path = os.path.expanduser(base_opts.mission_dir)
    else:
        log_error('You must specify --mission_dir"')
        return 1

    full_dive_list = [] # all available dives we have data files for
    dive_list = [] # dives we want to MDP
    all_dive_nc_file_names = [] # all available nc files
    dive_nc_file_names = [] # those we actually MDPd

    if(os.path.isdir(base_path)):
        # Include only valid dive files
        glob_expr = ("p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].log",
                     "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].eng",
                     "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].nc"
                     #"p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].nc.gz"
                     )
        for g in glob_expr:
            nc_match = True if g.find('.nc') > 0 else False
            for match in glob.glob(os.path.join(base_path, g)):
                log_debug("Found dive file %s" % match)
                if nc_match:
                    all_dive_nc_file_names.append(match)
                # match = match.replace('.nc.gz', '.nc')
                head, tail = os.path.splitext(os.path.abspath(match))
                full_dive_list.append(head)
                
            full_dive_list = sorted(Utils.unique(full_dive_list))

        if (len(args)):
            expanded_dive_nums = []
            for dive_num in args:
                strs = dive_num.split(':', 1)
                if (len(strs) == 2):
                    expanded_dive_nums.extend(list(range(int(strs[0]), int(strs[1])+1)))
                else:
                    expanded_dive_nums.append(int(dive_num))

            for dive_num in expanded_dive_nums:
                # Include only valid dive files
                glob_expr = ("p*%04d.log" % dive_num,
                             "p*%04d.eng" % dive_num,
                             "p*%04d.nc"  % dive_num,
                             # "p*%s.nc.gz" % dive_num,
                             )
                for g in glob_expr:
                    for match in glob.glob(os.path.join(base_path, g)):
                        log_debug("Found dive file %s" % match)
                        # match = match.replace('.nc.gz', '.nc')
                        head, tail = os.path.splitext(os.path.abspath(match))
                        dive_list.append(head)
                dive_list = sorted(Utils.unique(dive_list))
        else:
            log_info("Making profiles for all dives in %s" % base_path)
            dive_list = full_dive_list
    else:
        log_error("Directory %s does not exist -- exiting" % base_path)

    if not process_MDP:
        log_debug("Skipping MDP")
        dive_list = []
        
    sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")
    calib_consts = getSGCalibrationConstants(sg_calib_file_name)
    if(not calib_consts):
        log_warning("Could not process %s" % sg_calib_file_name)
        return 1
    
    try:
        instrument_id = int(calib_consts['id_str'])
    except:
        # base_opts always supplies a default (0)
        instrument_id = int(base_opts.instrument_id)
    if(instrument_id == 0):
        log_warning("Unable to determine instrument id; assuming 0")

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if(init_ret_val > 0):
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    logger_init(init_dict)

    # Initialze the netCDF tables
    init_tables(init_dict)

    # Find any associated logger eng files for each dive in dive_list
    logger_eng_files = find_dive_logger_eng_files(dive_list, base_opts, instrument_id, init_dict)
    
    if process_FLIGHT:
        flight_dir = os.path.join(base_opts.mission_dir, "flight")
        flight_dir_backup = os.path.join(base_opts.mission_dir, "flight_%s" % time.strftime("%Y%m%d_%H%M%S"))
        if os.path.exists(flight_dir):
            log_info("Backing up %s to %s" % (flight_dir, flight_dir_backup))
            try:
                shutil.move(flight_dir, flight_dir_backup)
            except:
                log_error("Failed to move %s to %s - profiles will use existing flight model data" % (flight_dir, flight_dir_backup), 'exc')
 
    # Now, create the profiles
    dives_processed = [] # MDP succeeded
    dives_not_processed = [] # MDP failed
    for dive_path in dive_list:
        log_debug("Processing %s" % dive_path)
        head, tail = os.path.splitext(os.path.abspath(dive_path))
        if(base_opts.target_dir):
            p, base = os.path.split(os.path.abspath(dive_path))
            outhead = os.path.join(base_opts.target_dir, base)
        else:
            outhead = head

        log_info("Head = %s" % head)

        eng_file_name = head + ".eng"
        log_file_name = head + ".log"
        dive_num = get_dive(eng_file_name)

        # Running make_dive_profiles directly always implies make_dive_netCDF
        base_opts.make_dive_netCDF = True
        if(base_opts.make_dive_netCDF):
            nc_dive_file_name = outhead + ".nc"
        else:
            nc_dive_file_name = None

        if(base_opts.make_dive_pro):
            profile_file_name = outhead + ".pro"
        else:
            profile_file_name = None
        if(base_opts.make_dive_bpo):
            binned_profile_file_name = outhead + ".bpo"
        else:
            binned_profile_file_name = None

        if(base_opts.make_dive_kkyy):
            kkyy_up_file_name = os.path.join(outhead + ".up_kkyy")
            kkyy_down_file_name = os.path.join(outhead + ".dn_kkyy")
        else:
            kkyy_up_file_name = None
            kkyy_down_file_name = None

        sg_calib_file_name, tmp = os.path.split(os.path.abspath(dive_path))
        sg_calib_file_name = os.path.join(sg_calib_file_name, "sg_calib_constants.m")

        dive_num = get_dive(eng_file_name)
        log_info("Dive number = %d" % dive_num)
        log_debug("logger_eng_files = %s" % logger_eng_files[dive_path])

        try:
            (temp_ret_val, tmp_name)  = MakeDiveProfiles.make_dive_profile(base_opts.force, dive_num, eng_file_name, log_file_name, sg_calib_file_name,
                                                                          base_opts, nc_dive_file_name,
                                                                          logger_eng_files=logger_eng_files[dive_path])
        except KeyboardInterrupt:
            log_info("Interrupted by user - bailing out")
            ret_val = 1
            break
        except:
            log_error("Error processing dive %d - skipping" % dive_num, 'exc')
            temp_ret_val = True
            
        if (not temp_ret_val):
            # no problem writting the nc file, try for the others
            dive_nc_file_names.append(nc_dive_file_name)
            if (process_aux):
                MakeDiveProfiles.write_auxillary_files(base_opts, nc_dive_file_name,
                                                       profile_file_name, binned_profile_file_name,
                                                       kkyy_up_file_name, kkyy_down_file_name)
                
        trace_results_stop() # Just in case we bailed out...no harm if closed
        qc_log_stop()
        if(temp_ret_val == 1):
            ret_val = 1
            dives_not_processed.append(dive_num)
        elif(temp_ret_val == 2):
            log_info("Skipped processing dive %d" % dive_num)
        else:
            dives_processed.append(dive_num)

    log_info("Finished processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
    log_info("Dives processed = %s" % dives_processed)
    log_info("Dives failed to process = %s" % dives_not_processed)

    # Now update other related files for each file we processed
    dive_nc_file_names = sorted(Utils.unique(dive_nc_file_names))
    # TODO process .extensions here using something like:
    # from Base import known_mailer_tags, known_ftp_tags
    # process_extensions('.extensions', base_opts, sg_calib_file_name, dive_nc_file_names,  dive_nc_file_names, [], Base.known_mailer_tags, Base.known_ftp_tags)

    # Now update all composite files using all available nc files
    all_dive_nc_file_names.extend(dive_nc_file_names)
    all_dive_nc_file_names = sorted(Utils.unique(all_dive_nc_file_names))
    if len(all_dive_nc_file_names):
        if process_FLIGHT and FLIGHT_available:
            log_info("Started FLIGHT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
            FlightModel.main(instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names)
            log_info("Finished FLIGHT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
        else:
            log_info("Skipping FLIGHT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

        if process_MMP:
            log_info("Started MMP processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
            (temp_ret_val, mission_profile_file_name) = MakeDiveProfiles.make_mission_profile(all_dive_nc_file_names, base_opts)
            log_info("Finished MMP processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
        else:
            log_info("Skipping MMP processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

        if process_MMT:
            log_info("Started MMT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
            (temp_ret_val, mission_timeseries_file_name) =  MakeDiveProfiles.make_mission_timeseries(all_dive_nc_file_names, base_opts)
            log_info("Finished MMT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
        else:
            log_info("Skipping MMT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

        if process_KML and KML_available:
            log_info("Started KML processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
            MakeKML.main(instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names)
            log_info("Finished KML processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
        else:
            log_info("Skipping KML processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

        if process_PLOTS and PLOTS_available:
            log_info("Started PLOT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
            MakePlot.main(instrument_id, base_opts, sg_calib_file_name, all_dive_nc_file_names)
            log_info("Finished PLOT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
        else:
            log_info("Skipping PLOT processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

        if process_NODC:
            log_info("Started NODC processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
            NODC.process_nc_files(base_opts, all_dive_nc_file_names, enable_ftp=False)
            log_info("Finished NODC processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
        else:
            log_info("Skipping NODC processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))


    return ret_val
                             

if __name__ == "__main__":
    import hotshot, hotshot.stats, sys, os.path


    retval = 1
    
    # Force to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()

    try:
        if(("--profile" in sys.argv) or ("--PROFILE" in sys.argv)):
            profile_file_name = os.path.splitext(os.path.split(sys.argv[0])[1])[0] + '_' + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())).replace(' ', '_') + ".prof"
            # Generate line timings
            prof = hotshot.Profile(profile_file_name, 1, 1)
            retval = prof.runcall(main)
            prof.close()
            stats = hotshot.stats.load(profile_file_name)
            stats.strip_dirs()
            stats.sort_stats('time', 'calls')
            stats.sort_stats('cumulative')
            stats.print_stats()
        else:
            retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting: %s" % traceback.format_exc()) # deliberately duplicate the exc for reuse
       
    sys.exit(retval)
    
