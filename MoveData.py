#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023  University of Washington.
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
MoveData.py: Move all raw data and processed files from the dive directory
    (e.g., ~sgXXX) to the target directory, which the script creates (nested
    if necessary).
"""

import sys
import os
import shutil
import glob
import traceback

import CommLog
import BaseOpts
from BaseLog import (
    BaseLogger,
    log_debug,
    log_info,
    log_critical,
    log_error,
    log_warning,
)
import Const
import FileMgr
import Sensors

from Globals import known_files


def moveFiles(file_re_str, src, dest, copy=False):
    """
    Moves (or copies) all local files matching file_re_str to dest directory.

    Assumes dest directory already exists.
    Logs info and error messages.
    """
    ret_val = 0
    if copy:
        op = shutil.copy
        op_gerund = "Copying"
        op_past = "Copied"
    else:
        op = shutil.move
        op_gerund = "Moving"
        op_past = "Moved"

    files = os.path.abspath(src + "/" + file_re_str)
    log_debug("%s %s" % (op_gerund, str(files)))

    myglob = glob.glob(files)
    for file in myglob:
        if os.path.isfile(file):
            try:
                op(file, dest)
                log_info("    %s %s" % (op_past, os.path.basename(file)))
            except:
                log_error(
                    "%s %s failed (%s)" % (op_gerund, file, traceback.format_exc())
                )
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
        op_gerund = "Copying"
        op_past = "Copied"
    else:
        op = shutil.move
        op_gerund = "Moving"
        op_past = "Moved"

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
    """Prepares a home directory for a new deployment by moving mission files to a new location

    Returns:
        0 for success
        1 for failure

    Raises:
        Any exceptions raised are considered critical errors and not expected

    """
    # Get options
    base_opts = BaseOpts.BaseOptions(
        "Prepares a home directory for a new deployment by moving mission files to a new location (run as root)"
    )
    BaseLogger(base_opts)  # initializes BaseLog

    log_info(f"Moving from {base_opts.mission_dir} to {base_opts.target_dir}")

    # Supports "./" to indicate local path
    # Supports absolute paths
    # Supports creation of trees, not just a single leaf directory
    # Does NOT stuff files into a directory that already existed

    if os.path.exists(base_opts.target_dir):
        if os.path.isdir(base_opts.target_dir):
            log_warning("directory already exists - proceeding")
        else:
            log_critical(
                "directory specified (%s) is a file. Bailing out" % base_opts.target_dir
            )
            return 1

    if not os.path.isdir(base_opts.target_dir):
        try:
            os.makedirs(base_opts.target_dir)
            log_info("created directory: " + base_opts.target_dir)
        except:
            log_critical("Unable to create directory: " + base_opts.target_dir)
            return 1

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
            base_opts.instrument_id = int(tail[-3:])
        except:
            log_error("Can't figure out the instrument id - bailing out")
            return 1

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    FileMgr.logger_init(init_dict)

    # Update local lists from loggers
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if "known_files" in d:
            for b in d["known_files"]:
                known_files.append(b)

    #
    # Copy these files for documentation but leave for next deployment
    #

    moveFiles(
        "sg_calib_constants.m", base_opts.mission_dir, base_opts.target_dir, copy=True
    )
    moveFiles(
        "sg_plot_constants.m", base_opts.mission_dir, base_opts.target_dir, copy=True
    )
    moveFiles("cmdfile", base_opts.mission_dir, base_opts.target_dir, copy=True)
    moveFiles("targets", base_opts.mission_dir, base_opts.target_dir, copy=True)
    moveFiles("science", base_opts.mission_dir, base_opts.target_dir, copy=True)
    moveFiles("pdoscmds.bat", base_opts.mission_dir, base_opts.target_dir, copy=True)

    #
    # Move files
    #

    if base_opts.ver_65:
        moveFiles(
            Const.raw_data_file_prefix + "*.*",
            base_opts.mission_dir,
            base_opts.target_dir,
        )  # A*.LOG and A*.000, etc.
        moveFiles(
            Const.archived_data_file_prefix + "*.*",
            base_opts.mission_dir,
            base_opts.target_dir,
        )  # Z*.LOG and Z*.000, etc. from bogue.pl
        moveFiles(
            Const.raw_gzip_file_prefix + "*.*",
            base_opts.mission_dir,
            base_opts.target_dir,
        )  # Y*.LOG and Y*.000, etc.
        moveFiles(
            Const.processed_prefix + "*.*",
            base_opts.mission_dir,
            base_opts.target_dir,
        )  # p*.asc, p*.eng, and p*.log
        moveFiles(Const.GPS_prefix + "*", base_opts.mission_dir, base_opts.target_dir)
        moveFiles(
            Const.encoded_GPS_prefix + "*",
            base_opts.mission_dir,
            base_opts.target_dir,
        )

        moveFiles(Const.convert_log, base_opts.mission_dir, base_opts.target_dir)
        moveFiles("convert_*", base_opts.mission_dir, base_opts.target_dir)

    if not base_opts.ver_65:
        # Move raw seaglider files and files generated during basestation2 processing

        fc = FileMgr.FileCollector(
            base_opts.mission_dir, base_opts.instrument_id
        )  # look at all glider files in current directory

        moveFileList(fc.get_pre_proc_files(), base_opts.target_dir)
        moveFileList(fc.get_intermediate_files(), base_opts.target_dir)
        moveFileList(fc.get_post_proc_files(), base_opts.target_dir)

        moveFiles("processed_files.cache", base_opts.mission_dir, base_opts.target_dir)

        # Move files generated by seaglider login and logout procedure
        moveFiles("baselog*", base_opts.mission_dir, base_opts.target_dir)
        moveFiles("glider_early*", base_opts.mission_dir, base_opts.target_dir)
        moveFiles("convert_*", base_opts.mission_dir, base_opts.target_dir)
        moveFiles("errors_*", base_opts.mission_dir, base_opts.target_dir)
        moveFiles("alert_message*", base_opts.mission_dir, base_opts.target_dir)
        moveFiles("SG_???_positions.txt", base_opts.mission_dir, base_opts.target_dir)

    moveFiles("sg???.db", base_opts.mission_dir, base_opts.target_dir)
    moveFiles("sections.yml", base_opts.mission_dir, base_opts.target_dir)

    moveFiles("targedit.log", base_opts.mission_dir, base_opts.target_dir)
    moveFiles("sciedit.log", base_opts.mission_dir, base_opts.target_dir)
    moveFiles("cmdedit.log", base_opts.mission_dir, base_opts.target_dir)

    # Files common to both versions of the basestation
    moveFiles("comm.log", base_opts.mission_dir, base_opts.target_dir)
    moveFiles(
        "history.log", base_opts.mission_dir, base_opts.target_dir
    )  # shell command history
    moveFiles(
        "comm_merged.log", base_opts.mission_dir, base_opts.target_dir
    )  # merged comm log and shell history
    moveFiles(
        "sg_directives*.*", base_opts.mission_dir, base_opts.target_dir
    )  # any pilot directives or suggestions
    moveFiles(Const.logfiles, base_opts.mission_dir, base_opts.target_dir)
    moveFiles(
        "p%03d*.tar.bz2" % base_opts.instrument_id,
        base_opts.mission_dir,
        base_opts.target_dir,
    )
    moveFiles(
        "pt%03d*.tar.bz2" % base_opts.instrument_id,
        base_opts.mission_dir,
        base_opts.target_dir,
    )
    moveFiles(
        "sg%03d.kmz" % base_opts.instrument_id,
        base_opts.mission_dir,
        base_opts.target_dir,
    )
    moveFiles(
        "sg%03d_network.kml" % base_opts.instrument_id,
        base_opts.mission_dir,
        base_opts.target_dir,
    )
    moveFiles(
        "p%03d*.ncdf" % base_opts.instrument_id,
        base_opts.mission_dir,
        base_opts.target_dir,
    )
    moveFiles(
        "p%03d*.ncf" % base_opts.instrument_id,
        base_opts.mission_dir,
        base_opts.target_dir,
    )
    moveFiles(
        "p%03d*.ncfb" % base_opts.instrument_id,
        base_opts.mission_dir,
        base_opts.target_dir,
    )

    # Move backup and recovery versions but NOT main versions of known_files from loggers
    for known_file in known_files:
        mv_file = known_file + ".*"  # But not basefiles
        moveFiles(mv_file, base_opts.mission_dir, base_opts.target_dir)
        mv_file = known_file + ".*.*"  # recovery files
        moveFiles(mv_file, base_opts.mission_dir, base_opts.target_dir)

    try:
        # ensure we start out next mission connected...
        # this could happen if the pilot was in the middle of a transmissions when they move data (unlikely)
        # or (more likely) they wanded off the glider during recovery in the middle of a transmission/
        # in any case, if this file is not removed, the next call, which will start a new comm.log
        # will start off with a "Reconnected" and foul comm.log parsing
        os.remove(os.path.abspath(base_opts.mission_dir + "/.connected"))
    except:
        pass  # ok if it doesn't exist

    # Look for sub-directories created by loggers and move those
    for l in FileMgr.logger_prefixes:
        g = "%s/%s[0-9][0-9][0-9][0-9][abcd]" % (base_opts.mission_dir, l)
        for d in glob.glob(g):
            _, tmp = os.path.split(d)
            t = os.path.join(base_opts.target_dir, tmp)
            if os.path.isdir(d):
                try:
                    shutil.move(d, t)
                    log_info("Moved %s" % d)
                except:
                    log_error("Moving %s failed (%s)" % (d, traceback.format_exc()))

    # If exists, move the sub-directories
    for mnt in (
        "mnt",
        "mi_download",
        "plots",
        "flight",
        "gliderdac",
        "inbox",
        "outbox",
        "outbox_archive",
        "outbox_modem",
        "inbox_modem",
    ):
        mnt_dir = os.path.join(base_opts.mission_dir, mnt)
        mnt_tgt_dir = os.path.join(base_opts.target_dir, mnt)
        if os.path.exists(mnt_dir):
            try:
                shutil.move(mnt_dir, mnt_tgt_dir)
                log_info("Moved %s" % mnt_dir)
            except:
                log_error("Moving %s failed" % mnt_dir)

    moveFiles("monitor_dive*log", base_opts.mission_dir, base_opts.target_dir)
    moveFiles("gps-sync*", base_opts.mission_dir, base_opts.target_dir)

    return 0


if __name__ == "__main__":
    retval = main()
    sys.exit(retval)
