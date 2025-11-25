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
Base.py: Main entry point for Seaglider basestation.

Cleans up and converts raw data files & organizes files associated
with dive.
"""

import cProfile
import functools
import glob
import math
import os
import pathlib
import pdb
import pprint
import pstats
import re
import shutil
import signal
import stat
import struct
import sys
import tarfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

import orjson

import BaseCtrlFiles
import BaseDB
import BaseDotFiles
import BaseGZip
import BaseNetCDF
import BaseNetwork
import BaseOpts
import BaseParquet
import BasePlot
import Bogue
import CalibConst
import CommLog
import Daemon
import DataFiles
import FileMgr
import FlightModel
import LogFile
import MakeDiveProfiles
import MakeKML
import MakeMissionProfile
import MakeMissionTimeSeries
import PlotUtils
import Sensors
import Strip1A
import Utils
import Ver65
from BaseLog import (
    BaseLogger,
    log_alerts,
    log_conversion_alert,
    log_conversion_alerts,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_tracebacks,
    log_warn_errors,
    log_warning,
)
from Globals import known_files, known_ftp_tags, known_mailer_tags

# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False

# TODOCC
# 1) Largest issue is to remove mismash of globals and globals passed as arguments.
#    Creation of a "global_state" class the contians the various lists and objects and that
#    is to be passed to everything along with base_opts

# Globals
file_trans_received = "r"
processed_files_cache = "processed_files.cache"
# Set by signal handler to skip the time consuming processing of the whole mission data
stop_processing_event = threading.Event()
base_lockfile_name = ".conversion_lock"
base_completed_name = ".completed"

# Configuration
previous_conversion_time_out = 60  # Time to wait for previous conversion to complete


# Utility functions
def set_globals() -> None:
    global \
        logger_eng_readers, \
        processed_logger_payload_files, \
        processed_eng_and_log_files, \
        processed_selftest_eng_and_log_files, \
        processed_other_files, \
        processed_logger_eng_files, \
        processed_logger_other_files

    logger_eng_readers = {}  # Mapping from logger prefix to eng_file readers

    ## Global lists and dicts
    # incomplete_files = []
    processed_logger_payload_files = {}  # Dictionay of lists of files from a logger payload file, keyed by logger prefix
    # Files in these lists do not conform to normal logger basestation naming conventions
    processed_eng_and_log_files = []
    processed_selftest_eng_and_log_files = []
    processed_other_files = []
    processed_logger_eng_files = []  # List of eng files from all loggers - files on this list must conform to the basestation file and
    # dive directory naming convention
    processed_logger_other_files = []  # List of all non-eng files from all loggers - files on this list do not need to
    #    conform to basestation directory and filename convetions


set_globals()


# urllib override to prevent username/passwd prompting on stdin
def my_prompt_user_passwd(self, host, realm):
    """
    Stub function for user password
    """
    # pylint: disable=W0613
    return None, None


urllib.request.FancyURLopener.prompt_user_passwd = my_prompt_user_passwd


def read_processed_files(glider_dir, instrument_id):
    """Reads the processed file cache

    Returns: list of processed dive files and a list of processed pdos logfiles
             None for error opening the file

    Raises: IOError for file errors
    """
    log_debug("Enterting read_processed_files")

    processed_dive_file_name = glider_dir + processed_files_cache

    files_dict = {}
    pdos_logfiles_dict = {}
    if not os.path.exists(processed_dive_file_name):
        return (files_dict, pdos_logfiles_dict)

    with open(processed_dive_file_name, "r") as processed_dives_file:
        for raw_line in processed_dives_file:
            raw_line = raw_line.rstrip()
            if raw_line == "":
                continue
            if raw_line[0:1] == "#":
                continue

            raw_parts = raw_line.split(",")

            fc = FileMgr.FileCode(raw_parts[0], instrument_id)
            if fc.is_pdos_log():
                try:
                    pdos_logfiles_dict[raw_parts[0]] = time.mktime(
                        time.strptime(raw_parts[1].lstrip(), "%H:%M:%S %d %b %Y %Z")
                    )
                except (ValueError, IndexError):
                    # Old way - assume the current time
                    pdos_logfiles_dict[raw_parts[0]] = time.time()
            elif fc.is_seaglider() or fc.is_seaglider_selftest() or fc.is_logger():
                try:
                    files_dict[raw_parts[0]] = time.mktime(
                        time.strptime(raw_parts[1].lstrip(), "%H:%M:%S %d %b %Y %Z")
                    )
                except ValueError:
                    # Old format - read it in w/o regard to timezone
                    files_dict[raw_parts[0]] = time.mktime(
                        time.strptime(raw_parts[1].lstrip())
                    )
            else:
                log_error(
                    f"Unknown entry {raw_line} in {processed_files_cache} - skipping"
                )

    del processed_dives_file
    try:
        os.chmod(
            processed_dive_file_name,
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IRGRP
            | stat.S_IWGRP
            | stat.S_IROTH
            | stat.S_IWOTH,
        )
    except Exception:
        log_error(f"Unable to change mode of {processed_dive_file_name}", "exc")

    log_debug("Leaving read_processed_files")

    return (files_dict, pdos_logfiles_dict)


def write_processed_dives(glider_dir, files_dict, pdos_logfiles_dict):
    """Writes out the processed dive file

    Returns: 0 for success, non-zero for failure
    Raises: IOError for fil
    """
    processed_dive_file_name = glider_dir + processed_files_cache

    # processed_pdos_logfiles.sort()
    pdos_items = sorted(list(pdos_logfiles_dict.items()))

    items = sorted(files_dict.items())

    with open(processed_dive_file_name, "w") as processed_dive_file:
        processed_dive_file.write(
            "# This file contains the dives that have been"
            " processed and the times they were processed\n"
        )
        processed_dive_file.write(
            "# To force a file to be re-processed, delete the"
            " corresponding line from this file\n"
        )
        processed_dive_file.write(
            "# Written %s\n"
            % time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
        )

        # for i in processed_pdos_logfiles:
        #    processed_dive_file.write("%s\n" % i)
        for i, j in pdos_items:
            processed_dive_file.write(
                f"{i}, {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(j))}\n"
            )

        for i, j in items:
            # processed_dive_file.write("%s, %.2f\n" % (i, j))
            processed_dive_file.write(
                f"{i}, {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(j))}\n"
            )

    del processed_dive_file

    return 0


def group_dive_files(dive_files, instrument_id):
    """Given a sorted list of dive files, break the list up
    into a dictionary with the key as the base name for the
    files (no extensions or leading dirs) and the item as a list of
    file fragments
    """
    file_group = {}
    for i in dive_files:
        fc = FileMgr.FileCode(i, instrument_id)
        if fc.base_name() not in file_group:
            file_group[fc.base_name()] = []
        file_group[fc.base_name()].append(i)

    return file_group


def process_dive_selftest(
    base_opts,
    dive_files,
    dive_num,
    fragment_size_dict,
    calib_consts,
    instrument_id,
    comm_log,
    complete_files_dict,
    incomplete_files,
):
    """Given a list of files belonging to a single dive, process them

    Returns:
    -1 for failure to process
    0 for nothing to do (dive already processed)
    1 for successful processing

    """
    ret_val = 0
    force_data_processing = False

    log_debug(f"process_dive_selftest file list {pprint.pformat(dive_files)}")

    # Here the order to process in
    # 1) Logfiles from the seaglider (this contains the file fragment size)
    # 2) Everything else
    #
    # Note: the old version first worked on tar files.  This can be reinstated
    # here if need be

    # Get the files into groups - a dictionary of lists
    dive_files_dict = group_dive_files(dive_files, instrument_id)

    log_debug(
        f"process_dive_selftest dive files dictionary {pprint.pformat(dive_files_dict)}"
    )

    # Process any log files from the seaglider - this is needed to understand
    # the fragment size for the given dive and must happen before processing
    # of seaglider data files
    for base, file_group in list(dive_files_dict.items()):
        # Process the file only if it hasn't been processed yet
        if check_process_file_group(base, file_group, complete_files_dict):
            fc = FileMgr.FileCode(base, instrument_id)
            if fc.is_log() and (fc.is_seaglider() or fc.is_seaglider_selftest()):
                try:
                    pfg_retval = process_file_group(
                        base_opts,
                        file_group,
                        fragment_size_dict,
                        0,
                        calib_consts,
                        instrument_id,
                        comm_log,
                        incomplete_files,
                    )
                except Exception:
                    log_error(f"Could not process {fc.base_name()} - skipping", "exc")
                    ret_val = -1
                else:
                    if pfg_retval:
                        log_error(f"Could not process {fc.base_name()} - skipping")
                        ret_val = -1
                    else:
                        # complete_files.append(base)
                        complete_files_dict[base] = time.time()
                        del dive_files_dict[base]  # All processed
                        # Force the data file to be (re)converted to generate the eng file, if it
                        # is in the list
                        if fc.make_data() in dive_files_dict:
                            force_data_processing = True
                        if ret_val == 0:
                            ret_val = 1

    # Process what's left remainder
    for base, file_group in list(dive_files_dict.items()):
        # if(complete_files.count(base) == 0):
        fc = FileMgr.FileCode(base, instrument_id)
        if check_process_file_group(base, file_group, complete_files_dict) or (
            fc.is_data() and force_data_processing
        ):
            if (fc.is_seaglider() or fc.is_seaglider_selftest()) and fc.is_pdos_log():
                # This is covered way before we get here.
                continue
            try:
                # log_info(f"fragment_size = {fragment_size}")
                pfg_retval = process_file_group(
                    base_opts,
                    file_group,
                    fragment_size_dict,
                    0,
                    calib_consts,
                    instrument_id,
                    comm_log,
                    incomplete_files,
                )
            except Exception:
                if DEBUG_PDB:
                    _, _, tb = sys.exc_info()
                    traceback.print_exc()
                    pdb.post_mortem(tb)

                log_error(f"Could not process {fc.base_name()} - skipping", "exc")
                ret_val = -1
            else:
                if pfg_retval:
                    log_error(f"Could not process {fc.base_name()} - skipping")
                    ret_val = -1
                else:
                    # complete_files.append(base)
                    complete_files_dict[base] = time.time()
                    del dive_files_dict[base]  # All processed
                    if ret_val == 0:
                        ret_val = 1

    log_debug("process_dive_selftest(%d) = %d" % (dive_num, ret_val))
    return ret_val


def select_fragments(file_group, instrument_id):
    """Given a sorted list of fragments, possibly containing PARTIAL files,
    return a list which contains only one file for each fragment slot.
    Note: this depends on the non-PARITAL file being GREATER (to the right)
    of any PARITAL files, if it exists in the list
    """
    new_file_group = []
    current_frag = None
    for fragment in file_group:
        if current_frag is None:
            current_frag = fragment
        if FileMgr.get_non_partial_filename(
            current_frag
        ) != FileMgr.get_non_partial_filename(fragment):
            new_file_group.append(current_frag)
        current_frag = fragment
    new_file_group.append(current_frag)
    for fragment in new_file_group:
        if fragment != FileMgr.get_non_partial_filename(fragment):
            root, _ = os.path.splitext(FileMgr.get_non_partial_filename(fragment))
            defrag_file_name = root + "." + file_trans_received
            log_conversion_alert(
                defrag_file_name,
                f"File {fragment} is a PARTIAL file",
                generate_resend(fragment, instrument_id),
            )

    return new_file_group


def generate_resend(fragment_name, instrument_id):
    """Given a fragment name, return the appropriate resend dive message"""
    fragment_fc = FileMgr.FileCode(fragment_name, instrument_id)
    ret_val = ""
    if fragment_fc.is_seaglider() or fragment_fc.is_seaglider_selftest():
        if fragment_fc.is_log():
            ret_val = ret_val + "resend_dive /l %d" % fragment_fc.dive_number()
        elif fragment_fc.is_data():
            ret_val = ret_val + "resend_dive /d %d" % fragment_fc.dive_number()
        elif fragment_fc.is_capture():
            ret_val = ret_val + "resend_dive /c %d" % fragment_fc.dive_number()
        elif fragment_fc.is_tar():
            ret_val = ret_val + "resend_dive /t %d" % fragment_fc.dive_number()
        else:
            # Don't know about this file type
            ret_val = ret_val + "resend"

        frag_num = fragment_fc.get_fragment_counter()
        if frag_num >= 0:
            ret_val = ret_val + " %d" % frag_num
        else:
            ret_val = ret_val + "recommend resend the entire file"

    return ret_val


def check_process_file_group(base, file_group, complete_files_dict):
    """Determines if the file group should be processed and reports details on why

    Returns: True to indicate the group should be processed
             False to inicated the group should not be processed
    """
    if base not in complete_files_dict:
        return True

    for file_name in file_group:
        # Get the file stamp of the fragment and compare against the most recent conversion
        if os.path.getmtime(file_name) > complete_files_dict[base]:
            return True

    return False


def cat_fragments(output_file_name, fragment_list):
    """Helper routine to assemble a list of fragment"""
    log_debug(f"About to open {output_file_name}")
    ret_val = 0
    with open(output_file_name, "wb") as output_file:
        for filename in fragment_list:
            try:
                with open(filename, "rb") as fi:
                    data = fi.read()
            except PermissionError:
                log_error(f"Could not open {filename} due to file permissions")
                ret_val = 1
            output_file.write(data)
    return ret_val


def test_decompress(inp_file_name, inp_file_list):
    """Tests which of the two input inputs decompresses better

    Return:
        True if inp_file_name is better
        False if inp_file_list is better
    """

    tmp_file = inp_file_name + ".temp"
    ret1 = BaseGZip.decompress(inp_file_name, tmp_file)
    os.unlink(tmp_file)

    tmp_in_file = inp_file_list[0] + ".temp_in"
    cat_fragments(tmp_in_file, inp_file_list)
    tmp_out_file = inp_file_list[0] + ".temp_out"

    ret2 = BaseGZip.decompress(tmp_in_file, tmp_out_file)
    os.unlink(tmp_in_file)
    os.unlink(tmp_out_file)
    return ret1 <= ret2


def process_file_group(
    base_opts,
    file_group,
    fragment_size_dict,
    total_size,
    calib_consts,
    instrument_id,
    comm_log,
    incomplete_files,
):
    """Given a file group - one or more fragments - process the files

    Input:
        file_group - list of fragments
        fragment_size_dict - mapping of all fragments and expected sizes
        total_size - total size of the resulting file - 0 if not known

    Returns:
       0 success
       1 failure
    Raises:
      Any exceptions raised are considered critical errors and not expected
    """
    # pylint: disable=R0914

    ret_val = 0

    # pdb.set_trace()

    log_debug(f"process_file_group dictionary = {pprint.pformat(file_group)}")
    root, ext = os.path.splitext(FileMgr.get_non_partial_filename(file_group[0]))
    defrag_file_name = root + "." + file_trans_received

    log_info(f"Processing {root}")

    file_group.sort(key=functools.cmp_to_key(FileMgr.sort_fragments))

    file_group = select_fragments(file_group, instrument_id)

    # Eliminate Bogue syndrome
    for bogue_file in file_group:
        # No Bogue for raw xfer
        _, t = os.path.split(bogue_file)
        log_debug(f"{t} = {comm_log.find_fragment_transfer_method(t)}")
        if (
            comm_log.find_fragment_transfer_method(t) in ("raw", "ymodem", "unknown")
            or not base_opts.run_bogue
        ):
            continue
        try:
            i = file_group.index(bogue_file)
            file_group[i] = Bogue.Bogue(
                bogue_file
            )  # replaces filename with bogue'd filename if bogue's syndrome was removed
        except Exception:
            log_error(
                f"Exception raised in Bogue processing {bogue_file} - skipping dive processing."
            )
            return 1
        else:
            if file_group[i] is None:
                log_error(
                    "Couldn't Bogue %s, got %s - skipping dive processing." % bogue_file
                )
                return 1

    fc = FileMgr.FileCode(defrag_file_name, instrument_id)

    # Strip1A all the files
    fragments_1a = []
    last_fragment = file_group[-1]
    for fragment in file_group:
        # No 1a for raw xfer or logger payload files
        _, t = os.path.split(fragment)
        # Even if raw, logger payload files have often been moved
        # from logger to glider by xmodem, so they may well have trailing
        # 1as

        # GBS 2020/03/10 - The above logic applies also to scicon/tmico/pmar files,
        # so they all get the strip1a treatment for the last fragment only

        # GBS 2020/12/19 - With the replacement of ymodem for xmodem in the
        # logger/glider transfer method, the need to strip files logger files.
        # The check for fc.is_logger_strip_files() below can be removed once
        # ymodem is in general use.
        log_debug(
            "fragment:%s transfer:%s logger:%s strip_files:%s"
            % (
                t,
                comm_log.find_fragment_transfer_method(t),
                fc.is_logger_payload(),
                fc.is_logger_strip_files(),
            )
        )
        if (
            comm_log.find_fragment_transfer_method(t) in ("raw", "ymodem", "unknown")
            and not fc.is_logger_payload()
            and not (fc.is_logger_strip_files() and fragment == last_fragment)
        ):
            fragments_1a.append(fragment)
            continue

        root, ext = os.path.splitext(fragment)
        fragment_1a = root + ".1a" + ext
        # Ignore any size issues for the last fragment or logger payload files
        if fragment is last_fragment or fc.is_logger_payload():
            ret_val = Strip1A.strip1A(fragment, fragment_1a)
        else:
            ret_val = Strip1A.strip1A(
                fragment, fragment_1a, fragment_size_dict[fragment].expectedsize
            )
        if ret_val and not fc.is_logger_payload():
            log_error(f"Couldn't strip1a {fragment_1a}. Skipping dive processing")
            return 1
        fragments_1a.append(fragment_1a)

    if fc.is_logger_payload():
        # Generic payload from the logger - hand it off to the extension and
        # skip the rest of the processing

        tmp_processed_logger_payload_files = []
        tmp_incomplete_other_files = []
        if (
            Sensors.process_logger_func(
                fc.logger_prefix(),
                "process_payload_files",
                fragments_1a,
                fc,
                tmp_processed_logger_payload_files,
                tmp_incomplete_other_files,
            )
            != 0
        ):
            log_error(f"Problems processing logger file {defrag_file_name}")

        # Record the incomplte files
        for i in tmp_incomplete_other_files:
            incomplete_files.append(i)

        # Even if there are problems processing files, continue on

        # log_info(tmp_processed_logger_payload_files)
        if fc.logger_prefix() not in processed_logger_payload_files:
            processed_logger_payload_files[fc.logger_prefix()] = []

        for i in tmp_processed_logger_payload_files:
            processed_other_files.append(i)
            processed_logger_payload_files[fc.logger_prefix()].append(i)
        # log_info( processed_logger_payload_files )
        return 0

    # At this point, the fragments should be of the correct size, so now we can check them
    check_file_fragments(
        defrag_file_name,
        fragments_1a,
        fragment_size_dict,
        total_size,
        instrument_id,
    )

    #
    # GBS 2022/03/31 Scan the fragment list - if there is a mix of a
    # straight .x file and fragments in the list, there are
    # decisions to be made.
    #
    # In the case of zipped files, test the fragments and straight
    # upload to determine which is "better" for for decompression and
    # select the better option.
    #
    # For all other files, if selftest, chose the fragments over the
    # whole file (reasoning, the fragments came up via uploadst and
    # are "better").  Otherwise, choose the straight .x file
    # (reasoning, that file was likely copied over from a CF/SD card
    # post-deployment for post-processing)
    #
    complete_xmit_filename = None
    for filename in fragments_1a:
        if FileMgr.is_complete_xmit(filename):
            complete_xmit_filename = filename
            break

    if complete_xmit_filename and len(fragments_1a) > 1:
        if fc.is_gzip() or fc.is_tgz():
            fragments_1a.remove(complete_xmit_filename)
            if test_decompress(complete_xmit_filename, fragments_1a):
                log_info(
                    f"{complete_xmit_filename} decompresses (better) then fragments - using {complete_xmit_filename}"
                )
                fragments_1a = [complete_xmit_filename]
            else:
                log_info(
                    f"Fragments decompress (better) then {complete_xmit_filename} - using fragments"
                )
        elif fc.is_seaglider_selftest():
            log_info(f"Not using {complete_xmit_filename} in favor of fragments")
            fragments_1a.remove(complete_xmit_filename)
        else:
            log_info(f"Using {complete_xmit_filename} instead of fragments")
            fragments_1a = [complete_xmit_filename]

    if cat_fragments(defrag_file_name, fragments_1a):
        log_error(
            f"Couldn't concatenate fragments for {defrag_file_name}. Skipping dive processing"
        )
        return 1

    # Now process based on the specifics of the file
    log_info(f"Processing {defrag_file_name} in process_file_group")

    # CONSIDER - add a note to the errors analysis that indicates the actual name downloaded

    # Raw processing lists
    file_list = []

    if fc.is_tar() or fc.is_tgz() or fc.is_tjz():
        saved_defrag_file_name = defrag_file_name
        if fc.is_tgz():
            # Use our own unzip - more robust
            head, tail = os.path.split(defrag_file_name)
            b, e = os.path.splitext(tail)
            b = f"{b[0:7]}{'t'}{b[8:]}"
            tar_file_name = os.path.join(head, f"{b}{e}")
            r_v = BaseGZip.decompress(defrag_file_name, tar_file_name)
            if r_v > 0:
                log_error(f"Problem gzip decompressing {defrag_file_name}")
            # If the file
            if os.path.exists(tar_file_name):
                defrag_file_name = tar_file_name
            else:
                ret_val = r_v
                incomplete_files.append(defrag_file_name)
        try:
            tar = tarfile.open(defrag_file_name, "r")
        except tarfile.ReadError as exception:
            log_error(
                f"Error reading {defrag_file_name} - skipping ({exception.args}) (might be empty tarfile)"
            )
            incomplete_files.append(defrag_file_name)
            ret_val = 1
        else:
            # Loggers maintain their own name space - extract the contents of the
            # tar file and hand it of to the loggers module for further procesing
            if fc.is_logger():
                logger_file_list = []
            for tarmember in tar:
                if tarmember.isreg():
                    log_info(
                        f"Extracting {tarmember.name} from {defrag_file_name} to directory {base_opts.mission_dir}"
                    )
                    try:
                        if sys.version_info < (3, 10, 11):  # noqa: UP036
                            tar.extract(tarmember.name, base_opts.mission_dir)
                        else:
                            tar.extract(
                                tarmember.name, base_opts.mission_dir, filter="data"
                            )

                    except OverflowError as exception:
                        log_warning(
                            f"Potential problems extracting {tarmember.name} ({exception.args})"
                        )
                    except struct.error as exception:
                        log_warning(
                            f"Potential problems extracting {tarmember.name} ({exception.args})"
                        )

                    tarmember_fullpath = os.path.abspath(
                        os.path.join(base_opts.mission_dir, tarmember.name)
                    )

                    if fc.is_logger():
                        logger_file_list.append(tarmember_fullpath)
                    else:
                        file_list.append(tarmember_fullpath)
                    try:
                        os.chmod(
                            tarmember_fullpath,
                            stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH,
                        )
                        # CONSIDER - for loggers, leave the time stamp as is
                        os.utime(tarmember_fullpath, None)
                    except OSError as exception:
                        log_error(
                            "Could not access %s (%s) - potential problem with tar file extraction"
                            % (tarmember_fullpath, exception.args)
                        )
                        incomplete_files.append(defrag_file_name)
                        ret_val = 1
            tar.close()

            # For loggers, hand off to logger extension
            if fc.is_logger():
                try:
                    if (
                        Sensors.process_logger_func(
                            fc.logger_prefix(),
                            "process_tar_members",
                            fc,
                            logger_file_list,
                            processed_logger_eng_files,
                            processed_logger_other_files,
                        )
                        != 0
                    ):
                        log_error(
                            f"Problems processing logger {defrag_file_name} tar data"
                        )
                        incomplete_files.append(saved_defrag_file_name)
                        ret_val = 1

                except Exception:
                    log_error(
                        f"Problems processing logger {defrag_file_name} tar data",
                        "exc",
                    )
                    incomplete_files.append(saved_defrag_file_name)
                    ret_val = 1

    elif fc.is_gzip():
        uc_file_name = fc.make_uncompressed()

        log_debug(f"Decompressing gzip {defrag_file_name} to {uc_file_name}")
        if BaseGZip.decompress(defrag_file_name, uc_file_name) > 0:
            log_error(f"Problem gzip decompressing {defrag_file_name} - skipping")
            incomplete_files.append(defrag_file_name)
            ret_val = 1
        else:
            if os.path.getsize(uc_file_name) == 0:
                log_error(
                    f"File {uc_file_name} is zero sized - skipping further processing"
                )
                log_error("Could not get file size", "exc")
            else:
                file_list.append(uc_file_name)
    elif fc.is_bzip():
        uc_file_name = fc.make_uncompressed()

        log_debug(f"Decompressing bzip {defrag_file_name} to {uc_file_name}")

        if Utils.bzip_decompress(defrag_file_name, uc_file_name) > 0:
            log_error(f"Problem bzip decompressing {defrag_file_name} - skipping")
            incomplete_files.append(defrag_file_name)
            ret_val = 1
        else:
            file_list.append(uc_file_name)
    elif fc.is_seaglider and fc.is_parm_file():
        # Process this here because the parm file has no uncompressed encoding
        # form in the file namespace
        parm_file_name = fc.mk_base_parm_name()
        if BaseGZip.decompress(defrag_file_name, parm_file_name) > 0:
            log_error(f"Problem decompressing {defrag_file_name} - skipping")
            incomplete_files.append(defrag_file_name)
            ret_val = 1
        else:
            file_list.append(defrag_file_name)
    else:
        file_list.append(defrag_file_name)

    # Do this as a list of files
    for in_file_name in file_list:
        fc = FileMgr.FileCode(in_file_name, instrument_id)
        log_debug(f"Content specific processing of {in_file_name}")
        if fc.is_seaglider() or fc.is_seaglider_selftest():
            if fc.is_parm_file():
                # Handled above
                pass
            elif fc.is_log():
                shutil.move(in_file_name, fc.mk_base_logfile_name())
                log_info(f"Removing secrets from {fc.mk_base_logfile_name()}")
                try:
                    expunge_secrets(fc.mk_base_logfile_name())
                except Exception:
                    log_error(f"Could not expunge secrets for {in_file_name}", "exc")
                if not fc.is_seaglider_selftest():
                    processed_eng_and_log_files.append(fc.mk_base_logfile_name())
                else:
                    processed_selftest_eng_and_log_files.append(
                        fc.mk_base_logfile_name()
                    )

            elif fc.is_data():
                shutil.copyfile(in_file_name, fc.mk_base_datfile_name())
                sg_data_file = DataFiles.process_data_file(
                    in_file_name, "dat", calib_consts
                )
                if (
                    not sg_data_file
                    or sg_data_file.data is None
                    or len(sg_data_file.data) == 0
                ):
                    log_error(
                        f"Could not process {in_file_name}, skipping eng file creation"
                    )
                    ret_val = 1
                else:
                    # Save the asc file out for debugging
                    sg_data_file.dat_to_asc()
                    with open(fc.mk_base_ascfile_name(), "w") as fo:
                        sg_data_file.dump(fo)
                    del fo
                    processed_other_files.append(fc.mk_base_ascfile_name())
                    # Convert to the eng file
                    sg_log_file = LogFile.parse_log_file(
                        fc.mk_base_logfile_name(),
                        issue_warn=True,
                    )
                    if not sg_log_file:
                        log_error(
                            f"Could not parse {fc.mk_base_logfile_name()}, skipping eng file creation"
                        )
                        # Don't add defrag_file_name to the incomplete_files list on account of this
                        ret_val = 1
                    else:
                        if sg_data_file.asc_to_eng(sg_log_file):
                            log_error(
                                f"Could not convert {fc.mk_base_ascfile_name()} to eng file"
                            )
                            ret_val = 1
                        else:
                            with open(fc.mk_base_engfile_name(), "w") as fo:
                                sg_data_file.dump(fo)

                # Add this to the list potential dives to be processed for
                if not fc.is_seaglider_selftest():
                    processed_eng_and_log_files.append(fc.mk_base_engfile_name())
                else:
                    processed_selftest_eng_and_log_files.append(
                        fc.mk_base_engfile_name()
                    )

            elif fc.is_capture():
                shutil.move(in_file_name, fc.mk_base_capfile_name())
                if fc.is_seaglider_selftest():
                    log_info(f"Removing secrets from {fc.mk_base_capfile_name()}")
                    expunge_secrets_st(fc.mk_base_capfile_name())

                processed_other_files.append(fc.mk_base_capfile_name())
            elif fc.is_network():
                if fc.is_network_logfile():
                    BaseNetwork.convert_network_logfile(
                        base_opts, in_file_name, fc.mk_base_logfile_name()
                    )
                    processed_other_files.append(fc.mk_base_logfile_name())
                elif fc.is_network_profile():
                    BaseNetwork.convert_network_profile(
                        in_file_name, fc.mk_base_datfile_name()
                    )
                    processed_other_files.append(fc.mk_base_datfile_name())
            else:
                log_error(
                    f"Don't know how to deal with file ({in_file_name}) - unknown type"
                )
                ret_val = 1

        elif fc.is_logger():
            if fc.is_log():
                if (
                    Sensors.process_logger_func(
                        fc.logger_prefix(),
                        "process_log_files",
                        fc,
                        processed_logger_other_files,
                    )
                    != 0
                ):
                    log_error(f"Problems processing logger file {in_file_name}")
            elif fc.is_data() or fc.is_down_data() or fc.is_up_data():
                if (
                    Sensors.process_logger_func(
                        fc.logger_prefix(),
                        "process_data_files",
                        calib_consts,
                        fc,
                        processed_logger_eng_files,
                        processed_logger_other_files,
                    )
                    != 0
                ):
                    log_error(f"Problems processing logger file {in_file_name}")
            else:
                log_error(
                    f"Don't know how to deal with logger file ({in_file_name}) - unknown type"
                )
                ret_val = 1
        else:
            log_error(
                f"Don't know how to deal with file ({in_file_name}) - unknown type"
            )
            ret_val = 1

    return ret_val


def check_file_fragments(
    defrag_file_name, fragment_list, fragment_size_dict, total_size, instrument_id
):
    """Checks that the file fragments are of a reasonable size

    Note: this function will issue incorrect diagnostics if the size of fragment is
    differnt then what is noted in the comm.log (that is, N_FILEKB has been changed)

    Returns:
       TRUE for success
       FALSE for a failure and issues a warning
    """
    ret_val = True

    # if fragment_size <= 0:
    #    log_info(
    #        f"Fragment size specified is {str(fragment_size)}, skipping file fragment check."
    #    )
    #    return True

    # Assume sorted
    # fragment_list.sort()  #In case this hasn't already been done

    size_from_fragments = 0
    number_of_fragments = len(fragment_list)
    last_frag_expected_size = 0

    # This math assumes a constant fragment size, so we just use the first
    # fragments expectedsize
    if total_size != 0:
        fragment_size = fragment_size_dict[
            FileMgr.get_non_1a_filename(
                os.path.basename(fragment_list[-1])
            ).expectedsize
        ]
        number_expected_fragments = math.ceil(total_size / fragment_size)
        if total_size % fragment_size > 0:
            number_expected_fragments = number_expected_fragments + 1
            last_frag_expected_size = total_size % fragment_size
        else:
            last_frag_expected_size = fragment_size

        if number_of_fragments == number_expected_fragments:
            log_debug(
                "Got %d fragments, expected %d."
                % (number_of_fragments, number_expected_fragments)
            )
        elif number_of_fragments < number_expected_fragments:
            log_info(
                "Missing fragments: total size logged was %d, got %d, expected %d."
                % (total_size, number_of_fragments, number_expected_fragments)
            )
        else:
            log_info(
                "Too many fragments: total size logged was %d; got %d, expected %d."
                % (total_size, number_of_fragments, number_expected_fragments)
            )
        del fragment_size

    # check fragment sizes:
    fragment_cntr = 0
    for fragment in fragment_list:
        log_info(f"Checking fragment {fragment}")

        while fragment_cntr < FileMgr.get_counter(fragment):
            msg = "Fragment %d for file %s is missing" % (
                fragment_cntr,
                defrag_file_name,
            )
            log_warning(msg)
            log_conversion_alert(
                defrag_file_name,
                msg,
                generate_resend(fragment, instrument_id),
            )
            ret_val = False
            # See if there are more
            fragment_cntr = fragment_cntr + 1

        fragment_cntr = fragment_cntr + 1

        current_fragment_size = os.stat(fragment).st_size
        # preceeding frags must be frag_size (may be padded with \1A chars)
        if fragment_list.index(fragment) != (number_of_fragments - 1):
            expectedsize = fragment_size_dict[
                FileMgr.get_non_1a_filename(os.path.basename(fragment))
            ].expectedsize
            if current_fragment_size != expectedsize:
                msg = "Fragment %s file size (%d) not equal to expected size (%d)" % (
                    fragment,
                    current_fragment_size,
                    expectedsize,
                )
                log_warning(msg)
                log_conversion_alert(
                    defrag_file_name,
                    msg,
                    generate_resend(fragment, instrument_id),
                )
                ret_val = False
            else:
                log_debug(
                    "Fragment %s size (%d) is expected."
                    % (fragment, current_fragment_size)
                )
        else:
            # First check if we have a known mismatch between the expected vs received size - this really
            # is just applies to raw for the last fragment in the chain.  If that isn't the case,
            # and the total_size is known, last frag size should be expected
            # OR <= frag_size if total_size is unknown
            expectedsize, receivedsize = fragment_size_dict[
                FileMgr.get_non_1a_filename(os.path.basename(fragment))
            ]
            if receivedsize >= 0 and expectedsize != receivedsize:
                msg = "Fragment %s file size (%d) not equal to expected size (%d)" % (
                    fragment,
                    receivedsize,
                    expectedsize,
                )
                log_warning(msg)
                log_conversion_alert(
                    defrag_file_name,
                    msg,
                    generate_resend(fragment, instrument_id),
                )
                ret_val = False

            elif total_size != 0:
                if current_fragment_size != last_frag_expected_size:
                    msg = (
                        "Final fragment %s size (%d) is not expected (should be %d)."
                        % (fragment, current_fragment_size, last_frag_expected_size)
                    )
                    log_warning(msg)
                    log_conversion_alert(
                        defrag_file_name,
                        msg,
                        generate_resend(fragment, instrument_id),
                    )

            elif current_fragment_size > expectedsize:
                size_from_fragments += current_fragment_size
                fc = FileMgr.FileCode(fragment, instrument_id)
                if fc.get_fragment_counter() >= 0 and not (
                    fc.is_seaglider_selftest() and fc.is_capture()
                ):
                    # This message only applies if the file is actually a fragment
                    msg = (
                        "Final fragment %s size (%d) is too big, expected less than or equal to %d."
                        % (fragment, current_fragment_size, expectedsize)
                    )
                    log_warning(msg)
                    log_conversion_alert(
                        defrag_file_name,
                        msg,
                        generate_resend(fragment, instrument_id),
                    )

    if total_size != 0 and size_from_fragments != total_size:
        log_warning(
            "Size from frags (%d) does not match logged value (%d)"
            % (size_from_fragments, total_size)
        )
        ret_val = False

    return ret_val


def process_pdoscmd_log(base_opts, pdos_logfile_name, instrument_id):
    """Processes a pdos_logfile.  These file names are outside the normal rules of
    file processing, so are handled in this different routine

    Return 0 for success, non-zero for failure
    """
    log_info(f"Processing {pdos_logfile_name}")

    # N.B. No fragment checking done here - it is assumed that this file is less
    # then a fragment in size

    fc = FileMgr.FileCode(pdos_logfile_name, instrument_id)
    if fc.is_seaglider() or fc.is_seaglider_selftest():
        root, ext = os.path.splitext(pdos_logfile_name)
        pdos_logfile_1a_name = root + ".1a" + ext
        if Strip1A.strip1A(pdos_logfile_name, pdos_logfile_1a_name):
            log_error(
                f"Couldn't strip1a {pdos_logfile_1a_name}. Skipping dive processing"
            )
            return 1
        if fc.is_gzip():
            pdos_uc_logfile_name = fc.mk_base_pdos_logfile_name()
            try:
                if BaseGZip.decompress(pdos_logfile_1a_name, pdos_uc_logfile_name) > 0:
                    log_error(f"Error decompressing {pdos_logfile_name}")
                    return 1
            except Exception:
                log_error(f"Error decompressing {pdos_logfile_name}", "exc")
                return 1

        else:
            shutil.copyfile(pdos_logfile_1a_name, fc.mk_base_pdos_logfile_name())

        _, ext = os.path.splitext(fc.full_filename())
        BaseDB.logControlFile(
            base_opts,
            fc.dive_number(),
            int(ext.lstrip(".")),
            "pdoslog",
            os.path.basename(fc.mk_base_pdos_logfile_name()),
        )
        return 0
    else:
        log_error("Don't know how to deal with a non-seaglider pdos file")
        return 1


def expunge_secrets(logfile_name):
    """Removes the sensitive parameters from a logfile

    Returns: 0 for success
             non-zero for failure
    """

    private = ["$PASSWD", "$TEL_NUM", "$TEL_PREFIX", "$ALT_TEL_NUM", "$ALT_TEL_PREFIX"]

    try:
        pub = open(logfile_name, "rb")
    except OSError:
        log_error(
            f"could not open {logfile_name} for reading - skipping secret expunge"
        )
        return 1

    public_lines = ""
    private_lines = ""

    header = True
    private_keys_found = False

    for s in pub:
        try:
            s = s.decode("utf-8")
        except UnicodeDecodeError:
            log_warning(f"Could not decode line {s} in {logfile_name} - skipping")
            continue

        if s in ("", "\n"):
            continue

        if header:
            try:
                key, _ = s.split(":")
            except ValueError:
                log_error("trying to split header line " + s)
                return 1

            private_lines = private_lines + s
            public_lines = public_lines + s
            if key == "data":
                header = False
        else:
            try:
                key, _ = s.split(",", 1)
            except ValueError:
                try:
                    key, _ = s.split("=", 1)
                except ValueError:
                    log_error("trying to split data line " + s)
                    return 1

            if key in private:
                private_lines = private_lines + s
                private_keys_found = True
            else:
                public_lines = public_lines + s

    pub.close()

    if private_keys_found:
        base, _ = os.path.splitext(logfile_name)
        try:
            pvt = open(base + ".pvt", "w")
        except OSError:
            log_error("could not open " + base + ".pvt" + " for writing")
            return 1
        try:
            pub = open(logfile_name, "w")
        except OSError:
            log_error("could not open " + logfile_name + " for writing")
            return 1

        pub.write(public_lines)
        pvt.write(private_lines)

        pub.close()
        pvt.close()

        os.chmod(base + ".pvt", 0o660)
    else:
        log_info(f"No private keys found in {logfile_name}")
    return 0


def expunge_secrets_st(selftest_name):
    """Removes the sensitive parameters from a revE selftest

    Returns: 0 for success
             non-zero for failure
    """

    private = ("password = ", "telnum = ", "altnum = ")

    try:
        pub = open(selftest_name, "rb")
    except OSError:
        log_error(
            f"could not open {selftest_name} for reading - skipping secret expunge"
        )
        return 1

    public_lines = b""
    private_lines = b""

    base, _ = os.path.splitext(selftest_name)
    pvt_name = base + ".pvtst"

    private_keys_found = False

    line_count = 0
    for raw_line in pub:
        line_count += 1  # noqa: SIM113
        try:
            s = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            log_warning(
                f"Could not decode line {line_count} in {selftest_name} - assuming no secret"
            )
            public_lines = public_lines + raw_line
        else:
            if any(k in s for k in private):
                private_lines = private_lines + raw_line
                private_keys_found = True
            else:
                public_lines = public_lines + raw_line

    pub.close()

    if private_keys_found:
        try:
            pvt = open(pvt_name, "wb")
        except OSError:
            log_error("could not open " + pvt_name + " for writing")
            return 1
        try:
            pub = open(selftest_name, "wb")
        except OSError:
            log_error("could not open " + selftest_name + " for writing")
            return 1

        pub.write(public_lines)
        pvt.write(private_lines)

        pub.close()
        pvt.close()

        os.chmod(pvt_name, 0o660)
    else:
        log_info(f"No private keys found in {selftest_name}")
    return 0


def run_extension_script(script_name, script_args):
    """Attempts to execute a script named under a shell context

    Output is recorded to the log, error code is ignored, no timeout enforced
    """
    if os.path.exists(script_name):
        log_info(f"Processing {script_name}")
        cmdline = f"{script_name} "
        if script_args:
            for i in script_args:
                cmdline = f"{cmdline} {i} "
        log_debug(f"Running ({cmdline})")
        try:
            (_, fo) = Utils.run_cmd_shell(cmdline)
        except Exception:
            log_error(f"Error running {cmdline}", "exc")
        else:
            for f in fo:
                log_info(f)
            fo.close()
    else:
        log_info(f"Extension script {script_name} not found")


def remove_dive_from_dict(complete_files_dict, dive_num, instrument_id):
    """Returns an updated complete_files_dict with all files from a dive_num removed"""
    new_dict = {}
    for k, v in complete_files_dict.items():
        fc = FileMgr.FileCode(k, instrument_id)
        if fc.is_seaglider_selftest() or fc.dive_number() != dive_num:
            new_dict[k] = v
    return new_dict


def signal_handler_abort_processing(signum, frame):
    """Handles SIGUSR1 - indicates processing should stop"""
    # pylint: disable=unused-argument
    if signum == signal.SIGUSR1:
        log_warning("Caught SIGUSR1 - attempting to stop further processing")
        stop_processing_event.set()


class ProcessProgress:
    # TODO - add in comm.log data - dive_number, call_cycle, calls_made for stats building
    def __init__(self, base_opts):
        self.update_base_opts(base_opts)

        # Default section times.  Numbers from AWS instance with NFS file system
        self.section_times = {
            "setup": {"yellow": 6.0, "red": 11.0},
            "dive_files": {"yellow": 9.0, "red": 18.0},
            "per_dive_netcdfs": {"yellow": 14.0, "red": 29.0},
            "parquet_generation": {"yellow": 7.0, "red": 20.0},
            "backup_files": {"yellow": 2.0, "red": 4.0},
            "flight_model": {"yellow": 22.0, "red": 45.0},
            "per_dive_scripts": {"yellow": 2.0, "red": 4.0},
            "update_db": {"yellow": 3.0, "red": 6.0},
            "per_dive_plots": {"yellow": 182.0, "red": 364.0},
            "per_dive_extensions": {"yellow": 5.0, "red": 10.0},
            "mission_profile": {"yellow": 125.0, "red": 250.0},
            "mission_timeseries": {"yellow": 125.0, "red": 250.0},
            "mission_plots": {"yellow": 90.0, "red": 180.0},
            "mission_kml": {"yellow": 128.0, "red": 256.0},
            "mission_early_extensions": {"yellow": 60.0, "red": 120.0},
            "mission_extensions": {"yellow": 60.0, "red": 120.0},
            "notifications": {"yellow": 8.0, "red": 15.0},
        }
        self.times = {k: {"start": 0, "stop": 0} for k in self.section_times}

    def update_base_opts(self, base_opts):
        self.glider_id = base_opts.instrument_id
        self.job_id = base_opts.job_id
        self.mission_dir = pathlib.Path(base_opts.mission_dir)
        # TODO - possibly drop
        self.base_opts = base_opts

    def write_stats(self):
        # TODO - convert to write to a database - under option (off by default)
        log_info("Base.py::main() stats")
        for k, v in self.times.items():
            log_info(f"{k}:{v['stop']-v['start']:.3f}")

    def process_progress(
        self, section: str, action: str, send: bool = True, reason: str | None = None
    ) -> None:
        """Notifiy vis of progress through main() and calcuate runtime stats"""

        if section not in self.section_times:
            log_warning("Uknown section name {section}")
            return

        t0 = time.time()
        if action in ("start", "stop"):
            try:
                self.times[section][action] = t0
            except KeyError:
                log_error(f"Uknown section:{section}", "exc")

        if send:
            msg = {
                "section": section,
                "glider": self.glider_id,
                "action": action,
                "time": float(f"{t0:.3f}"),
                "id": self.job_id,
                "yellow": self.section_times[section]["yellow"],  # warning_time_length
                "red": self.section_times[section]["red"],  # probably_stuck_time_length
            }
            if reason:
                msg["reason"] = reason
            payload = orjson.dumps(msg).decode("utf-8")
            # log_info(payload)
            Utils.notifyVis(
                self.glider_id,
                "proc-progress",
                payload,
            )


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Command line driver for the all basestation processing.

    Base.py is normally invoked as part of the glider logout sequence, but it
    can be run from the command line.  It is best to run from the glider
    account.  Running this process multiple times is not detremental - no files
    from the glider are destroyed or altered as part of this processing.


    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    data_product_file_names = []
    failed_profiles = []
    incomplete_files = []

    instrument_id = None
    comm_log = None

    failed_mission_timeseries = False
    failed_mission_profile = False

    mission_profile_name = None
    mission_timeseries_name = None

    # Get options
    base_opts = BaseOpts.BaseOptions(
        "Command line driver for the all basestation processing.",
        cmdline_args=cmdline_args,
    )

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    # Initialize log
    BaseLogger(base_opts, include_time=True)

    Utils.check_versions()

    # Reset priority
    if base_opts.nice:
        try:
            os.nice(base_opts.nice)
        except Exception:
            log_error("Setting nice to %d failed" % base_opts.nice)

    # Check for required "options"
    if not base_opts.mission_dir:
        print(main.__doc__)
        log_critical("Dive directory must be supplied. See Base.py -h")
        return 1

    if not os.path.exists(base_opts.mission_dir):
        log_critical(
            f"Dive directory {base_opts.mission_dir} does not exist - bailing out"
        )
        return 1

    if PlotUtils.setup_plot_directory(base_opts):
        log_error("Failed to setup plot directory - no plots being generated")

    if base_opts.generate_parquet and Utils.setup_parquet_directory(base_opts):
        log_error(
            "Failed to setup parquet directory - no parquet files will be generated"
        )

    if base_opts.daemon and Daemon.createDaemon(base_opts.mission_dir, False):
        log_error("Could not launch as a daemon - continuing synchronously")

    cmdline = ""
    for i in sys.argv:
        cmdline += f"{i} "

    log_info(f"Invoked with command line [{cmdline}]")

    if cmdline_args:
        cmdline_args_str = ""
        for ii in cmdline_args:
            cmdline_args_str += f"{ii} "
        log_info(f"cmdline_args [{cmdline_args_str}]")

    log_info(f"PID:{os.getpid():d} job_id:{base_opts.job_id}")

    po = ProcessProgress(base_opts)
    po.process_progress("setup", "start", send=False)

    # sleep_secs = 0
    # log_info(f"Sleeping for {sleep_secs} secs")
    # time.sleep(sleep_secs)

    sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")

    # If present, this file indicates that FMS, MMT, MMP, MakeKML and WholeMission plots should be skipped
    go_fast_file = pathlib.Path(base_opts.mission_dir).joinpath(".go_fast")

    calib_consts = CalibConst.getSGCalibrationConstants(
        sg_calib_file_name, ignore_fm_tags=not base_opts.ignore_flight_model
    )
    if not calib_consts:
        log_warning(f"Could not process {sg_calib_file_name}")

    # These functions reset large blocks of global variables being used in other modules that
    # assume an initial value on first load, then are updated throughout the run.  The call
    # here sets back to the initial state to handle multiple runs under pytest
    set_globals()
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    FlightModel.set_globals()

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

    # Update local lists from loggers
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if "known_files" in d:
            for b in d["known_files"]:
                known_files.append(b)

        if "known_mailer_tags" in d:
            for k in d["known_mailer_tags"]:
                known_mailer_tags.append(k)

        if "known_ftp_tags" in d:
            for k in d["known_ftp_tags"]:
                known_ftp_tags.append(k)

        if "eng_file_reader" in d and "logger_prefix" in d:
            logger_eng_readers[d["logger_prefix"]] = d["eng_file_reader"]

    log_debug(f"known_files = {known_files}")
    log_debug(f"known_mailer_tags = {known_mailer_tags}")
    log_debug(f"known_ftp_tags = {known_ftp_tags}")
    log_debug(f"logger_eng_readers = {logger_eng_readers}")

    # TODO - Check for installed tools

    # Record start of conversion time
    processing_start_time = time.gmtime(time.time())
    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", processing_start_time)
    )

    # Parse comm log
    (comm_log, _, _, _, _) = CommLog.process_comm_log(
        os.path.join(base_opts.mission_dir, "comm.log"),
        base_opts,
        known_commlog_files=known_files,
    )
    if comm_log is None:
        log_critical("Could not process comm.log -- bailing out")
        Utils.cleanup_lock_file(base_opts, base_lockfile_name)
        return 1

    # Check for resends in the last session
    for filename, retries in comm_log.last_surfacing().file_retries.items():
        log_warning(f"{filename} resent {retries} times", alert="FILE_RETRY")

    # sys.stdout.write("Transfer Methods")
    # for i in comm_log.file_transfer_method.keys():
    #    sys.stdout.write("%s = %s\n" % (i, comm_log.file_transfer_method[i]))

    # Collect the things we'll need for later processing
    instrument_id = comm_log.get_instrument_id()
    if not instrument_id:
        head, tail = os.path.split(
            os.path.abspath(os.path.expanduser(base_opts.mission_dir))
        )
        try:
            instrument_id = int(tail[2:5])
        except ValueError:
            log_critical("Could not determine the glider's id")

        if not instrument_id:
            if base_opts.instrument_id is not None:
                instrument_id = int(base_opts.instrument_id)
            else:
                instrument_id = 0
    else:
        base_opts.instrument_id = instrument_id

    log_info(f"Instrument ID = {str(instrument_id)}")

    po.update_base_opts(base_opts)

    # Catch signal from later started processing
    signal.signal(signal.SIGUSR1, signal_handler_abort_processing)
    base_opts.stop_processing_event = stop_processing_event

    # Check for lock file - do this after processing the comm log so we have the glider id
    lock_file_pid = Utils.check_lock_file(base_opts, base_lockfile_name)
    if lock_file_pid < 0:
        log_error("Error accessing the lockfile - proceeding anyway...")
    elif lock_file_pid > 0:
        # The PID still exists
        log_warning(
            "Previous conversion process (pid:%d) still exists - signalling process to complete"
            % lock_file_pid
        )
        os.kill(lock_file_pid, signal.SIGUSR1)
        if Utils.wait_for_pid(lock_file_pid, previous_conversion_time_out):
            # The alternative here is to try and kill the process:
            # os.kill(lock_file_pid, signal.SIGKILL)
            lock_file_msg = (
                "Process pid:%d did not respond to sighup after %d seconds - bailing out"
                % (lock_file_pid, previous_conversion_time_out)
            )
            log_error(lock_file_msg)
            if not base_opts.local:
                BaseDotFiles.process_pagers(
                    base_opts,
                    instrument_id,
                    ("alerts",),
                    pagers_convert_msg=lock_file_msg,
                )
                BaseCtrlFiles.process_pagers_yml(
                    base_opts,
                    instrument_id,
                    ("alerts",),
                    pagers_convert_msg=lock_file_msg,
                )
            return 1
        else:
            log_info(
                "Previous conversion process (pid:%d) apparently received the signal - proceeding"
                % lock_file_pid
            )
    else:
        # No lock file - move along
        pass

    Utils.create_lock_file(base_opts, base_lockfile_name)

    if not base_opts.local:
        BaseDotFiles.process_pagers(
            base_opts,
            instrument_id,
            ("lategps", "recov", "critical", "drift"),
            comm_log=comm_log,
        )
        BaseCtrlFiles.process_pagers_yml(
            base_opts,
            instrument_id,
            ("lategps", "recov", "critical", "drift"),
            comm_log=comm_log,
        )

    log_info("Processing comm_merged.log")
    history_logfile_name = os.path.join(base_opts.mission_dir, "history.log")
    if os.path.exists(history_logfile_name):
        try:
            command_list_with_ts = CommLog.process_history_log(history_logfile_name)
        except Exception:
            log_error(
                "History file processing threw an exception - no merged file produced",
                "exc",
            )
        else:
            new_list_with_ts = CommLog.merge_lists_with_ts(
                comm_log.raw_lines_with_ts, command_list_with_ts
            )
            comm_log_merged_name = os.path.join(
                base_opts.mission_dir, "comm_merged.log"
            )
            try:
                comm_log_merged = open(comm_log_merged_name, "w")
            except OSError as exception:
                log_error(
                    "Could not open %s (%s) - no merged comm log created"
                    % (comm_log_merged_name, exception.args)
                )
            else:
                for i in new_list_with_ts:
                    comm_log_merged.write(f"{i[0]:.0f}: {i[1]}\n")
                comm_log_merged.close()

    log_info("Finished processing comm_merged.log")

    # If this is a version 65 glider, convert the files first
    if base_opts.ver_65:
        file_names = Ver65.get_ver_65_conv_file_names(base_opts.mission_dir)
        if not file_names:
            log_info("No version 65 files found")
        else:
            file_names = Ver65.select_basestation_files(file_names)
            Ver65.conv_ver_65_files(base_opts.mission_dir, file_names)

        # Handle the zipped FLASH file
        flash_file_name = os.path.join(base_opts.mission_dir, "FLASH.gz")
        if os.path.exists(flash_file_name):
            (
                rename_divenum,
                rename_call_counter,
            ) = comm_log.get_last_dive_num_and_call_counter()
            # pdos_log_name = "sg%04dpz.%03d" % (comm_log.last_surfacing().dive_num, comm_log.last_surfacing().calls_made)
            pdos_log_name = "sg%04dpz.%03d" % (rename_divenum, rename_call_counter)
            pdos_log_name = os.path.join(base_opts.mission_dir, pdos_log_name)
            log_info(f"Moving {flash_file_name} to {pdos_log_name}")
            shutil.move(flash_file_name, pdos_log_name)

        # Handle the FLASH file
        flash_file_name = os.path.join(base_opts.mission_dir, "FLASH")
        if os.path.exists(flash_file_name):
            (
                rename_divenum,
                rename_call_counter,
            ) = comm_log.get_last_dive_num_and_call_counter()
            if rename_divenum is None:
                rename_divenum = 0
                log_error("No DiveNum found in comm.log - useing 0 as default")
            if rename_call_counter is None:
                rename_call_counter = 0
                log_error("No CallCounter found in comm.log - useing 0 as default")
            # pdos_log_name = "sg%04dpu.%03d" % (comm_log.last_surfacing().dive_num, comm_log.last_surfacing().calls_made)
            pdos_log_name = "sg%04dpu.%03d" % (rename_divenum, rename_call_counter)
            pdos_log_name = os.path.join(base_opts.mission_dir, pdos_log_name)
            log_info(f"Moving {flash_file_name} to {pdos_log_name}")
            shutil.move(flash_file_name, pdos_log_name)

        # Unzip parm file
        # First - strip 1a
        parms_zipped_file_name = os.path.join(base_opts.mission_dir, "parms.gz")
        if os.path.exists(parms_zipped_file_name):
            root, ext = os.path.splitext(parms_zipped_file_name)
            parms_zipped_file_name_1a = root + ".1a" + ext
            if Strip1A.strip1A(parms_zipped_file_name, parms_zipped_file_name_1a):
                log_error(
                    f"Couldn't strip1a {parms_zipped_file_name_1a}. Skipping processing"
                )
                # Proceed anyway
            else:
                parms_file_name = os.path.join(base_opts.mission_dir, "parms")
                if BaseGZip.decompress(parms_zipped_file_name_1a, parms_file_name) > 0:
                    log_error(
                        f"Problem decompressing {parms_zipped_file_name} - skipping"
                    )
                else:
                    os.remove(parms_zipped_file_name_1a)
                    os.remove(parms_zipped_file_name)

        # Handle the parms files
        parms_file_name = os.path.join(base_opts.mission_dir, "parms")
        if os.path.exists(parms_file_name):
            (
                rename_divenum,
                rename_call_counter,
            ) = comm_log.get_last_dive_num_and_call_counter()
            # parms_name = "parms.%04dpu.%03d" % (comm_log.last_surfacing().dive_num, comm_log.last_surfacing().calls_made)
            parms_name = "parms.%d.%d" % (rename_divenum, rename_call_counter)
            parms_name = os.path.join(base_opts.mission_dir, parms_name)
            log_info(f"Moving {parms_file_name} to {parms_name}")
            shutil.move(parms_file_name, parms_name)

    # fragment_size = comm_log.last_fragment_size()
    # if(fragment_size is None):
    #    log_error("No complete surfacings found in comm.log with valid fragment size - assuming 4K fragment size")
    #    fragment_size = 4096
    # fragment_dict = comm_log.get_fragment_dictionary()
    fragment_size_dict = comm_log.get_fragment_size_dict()

    # Collect all files to be processed - be sure to include all files, including the flash files
    file_collector = FileMgr.FileCollector(base_opts.mission_dir, instrument_id)

    # Ensure that all pre-processed files are readable by all
    # pre_proc_files = file_collector.get_pre_proc_files()
    # GBS 2022/06/17 - this was essentially a hack for not setting the umask correctly
    # and long standing decision to have xmodem files get created for 0640 permissions
    # Both correct with this checkin
    #
    # for file_name in pre_proc_files:
    #    os.chmod(file_name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

    # Read cache for conversions done thus far
    if base_opts.force:
        complete_files_dict = {}
        processed_pdos_logfiles_dict = {}
    else:
        try:
            complete_files_dict, processed_pdos_logfiles_dict = read_processed_files(
                base_opts.mission_dir, instrument_id
            )
        except OSError as exception:
            log_critical(
                f"Error opening processed dives conf file ({exception.args}) - exiting"
            )
            Utils.cleanup_lock_file(base_opts, base_lockfile_name)
            return 1
        if base_opts.reprocess:
            for ff in list(complete_files_dict.keys()):
                fc = FileMgr.FileCode(ff, instrument_id)
                if (
                    fc.is_seaglider() or fc.is_logger()
                ) and fc.dive_number() == base_opts.reprocess:
                    del complete_files_dict[ff]
    po.process_progress("setup", "stop", send=False)
    po.process_progress("dive_files", "start")

    # Start with self tests
    log_info("Processing seaglider selftests")
    new_selftests_processed = []
    selftests_not_processed = []

    log_debug(f"Selftests found: {pprint.pformat(file_collector.all_selftests)}")

    for i in file_collector.all_selftests:
        selftest_files = file_collector.get_pre_proc_selftest_files(i)
        # if i in list(fragment_dict.keys()):
        #     fragment_size = fragment_dict[i]
        # else:
        #     fragment_size = 8192
        #     log_warning(
        #         "No fragment size found for %s - using %d as default"
        #         % (i, fragment_size)
        #     )
        selftest_processed = process_dive_selftest(
            base_opts,
            selftest_files,
            i,
            fragment_size_dict,
            calib_consts,
            instrument_id,
            comm_log,
            complete_files_dict,
            incomplete_files,
        )
        if selftest_processed > 0:
            new_selftests_processed.append(i)
        elif selftest_processed < 0:
            selftests_not_processed.append(i)

    # Notification
    if new_selftests_processed:
        log_info(f"Processed selftests(s) {new_selftests_processed}")
    else:
        log_info("No new selftests to processed")

    log_info("Processing pdoscmd.bat logs")

    new_pdos_logfiles_processed = []
    pdos_logfile_names = file_collector.get_pdoscmd_log_files()
    for i in pdos_logfile_names:
        log_debug(f"Checking {i} for processing")

        if (
            os.path.basename(i) not in processed_pdos_logfiles_dict
            or os.path.getmtime(os.path.join(base_opts.mission_dir, i))
            > processed_pdos_logfiles_dict[os.path.basename(i)]
        ) and not process_pdoscmd_log(base_opts, i, instrument_id):
            new_pdos_logfiles_processed.append(os.path.basename(i))

    # PDos logs notification
    if new_pdos_logfiles_processed:
        log_info(f"Processed pdos logfile(s) {new_pdos_logfiles_processed}")
    else:
        log_info("No pdos logfiles found to process")

    # Update the processed files
    for i in new_pdos_logfiles_processed:
        processed_pdos_logfiles_dict[i] = time.time()

    # Iterate over the dives and process the files
    log_info("Processing dive(s)")

    new_dives_processed = []
    dives_not_processed = []

    for i in file_collector.all_dives:
        dive_files = file_collector.get_pre_proc_dive_files(i)
        # if i in list(fragment_dict.keys()):
        #     fragment_size = fragment_dict[i]
        # else:
        #     fragment_size = 8192
        #     log_warning(
        #         "No fragment size found for dive %s - using %d as default"
        #         % (i, fragment_size)
        #     )
        dive_processed = process_dive_selftest(
            base_opts,
            dive_files,
            i,
            fragment_size_dict,
            calib_consts,
            instrument_id,
            comm_log,
            complete_files_dict,
            incomplete_files,
        )
        if dive_processed > 0:
            new_dives_processed.append(i)
        elif dive_processed < 0:
            dives_not_processed.append(i)

    # Dive processing notification
    if new_dives_processed:
        log_info(f"Processed dive(s) {new_dives_processed}")
    else:
        log_warning("No dives to process")

    # When netcdf output is enabled, defer writing out processed files until after netcdf creation
    if not (
        base_opts.make_dive_profiles
        or base_opts.make_mission_profile
        or base_opts.make_mission_timeseries
    ):
        write_processed_dives(
            base_opts.mission_dir, complete_files_dict, processed_pdos_logfiles_dict
        )
    po.process_progress("dive_files", "stop")

    #
    # Per dive profile, netcdf and KKYY file processing
    #
    nc_dive_file_names = []
    nc_files_created = []
    if (
        base_opts.make_dive_profiles
        or base_opts.make_mission_profile
        or base_opts.make_mission_timeseries
    ):
        po.process_progress("per_dive_netcdfs", "start")
        if not base_opts.skip_flight_model and base_opts.backup_flight:
            # Start with a fresh flight directory
            flight_dir = os.path.join(base_opts.mission_dir, "flight")
            flight_dir_backup = os.path.join(
                base_opts.mission_dir, f"flight_{time.strftime('%Y%m%d_%H%M%S')}"
            )
            if os.path.exists(flight_dir):
                log_info(
                    f"Backing up {flight_dir} to {flight_dir_backup} due to --force option"
                )
                try:
                    shutil.move(flight_dir, flight_dir_backup)
                except Exception:
                    log_error(
                        "Failed to move %s to %s - profiles will use existing flight model data"
                        % (flight_dir, flight_dir_backup),
                        "exc",
                    )

        # Process network files to netcdf
        network_files_to_process = []
        for file_name in processed_other_files:
            fc = FileMgr.FileCode(file_name, instrument_id)
            if fc.is_processed_network_log() or fc.is_processed_network_profile():
                network_files_to_process.append(file_name)

        if network_files_to_process:
            BaseNetwork.make_netcdf_network_files(
                network_files_to_process, processed_other_files
            )
            for ncf in processed_other_files:
                if ".ncdf" in ncf:
                    BaseDB.loadDB(base_opts, ncf, run_dive_plots=False)

        # Process regular files
        dives_to_profile = []  # A list of basenames to profile

        # log_info("processed_eng_and_log_files (%s)" % processed_eng_and_log_files)
        # log_info("processed_logger_eng_files (%s)" % processed_logger_eng_files)

        dive_nums_to_process = []
        # 1) Walk the seaglider log and eng files - add to dives to process, if both the
        for log_eng_file_name in processed_eng_and_log_files:
            _, tail = os.path.split(log_eng_file_name)
            dive_nums_to_process.append(int(tail[4:8]))

        # 2) Walk the logger eng files - add to dives to process
        for eng_file_name in processed_logger_eng_files:
            _, tail = os.path.split(eng_file_name)
            dive_nums_to_process.append(int(tail[6:10]))

        dive_nums_to_process = sorted(Utils.unique(dive_nums_to_process))
        log_info(f"Dives to process = {dive_nums_to_process}")

        # 3) Walk dives to process - if the seaglider log and eng files exists, we can proceed
        #                            add in any logger eng files that might exists (regular file in home directory and any sub-directories)
        for d in dive_nums_to_process:
            seaglider_eng_file_name = "%sp%03d%04d.eng" % (
                base_opts.mission_dir,
                instrument_id,
                d,
            )
            seaglider_log_file_name = "%sp%03d%04d.log" % (
                base_opts.mission_dir,
                instrument_id,
                d,
            )
            # log_info("%s:%s" % ( seaglider_eng_file_name, seaglider_log_file_name))
            if os.path.exists(seaglider_eng_file_name) and os.path.exists(
                seaglider_log_file_name
            ):
                dives_to_profile.append(seaglider_log_file_name)

        # Find any associated logger eng files for each dive in dives_to_profile
        logger_eng_files = FileMgr.find_dive_logger_eng_files(
            dives_to_profile, base_opts, instrument_id, init_dict
        )

        # Now, walk the list and create the profiles
        for dive_to_profile in dives_to_profile:
            head, tail = os.path.splitext(dive_to_profile)
            log_info(f"Processing ({head}) for profiles")
            log_file_name = head + ".log"
            eng_file_name = head + ".eng"
            if base_opts.make_dive_profiles:
                nc_dive_file_name = head + ".nc"
            else:
                nc_dive_file_name = None

            retval = None
            dive_num = FileMgr.get_dive(eng_file_name)

            # log_info("logger_eng_files = %s" % logger_eng_files[dive_to_profile])

            try:
                (retval, nc_dive_file_name) = MakeDiveProfiles.make_dive_profile(
                    True,
                    dive_num,
                    eng_file_name,
                    log_file_name,
                    sg_calib_file_name,
                    base_opts,
                    nc_dive_file_name,
                    # logger_ct_eng_files=logger_ct_eng_files[dive_to_profile],
                    logger_eng_files=logger_eng_files[dive_to_profile],
                )
            except KeyboardInterrupt:
                log_error(
                    "MakeDiveProfiles caught a keyboard exception - bailing out", "exc"
                )
                return 1
            except Exception:
                log_error(
                    f"MakeDiveProfiles raised an exception - dive profiles not created for {head}",
                    "exc",
                )
                log_info("Continuing processing...")
                failed_profiles.append(dive_num)
                # Edit complete files dictionary to remove any files associated with this dive
                complete_files_dict = remove_dive_from_dict(
                    complete_files_dict, dive_num, instrument_id
                )
            else:
                # Edit complete files dictionary to remove any files associated with this dive
                # if there is no ncf file generated and we didn't skip on purpose
                if not nc_dive_file_name and retval != 2:
                    complete_files_dict = remove_dive_from_dict(
                        complete_files_dict, dive_num, instrument_id
                    )
                # Even if the processing failed, we may get a netcdf files out
                if nc_dive_file_name:
                    nc_files_created.append(nc_dive_file_name)

                if retval == 1:
                    log_error(f"Failed to create profiles for {head}")
                    failed_profiles.append(dive_num)
                elif retval == 2:
                    log_info(f"Skipped creating profiles for {head}")
                else:
                    # Add to list of data product files created/updated
                    if nc_dive_file_name:
                        data_product_file_names.append(nc_dive_file_name)
                        nc_dive_file_names.append(nc_dive_file_name)

        write_processed_dives(
            base_opts.mission_dir, complete_files_dict, processed_pdos_logfiles_dict
        )

        if not dives_to_profile:
            log_info("No dives found to profile")
        po.process_progress("per_dive_netcdfs", "stop")
    else:
        po.process_progress("per_dive_netcdfs", "skip", reason="By option setting")
    (
        backup_dive_num,
        backup_call_cycle,
    ) = comm_log.get_last_dive_num_and_call_counter()

    po.process_progress("backup_files", "start", send=False)

    # Back up all files - using the dive # and call_cycle # from the comm log
    # Do this without regard to what dives got processed
    for known_file in known_files:
        backup_filename = os.path.join(base_opts.mission_dir, known_file)
        if os.path.exists(backup_filename):
            if backup_dive_num is not None:
                backup_target_filename = "%s.%04d.%04d" % (
                    backup_filename,
                    int(backup_dive_num),
                    int(backup_call_cycle),
                )
                log_info(f"Backing up {backup_filename} to {backup_target_filename}")
                shutil.copyfile(backup_filename, backup_target_filename)

                if "cmdfile" not in backup_filename:
                    BaseDB.logControlFile(
                        base_opts,
                        backup_dive_num,
                        backup_call_cycle,
                        os.path.basename(backup_filename),
                        os.path.basename(backup_target_filename),
                    )
            else:
                log_error(
                    f"Could not find a dive number in the comm.log - not backing up file {backup_filename}"
                )

    if backup_dive_num is not None and int(backup_dive_num) >= 1:
        cmdfile_name = (
            f"cmdfile.{int(backup_dive_num):04d}.{int(backup_call_cycle):04d}"
        )

        fullname = os.path.join(base_opts.mission_dir, cmdfile_name)
        if os.path.exists(fullname):
            BaseDB.logParameterChanges(base_opts, backup_dive_num, cmdfile_name)

    # Known files have been back up.
    delete_files = []
    preserve_files = []
    for kf in known_files:
        delete_files.append(
            os.path.join(base_opts.mission_dir, f".delete_{kf.replace('.', '_')}")
        )
        preserve_files.append(
            os.path.join(base_opts.mission_dir, f".preserve_{kf.replace('.', '_')}")
        )

    log_debug(delete_files)

    # Two different mechanisms for removing input files after successful upload
    for ii in range(len(known_files)):
        known_file = os.path.join(base_opts.mission_dir, known_files[ii])

        if os.path.exists(delete_files[ii]):
            # See if the glider (via x!) or some other process has touched .delete_{known_file}
            # where the known_file has any . replaced with _
            # In which case, waste them both if they exist
            # Check for the .delete file first and eliminate it always since it might become stale or out of sync
            # then waste known_file if it happens to exist at this time
            try:
                os.remove(delete_files[ii])
            except OSError:
                log_error(f"Unable to remove {delete_files[ii]} -- permissions?")

            if os.path.exists(known_file):
                log_info(f"Deleting {known_file}")
                try:
                    os.remove(known_file)
                except OSError:
                    log_error(f"Unable to remove {known_file} -- permissions?")
        else:
            if (
                base_opts.delete_upload_files
                and not os.path.exists(preserve_files[ii])
                and known_files[ii] != "cmdfile"
                and os.path.exists(known_file)
            ):
                # Remove the uploaded file if it was transferred in the most recent comm session
                # and the size and date criteria are met
                session = comm_log.last_complete_surfacing()
                if (
                    known_files[ii] in session.file_stats
                    and time.mktime(session.disconnect_ts)
                    > os.stat(known_file).st_mtime
                ):
                    if (
                        session.file_stats[known_files[ii]].receivedsize
                        != os.stat(known_file).st_size
                    ):
                        log_info(
                            "File %s appear to be uploaded, but file size does not match (%d:%d) - not deleting"
                            % (
                                known_file,
                                session.file_stats[known_files[ii]].receivedsize,
                                os.stat(known_file).st_size,
                            )
                        )
                    else:
                        try:
                            os.unlink(known_file)
                        except Exception:
                            log_error(f"Could not remove uploaded file {known_file}")
                        else:
                            log_info(f"{known_file} was uploaded and deleted")

    po.process_progress("backup_files", "stop", send=False)

    if base_opts.make_dive_profiles:
        last_session = comm_log.last_surfacing()
        if go_fast_file.exists():
            po.process_progress("flight_model", "skip", reason="Per .go_fast")
            log_info("Skipping flight model processing per .go_fast")
        elif base_opts.queue_length:
            po.process_progress(
                "flight_model",
                "skip",
                reason=f"Non-zero queue length {base_opts.queue_length}",
            )
            log_info(
                f"Skipping flight model processing per non-zero queue length {base_opts.queue_length}"
            )
        elif base_opts.skip_flight_model:
            po.process_progress("flight_model", "skip", reason="Per directive")
            log_info("Skipping flight model processing per directive")
        elif last_session and last_session.recov_code and not base_opts.force:
            po.process_progress("flight_model", "skip", reason="In recovery")
            log_info(f"Skipping flight model due to recovery {last_session.recov_code}")
        # This covers the case where the first call in has a QUIT in place, but the glider isn't in recovery yet
        elif (
            last_session
            and last_session.cmd_directive
            and "QUIT" in last_session.cmd_directive
            and last_session.dive_num > FlightModel.early_volmax_adjust
            and not base_opts.force
        ):
            po.process_progress("flight_model", "skip", reason="In QUIT")
            log_info("Skipping flight model due to QUIT command")
        elif stop_processing_event.is_set():
            log_warning("Caught SIGUSR1 - bailing out")
            return 1
        else:
            # Run FlightModel here and before mission processing so combined data reflects best flight model results
            # Run before alert processing occurs so FM complaints are reported to the pilot
            po.process_progress("flight_model", "start")
            try:
                fm_nc_files_created = []
                FlightModel.main(
                    base_opts,
                    sg_calib_file_name,
                    fm_nc_files_created,
                    exit_event=stop_processing_event,
                )
            except Exception:
                log_critical("FlightModel failed", "exc")
            else:
                fm_nc_files_created = list(set(fm_nc_files_created))
                log_info(f"FM files updated {fm_nc_files_created}")
                nc_files_created += fm_nc_files_created
                nc_files_created = sorted(nc_files_created)
            po.process_progress("flight_model", "stop")
            if stop_processing_event.is_set():
                log_warning("Caught SIGUSR1 - bailing out")
                return 1

    po.process_progress("per_dive_scripts", "start", send=False)
    # Run extension scripts for any new logger files
    # TODO GBS - combine ALL logger lists and invoke the extension with the complete list
    # processed_file_names.append(processed_logger_eng_files)
    # processed_file_names.append(processed_logger_other_files)
    for k in list(processed_logger_payload_files.keys()):
        if len(processed_logger_payload_files[k]) > 0:
            run_extension_script(
                os.path.join(base_opts.mission_dir, f".{k}_ext"),
                processed_logger_payload_files[k],
            )

    # Run the post dive processing script
    run_extension_script(os.path.join(base_opts.mission_dir, ".post_dive"), None)

    po.process_progress("per_dive_scripts", "stop", send=False)

    dive_nc_file_names = []
    # Collect up the possible files
    if base_opts.make_mission_profile or base_opts.make_mission_timeseries:
        dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)

    # Add netcdf files to mission sql database
    if base_opts.add_sqlite:
        log_info("Starting netcdf load to db")
        po.process_progress("update_db", "start")

        if base_opts.force:
            try:
                BaseDB.rebuildDivesGC(base_opts, "nc")
            except Exception:
                log_error("Failed to rebuild mission sqlite db", "exc")
        else:
            for ncf in nc_files_created:
                try:
                    BaseDB.loadDB(base_opts, ncf, run_dive_plots=False)
                except Exception:
                    log_error(f"Failed to add {ncf} to mission sqlite db", "exc")
            log_info("netcdf load to db done")
        po.process_progress("update_db", "stop")
    else:
        po.process_progress("update_db", "skip", reason="Per option")

    # Parquet file generation
    if base_opts.generate_parquet and base_opts.parquet_directory is not None:
        log_info("Starting parquet from netcdf generation")
        po.process_progress("parquet_generation", "start")
        _, parquet_output_files = BaseParquet.write_parquet_files(
            [pathlib.Path(x) for x in nc_files_created], base_opts
        )
        processed_other_files.extend(parquet_output_files)

        po.process_progress("parquet_generation", "stop")
    else:
        po.process_progress("parquet_generation", "skip", reason="Per option")

    # Run and dive extensions
    processed_file_names = []
    processed_file_names.append(processed_eng_and_log_files)
    processed_file_names.append(processed_selftest_eng_and_log_files)
    # processed_file_names.append(processed_other_files)
    processed_file_names.append(data_product_file_names)
    processed_file_names.append(processed_logger_eng_files)
    processed_file_names.append(processed_logger_other_files)
    processed_file_names = Utils.flatten(processed_file_names)

    # Per-dive plotting
    if "dives" in base_opts.plot_types:
        log_info("Starting per-dive plots")
        po.process_progress("per_dive_plots", "start")
        plot_dict = BasePlot.get_dive_plots(base_opts)
        _, output_files = BasePlot.plot_dives(base_opts, plot_dict, nc_files_created)
        if stop_processing_event.is_set():
            log_warning("Caught SIGUSR1 - bailing out")
            return 1
        for output_file in output_files:
            processed_other_files.append(output_file)
        log_info("Per-dive plots complete")
        po.process_progress("per_dive_plots", "stop")
    else:
        po.process_progress("per_dive_plots", "skip", reason="Per option")

    po.process_progress("per_dive_extensions", "start")

    # Invoke extensions, if any
    BaseDotFiles.process_extensions(
        ("dive",),
        base_opts,
        sg_calib_file_name=sg_calib_file_name,
        dive_nc_file_names=dive_nc_file_names,
        nc_files_created=nc_files_created,
        processed_other_files=processed_other_files,  # Output list for extension created files
        known_mailer_tags=known_mailer_tags,
        known_ftp_tags=known_ftp_tags,
        processed_file_names=processed_file_names,
    )
    del processed_file_names

    po.process_progress("per_dive_extensions", "stop")

    (dive_num, _) = comm_log.get_last_dive_num_and_call_counter()
    # Process the urls file for the first pass (before mission profile, timeseries, etc).
    if not base_opts.local:
        BaseDotFiles.process_urls(base_opts, 1, instrument_id, dive_num)
        try:
            msg = {
                "glider": instrument_id,
                "dive": dive_num,
                "content": "files=perdive",
                "time": time.time(),
            }
            Utils.notifyVis(
                instrument_id, "urls-files", orjson.dumps(msg).decode("utf-8")
            )
        except Exception:
            log_error("notifyVis failed", "exc")

    if stop_processing_event.is_set():
        log_warning("Caught SIGUSR1 - bailing out")
        return 1

    # Begin whole mission processing here

    #
    # Create the mission profile file
    #
    if go_fast_file.exists():
        po.process_progress("mission_profile", "skip", reason="Per .go_fast")
        log_info("Skipping mission profile processing per .go_fast")
    elif base_opts.queue_length:
        po.process_progress(
            "mission_profile",
            "skip",
            reason=f"Non-zero queue length {base_opts.queue_length}",
        )
        log_info(
            f"Skipping mission_profile processing per non-zero queue length {base_opts.queue_length}"
        )
    elif not base_opts.make_mission_profile:
        po.process_progress("mission_profile", "skip", reason="By option setting")
    else:
        if len(nc_files_created) < 1:
            log_info(
                "No new dive netCDF file created - mission netCDF file will not be updated"
            )
            po.process_progress(
                "mission_profile", "skip", reason="No new dive netCDF file created"
            )
        else:
            po.process_progress("mission_profile", "start")
            try:
                (
                    mp_ret_val,
                    mission_profile_name,
                ) = MakeMissionProfile.make_mission_profile(
                    dive_nc_file_names, base_opts
                )
                if stop_processing_event.is_set():
                    log_warning("Caught SIGUSR1 - bailing out")
                    return 1
                if mp_ret_val:
                    failed_mission_profile = True
                else:
                    data_product_file_names.append(mission_profile_name)
            except Exception:
                log_error("Failed to create mission profile", "exc")
                failed_mission_profile = True
            po.process_progress(
                "mission_profile",
                "stop",
            )

    #
    # Create the mission timeseries file
    #
    if go_fast_file.exists():
        po.process_progress("mission_timeseries", "skip", reason="Per .go_fast")
        log_info("Skipping mission timeseries processing per .go_fast")
    elif base_opts.queue_length:
        po.process_progress(
            "mission_timeseries",
            "skip",
            reason=f"Non-zero queue length {base_opts.queue_length}",
        )
        log_info(
            f"Skipping mission_timeseries processing per non-zero queue length {base_opts.queue_length}"
        )
    elif not base_opts.make_mission_timeseries:
        po.process_progress("mission_timeseries", "skip", reason="By option setting")
        log_info("Skipping mission_timeseries due to option setting")
    elif len(nc_files_created) < 1:
        log_info(
            "No dive new netCDF file created - mission timeseries file will not be updated"
        )
        po.process_progress(
            "mission_timeseries", "skip", reason="No dive new netCDF file created"
        )
    else:
        po.process_progress("mission_timeseries", "start")
        try:
            (
                mt_retval,
                mission_timeseries_name,
            ) = MakeMissionTimeSeries.make_mission_timeseries(
                dive_nc_file_names, base_opts
            )
            if stop_processing_event.is_set():
                log_warning("Caught SIGUSR1 - bailing out")
                return 1
            if mt_retval == 1:
                failed_mission_timeseries = True
            elif mt_retval == 0:
                data_product_file_names.append(mission_timeseries_name)
        except Exception:
            log_error("Failed to create mission timeseries", "exc")
            failed_mission_timeseries = True
        po.process_progress("mission_timeseries", "stop")

    processed_file_names = []
    processed_file_names.append(processed_eng_and_log_files)
    processed_file_names.append(processed_selftest_eng_and_log_files)
    # processed_file_names.append(processed_other_files)
    processed_file_names.append(data_product_file_names)
    processed_file_names.append(processed_logger_eng_files)
    processed_file_names.append(processed_logger_other_files)
    processed_file_names = Utils.flatten(processed_file_names)

    # Any extensions that need to be run before the whole mission plots are generated
    if base_opts.queue_length:
        po.process_progress(
            "mission_early_extensions",
            "skip",
            reason=f"Non-zero queue length {base_opts.queue_length}",
        )
        log_info(
            f"Skipping mission_early_extension processing per non-zero queue length {base_opts.queue_length}"
        )
    else:
        po.process_progress("mission_early_extensions", "start")
        # Invoke extensions, if any
        BaseDotFiles.process_extensions(
            ("missionearly",),
            base_opts,
            sg_calib_file_name=sg_calib_file_name,
            dive_nc_file_names=dive_nc_file_names,
            nc_files_created=nc_files_created,
            processed_other_files=processed_other_files,
            known_mailer_tags=known_mailer_tags,
            known_ftp_tags=known_ftp_tags,
            processed_file_names=processed_file_names,
        )
        po.process_progress("mission_early_extensions", "stop")

    # Whole mission plotting
    if go_fast_file.exists():
        po.process_progress("mission_plots", "skip", reason="Per .go_fast")
        log_info("Skipping mission plots processing per .go_fast")
    elif base_opts.queue_length:
        po.process_progress(
            "mission_plots",
            "skip",
            reason=f"Non-zero queue length {base_opts.queue_length}",
        )
        log_info(
            f"Skipping mission_plots processing per non-zero queue length {base_opts.queue_length}"
        )
    elif "mission" not in base_opts.plot_types:
        po.process_progress("mission_plots", "skip", reason="Per option")
    else:
        po.process_progress("mission_plots", "start")
        mission_str = BasePlot.get_mission_str(base_opts, calib_consts)
        plot_dict = BasePlot.get_mission_plots(base_opts)
        _, output_files = BasePlot.plot_mission(base_opts, plot_dict, mission_str)
        if stop_processing_event.is_set():
            log_warning("Caught SIGUSR1 - bailing out")
            return 1
        for output_file in output_files:
            processed_other_files.append(output_file)
        po.process_progress("mission_plots", "stop")

    # Change to look for the a .skip_whole_mission file - to skip FMS, MMP, MMT, mission_plots and KML

    # Generate KML
    try:
        if go_fast_file.exists():
            po.process_progress("mission_kml", "skip", reason="Per .go_fast")
            log_info("Skipping mission kml processing per .go_fast")
        elif base_opts.queue_length:
            po.process_progress(
                "mission_kml",
                "skip",
                reason=f"Non-zero queue length {base_opts.queue_length}",
            )
            log_info(
                f"Skipping mission_kml processing per non-zero queue length {base_opts.queue_length}"
            )
        elif base_opts.skip_kml:
            po.process_progress("mission_kml", "skip", reason="Per option")
            log_info("Skipping mission_kml per opion")
        else:
            po.process_progress("mission_kml", "start")
            MakeKML.main(
                base_opts,
                calib_consts,
                processed_other_files,
            )
            po.process_progress("mission_kml", "stop")

    except Exception:
        log_error("Failed to generate KML", "exc")

    if stop_processing_event.is_set():
        log_warning("Caught SIGUSR1 - bailing out")
        return 1

    if base_opts.queue_length:
        po.process_progress(
            "mission_extensions",
            "skip",
            reason=f"Non-zero queue length {base_opts.queue_length}",
        )
        log_info(
            f"Skipping mission_extensions processing per non-zero queue length {base_opts.queue_length}"
        )
    else:
        po.process_progress("mission_extensions", "start")
        # Invoke extensions, if any
        BaseDotFiles.process_extensions(
            ("global", "mission"),
            base_opts,
            sg_calib_file_name=sg_calib_file_name,
            dive_nc_file_names=dive_nc_file_names,
            nc_files_created=nc_files_created,
            processed_other_files=processed_other_files,  # Output list for extension created files
            known_mailer_tags=known_mailer_tags,
            known_ftp_tags=known_ftp_tags,
            processed_file_names=processed_file_names,
        )
        po.process_progress("mission_extensions", "stop")

    del processed_file_names

    po.process_progress("notifications", "start", send=False)

    # Alert message and file processing
    alerts_d = log_alerts()
    conversion_alerts_d = log_conversion_alerts()
    pagers_convert_msg = None

    alert_warning_msg = ""

    alert_message_base_name = "alert_message.html"
    (backup_dive_num, backup_call_cycle) = comm_log.get_last_dive_num_and_call_counter()
    if backup_dive_num is not None:
        alert_message_file_name = "%s.%04d.%04d" % (
            alert_message_base_name,
            int(backup_dive_num),
            int(backup_call_cycle),
        )
    else:
        log_error(
            f"Could not find a dive number in the comm.log - using {alert_message_base_name} for alerts"
        )
        alert_message_file_name = alert_message_base_name

    alert_msg_file_name = os.path.join(base_opts.mission_dir, alert_message_file_name)

    if base_opts.base_log is not None and base_opts.base_log != "":
        conversion_log = base_opts.base_log
    else:
        conversion_log = "the conversion log"

    if (
        dives_not_processed
        or selftests_not_processed
        or incomplete_files
        or failed_profiles
        or failed_mission_profile
        or failed_mission_timeseries
        or alerts_d
    ):
        # List housekeeping
        incomplete_files = sorted(Utils.flatten(incomplete_files))
        incomplete_files = sorted(Utils.unique(incomplete_files))

        # Recomendations
        for incomplete_file in incomplete_files:
            recomendation = comm_log.check_multiple_sectors(
                incomplete_file, instrument_id
            )
            if recomendation:
                log_info(recomendation, alert=incomplete_file)

        # For now, write out to a static file with the resends
        # TODO - Full feature - check for a logout. If seen, then append to or create the
        # new pdoscmds.bat file to issue the resends
        if conversion_alerts_d:
            resend_file_name = os.path.join(
                base_opts.mission_dir, "pdoscmds.bat.resend"
            )
            with open(resend_file_name, "w") as resend_file:
                for _, alert_tuple in conversion_alerts_d.items():
                    for _, resend_cmd in alert_tuple:
                        if resend_cmd:
                            resend_file.write(f"{resend_cmd}\n")

        # Construct the pagers_convert_msg and alter_msg_file
        pagers_convert_msg = ""

        try:
            alert_msg_file = open(alert_msg_file_name, "w")
        except Exception:
            log_error("Could not open alert_msg_file_name", "exc")
            log_info("... skipping")
            alert_msg_file = None

        reboot_msg = comm_log.has_glider_rebooted()
        (
            _,
            recov_code,
            _,
            _,
        ) = comm_log.last_GPS_lat_lon_and_recov(None, None)
        if recov_code is not None and recov_code != "QUIT_COMMAND":
            recov_msg = f"In non-quit recovery {recov_code}"
        else:
            recov_msg = None

        for msg, alert_class in (
            (reboot_msg, "GLIDER_REBOOT"),
            (recov_msg, "NON_QUIT_RECOVERY"),
        ):
            if msg:
                alert_msg_file.write(
                    f'<div class="{alert_class}">\n<p><a  href="alerthelp#{alert_class}">Alert: {alert_class}</a>\n<ul>\n'
                )
                alert_msg_file.write(f"<li>CRITICAL: {msg}</li>\n")
                alert_msg_file.write("</ul></div>\n")

        f_conversion_issues = False
        if alert_msg_file and (
            dives_not_processed
            or selftests_not_processed
            or failed_profiles
            or failed_mission_profile
            or failed_mission_timeseries
            or incomplete_files
        ):
            alert_msg_file.write(
                '<div class="CONVERSION_ISSUES">\n<p><a  href="alerthelp#CONVERSION_ISSUES">Alert: CONVERSION_ISSUES</a>\n<ul>\n'
            )
            f_conversion_issues = True

        if dives_not_processed:
            tmp = f"Dive {dives_not_processed} failed to process completely."
            if alert_msg_file:
                alert_msg_file.write(f"<li>INFO: {tmp}</li>")
            pagers_convert_msg = pagers_convert_msg + tmp + "\n\n"
        if selftests_not_processed:
            tmp = f"Selftest {selftests_not_processed} failed to process completely."
            if alert_msg_file:
                alert_msg_file.write(f"<li>INFO: {tmp}</li>")
            pagers_convert_msg = pagers_convert_msg + tmp + "\n\n"
        if failed_profiles:
            tmp = f"Profiles for dive {failed_profiles} had problems during processing."
            if alert_msg_file:
                alert_msg_file.write(f"<li>INFO: {tmp}</li>")
            pagers_convert_msg = pagers_convert_msg + tmp + "\n\n"
        if failed_mission_profile:
            tmp = f"The mission profile {mission_profile_name} had problems during processing."
            if alert_msg_file:
                alert_msg_file.write(f"<li>INFO: {tmp}</li>")
            pagers_convert_msg = pagers_convert_msg + tmp + "\n\n"
        if failed_mission_timeseries:
            tmp = f"The mission timeseries {mission_timeseries_name} had problems during processing."
            if alert_msg_file:
                alert_msg_file.write(f"<li>INFO: {tmp}</li>")
            pagers_convert_msg = pagers_convert_msg + tmp + "\n\n"
        if incomplete_files:
            pagers_convert_msg = (
                pagers_convert_msg
                + "The following files were not processed completely:\n"
            )
            if alert_msg_file:
                alert_msg_file.write("<ul>\n")

            for file_name in incomplete_files:
                incomplete_file_name = os.path.abspath(
                    os.path.join(base_opts.mission_dir, file_name)
                )
                pagers_convert_msg = (
                    pagers_convert_msg + f"    {incomplete_file_name}\n"
                )
                if alert_msg_file:
                    alert_msg_file.write(
                        # '<div class="%s">\n<p>INFO: File %s was not processed completely\n'
                        # % (os.path.basename(incomplete_file_name), incomplete_file_name)
                        "<li>INFO: File %s was not processed completely</li>\n"
                        % incomplete_file_name
                    )
                    # fc = FileMgr.FileCode(incomplete_file_name, instrument_id)
                    # if fc.is_seaglider_selftest():
                    #     alert_msg_file.write(
                    #         "<!--selftest=%d-->\n"
                    #         % FileMgr.get_dive(incomplete_file_name)
                    #     )
                    # else:
                    #     alert_msg_file.write(
                    #         "<!--diveno=%d-->\n"
                    #         % FileMgr.get_dive(incomplete_file_name)
                    #     )
                if file_name in conversion_alerts_d:
                    # if alert_msg_file:
                    #    alert_msg_file.write("<ul>\n")
                    prev_full_msg = ""  # format the text of the alert
                    for msg, resend_cmd in conversion_alerts_d[file_name]:
                        full_msg = (
                            f"{msg} - consider {resend_cmd}"
                            if resend_cmd is not None
                            else msg
                        )
                        if full_msg != prev_full_msg:
                            pagers_convert_msg = (
                                pagers_convert_msg + f"        {full_msg}\n"
                            )
                            if alert_msg_file:
                                alert_msg_file.write(f"<li>INFO: {full_msg}</li>\n")
                            prev_full_msg = full_msg
                    del conversion_alerts_d[
                        file_name
                    ]  # clean up after ourselves - not clear this is needed anymore
                    # if alert_msg_file:
                    #    alert_msg_file.write("</ul>\n")
                    pagers_convert_msg = pagers_convert_msg + "\n"
                # alert_msg_file.write("</div>\n")
            if alert_msg_file:
                # alert_msg_file.write("</p>\n")
                alert_msg_file.write("</ul>\n")
                if comm_log.last_surfacing().logout_seen:
                    alert_msg_file.write(
                        # "<p>INFO: Glider logout seen  - transmissions from glider complete</p>\n"
                        "<li>INFO: Glider logout seen  - transmissions from glider complete</li>\n"
                    )
                else:
                    alert_msg_file.write(
                        # "<p>INFO: Glider logout not seen - retransmissions from glider possible</p>\n"
                        "<li>INFO: Glider logout not seen - retransmissions from glider possible</li>\n"
                    )
                alert_msg_file.write("</ul>")
        if alert_msg_file and f_conversion_issues:
            alert_msg_file.write("</div>\n")

        if pagers_convert_msg:
            if comm_log.last_surfacing().logout_seen:
                pagers_convert_msg = (
                    pagers_convert_msg
                    + "Glider logout seen - transmissions from glider complete\n"
                )
            else:
                pagers_convert_msg = (
                    pagers_convert_msg
                    + "Glider logout not seen - retransmissions from glider possible\n"
                )

        if alert_msg_file:
            for alert_topic in list(alerts_d.keys()):
                log_info("Processing " + alert_topic)
                alert_msg_file.write(
                    f'<div class="{Utils.ensure_basename(alert_topic)}">\n<p><a href="alerthelp#{alert_topic}">Alert: {alert_topic}</a>\n<ul>\n'
                )
                alert_warning_msg = alert_warning_msg + f"ALERT:{alert_topic}\n"
                for alert in alerts_d[alert_topic]:
                    alert_msg_file.write(f"<li>{alert}</li>\n")
                    alert_warning_msg = alert_warning_msg + f"    {alert}\n"
                del alerts_d[alert_topic]  # clean up
                alert_msg_file.write("</ul></p></div>\n")

            if "baselog" in os.path.basename(conversion_log):
                try:
                    _, date_str = os.path.basename(conversion_log).split("_", 1)
                except Exception:
                    log_error(f"Error processing {os.path.basename(conversion_log)}")
                else:
                    alert_msg_file.write(f"<!-- BASELOG={date_str} -->\n")
                    alert_msg_file.write(
                        f'<p>INFO: Consult <a href="BASELOGREF">{os.path.basename(conversion_log)}</a> for details</p>\n'
                    )
            else:
                alert_msg_file.write(
                    f"<p>INFO: Consult {os.path.basename(conversion_log)} for details</p>\n"
                )

        if alert_warning_msg:
            alert_warning_msg = (
                alert_warning_msg
                + f"Consult {os.path.basename(conversion_log)} for details."
            )
            log_warning(alert_warning_msg)

        if alert_msg_file:
            alert_msg_file.close()

        # Put the alert message into  the logfile
        if pagers_convert_msg != "":
            log_error(pagers_convert_msg)

        if backup_dive_num is not None and int(backup_dive_num) > 0:
            BaseDB.addValToDB(base_opts, int(backup_dive_num), "alerts", 1)
    else:
        # No alerts - remove the alert file, if it exists
        if os.path.exists(alert_msg_file_name):
            if backup_dive_num is not None and int(backup_dive_num) > 0:
                BaseDB.addValToDB(base_opts, int(backup_dive_num), "alerts", 0)
            try:
                os.remove(alert_msg_file_name)
            except Exception:
                log_error(f"Could not remove alert message file {alert_msg_file_name}")

    processed_file_names = []
    processed_file_names.append(processed_eng_and_log_files)
    processed_file_names.append(processed_selftest_eng_and_log_files)
    processed_file_names.append(processed_other_files)
    processed_file_names.append(data_product_file_names)
    # Already added above
    # for k in processed_logger_payload_files.keys():
    #     if(len(processed_logger_payload_files[k]) > 0):
    #         processed_file_names.append(processed_logger_payload_files[k])
    processed_file_names.append(processed_logger_eng_files)
    processed_file_names.append(processed_logger_other_files)
    processed_file_names = Utils.flatten(processed_file_names)

    # Remove anything that is None
    processed_file_names = [item for item in processed_file_names if item]

    processed_files_msg = f"Processing complete as of {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(time.time()))}\n"

    if processed_file_names:
        for processed_file_name in processed_file_names:
            if processed_file_name is None:
                continue
            if isinstance(processed_file_name, str):
                p = processed_file_name.replace(base_opts.mission_dir, "")
            else:
                # pathlib
                p = processed_file_name.relative_to(pathlib.Path(base_opts.mission_dir))

            processed_files_msg += f"{p}\n"

        log_info(f"Processed files msg:\n{processed_files_msg}")
    else:
        processed_files_msg += "No new files processed\n"

    # Run the post mission processing script
    run_extension_script(
        os.path.join(base_opts.mission_dir, ".post_mission"), processed_file_names
    )

    if base_opts.divetarballs != 0 and processed_file_names:
        dive_nums = []
        dive_tarballs = []
        dn = re.compile(r".*\/p.*\d\d\d(?P<divenum>\d\d\d\d).*")
        # Collect the dive numbers
        for pf in processed_file_names:
            values = dn.search(pf)
            if values and len(values.groupdict()) == 1:
                dive_nums.append(int(values.groupdict()["divenum"]))

        dive_nums = Utils.unique(dive_nums)
        log_info(f"Found files from dive/selftest {dive_nums} to build tarball(s)")
        # Build the list of files for each dive number
        for dive_num in dive_nums:
            for st in ("", "t"):
                tarfile_files = []
                # Find all files that contribute and exist
                for ext in (".eng", ".log", ".cap"):
                    file_name = os.path.join(
                        base_opts.mission_dir,
                        "p%s%03d%04d%s" % (st, instrument_id, dive_num, ext),
                    )
                    if os.path.exists(file_name):
                        tarfile_files.append(file_name)
                    else:
                        log_info(f"{file_name} does not exists")
                if st == "":
                    for logger in ("sc", "tm"):
                        for profile in ("a", "b", "c"):
                            for file_name in glob.glob(
                                os.path.join(
                                    base_opts.mission_dir,
                                    "%s%04d%s/*eng" % (logger, dive_num, profile),
                                )
                            ):
                                tarfile_files.append(file_name)

                if len(tarfile_files) == 0:
                    continue
                log_info(
                    "Tarfiles for %s %d: %s"
                    % ("selftest" if st == "t" else "dive", dive_num, tarfile_files)
                )
                tar_name = os.path.join(
                    base_opts.mission_dir,
                    "p%s%03d%04d.tar.bz2" % (st, instrument_id, dive_num),
                )
                try:
                    tf = tarfile.open(tar_name, "w:bz2", compresslevel=9)
                except Exception:
                    log_error(f"Error opening {tar_name} - skipping creation", "exc")
                    continue
                for fn in tarfile_files:
                    tf.add(fn, arcname=fn.replace(base_opts.mission_dir, "./"))
                tf.close()
                processed_file_names.append(tar_name)
                dive_tarballs.append(tar_name.replace(base_opts.mission_dir, ""))

                if base_opts.divetarballs > 0:
                    try:
                        with open(tar_name, "rb") as fi:
                            buff = fi.read()
                    except Exception:
                        log_error(
                            f"Could not process {tar_name} for fragmentation - skipping",
                            "exc",
                        )
                        continue
                    # Create fragments
                    for ii in range(100):
                        if ii * base_opts.divetarballs > len(buff):
                            break
                        tar_frag_name = os.path.join(
                            base_opts.mission_dir,
                            "p%s%03d%04d_%02d.tar.bz2"
                            % (st, instrument_id, dive_num, ii),
                        )

                        try:
                            with open(tar_frag_name, "wb") as fo:
                                fo.write(
                                    buff[
                                        ii * base_opts.divetarballs : (ii + 1)
                                        * base_opts.divetarballs
                                        if (ii + 1) * base_opts.divetarballs < len(buff)
                                        else len(buff)
                                    ]
                                )
                        except Exception:
                            log_error(
                                f"Could not process {tar_frag_name} for fragmentation - skipping",
                                "exc",
                            )
                            break
                        processed_file_names.append(tar_frag_name)
                        dive_tarballs.append(
                            tar_frag_name.replace(base_opts.mission_dir, "")
                        )

        # Send out an alert that the tarball exists
        if len(dive_tarballs):
            tarball_str = "New tarballs "
            for d in dive_tarballs:
                tarball_str += f"{d} "
            BaseDotFiles.process_pagers(
                base_opts,
                instrument_id,
                ("divetar",),
                processed_files_message=tarball_str,
            )
            BaseCtrlFiles.process_pagers_yml(
                base_opts,
                instrument_id,
                ("divetar",),
                processed_files_message=tarball_str,
            )

    # Look for capture file with critical errors
    critical_msg = ""
    prog = re.compile(r"^[-\d]*\.[\d]*,[A-Z]*\,C,.*", re.MULTILINE)
    for p in processed_file_names:
        if p is None:
            continue
        _, tail = os.path.splitext(p)
        if tail == ".cap":
            try:
                fi = open(p, "rb")
            except Exception:
                log_error("Unable to open %s (%s) - skipping" % p, "exc")
            else:
                cap_text = fi.read()
                fi.close()
                if cap_text is None:
                    continue
                line_count = 1
                cap_lines = []
                for ll in cap_text.splitlines():
                    try:
                        ll = ll.decode("utf-8")
                    except Exception:
                        log_warning(
                            f"Could not decode line number {line_count} in {p} - skipping"
                        )
                    else:
                        cap_lines.append(ll)
                    line_count += 1
                new_cap_text = "\n".join(cap_lines)
                crits = prog.findall(new_cap_text)
                num_crits = len(crits)

                f = os.path.basename(p)
                dive = int(os.path.basename(p)[4:8])

                if num_crits > 0:
                    if critical_msg == "":
                        critical_msg = (
                            "The following capture files contain critical lines:\n"
                        )
                    critical_msg += "%s (%d critical)\n" % (p, num_crits)
                    for c in crits:
                        critical_msg += f"    {c}\n"

                    if f[0] == "p" and len(f) == 12:
                        BaseDB.addValToDB(base_opts, dive, "criticals", num_crits)

                if f[0] == "p" and len(f) == 12:
                    BaseDB.addValToDB(base_opts, dive, "capture", 1)

    if critical_msg:
        log_warning(critical_msg)

    # Process pagers
    if not base_opts.local:
        BaseDotFiles.process_pagers(
            base_opts, instrument_id, ("alerts",), crit_other_message=critical_msg
        )

        BaseDotFiles.process_pagers(
            base_opts, instrument_id, ("alerts",), warn_message=alert_warning_msg
        )

        BaseDotFiles.process_pagers(
            base_opts,
            instrument_id,
            ("alerts", "comp"),
            comm_log=comm_log,
            pagers_convert_msg=pagers_convert_msg,
            processed_files_message=processed_files_msg,
        )
        #
        BaseCtrlFiles.process_pagers_yml(
            base_opts, instrument_id, ("alerts",), crit_other_message=critical_msg
        )

        BaseCtrlFiles.process_pagers_yml(
            base_opts, instrument_id, ("alerts",), warn_message=alert_warning_msg
        )

        BaseCtrlFiles.process_pagers_yml(
            base_opts,
            instrument_id,
            ("alerts", "comp"),
            comm_log=comm_log,
            pagers_convert_msg=pagers_convert_msg,
            processed_files_message=processed_files_msg,
        )
        #
        BaseDotFiles.process_ftp(
            base_opts,
            processed_file_names,
            mission_timeseries_name,
            mission_profile_name,
            known_ftp_tags,
        )

        BaseDotFiles.process_ftp(
            base_opts,
            processed_file_names,
            mission_timeseries_name,
            mission_profile_name,
            known_ftp_tags,
            ftp_type=".sftp",
        )

        BaseDotFiles.process_mailer(
            base_opts,
            instrument_id,
            known_mailer_tags,
            processed_file_names,
            mission_timeseries_name,
            mission_profile_name,
        )

        # Process the urls file for the second time
        if not base_opts.local:
            BaseDotFiles.process_urls(base_opts, 2, instrument_id, dive_num)
            try:
                msg = {
                    "glider": instrument_id,
                    "dive": dive_num,
                    "content": "files=all",
                    "time": time.time(),
                }
                Utils.notifyVis(
                    instrument_id, "urls-files", orjson.dumps(msg).decode("utf-8")
                )
            except Exception:
                log_error("notifyVis failed", "exc")

        # Notify about all WARNINGS, ERRORS and CRITICALS
        warn_errors = log_warn_errors()
        if warn_errors.getvalue():
            BaseDotFiles.process_pagers(
                base_opts,
                instrument_id,
                ("errors",),
                processed_files_message=f"From {conversion_log}\n{warn_errors.getvalue()}",
            )
            BaseCtrlFiles.process_pagers_yml(
                base_opts,
                instrument_id,
                ("errors",),
                processed_files_message=f"From {conversion_log}\n{warn_errors.getvalue()}",
            )

        tracebacks = log_tracebacks()
        if tracebacks.getvalue():
            BaseCtrlFiles.process_pagers_yml(
                base_opts,
                instrument_id,
                ("traceback",),
                processed_files_message=f"From {conversion_log}\n{tracebacks.getvalue()}",
            )

    # Optionally: Clean up intermediate (working) files here
    if base_opts.clean:
        # get updated list of intermediate files in the mission directory
        fc = FileMgr.FileCollector(base_opts.mission_dir, instrument_id)
        try:
            for file in fc.get_intermediate_files():
                if os.path.isfile(file):
                    os.remove(file)
                    log_info("Deleted intermediate file: " + os.path.basename(file))
        except Exception:
            log_debug(
                f"Error ({sys.exc_info()}) when deleting intermediate files: \n{repr(fc.get_intermediate_files())}"
            )

    Utils.cleanup_lock_file(base_opts, base_lockfile_name)
    po.process_progress("notifications", "stop", send=False)
    po.write_stats()

    # looked at processed_other_files list to decide if we should be more
    # granular about what is completed
    base_completed_name_fullpath = os.path.join(
        base_opts.mission_dir, base_completed_name
    )
    try:
        with open(base_completed_name_fullpath, "w") as file:
            file.write(
                "Finished processing "
                + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
    except Exception:
        log_error(f"Failed to open {base_completed_name_fullpath}")

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    return 0


if __name__ == "__main__":
    return_val = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove("--profile")
            prof_file_name = (
                os.path.splitext(os.path.split(sys.argv[0])[1])[0]
                + "_"
                + Utils.ensure_basename(
                    time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                + ".cprof"
            )
            # Generate line timings
            return_val = cProfile.run("main()", filename=prof_file_name)
            stats = pstats.Stats(prof_file_name)
            stats.sort_stats("time", "calls")
            stats.print_stats()
        else:
            return_val = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(return_val)
