#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2015, 2016, 2018, 2019, 2020, 2021 by University of Washington.  All rights reserved.
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
MoveData.py: Move all raw data and processed files from the dive directory
    (e.g., ~sgXXX) to the target directory, which the script creates (nested
    if necessary).
"""

#TODO - Add proper help message
#TODO - Add options so if no mission_dir is specified, the current directory is used

import string
import sys
import os
import shutil
import glob
import traceback

import CommLog
import BaseOpts
from BaseLog import *

from Const import *
from FileMgr import *

import Sensors

# globals
base_opts = None

known_files = ["cmdfile", "pdoscmds.bat", "targets", "science", "tcm2mat.cal"]

def moveFiles(file_re_str, src, dest, copy=False):
   """
   Moves (or copies) all local files matching file_re_str to dest directory.

   Assumes dest directory already exists.
   Logs info and error messages. 
   """
   ret_val = 0
   if copy:
       op = shutil.copy
       op_gerund = 'Copying'
       op_past   = 'Copied'
   else:
       op = shutil.move
       op_gerund = 'Moving'
       op_past   = 'Moved'
   
   files = os.path.abspath(src + "/" + file_re_str)
   log_debug("%s %s" % (op_gerund, str(files)))

   myglob = glob.glob(files)
   for file in myglob:
       if os.path.isfile(file):
           try:
               op(file, dest)
               log_info("    %s %s" % (op_past, os.path.basename(file)))
           except:
               log_error("%s %s failed (%s)" % (op_gerund, file, traceback.format_exc()) )
               ret_val = 1
               
   return ret_val

def moveFileList(files, target_dir, copy=False):
   """
   Moves (or copies) all files listed to dest directory.
   Caller should get file list from Base.FileCollector.get_dive_files(dive).

   Assumes dest directory already exists.
   Logs info and error messages. 
   """
   ret_val = 0
   if copy:
       op = shutil.copy
       op_gerund = 'Copying'
       op_past   = 'Copied'
   else:
       op = shutil.move
       op_gerund = 'Moving'
       op_past   = 'Moved'

   log_debug("%s %s" % (op_gerund, str(files)))
   for file in files:
       if os.path.isfile(file):
           try:
               op(file, target_dir)
               log_info("    %s %s" % (op_past, os.path.basename(file)))
           except:
               log_error("%s %s failed" % (op_gerund, str(file)))
               ret_val = 1
   return ret_val
       

def main():
    """ Prepares a home directory for a new deployment by moving mission files to a new location

    Useage: MoveData.py --mission_dir MISSION_DIR -t TARGET_DIR
    
    Where:
        -t TARGET_DIR, --target_dir=TARGET_DIR
                              target directory, used by MoveData.py
        -m MISSION_DIR, --mission_dir=MISSION_DIR
                              dive directory

    Notes:
        You must be root to run this script

    Returns:
        0 for success
        1 for failure
        
    Raises:
        Any exceptions raised are considered critical errors and not expected

    """
    global base_opts
    global instrument_id

    # Get options
    if base_opts is None:
        base_opts = BaseOpts.BaseOptions(sys.argv, 'm',
                                         usage="%prog --mission_dir MISSION_DIR -t TARGET_DIR")
    BaseLogger(base_opts) # initializes BaseLog

    #
    # Get directory to move data from
    #

    mission_dir = base_opts.mission_dir
    
    if mission_dir is None:
       log_critical("Must specify mission directory (source)")
       log_critical(main.__doc__)
       return 1
   
    log_info("mission_dir supplied: " + mission_dir)

    if not(os.path.isabs(mission_dir)):
       mission_dir = os.path.abspath(mission_dir)

    #
    # Get directory to move data to
    #

    target_dir = base_opts.target_dir
    
    if target_dir is None:
       log_critical("Must specify target directory.")
       log_critical(main.__doc__)
       return 1
   
    log_info("target_dir supplied: " + target_dir)

    if not(os.path.isabs(target_dir)):
       target_dir = os.path.abspath(target_dir)

    # Supports "./" to indicate local path
    # Supports absolute paths
    # Supports creation of trees, not just a single leaf directory
    # Does NOT stuff files into a directory that already existed

    if (os.path.exists(target_dir)):
       if os.path.isdir(target_dir):
          log_warning("directory already exists - proceeding")
       else:
          log_critical("directory specified (%s) is a file. Bailing out" % target_dir)
          return 1

    if(not os.path.isdir(target_dir)):
        try:
            os.makedirs(target_dir)
            log_info("created directory: " + target_dir)
        except:
            log_critical("Unable to create directory: " + target_dir)
            return 1

    #
    # Get glider version and instrument id from CommLog
    #

    software_version = None
    instrument_id = None

    try:
       log_debug("base_opts.mission_dir: " + base_opts.mission_dir)
       log_debug("comm_log: " + comm_log)

       (commlog, start_pos, _, _, _) = CommLog.process_comm_log(base_opts.mission_dir + comm_log, base_opts) # returns a CommLog object
       if (commlog is None):
          return 1
          
       instrument_id = commlog.get_instrument_id()
       log_debug("sg_id from commlog: " + str(instrument_id))

       if (commlog.last_complete_surfacing().software_version):
          software_version = float(commlog.last_complete_surfacing().software_version)
          log_debug("software_version: " + str(software_version))

    except SystemExit:
       log_warning("failed to process comm log: " + comm_log)

    if (instrument_id is None):
        if base_opts.instrument_id is not None:
            instrument_id = int(base_opts.instrument_id)
        else:
            instrument_id = 0 # yes, cheating, but instrumentID isn't needed for MoveData
            
    if(software_version):
        software_version = int(software_version)
    if (software_version is None):
        log_warning("glider software version not specified in " + comm_log)
        if base_opts.ver_65:
            software_version = 65
        else:
            software_version = 66 
            log_warning("Glider software version not listed in comm.log or options; assumed to be 66.")

    if not((software_version == 65) or (software_version >= 66)): # we only handle these two versions
        log_critical("Glider version must be 65 or 66 (%s). Check %s" % (software_version, comm_log))
        return 1

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if(init_ret_val > 0):
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    logger_init(init_dict)

    # Update local lists from loggers
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if('known_files' in d):
            for b in d['known_files']:
                known_files.append(b)

                
    #
    # Copy these files for documentation but leave for next deployment
    #

    moveFiles('sg_calib_constants.m', mission_dir, target_dir, copy=True)
    moveFiles('sg_plot_constants.m', mission_dir, target_dir, copy=True)
    moveFiles('cmdfile', mission_dir, target_dir, copy=True)
    moveFiles('targets', mission_dir, target_dir, copy=True)
    moveFiles('science', mission_dir, target_dir, copy=True)
    moveFiles('pdoscmds.bat', mission_dir, target_dir, copy=True)
    
    #
    # Move files
    #

    if (software_version == 65):
       moveFiles(raw_data_file_prefix + "*.*", mission_dir, target_dir) # A*.LOG and A*.000, etc.
       moveFiles(archived_data_file_prefix + "*.*", mission_dir, target_dir) # Z*.LOG and Z*.000, etc. from bogue.pl
       moveFiles(raw_gzip_file_prefix + "*.*", mission_dir, target_dir) # Y*.LOG and Y*.000, etc.
       moveFiles(processed_prefix + "*.*", mission_dir, target_dir) # p*.asc, p*.eng, and p*.log
       moveFiles(GPS_prefix + "*", mission_dir, target_dir)
       moveFiles(encoded_GPS_prefix + "*", mission_dir, target_dir)

       moveFiles(convert_log, mission_dir, target_dir)
       moveFiles("convert_*", mission_dir, target_dir)

    if (software_version >= 66):

        # Move raw seaglider files and files generated during basestation2 processing
        
        fc = FileCollector(mission_dir, instrument_id) # look at all glider files in current directory

        moveFileList(fc.get_pre_proc_files(), target_dir)
        moveFileList(fc.get_intermediate_files(), target_dir)
        moveFileList(fc.get_post_proc_files(), target_dir)

        moveFiles("processed_files.cache", mission_dir, target_dir)
        
        # Move files generated by seaglider login and logout procedure
        moveFiles("baselog_*", mission_dir, target_dir)
        moveFiles("glider_early*", mission_dir, target_dir)
        moveFiles("convert_*", mission_dir, target_dir)
        moveFiles("errors_*", mission_dir, target_dir)
        moveFiles("alert_message*", mission_dir, target_dir)
        
    # Files common to both versions of the basestation
    moveFiles(comm_log, mission_dir, target_dir)
    moveFiles('history.log', mission_dir, target_dir) # shell command history
    moveFiles('comm_merged.log', mission_dir, target_dir) # merged comm log and shell history
    moveFiles('sg_directives*.*', mission_dir, target_dir) # any pilot directives or suggestions
    moveFiles(logfiles, mission_dir, target_dir)
    moveFiles("p%03d*.tar.bz2" % instrument_id, mission_dir, target_dir)
    moveFiles("pt%03d*.tar.bz2" % instrument_id, mission_dir, target_dir)

    # Move backup and recovery versions but NOT main versions of known_files from loggers
    for known_file in known_files:
        mv_file = known_file + ".*" # But not basefiles
        moveFiles(mv_file, mission_dir, target_dir)
        mv_file = known_file + ".*.*" # recovery files
        moveFiles(mv_file, mission_dir, target_dir)

    try:
        # ensure we start out next mission connected...
        # this could happen if the pilot was in the middle of a transmissions when they move data (unlikely)
        # or (more likely) they wanded off the glider during recovery in the middle of a transmission/
        # in any case, if this file is not removed, the next call, which will start a new comm.log
        # will start off with a "Reconnected" and foul comm.log parsing
        os.remove(os.path.abspath(mission_dir + "/.connected"))
    except:
        pass # ok if it doesn't exist

    # Look for sub-directories created by loggers and move those
    for l in logger_prefixes:
        g = "%s/%s[0-9][0-9][0-9][0-9][abcd]" % (mission_dir, l)
        for d in glob.glob(g):
            _, tmp = os.path.split(d)
            t = os.path.join(target_dir, tmp)
            if os.path.isdir(d):
                try:
                    shutil.move(d, t)
                    log_info("Moved %s" % d)
                except:
                    log_error("Moving %s failed (%s)" % (d, traceback.format_exc()))

    # If exists, move the sub-directories
    for mnt in ('mnt', 'mi_download', 'plots', 'flight', 'inbox', 'outbox', 'outbox_archive',
                'outbox_modem', 'inbox_modem'):
        mnt_dir = os.path.join(mission_dir, mnt)
        mnt_tgt_dir = os.path.join(target_dir, mnt)
        if (os.path.exists(mnt_dir)):
            try:
                shutil.move(mnt_dir, mnt_tgt_dir)
                log_info("Moved %s" % mnt_dir)
            except:
                log_error("Moving %s failed" % mnt_dir)
                
    moveFiles("monitor_dive*log", mission_dir, target_dir)
    moveFiles("gps-sync*", mission_dir, target_dir)

    return 0


if __name__ == "__main__":
    retval = main()
    sys.exit(retval)
