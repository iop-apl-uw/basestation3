#! /usr/bin/env python

##
## Copyright (c) 2006-2020 by University of Washington.  All rights reserved.
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
Base.py: Main entry point for Seaglider basestation.

Cleans up and converts raw data files & organizes files associated
with dive.
"""
import cProfile
import fnmatch
import functools
import glob
import math
import os
import pprint
import pstats
import re
import shutil
import signal
import smtplib
import stat
import struct
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

from email.mime.multipart import MIMEMultipart
from email.mime.multipart import MIMEBase
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate
from email import encoders

import BaseGZip
import BaseOpts
import BaseNetCDF
import Bogue
import CalibConst
import CommLog
import Daemon
import DataFiles
import FileMgr
import FlightModel
import LogFile
import MakeDiveProfiles
import Sensors
import Strip1A
import Utils
import Ver65
from BaseLog import log_critical, log_error, log_warning, log_info, log_debug, log_conversion_alert, log_conversion_alerts, log_alert, log_alerts, BaseLogger

# TODOCC
# 1) Largest issue is to remove mismash of globals and globals passed as arguments.
#    Creation of a "global_state" class the contians the various lists and objects and that
#    is to be passed to everything along with base_opts

# Globals
file_trans_received = "r"
processed_files_cache = "processed_files.cache"
known_files = ["cmdfile", "pdoscmds.bat", "targets", "science", "tcm2mat.cal"]
known_mailer_tags = ['eng', 'log', 'pro', 'bpo', 'asc', 'cap', 'comm', 'dn_kkyy', 'up_kkyy', 'nc', 'ncf', 'mission_ts', 'mission_pro', 'bz2']
known_ftp_tags = known_mailer_tags
skip_mission_processing = False    # Set by signal handler to skip the time consuming processing of the whole mission data
base_lockfile_name = '.conversion_lock'
#pagers_ext = {'html' : lambda *args: send_email(*args, html_format=True)}
pagers_ext = {'html' : lambda base_opts, instrument_id, email_addr, subject_line, message_body: \
              send_email(base_opts, instrument_id, email_addr, subject_line, message_body, html_format=True)}
logger_eng_readers = {}  # Mapping from logger prefix to eng_file readers

comm_log = None

# inReach message sender
try:
    import InReachSend
except ImportError:
    pass
else:
    pagers_ext['inreach'] = InReachSend.send_inreach

# slack post
try:
    import SlackPost
except ImportError:
    print("Failed slack import")
else:
    pagers_ext['slack'] = SlackPost.post_slack

# AES support
def decrypt_file(in_file_name, out_file_name, mission_dir):
    """
    Stub function for decryption
    """
    # pylint: disable=W0613
    return 0

# Configuration
mail_server = 'localhost'
previous_conversion_time_out = 20  # Time to wait for previous conversion to complete

# Utility functions

# urllib override to prevent username/passwd prompting on stdin
def my_prompt_user_passwd(self, host, realm):
    """
    Stub function for user password
    """
    # pylint: disable=W0613
    return None, None

urllib.request.FancyURLopener.prompt_user_passwd = my_prompt_user_passwd

def read_processed_files(glider_dir):
    """Reads the processed file cache

       Returns: list of processed dive files and a list of processed pdos logfiles
                None for error opening the file

       Raises: IOError for file errors
    """
    log_debug("Enterting read_processed_files")

    processed_dive_file_name = glider_dir + processed_files_cache

    processed_files_dict = {}
    processed_pdos_logfiles_dict = {}
    if not os.path.exists(processed_dive_file_name):
        return (processed_files_dict, processed_pdos_logfiles_dict)

    processed_dives_file = open(processed_dive_file_name, "r")

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
                processed_pdos_logfiles_dict[raw_parts[0]] = time.mktime(time.strptime(raw_parts[1].lstrip(), '%H:%M:%S %d %b %Y %Z'))
            except (ValueError, IndexError):
                # Old way - assume the current time
                processed_pdos_logfiles_dict[raw_parts[0]] = time.time()
        elif fc.is_seaglider() or fc.is_seaglider_selftest() or fc.is_logger():
            try:
                processed_files_dict[raw_parts[0]] = time.mktime(time.strptime(raw_parts[1].lstrip(), '%H:%M:%S %d %b %Y %Z'))
            except ValueError:
                # Old format - read it in w/o regard to timezone
                processed_files_dict[raw_parts[0]] = time.mktime(time.strptime(raw_parts[1].lstrip()))
        else:
            log_error("Unknown entry %s in %s - skipping" % (raw_line, processed_files_cache))

    processed_dives_file.close()
    try:
        os.chmod(processed_dive_file_name, stat.S_IRUSR|stat.S_IWUSR|stat.S_IRGRP|stat.S_IWGRP|stat.S_IROTH|stat.S_IWOTH)
    except:
        log_error("Unable to change mode of %s" % processed_dive_file_name, 'exc')

    log_debug("Leaving read_processed_files")

    return (processed_files_dict, processed_pdos_logfiles_dict)

def write_processed_dives(glider_dir, processed_files_dict, processed_pdos_logfiles_dict):
    """Writes out the processed dive file

    Returns: 0 for success, non-zero for failure
    Raises: IOError for fil
    """
    processed_dive_file_name = glider_dir + processed_files_cache

    #processed_pdos_logfiles.sort()
    pdos_items = sorted(list(processed_pdos_logfiles_dict.items()))

    items = sorted(processed_files_dict.items())

    processed_dive_file = open(processed_dive_file_name, "w")

    processed_dive_file.write("# This file contains the dives that have been"
                              " processed and the times they were processed\n")
    processed_dive_file.write("# To force a file to be re-processed, delete the"
                              " corresponding line from this file\n")
    processed_dive_file.write("# Written %s\n"
                              % time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

    #for i in processed_pdos_logfiles:
    #    processed_dive_file.write("%s\n" % i)
    for i, j in pdos_items:
        processed_dive_file.write("%s, %s\n" % (i, time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(j))))

    for i, j in items:
        #processed_dive_file.write("%s, %.2f\n" % (i, j))
        processed_dive_file.write("%s, %s\n" % (i, time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(j))))

    processed_dive_file.close()

    return 0

def group_dive_files(dive_files):
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

def process_dive_selftest(dive_files, dive_num, fragment_size, calib_consts):
    """Given a list of files belonging to a single dive, process them

    Returns:
    -1 for failure to process
    0 for nothing to do (dive already processed)
    1 for successful processing

    """
    ret_val = 0
    force_data_processing = False

    log_debug("process_dive_selftest file list %s" % pprint.pformat(dive_files))

    # Here the order to process in
    # 1) Logfiles from the seaglider (this contains the file fragment size)
    # 2) Everything else
    #
    # Note: the old version first worked on tar files.  This can be reinstated
    # here if need be

    # Get the files into groups - a dictionary of lists
    dive_files_dict = group_dive_files(dive_files)

    log_debug("process_dive_selftest dive files dictionary %s" % pprint.pformat(dive_files_dict))

    # Process any log files from the seaglider - this is needed to understand
    # the fragment size for the given dive and must happen before processing
    # of seaglider data files
    for base, file_group in list(dive_files_dict.items()):
        # Process the file only if it hasn't been processed yet
        if check_process_file_group(base, file_group):
            fc = FileMgr.FileCode(base, instrument_id)
            if(fc.is_log() and (fc.is_seaglider() or fc.is_seaglider_selftest())):
                try:
                    #TODO - get the file fragment size back
                    pfg_retval = process_file_group(file_group, fragment_size, 0, calib_consts)
                except:
                    log_error("Could not process %s - skipping" % fc.base_name(), 'exc')
                    ret_val = -1
                else:
                    if pfg_retval:
                        log_error("Could not process %s - skipping" % fc.base_name())
                        ret_val = -1
                    else:
                        #complete_files.append(base)
                        complete_files_dict[base] = time.time()
                        del dive_files_dict[base] # All processed
                        # Force the data file to be (re)converted to generate the eng file, if it
                        # is in the list
                        if fc.make_data() in dive_files_dict:
                            force_data_processing = True
                        if ret_val == 0:
                            ret_val = 1

    # Process what's left remainder
    for base, file_group in list(dive_files_dict.items()):
        #if(complete_files.count(base) == 0):
        fc = FileMgr.FileCode(base, instrument_id)
        if(check_process_file_group(base, file_group) or (fc.is_data() and force_data_processing)):
            if((fc.is_seaglider() or fc.is_seaglider_selftest()) and fc.is_pdos_log()):
                # This is covered way before we get here.
                continue
            try:
                log_info("fragment_size = %s" % fragment_size)
                pfg_retval = process_file_group(file_group, fragment_size, 0, calib_consts)
            except:
                log_error("Could not process %s - skipping" % fc.base_name(), 'exc')
                ret_val = -1
            else:
                if pfg_retval:
                    log_error("Could not process %s - skipping" % fc.base_name())
                    ret_val = -1
                else:
                    #complete_files.append(base)
                    complete_files_dict[base] = time.time()
                    del dive_files_dict[base] # All processed
                    if ret_val == 0:
                        ret_val = 1

    log_debug("process_dive_selftest(%d) = %d" % (dive_num, ret_val))
    return ret_val

def select_fragments(file_group):
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
        if FileMgr.get_non_partial_filename(current_frag) != FileMgr.get_non_partial_filename(fragment):
            new_file_group.append(current_frag)
        current_frag = fragment
    new_file_group.append(current_frag)
    for fragment in new_file_group:
        if fragment != FileMgr.get_non_partial_filename(fragment):
            root, _ = os.path.splitext(FileMgr.get_non_partial_filename(fragment))
            defrag_file_name = root + "." + file_trans_received
            log_conversion_alert(defrag_file_name, "File %s is a PARTIAL file - consider %s" % (fragment, generate_resend(fragment)))

    return new_file_group

def generate_resend(fragment_name):
    """Given a fragment name, return the appropriate resend dive message
    """
    fragment_fc = FileMgr.FileCode(fragment_name, instrument_id)
    ret_val = ""
    if(fragment_fc.is_seaglider() or fragment_fc.is_seaglider_selftest()):
        if fragment_fc.is_log():
            ret_val = ret_val + "resend_dive /l %d" % fragment_fc.dive_number()
        elif fragment_fc.is_data():
            ret_val = ret_val + "resend_dive /d %d" % fragment_fc.dive_number()
        elif fragment_fc.is_capture():
            ret_val = ret_val + "resend_dive /c %d" % fragment_fc.dive_number()
        elif fragment_fc.is_tar():
            ret_val = ret_val + "resend_dive /t %d" % fragment_fc.dive_number()
        else:
            #Don't know about this file type
            ret_val = ret_val + "resend"

        if fragment_fc.is_fragment():
            frag_num = fragment_fc.get_fragment_counter()
            if frag_num >= 0:
                ret_val = ret_val + " %d" % frag_num
        else:
            ret_val = ret_val + "recommend resend the entire file"

    return ret_val

def check_process_file_group(base, file_group):
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

def process_file_group(file_group, fragment_size, total_size, calib_consts):
    """Given a file group - one or more fragments - process the files

    Input:
        file_group - list of fragments
        fragment_size - the size of the fragments (after all transmission artifacts have been removed)
        total_size - total size of the resulting file - 0 if not known

    Returns:
       0 success
       1 failure
    Raises:
      Any exceptions raised are considered critical errors and not expected
    """
    # pylint: disable=R0914

    ret_val = 0

    log_debug("process_file_group dictionary = %s" % pprint.pformat(file_group))
    root, ext = os.path.splitext(FileMgr.get_non_partial_filename(file_group[0]))
    defrag_file_name = root + "." + file_trans_received

    log_info("Processing %s" % root)

    file_group.sort(key=functools.cmp_to_key(FileMgr.sort_fragments))

    file_group = select_fragments(file_group)

    # Eliminate Bogue syndrome
    for bogue_file in file_group:
        # No Bogue for raw xfer
        _, t = os.path.split(bogue_file)
        log_debug("%s = %s" % (t, comm_log.find_fragment_transfer_method(t)))
        if comm_log.find_fragment_transfer_method(t) == "raw":
            continue
        try:
            i = file_group.index(bogue_file)
            file_group[i] = Bogue.Bogue(bogue_file) # replaces filename with bogue'd filename if bogue's syndrome was removed
        except:
            log_error("Exception raised in Bogue processing %s - skipping dive processing." % bogue_file)
            return 1
        else:
            if file_group[i] is None:
                log_error("Couldn't Bogue %s, got %s - skipping dive processing." % bogue_file)
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
        log_debug("fragment:%s transfer:%s logger:%s strip_files:%s"
                  % (t, comm_log.find_fragment_transfer_method(t), fc.is_logger_payload(), fc.is_logger_strip_files()))
        if comm_log.find_fragment_transfer_method(t) == "raw" \
           and not fc.is_logger_payload() \
           and not (fc.is_logger_strip_files() and fragment == last_fragment):
            fragments_1a.append(fragment)
            continue

        root, ext = os.path.splitext(fragment)
        fragment_1a = root + ".1a" + ext
        # Ignore any size issues for the last fragment or logger payload files
        if(fragment is last_fragment or fc.is_logger_payload()):
            ret_val = Strip1A.strip1A(fragment, fragment_1a)
        else:
            ret_val = Strip1A.strip1A(fragment, fragment_1a, fragment_size)
        if(ret_val and not fc.is_logger_payload()):
            log_error("Couldn't strip1a %s. Skipping dive processing" % fragment_1a)
            return 1
        fragments_1a.append(fragment_1a)

    if not fc.is_logger_payload():
        # At this point, the fragments should be of the correct size, so now we can check them
        check_file_fragments(defrag_file_name, fragments_1a, fragment_size, total_size)
    else:
        # Generic payload from the logger - hand it off to the extension and
        # skip the rest of the processing
        fragments_1a_tmp = fragments_1a
        for fragment_name in fragments_1a_tmp:
            # Returns an error only if it is a encrypted file, but there are problems in processing
            if decrypt_file(fragment_name, fragment_name, base_opts.mission_dir):
                # Pull out any fragments with problems
                incomplete_files.append(fragment_name)
                fragments_1a.remove(fragment_name)

        del fragments_1a_tmp

        tmp_processed_logger_payload_files = []
        tmp_incomplete_other_files = []
        if Sensors.process_logger_func(fc.logger_prefix(), 'process_payload_files',
                                       fragments_1a, fc, tmp_processed_logger_payload_files, tmp_incomplete_other_files) != 0:
            log_error("Problems processing logger file %s" % defrag_file_name)

        # Record the incomplte files
        for i in tmp_incomplete_other_files:
            incomplete_files.append(i)

        # Even if there are problems processing files, continue on

        #log_info(tmp_processed_logger_payload_files)
        if fc.logger_prefix() not in list(processed_logger_payload_files.keys()):
            processed_logger_payload_files[fc.logger_prefix()] = []

        for i in tmp_processed_logger_payload_files:
            processed_other_files.append(i)
            processed_logger_payload_files[fc.logger_prefix()].append(i)
        #log_info( processed_logger_payload_files )
        return 0

    # Cat the fragments together
    log_debug("About to open %s" % defrag_file_name)
    output_file = open(defrag_file_name, 'wb')

    for i in fragments_1a:
        fi = open(i, 'rb')
        data = fi.read()
        fi.close()
        output_file.write(data)

    output_file.close()

    # Returns an error only if it is a encrypted file, but there are problems in processing
    if decrypt_file(defrag_file_name, defrag_file_name, base_opts.mission_dir):
        incomplete_files.append(defrag_file_name)
        return 1

    # Now process based on the specifics of the file
    log_info("Processing %s in process_file_group" % defrag_file_name)

    # CONSIDER - add a note to the errors analysis that indicates the actual name downloaded

    # Raw processing lists
    file_list = []

    if(fc.is_tar() or fc.is_tgz() or fc.is_tjz()):
        if fc.is_tgz():
            # Use our own unzip - more robust
            head, tail = os.path.split(defrag_file_name)
            b, e = os.path.splitext(tail)
            b = "%s%s%s" % (b[0:7], 't', b[8:])
            tar_file_name = os.path.join(head, "%s%s" % (b, e))
            r_v = BaseGZip.decompress(defrag_file_name, tar_file_name)
            if r_v > 0:
                log_error("Problem gzip decompressing %s" % defrag_file_name)
            # If the file
            if os.path.exists(tar_file_name):
                defrag_file_name = tar_file_name
            else:
                ret_val = r_v
                incomplete_files.append(defrag_file_name)
        try:
            tar = tarfile.open(defrag_file_name, "r")
        except tarfile.ReadError as exception:
            log_error("Error reading %s - skipping (%s) (might be empty tarfile)" % (defrag_file_name, exception.args))
            incomplete_files.append(defrag_file_name)
            ret_val = 1
        else:
            # Loggers maintain their own name space - extract the contents of the
            # tar file and hand it of to the loggers module for further procesing
            if fc.is_logger():
                logger_file_list = []
            for tarmember in tar:
                if tarmember.isreg():
                    log_info("Extracting %s from %s to directory %s" % (tarmember.name, defrag_file_name, base_opts.mission_dir))
                    try:
                        tar.extract(tarmember.name, base_opts.mission_dir)
                    except OverflowError as exception:
                        log_warning("Potential problems extracting %s (%s)" % (tarmember.name, exception.args))
                    except struct.error as exception:
                        log_warning("Potential problems extracting %s (%s)" % (tarmember.name, exception.args))

                    tarmember_fullpath = os.path.abspath(os.path.join(base_opts.mission_dir, tarmember.name))

                    if fc.is_logger():
                        logger_file_list.append(tarmember_fullpath)
                    else:
                        file_list.append(tarmember_fullpath)
                    try:
                        os.chmod(tarmember_fullpath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
                        # CONSIDER - for loggers, leave the time stamp as is
                        os.utime(tarmember_fullpath, None)
                    except OSError as exception:
                        log_error("Could not access %s (%s) - potential problem with tar file extraction" %
                                  (tarmember_fullpath, exception.args))
                        incomplete_files.append(defrag_file_name)
                        ret_val = 1
            tar.close()

            #For loggers, hand off to logger extension
            if fc.is_logger():
                if Sensors.process_logger_func(fc.logger_prefix(), 'process_tar_members',
                                               fc, logger_file_list, processed_logger_eng_files, processed_logger_other_files) != 0:
                    log_error("Problems processing logger %s tar data" % fc.logger_prefix())

    elif fc.is_gzip():
        uc_file_name = fc.make_uncompressed()

        log_debug("Decompressing gzip %s to %s" % (defrag_file_name, uc_file_name))
        if BaseGZip.decompress(defrag_file_name, uc_file_name) > 0:
            log_error("Problem gzip decompressing %s - skipping"
                      % defrag_file_name)
            incomplete_files.append(defrag_file_name)
            ret_val = 1
        else:
            file_list.append(uc_file_name)
    elif fc.is_bzip():
        uc_file_name = fc.make_uncompressed()

        log_debug("Decompressing bzip %s to %s" % (defrag_file_name, uc_file_name))

        if Utils.bzip_decompress(defrag_file_name, uc_file_name) > 0:
            log_error("Problem bzip decompressing %s - skipping" % defrag_file_name)
            incomplete_files.append(defrag_file_name)
            ret_val = 1
        else:
            file_list.append(uc_file_name)
    elif(fc.is_seaglider and fc.is_parm_file()):
        # Process this here because the parm file has no uncompressed encoding
        # form in the file namespace
        parm_file_name = fc.mk_base_parm_name()
        if BaseGZip.decompress(defrag_file_name, parm_file_name) > 0:
            log_error("Problem decompressing %s - skipping" % defrag_file_name)
            incomplete_files.append(defrag_file_name)
            ret_val = 1
        else:
            file_list.append(defrag_file_name)
    else:
        file_list.append(defrag_file_name)

    # Do this as a list of files
    for in_file_name in file_list:
        fc = FileMgr.FileCode(in_file_name, instrument_id)
        log_debug("Content specific processing of %s" % in_file_name)
        if(fc.is_seaglider() or fc.is_seaglider_selftest()):
            if fc.is_parm_file():
                # Handled above
                pass
            elif fc.is_log():
                shutil.move(in_file_name, fc.mk_base_logfile_name())
                log_info("Removing secrets from %s" % fc.mk_base_logfile_name())
                expunge_secrets(fc.mk_base_logfile_name())
                if not fc.is_seaglider_selftest():
                    processed_eng_and_log_files.append(fc.mk_base_logfile_name())
                else:
                    processed_selftest_eng_and_log_files.append(fc.mk_base_logfile_name())

            elif fc.is_data():
                shutil.copyfile(in_file_name, fc.mk_base_datfile_name())
                sg_data_file = DataFiles.process_data_file(in_file_name, "dat", calib_consts)
                if not sg_data_file:
                    log_error("Could not process %s, skipping eng file creation" % in_file_name)
                    ret_val = 1
                else:
                    # Save the asc file out for debugging
                    sg_data_file.dat_to_asc()
                    fo = open(fc.mk_base_ascfile_name(), "w")
                    sg_data_file.dump(fo)
                    fo.close()
                    processed_other_files.append(fc.mk_base_ascfile_name())
                    # Convert to the eng file
                    sg_log_file = LogFile.parse_log_file(fc.mk_base_logfile_name(), base_opts.mission_dir, issue_warn=True)
                    if not sg_log_file:
                        log_error("Could not parse %s, skipping eng file creation" % fc.mk_base_logfile_name())
                        #Don't add defrag_file_name to the incomplete_files list on account of this
                        #TODO - consider adding to a more generic list of files that are intended outputs, but failed to
                        #be created - for the pagers below
                        ret_val = 1
                    else:
                        if sg_data_file.asc_to_eng(sg_log_file):
                            log_error("Could not convert %s to eng file" % fc.mk_base_ascfile_name())
                            ret_val = 1
                        else:
                            fo = open(fc.mk_base_engfile_name(), "w")
                            sg_data_file.dump(fo)
                            fo.close()

                # Add this to the list potential dives to be processed for
                if not fc.is_seaglider_selftest():
                    processed_eng_and_log_files.append(fc.mk_base_engfile_name())
                else:
                    processed_selftest_eng_and_log_files.append(fc.mk_base_engfile_name())

            elif fc.is_capture():
                shutil.move(in_file_name, fc.mk_base_capfile_name())
                if fc.is_seaglider_selftest():
                    log_info("Removing secrets from %s" % fc.mk_base_capfile_name())
                    expunge_secrets_st(fc.mk_base_capfile_name())

                processed_other_files.append(fc.mk_base_capfile_name())
        elif fc.is_logger():
            if fc.is_log():
                if Sensors.process_logger_func(fc.logger_prefix(), 'process_log_files', fc, processed_logger_other_files) != 0:
                    log_error("Problems processing logger file %s" % in_file_name)
            elif(fc.is_data() or fc.is_down_data() or fc.is_up_data()):
                if Sensors.process_logger_func(fc.logger_prefix(), 'process_data_files',
                                               fc, processed_logger_eng_files, processed_logger_other_files) != 0:
                    log_error("Problems processing logger file %s" % in_file_name)
            else:
                log_error("Don't know how to deal with logger file (%s) - unknown type" % in_file_name)
                ret_val = 1
        else:
            log_error("Don't know how to deal with file (%s) - unknown type" % in_file_name)
            ret_val = 1

    return ret_val

def check_file_fragments(defrag_file_name, fragment_list, fragment_size, total_size):
    """Checks that the file fragments are of a reasonable size

       Note: this function will issue incorrect diagnostics if the size of fragment is
       differnt then what is noted in the comm.log (that is, N_FILEKB has been changed)

       Returns:
          TRUE for success
          FALSE for a failure and issues a warning
    """
    ret_val = True

    if fragment_size <= 0:
        log_info("Fragment size specified is %s, skipping file fragment check." % str(fragment_size))
        return True

    # Assume sorted
    #fragment_list.sort()  #In case this hasn't already been done

    size_from_fragments = 0
    number_of_fragments = len(fragment_list)
    last_frag_expected_size = 0

    if total_size != 0:
        number_expected_fragments = math.ceil(total_size / fragment_size)
        if total_size % fragment_size > 0:
            number_expected_fragments = number_expected_fragments + 1
            last_frag_expected_size = total_size % fragment_size
        else:
            last_frag_expected_size = fragment_size

        if number_of_fragments == number_expected_fragments:
            log_debug("Got %d fragments, expected %d." %
                      (number_of_fragments, number_expected_fragments))
        elif number_of_fragments < number_expected_fragments:
            log_info("Missing fragments: total size logged was %d, got %d, expected %d." %
                     (total_size, number_of_fragments, number_expected_fragments))
        else:
            log_info("Too many fragments: total size logged was %d; got %d, expected %d." %
                     (total_size, number_of_fragments, number_expected_fragments))

    # check fragment sizes:
    fragment_cntr = 0
    for fragment in fragment_list:
        log_info("Checking fragment %s" % fragment)

        while fragment_cntr < FileMgr.get_counter(fragment):
            msg = "Fragment %d for file %s is missing" % \
                  (fragment_cntr, defrag_file_name)
            log_warning(msg)
            log_conversion_alert(defrag_file_name, msg + " - consider %s" % generate_resend(fragment))
            ret_val = False
            # See if there are more
            fragment_cntr = fragment_cntr + 1

        fragment_cntr = fragment_cntr + 1

        current_fragment_size = os.stat(fragment).st_size
        # preceeding frags must be frag_size (may be padded with \1A chars)
        if fragment_list.index(fragment) != (number_of_fragments - 1):
            if current_fragment_size != fragment_size:
                msg = "Fragment %s file size (%d) not equal to expected size (%d)" % \
                      (fragment, current_fragment_size, fragment_size)
                log_warning(msg)
                log_conversion_alert(defrag_file_name, msg + " - consider %s" % generate_resend(fragment))
                ret_val = False
            else:
                log_debug("Fragment %s size (%d) is expected." % (fragment, current_fragment_size))
        # if total_size is known, last frag size should be expected OR <= frag_size if total_size is unknown
        else:
            if total_size != 0:
                if current_fragment_size != last_frag_expected_size:
                    msg = "Final fragment %s size (%d) is not expected (should be %d)." % \
                                  (fragment, current_fragment_size, last_frag_expected_size)
                    log_warning(msg)
                    log_conversion_alert(defrag_file_name, msg + "- consider %s\n" % generate_resend(fragment))

            elif current_fragment_size > fragment_size:
                size_from_fragments += current_fragment_size
                fc = FileMgr.FileCode(fragment, instrument_id)
                if(fc.is_fragment() and not (fc.is_seaglider_selftest() and fc.is_capture())):
                    # This message only applies if the file is actually a fragment
                    msg = "Final fragment %s size (%d) is too big, expected less than or equal to %d." % \
                          (fragment, current_fragment_size, fragment_size)
                    log_warning(msg)
                    log_conversion_alert(defrag_file_name, msg + "consider %s\n" % generate_resend(fragment))

    if total_size != 0:
        if size_from_fragments != total_size:
            log_warning("Size from frags (%d) does not match logged value (%d)" % (size_from_fragments, total_size))
            ret_val = False

    return ret_val

def process_pdoscmd_log(mission_dir, pdos_logfile_name):
    """Processes a pdos_logfile.  These file names are outside the normal rules of
    file processing, so are handled in this different routine

    Return 0 for success, non-zero for failure
    """
    log_info("Processing %s" % pdos_logfile_name)

    if decrypt_file(pdos_logfile_name, pdos_logfile_name, mission_dir):
        return 1

    # N.B. No fragment checking done here - it is assumed that this file is less
    # then a fragment in size

    fc = FileMgr.FileCode(pdos_logfile_name, instrument_id)
    if(fc.is_seaglider() or fc.is_seaglider_selftest()):
        root, ext = os.path.splitext(pdos_logfile_name)
        pdos_logfile_1a_name = root + ".1a" + ext
        if Strip1A.strip1A(pdos_logfile_name, pdos_logfile_1a_name):
            log_error("Couldn't strip1a %s. Skipping dive processing" % pdos_logfile_1a_name)
            return 1
        if fc.is_gzip():
            pdos_uc_logfile_name = fc.mk_base_pdos_logfile_name()
            if BaseGZip.decompress(pdos_logfile_1a_name, pdos_uc_logfile_name) > 0:
                log_error("Error decompressing %s" % pdos_logfile_name)
                return 1
        else:
            shutil.copyfile(pdos_logfile_1a_name, fc.mk_base_pdos_logfile_name())
        return 0
    else:
        log_error("Don't know how to deal with a non-seaglider pdos file")
        return 1

def expunge_secrets(logfile_name):
    """Removes the sensitive parameters from a logfile

    Returns: 0 for success
             non-zero for failure
    """

    private = ['$PASSWD', '$TEL_NUM', '$TEL_PREFIX', '$ALT_TEL_NUM', '$ALT_TEL_PREFIX']

    try:
        pub = open(logfile_name, "r")
    except IOError:
        log_error("could not open %s for reading - skipping secret expunge" % logfile_name)
        return 1

    public_lines = ""
    private_lines = ""

    header = True
    private_keys_found = False

    for s in pub:
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
                key, _ = s.split(',', 1)
            except ValueError:
                try:
                    key, value = s.split('=', 1)
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
        except IOError:
            log_error("could not open " +  base + ".pvt" + " for writing")
            return 1
        try:
            pub = open(logfile_name, "w")
        except IOError:
            log_error("could not open " + logfile_name + " for writing")
            return 1

        pub.write(public_lines)
        pvt.write(private_lines)

        pub.close()
        pvt.close()

        os.chmod(base + ".pvt", 0o660)
    else:
        log_info("No private keys found in %s" % logfile_name)
    return 0

def expunge_secrets_st(selftest_name):
    """Removes the sensitive parameters from a revE selftest

    Returns: 0 for success
             non-zero for failure
    """

    private = ('password = ', 'telnum = ', 'altnum = ')

    try:
        pub = open(selftest_name, "rb")
    except IOError:
        log_error("could not open %s for reading - skipping secret expunge" % selftest_name)
        return 1

    public_lines = ""
    private_lines = ""

    base, _ = os.path.splitext(selftest_name)
    pvt_name = base + ".pvtst"

    private_keys_found = False

    for s in pub:
        try:
            s = s.decode('utf-8')
        except UnicodeDecodeError:
            log_warning(f"Could not decode line {s} - skipping")
            continue

        if any(k in s for k in private):
            private_lines = private_lines + s
            private_keys_found = True
        else:
            public_lines = public_lines + s

    pub.close()

    if private_keys_found:

        try:
            pvt = open(pvt_name, "w")
        except IOError:
            log_error("could not open " +  pvt_name  + " for writing")
            return 1
        try:
            pub = open(selftest_name, "w")
        except IOError:
            log_error("could not open " + selftest_name + " for writing")
            return 1

        pub.write(public_lines)
        pvt.write(private_lines)

        pub.close()
        pvt.close()

        os.chmod(pvt_name, 0o660)
    else:
        log_info("No private keys found in %s" % selftest_name)
    return 0

def send_email(base_opts, instrument_id, email_addr, subject_line, message_body, html_format=False):
    """Sends out email from glider

    Input
        instrument_id - id of glider
        email_addr - string for the email address (one address only)
        subject_line - subject line for message
        message_body - contents of message

    Returns
        0 - success
        1 - failure
    """
    if base_opts.domain_name:
        email_send_from = "sg%03d@%s" % (instrument_id, base_opts.domain_name)
    else:
        email_send_from = "sg%03d" % (instrument_id)
    from_line = "Seaglider %d <%s>" % (instrument_id, email_send_from)
    return Utils.send_email_text(base_opts, email_send_from, email_addr, from_line, subject_line, message_body, html_format=html_format)

def process_ftp(processed_file_names, mission_timeseries_name, mission_profile_name):
    """ Process the .ftp file and push the data to a ftp server
    """
    ret_val = 0
    ftp_file_name = os.path.join(base_opts.mission_dir, ".ftp")
    if not os.path.exists(ftp_file_name):
        log_info("No .ftp file found - skipping .ftp processing")
        return 0

    log_info("Starting processing on .ftp")
    try:
        ftp_file = open(ftp_file_name, "r")
    except IOError as exception:
        log_error("Could not open %s (%s) - no mail sent" % (ftp_file_name, exception.args))
        ret_val = 1
    else:
        for ftp_line in ftp_file:
            try:
                Utils.process_ftp_line(base_opts, processed_file_names, mission_timeseries_name, mission_profile_name, ftp_line, known_ftp_tags)
            except:
                log_error("Could not process %s - skipping" % ftp_line, 'exc')
    log_info("Finished processing on .ftp")
    return ret_val

def process_pagers(base_opts, instrument_id, tags_to_process, comm_log=None, session=None, pagers_convert_msg=None,
                   processed_files_message=None, msg_prefix=None, crit_other_message=None, warn_message=None):
    """Processes the .pagers file for the tags specified
    """

    pagers_file_name = os.path.join(base_opts.mission_dir, ".pagers")
    if not os.path.exists(pagers_file_name):
        log_info("No .pagers file found - skipping .pagers processing")
    else:
        tags = ""
        for t in tags_to_process:
            tags = "%s %s" % (tags, t)
        log_info("Starting processing on .pagers for %s" % tags)
        log_debug("pagers_ext = %s" % pagers_ext)
        try:
            pagers_file = open(pagers_file_name, "r")
        except IOError as exception:
            log_error("Could not open %s (%s) - no mail sent" % (pagers_file_name, exception.args))
        else:
            for pagers_line in pagers_file:
                pagers_line = pagers_line.rstrip()
                log_debug("pagers line = (%s)" % pagers_line)
                if pagers_line == "":
                    continue
                if pagers_line[0] != '#':
                    log_info("Processing .pagers line (%s)" % pagers_line)
                    pagers_elts = pagers_line.split(',')
                    email_addr = pagers_elts[0]
                    # Look for alternate sending functions
                    if(len(pagers_elts) > 1 and (pagers_elts[1] in list(pagers_ext.keys()))):
                        log_info("Using sending function %s" % pagers_elts[1])
                        send_func = pagers_ext[pagers_elts[1]]
                        pagers_elts = pagers_elts[2:]
                    else:
                        send_func = send_email
                        pagers_elts = pagers_elts[1:]

                    tags_with_fmt = ['lategps', 'gps', 'recov', 'critical']
                    known_tags = ['lategps', 'gps', 'recov', 'critical', 'drift', 'divetar', 'comp', 'alerts']

                    fmt_dict = {}
                    for pagers_tag in pagers_elts:
                        pagers_tag = pagers_tag.lstrip().rstrip().lower()

                        # Strip off the format first
                        fmt = ''
                        for tag in tags_with_fmt:
                            if pagers_tag.startswith(tag):
                                fmt = pagers_tag[len(tag):]
                                pagers_tag = tag
                                break

                        if pagers_tag not in known_tags:
                            log_error("Unknown tag (%s) on line (%s) in %s - skipping" % (pagers_tag, pagers_line, pagers_file_name))
                            continue

                        log_debug("pagers_tag:%s fmt:%s" % (pagers_tag, fmt))

                        if 'drift' in tags_to_process and pagers_tag == 'drift':
                            if comm_log:
                                drift_message = comm_log.predict_drift(fmt)
                                subject_line = "Drift"
                                log_info("Sending %s (%s) to %s" % (subject_line, drift_message, email_addr))
                                send_func(base_opts, instrument_id, email_addr, subject_line, drift_message)
                            else:
                                log_warning("Internal error - no comm log - skipping drift predictions for (%s)" % email_addr)

                        elif pagers_tag in ('gps', 'recov', 'critical', 'lategps') and  pagers_tag in tags_to_process:
                            fmts = fmt.split('_')
                            dive_prefix = False
                            if len(fmts) > 1:
                                if fmts[1].lower()[0:7] == 'divenum':
                                    dive_prefix = True
                                fmt = fmts[0]

                            if comm_log:
                                gps_message, recov_code, escape_reason, prefix_str = comm_log.last_GPS_lat_lon_and_recov(fmt, dive_prefix)
                                reboot_msg = comm_log.has_glider_rebooted()
                            elif session:
                                gps_message, recov_code, escape_reason, prefix_str = CommLog.GPS_lat_lon_and_recov(fmt, dive_prefix, session)
                                if msg_prefix:
                                    gps_message = "%s%s" % (msg_prefix, gps_message)
                                reboot_msg = None
                            else:
                                log_warning("Internal error - no comm log, session or critical message supplied - skipping (%s)" % email_addr)
                                continue

                            if reboot_msg:
                                gps_message = "%s\n%s" % (gps_message, reboot_msg)

                            if prefix_str:
                                prefix_str = " SG%03d %s" % (instrument_id, prefix_str)

                            if pagers_tag in ("gps", "lategps"):
                                subject_line = "GPS%s" % prefix_str
                            elif pagers_tag in ("critical", "recov") and reboot_msg:
                                subject_line = "REBOOTED%s" % prefix_str
                            elif pagers_tag == "critical" and recov_code and recov_code != 'QUIT_COMMAND':
                                subject_line = "IN NON-QUIT RECOVERY%s" % prefix_str
                            elif pagers_tag == "recov" and recov_code:
                                subject_line = "IN RECOVERY%s" % prefix_str
                            elif pagers_tag == "recov" and escape_reason:
                                subject_line = "IN ESCAPE%s" % prefix_str
                            else:
                                subject_line = None

                            if subject_line is not None:
                                log_info("Sending %s (%s) to %s" % (subject_line, gps_message, email_addr))
                                send_func(base_opts, instrument_id, email_addr, subject_line, gps_message)

                        elif pagers_tag == 'alerts' and 'alerts' in tags_to_process:
                            if pagers_convert_msg and pagers_convert_msg != "":
                                subject_line = "CONVERSION PROBLEMS"
                                log_info("Sending %s to %s" % (subject_line, email_addr))
                                send_func(base_opts, instrument_id, email_addr, subject_line, pagers_convert_msg)
                            if crit_other_message and crit_other_message != "":
                                subject_line = "CRITICAL ERROR IN CAPTURE"
                                log_info("Sending %s to %s" % (subject_line, email_addr))
                                send_func(base_opts, instrument_id, email_addr, subject_line, crit_other_message)
                            if warn_message and warn_message != "":
                                subject_line = "ALERTS FROM PROCESSING"
                                log_info("Sending %s to %s" % (subject_line, email_addr))
                                send_func(base_opts, instrument_id, email_addr, subject_line, warn_message)

                        elif pagers_tag == 'comp' and 'comp' in tags_to_process:
                            if processed_files_message and processed_files_message != "":
                                subject_line = "Processing Complete"
                                log_info("Sending %s to %s" % (subject_line, email_addr))
                                send_func(base_opts, instrument_id, email_addr, subject_line, processed_files_message)

                        elif pagers_tag == 'divetar' and 'divetar' in tags_to_process:
                            if processed_files_message and processed_files_message != "":
                                subject_line = "New Dive Tarball(s)"
                                log_info("Sending %s to %s" % (subject_line, email_addr))
                                send_func(base_opts, instrument_id, email_addr, subject_line, processed_files_message)

        log_info("Finished processing on .pagers")

def process_extensions(extension_file_name, base_opts, sg_calib_file_name, dive_nc_file_names, nc_files_created,
                       processed_other_files, known_mailer_tags, known_ftp_tags):
    """Processes the extensions file, running each extension

    Returns:
        0 - success
        1 - failure
    """
    ret_val = 0
    extension_directory = base_opts.basestation_directory
    extensions_file_name = os.path.join(base_opts.mission_dir, extension_file_name)
    if not os.path.exists(extensions_file_name):
        log_info("No %s file found - skipping %s processing" % (extension_file_name, extension_file_name))
        return 0
    else:
        log_info("Starting processing on %s" % extension_file_name)
        try:
            extensions_file = open(extensions_file_name, "r")
        except IOError as exception:
            log_error("Could not open %s (%s) - skipping %s processing"
                      % (extensions_file_name, extension_file_name, exception.args))
            ret_val = 1
        else:
            for extension_line in extensions_file:
                extension_line = extension_line.rstrip()
                log_debug("extension file line = (%s)" % extension_line)
                if extension_line == "":
                    continue
                if extension_line[0] != '#':
                    log_info("Processing %s line (%s)" % (extension_file_name, extension_line))
                    extension_elts = extension_line.split(' ')
                    # First element - extension name, with .py file extension
                    extension_module_name = os.path.join(extension_directory, extension_elts[0])
                    extension_module = Sensors.loadmodule(extension_module_name)
                    if extension_module is None:
                        log_error("Error loading %s - skipping" % extension_module_name)
                        ret_val = 1
                    else:
                        try:
                            # Invoke the extension
                            extension_ret_val = extension_module.main(base_opts=base_opts, sg_calib_file_name=sg_calib_file_name,
                                                                      dive_nc_file_names=dive_nc_file_names, nc_files_created=nc_files_created,
                                                                      processed_other_files=processed_other_files,
                                                                      known_mailer_tags=known_mailer_tags, known_ftp_tags=known_ftp_tags)
                        except:
                            log_error("Extension %s raised an exception" % extension_module_name, 'exc')
                            extension_ret_val = 1
                        if extension_ret_val:
                            log_error("Error running %s - return %d" % (extension_module_name, extension_ret_val))
                            ret_val = 1

        log_info("Finished processing on %s" % extension_file_name)

    return ret_val

def run_extension_script(script_name, script_args):
    """Attempts to execute a script named under a shell context

       Output is recorded to the log, error code is ignored, no timeout enforced
    """
    if os.path.exists(script_name):
        log_info("Processing %s" % script_name)
        cmdline = "%s " % script_name
        if script_args:
            for i in script_args:
                cmdline = '%s %s ' % (cmdline, i)
        log_debug("Running (%s)" % cmdline)
        try:
            (_, fo) = Utils.run_cmd_shell(cmdline)
        except:
            log_error("Error running %s" % cmdline, 'exc')
        else:
            for f in fo:
                log_info(f)
            fo.close()
    else:
        log_info("Extension script %s not found" % script_name)

def signal_handler_defer(signum, frame):
    """Handles SIGUSR1 signal during per-dive processing
    """
    #pylint: disable=unused-argument
    global skip_mission_processing
    if signum == signal.SIGUSR1:
        log_warning("Caught SIGUSR1 - will skip whole mission processing")
        skip_mission_processing = True

def signal_handler_defer_end(signum, frame):
    """Handles SIGUSR1 signal during after whole mission processing
    """
    #pylint: disable=unused-argument
    global skip_mission_processing
    if signum == signal.SIGUSR1:
        log_warning("Caught SIGUSR1 - will end processing soon")
        skip_mission_processing = True

def signal_handler_abort_processing(signum, frame):
    """Handles SIGUSR1 during whole mission processing
    """
    #pylint: disable=unused-argument
    if signum == signal.SIGUSR1:
        log_warning("Caught SIGUSR1 - bailing out of further processing")
        raise AbortProcessingException

class AbortProcessingException(Exception):
    """Internal nofication to stop mission processing
    """
    def __init__(self):
        pass

def main():
    """Command line driver for the all basestation processing.

    Base.py is normally invoked as part of the glider logout sequence, but it
    can be run from the command line.  It is best to run from the glider
    account.  Running this process multiple times is not detremental - no files
    from the glider are destroyed or altered as part of this processing.

    Usage: Base.py [Options] --mission_dir MISSION_DIR

    Options:
      --version             show program's version number and exit
      -h, --help            show this help message and exit
      -c CONFIG, --config=CONFIG
                            script configuration file
      --base_log=BASE_LOG   basestation log file, records all levels of notifications
      --nice=NICE           processing priority level (niceness)
      -m MISSION_DIR, --mission_dir=MISSION_DIR
                            dive directory
      -v, --verbose         print status messages to stdout
      -q, --quiet           don't print status messages to stdout
      --debug               log/display debug messages
      -i INSTRUMENT_ID, --instrument_id=INSTRUMENT_ID
                            force instrument (glider) id
      --gzip_netcdf      Do not gzip netcdf files
      --profile             Profiles time to process
      --ver_65              Processes Version 65 glider format
      --bin_width=BIN_WIDTH
                            Width of bins
      --which_half=WHICH_HALF
                            Which half of the profile to use - 1 down, 2 up, 3 both, 4 combine down and
                            up
      --dac_src=DAC_SRC     What calculation is used as the basis for glider displacement and depth
                            averaged current: hdm - hydrodynamic model (default), gswm - glider slope
                            observed w model
      --daemon              Launch conversion as a daemon process
      --ignore_lock         Ignore the lock file, if present
      -f, --force           Forces conversion of all dives
      --local               Performs no remote operations (no .urls, .pagers, .mailer, etc.)
      --clean               Clean up (delete) intermediate files from working (mission) directory after
                            processing.
      --reply_addr=REPLY_ADDR
                            Optional email address to be inserted into the reply to field email
                            messages
      --domain_name=DOMAIN_NAME
                            Optional domain name to use for email messages
      --web_file_location=WEB_FILE_LOCATION
                            Optional location to prefix file locations in comp email messages
      --dive_data_kkyy_weed_hacker=DIVE_DATA_KKYY_WEED_HACKER
                            Data shallower then this setting is eliminated from the dive kkyy files
                            (implies --make_dive_kkyy)
      --climb_data_kkyy_weed_hacker=CLIMB_DATA_KKYY_WEED_HACKER
                            Data shallower then this setting is eliminated from the climb kkyy files
                            (implies --make_dive_kkyy)
      --make_dive_profiles  Create the common profile data products
      --make_dive_pro       Create the dive profile in text format
      --make_dive_bpo       Create the dive binned profile in text format
      --make_dive_netCDF    Create the dive netCDF output file
      --make_mission_profile
                            Create mission profile output file
      --make_mission_timeseries
                            Create mission timeseries output file
      --make_dive_kkyy      Create the dive kkyy output files
      --delete_upload_files Remove any input files (except cmdfile) after being successfully uploaded to the
                            glider.  N.B. The check for successful upload is the file appears in the most recent
                            completed comms session and that the size reported for upload matches the current
                            on-disk size.

    Files:
    As the processing code runs in the user context of the glider, any files that do not have permissions
    sufficient for the glider to gain read access will likely cause problems in processing.  If you edit
    files, be sure to check that the permissions have not be altered such that the glider can't read them.

    Input Files:

    processed_files.cache   Created and maintained by the Base.py, this file is a record of the
                            last time a file group from the glider was processed.  (A file group
                            is the collection of fragment files that is reassembled on the basestation
                            to make a single file from the glider)

    sg_calib_constants.m    The collection of name/value pairs in matlab format that provides the core
                            vechicle configuration information.  Note: This file is processed as faithfully
                            as possible to the way matlab would process it. Complicated expressions on the right
                            hand side of the name may not get correctly interpreted. It is recommended that you
                            keep the right hand side in simple strings or constants.

    comm.log                The ongoing communication record - processing doesn't even get started if this file
                            doesn't exist.

    .pagers                 These files are optional for processing, but enable useful features.  Consult
    .mailer                 the documentation at the head of each protype file in the ~sg000 directory.
    .urls
    .ftp

    Output Files:

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    global base_opts
    global instrument_id
    global incomplete_files
    global complete_files_dict
    global processed_eng_and_log_files
    global processed_selftest_eng_and_log_files
    global processed_logger_payload_files
    global processed_logger_eng_files
    global processed_logger_other_files
    global processed_other_files
    global data_product_file_names
    global comm_log

    incomplete_files = []
    complete_files_dict = {}
    processed_eng_and_log_files = []
    processed_selftest_eng_and_log_files = []
    processed_other_files = []
    processed_logger_payload_files = {}        # Dictionay of lists of files from a logger payload file, keyed by logger prefix
                                               # Files in these lists do not conform to normal logger basestation naming conventions
    processed_logger_eng_files = []            # List of eng files from all loggers - files on this list must conform to the basestation file and
                                               # dive directory naming convention
    processed_logger_other_files = []          # List of all non-eng files from all loggers - files on this list do not need to
                                               #    conform to basestation directory and filename convetions

    data_product_file_names = []
    failed_profiles = []

    instrument_id = None
    software_version = None
    software_revision = None
    fragment_size = None
    comm_log = None

    failed_mission_timeseries = False
    failed_mission_profile = False

    mission_profile_name = None
    mission_timeseries_name = None

    # Get options
    base_opts = BaseOpts.BaseOptions(sys.argv, 'b',
                                     usage="%prog [Options] --mission_dir MISSION_DIR"
                                     )
    # Initialize log
    BaseLogger("Base", base_opts)

    Utils.check_versions()

    # Reset priority
    if base_opts.nice:
        try:
            os.nice(base_opts.nice)
        except:
            log_error("Setting nice to %d failed" % base_opts.nice)

    # Check for required "options"
    if base_opts.mission_dir is None:
        print((main.__doc__))
        log_critical("Dive directory must be supplied. See Base.py -h")
        return 1

    if not os.path.exists(base_opts.mission_dir):
        log_critical("Dive directory %s does not exist - bailing out" % base_opts.mission_dir)
        return 1

    if base_opts.daemon:
        if Daemon.createDaemon(base_opts.mission_dir, False):
            log_error("Could not launch as a daemon - continuing synchronously")

    cmdline = ""
    for i in sys.argv:
        cmdline += "%s " % i

    log_info("Invoked with command line [%s]" % cmdline)

    log_info("PID:%d" % os.getpid())

    sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")

    calib_consts = CalibConst.getSGCalibrationConstants(sg_calib_file_name)
    if not calib_consts:
        log_warning("Could not process %s" % sg_calib_file_name)


    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    FileMgr.logger_init(init_dict)

    # Initialze the netCDF tables
    BaseNetCDF.init_tables(init_dict)

    # Update local lists from loggers
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if 'known_files' in d:
            for b in d['known_files']:
                known_files.append(b)

        if 'known_mailer_tags' in d:
            for k in d['known_mailer_tags']:
                known_mailer_tags.append(k)

        if 'known_ftp_tags' in d:
            for k in d['known_ftp_tags']:
                known_ftp_tags.append(k)

        if('eng_file_reader' in d and 'logger_prefix' in d):
            logger_eng_readers[d['logger_prefix']] = d['eng_file_reader']

    log_debug("known_files = %s" % known_files)
    log_debug("known_mailer_tags = %s" % known_mailer_tags)
    log_debug("known_ftp_tags = %s" % known_ftp_tags)
    log_debug("logger_eng_readers = %s" % logger_eng_readers)

    # TODO - Check for installed tools

    # Record start of conversion time
    processing_start_time = time.gmtime(time.time())
    log_info("Started processing " + time.strftime("%H:%M:%S %d %b %Y %Z", processing_start_time))

    # Parse comm log
    (comm_log, start_post, _, _) = CommLog.process_comm_log(os.path.join(base_opts.mission_dir, 'comm.log'),
                                                            base_opts, known_commlog_files=known_files)
    if comm_log is None:
        log_critical("Could not process comm.log -- bailing out")
        Utils.cleanup_lock_file(base_opts, base_lockfile_name)
        return 1

    #sys.stdout.write("Transfer Methods")
    #for i in comm_log.file_transfer_method.keys():
    #    sys.stdout.write("%s = %s\n" % (i, comm_log.file_transfer_method[i]))

    # Collect the things we'll need for later processing
    instrument_id = comm_log.get_instrument_id()
    if not instrument_id:
        head, tail = os.path.split(os.path.abspath(os.path.expanduser(base_opts.mission_dir)))
        try:
            instrument_id = int(tail[2:5])
        except ValueError:
            log_critical("Could not determine the glider's id")

        if not instrument_id:
            if base_opts.instrument_id is not None:
                instrument_id = int(base_opts.instrument_id)
            else:
                instrument_id = 0

    log_info("Instrument ID = %s" % str(instrument_id))

    # Ignore SIGUSR1 until we are through per-dive processing
    signal.signal(signal.SIGUSR1, signal_handler_defer)

    # Check for lock file - do this after processing the comm log so we have the glider id
    lock_file_pid = Utils.check_lock_file(base_opts, base_lockfile_name)
    if lock_file_pid < 0:
        log_error("Error accessing the lockfile - proceeding anyway...")
    elif lock_file_pid > 0:
        # The PID still exists
        log_warning("Previous conversion process (pid:%d) still exists - signalling process to complete" % lock_file_pid)
        os.kill(lock_file_pid, signal.SIGUSR1)
        if Utils.wait_for_pid(lock_file_pid, previous_conversion_time_out):
            # The alternative here is to try and kill the process:
            #os.kill(lock_file_pid, signal.SIGKILL)
            lock_file_msg = "Process pid:%d did not respond to sighup after %d seconds - bailing out" % (lock_file_pid, previous_conversion_time_out)
            log_error(lock_file_msg)
            if not base_opts.local:
                process_pagers(base_opts, instrument_id, ('alerts',), pagers_convert_msg=lock_file_msg)
            return 1
        else:
            log_info("Previous conversion process (pid:%d) apparently received the signal - proceeding" % lock_file_pid)
    else:
        # No lock file - move along
        pass

    Utils.create_lock_file(base_opts, base_lockfile_name)

    if not base_opts.local:
        process_pagers(base_opts, instrument_id, ('lategps', 'recov', 'critical', 'drift'), comm_log=comm_log)

    log_info("Processing comm_merged.log")
    history_logfile_name = os.path.join(base_opts.mission_dir, "history.log")
    if os.path.exists(history_logfile_name):
        try:
            command_list_with_ts = CommLog.process_history_log(history_logfile_name)
        except:
            log_error("History file processing threw an exception - no merged file produced", 'exc')
        else:
            new_list_with_ts = CommLog.merge_lists_with_ts(comm_log.raw_lines_with_ts, command_list_with_ts)
            comm_log_merged_name = os.path.join(base_opts.mission_dir, "comm_merged.log")
            try:
                comm_log_merged = open(comm_log_merged_name, "w")
            except IOError as exception:
                log_error("Could not open %s (%s) - no merged comm log created"
                          % (comm_log_merged_name, exception.args))
            else:
                for i in new_list_with_ts:
                    comm_log_merged.write("%.0f: %s\n" % (i[0], i[1]))
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
            (rename_divenum, rename_call_counter) = comm_log.get_last_dive_num_and_call_counter()
            #pdos_log_name = "sg%04dpz.%03d" % (comm_log.last_surfacing().dive_num, comm_log.last_surfacing().calls_made)
            pdos_log_name = "sg%04dpz.%03d" % (rename_divenum, rename_call_counter)
            pdos_log_name = os.path.join(base_opts.mission_dir, pdos_log_name)
            log_info("Moving %s to %s" % (flash_file_name, pdos_log_name))
            shutil.move(flash_file_name, pdos_log_name)

        # Handle the FLASH file
        flash_file_name = os.path.join(base_opts.mission_dir, "FLASH")
        if os.path.exists(flash_file_name):
            (rename_divenum, rename_call_counter) = comm_log.get_last_dive_num_and_call_counter()
            if rename_divenum is None:
                rename_divenum = 0
                log_error("No DiveNum found in comm.log - useing 0 as default")
            if rename_call_counter is None:
                rename_call_counter = 0
                log_error("No CallCounter found in comm.log - useing 0 as default")
            #pdos_log_name = "sg%04dpu.%03d" % (comm_log.last_surfacing().dive_num, comm_log.last_surfacing().calls_made)
            pdos_log_name = "sg%04dpu.%03d" % (rename_divenum, rename_call_counter)
            pdos_log_name = os.path.join(base_opts.mission_dir, pdos_log_name)
            log_info("Moving %s to %s" % (flash_file_name, pdos_log_name))
            shutil.move(flash_file_name, pdos_log_name)

        #Unzip parm file
        # First - strip 1a
        parms_zipped_file_name = os.path.join(base_opts.mission_dir, "parms.gz")
        if os.path.exists(parms_zipped_file_name):
            root, ext = os.path.splitext(parms_zipped_file_name)
            parms_zipped_file_name_1a = root + ".1a" + ext
            if Strip1a.strip1A(parms_zipped_file_name, parms_zipped_file_name_1a):
                log_error("Couldn't strip1a %s. Skipping processing" % parms_zipped_file_name_1a)
                # Proceed anyway
            else:
                parms_file_name = os.path.join(base_opts.mission_dir, "parms")
                if BaseGZip.decompress(parms_zipped_file_name_1a, parms_file_name) > 0:
                    log_error("Problem decompressing %s - skipping"
                              % parms_zipped_file_name)
                else:
                    os.remove(parms_zipped_file_name_1a)
                    os.remove(parms_zipped_file_name)

        # Handle the parms files
        parms_file_name = os.path.join(base_opts.mission_dir, "parms")
        if os.path.exists(parms_file_name):
            (rename_divenum, rename_call_counter) = comm_log.get_last_dive_num_and_call_counter()
            #parms_name = "parms.%04dpu.%03d" % (comm_log.last_surfacing().dive_num, comm_log.last_surfacing().calls_made)
            parms_name = "parms.%d.%d" % (rename_divenum, rename_call_counter)
            parms_name = os.path.join(base_opts.mission_dir, parms_name)
            log_info("Moving %s to %s" % (parms_file_name, parms_name))
            shutil.move(parms_file_name, parms_name)

    #fragment_size = comm_log.last_fragment_size()
    #if(fragment_size is None):
    #    log_error("No complete surfacings found in comm.log with valid fragment size - assuming 4K fragment size")
    #    fragment_size = 4096
    fragment_dict = comm_log.get_fragment_dictionary()

    (software_version, software_revision) = comm_log.last_software_version()
    if software_version is None:
        log_error("No complete surfacings found in comm.log - assuming version 66 software")
        software_revision = 66.00
        software_revision = None

    # Collect all files to be processed - be sure to include all files, including the flash files
    file_collector = FileMgr.FileCollector(base_opts.mission_dir, instrument_id)

    # Ensure that all pre-processed files are readable by all
    pre_proc_files = file_collector.get_pre_proc_files()
    for file_name in pre_proc_files:
        os.chmod(file_name, stat.S_IRUSR|stat.S_IWUSR|stat.S_IRGRP|stat.S_IROTH)

    # Read cache for conversions done thus far
    if base_opts.force:
        complete_files_dict = {}
        processed_pdos_logfiles_dict = {}
    else:
        try:
            complete_files_dict, processed_pdos_logfiles_dict = read_processed_files(base_opts.mission_dir)
        except IOError as exception:
            log_critical("Error opening processed dives conf file (%s) - exiting"
                         % (exception.args))
            Utils.cleanup_lock_file(base_opts, base_lockfile_name)
            return 1

    # Start with self tests
    log_info("Processing seaglider selftests")
    new_selftests_processed = []
    selftests_not_processed = []

    log_debug("Selftests found: %s" % pprint.pformat(file_collector.all_selftests))

    for i in file_collector.all_selftests:
        selftest_files = file_collector.get_pre_proc_selftest_files(i)
        if i in list(fragment_dict.keys()):
            fragment_size = fragment_dict[i]
        else:
            fragment_size = 8192
            log_warning("No fragment size found for %s - using %d as default" % (i, fragment_size))
        selftest_processed = process_dive_selftest(selftest_files, i, fragment_size, calib_consts)
        if selftest_processed > 0:
            new_selftests_processed.append(i)
        elif selftest_processed < 0:
            selftests_not_processed.append(i)

    # Notification
    if new_selftests_processed:
        log_info("Processed selftests(s) %s" % new_selftests_processed)
    else:
        log_info("No new selftests to processed")

    log_info("Processing pdoscmd.bat logs")

    new_pdos_logfiles_processed = []
    pdos_logfile_names = file_collector.get_pdoscmd_log_files()
    for i in pdos_logfile_names:
        log_debug("Checking %s for processing" % i)

        if(os.path.basename(i) not in processed_pdos_logfiles_dict
           or os.path.getmtime(os.path.join(base_opts.mission_dir, i)) > processed_pdos_logfiles_dict[os.path.basename(i)]):
            if not process_pdoscmd_log(base_opts.mission_dir, i):
                new_pdos_logfiles_processed.append(os.path.basename(i))

    # PDos logs notification
    if new_pdos_logfiles_processed:
        log_info("Processed pdos logfile(s) %s" % new_pdos_logfiles_processed)
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
        if i in list(fragment_dict.keys()):
            fragment_size = fragment_dict[i]
        else:
            fragment_size = 8192
            log_warning("No fragment size found for dive %s - using %d as default" % (i, fragment_size))
        dive_processed = process_dive_selftest(dive_files, i, fragment_size, calib_consts)
        if dive_processed > 0:
            new_dives_processed.append(i)
        elif dive_processed < 0:
            dives_not_processed.append(i)

    # Dive processing notification
    if new_dives_processed:
        log_info("Processed dive(s) %s" % new_dives_processed)
    else:
        log_warning("No dives to process")

    write_processed_dives(base_opts.mission_dir, complete_files_dict, processed_pdos_logfiles_dict)

    #
    # Per dive profile, netcdf and KKYY file processing
    #
    nc_dive_file_names = []
    nc_files_created = []
    if(base_opts.make_dive_pro or base_opts.make_dive_bpo or base_opts.make_dive_netCDF
       or base_opts.make_mission_profile or base_opts.make_mission_timeseries or base_opts.make_dive_kkyy):
        dives_to_profile = []      # A list of basenames to profile

        #log_info("processed_eng_and_log_files (%s)" % processed_eng_and_log_files)
        #log_info("processed_logger_eng_files (%s)" % processed_logger_eng_files)

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
        log_info("Dives to process = %s" % dive_nums_to_process)

        # 3) Walk dives to process - if the seaglider log and eng files exists, we can proceed
        #                            add in any logger eng files that might exists (regular file in home directory and any sub-directories)
        for d in dive_nums_to_process:
            seaglider_eng_file_name = "%sp%03d%04d.eng" % (base_opts.mission_dir, instrument_id, d)
            seaglider_log_file_name = "%sp%03d%04d.log" % (base_opts.mission_dir, instrument_id, d)
            #log_info("%s:%s" % ( seaglider_eng_file_name, seaglider_log_file_name))
            if(os.path.exists(seaglider_eng_file_name) and os.path.exists(seaglider_log_file_name)):
                dives_to_profile.append(seaglider_log_file_name)

        # Find any associated logger eng files for each dive in dives_to_profile
        logger_eng_files = FileMgr.find_dive_logger_eng_files(dives_to_profile, base_opts, instrument_id, init_dict)

        # Now, walk the list and create the profiles
        for dive_to_profile in dives_to_profile:
            head, tail = os.path.splitext(dive_to_profile)
            log_info("Processing (%s) for profiles" % head)
            log_file_name = head + ".log"
            eng_file_name = head + ".eng"
            if base_opts.make_dive_pro:
                profile_file_name = head + ".pro"
            else:
                profile_file_name = None
            if base_opts.make_dive_bpo:
                binned_profile_file_name = head + ".bpo"
            else:
                binned_profile_file_name = None
            if base_opts.make_dive_netCDF:
                nc_dive_file_name = head + ".nc"
            else:
                nc_dive_file_name = None
            if base_opts.make_dive_kkyy:
                kkyy_up_file_name = os.path.join(head + ".up_kkyy")
                kkyy_down_file_name = os.path.join(head + ".dn_kkyy")
            else:
                kkyy_up_file_name = None
                kkyy_down_file_name = None

            retval = None
            dive_num = FileMgr.get_dive(eng_file_name)

            #log_info("logger_eng_files = %s" % logger_eng_files[dive_to_profile])

            try:
                (retval, nc_dive_file_name) = MakeDiveProfiles.make_dive_profile(True, dive_num, eng_file_name, log_file_name, sg_calib_file_name,
                                                                                 base_opts, nc_dive_file_name,
                                                                                 #logger_ct_eng_files=logger_ct_eng_files[dive_to_profile],
                                                                                 logger_eng_files=logger_eng_files[dive_to_profile])
                if not retval:
                    # no problem writting the nc file, try for the others
                    retval = MakeDiveProfiles.write_auxillary_files(base_opts, nc_dive_file_name,
                                                                    profile_file_name, binned_profile_file_name,
                                                                    kkyy_up_file_name, kkyy_down_file_name)
            except KeyboardInterrupt:
                log_error("MakeDiveProfiles caught a keyboard exception - bailing out", 'exc')
                return 1
            except:
                log_error("MakeDiveProfiles raised an exception - dive profiles not created for %s" % head, 'exc')
                log_info("Continuing processing...")
                failed_profiles.append(dive_num)
            else:
                # Even if the processing failed, we may get a netcdf files out
                if profile_file_name:
                    data_product_file_names.append(profile_file_name)
                if retval == 1:
                    log_error("Failed to create profiles for %s" % head)
                    failed_profiles.append(dive_num)
                elif retval == 2:
                    log_info("Skipped creating profiles for %s" % head)
                else:
                    # Add to list of data product files created/updated
                    if binned_profile_file_name:
                        data_product_file_names.append(binned_profile_file_name)
                    if nc_dive_file_name:
                        data_product_file_names.append(nc_dive_file_name)
                        nc_dive_file_names.append(nc_dive_file_name)
                    if kkyy_down_file_name:
                        data_product_file_names.append(kkyy_down_file_name)
                    if kkyy_up_file_name:
                        data_product_file_names.append(kkyy_up_file_name)
                    nc_files_created.append(nc_dive_file_name)

        if not dives_to_profile:
            log_info("No dives found to profile")

    # Back up all files - using the dive # and call_cycle # from the comm log
    # Do this without regard to what dives got processed
    for i in known_files:
        for j in ('', '.plain'):
            known_file = "%s%s" % (i, j)
            backup_filename = os.path.join(base_opts.mission_dir, known_file)
            if os.path.exists(backup_filename):
                (backup_dive_num, backup_call_cycle) = comm_log.get_last_dive_num_and_call_counter()
                #backup_dive_num = comm_log.last_surfacing().dive_num
                #backup_call_cycle = comm_log.last_surfacing().call_cycle
                if backup_dive_num is not None:
                    if(backup_call_cycle is None or int(backup_call_cycle) == 0):
                        backup_target_filename = "%s.%d" % (backup_filename, int(backup_dive_num))
                    else:
                        backup_target_filename = "%s.%d.%d" % (backup_filename, int(backup_dive_num), int(backup_call_cycle))
                    log_info("Backing up %s to %s" % (backup_filename, backup_target_filename))
                    shutil.copyfile(backup_filename, backup_target_filename)
                else:
                    log_error("Could not find a dive number in the comm.log - not backing up file %s" % backup_filename)

    # Known files have been back up.
    delete_files = []
    preserve_files = []
    for kf in known_files:
        delete_files.append(os.path.join(base_opts.mission_dir, ".delete_%s" % kf.replace(".", "_")))
        preserve_files.append(os.path.join(base_opts.mission_dir, ".preserve_%s" % kf.replace(".", "_")))

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
                log_error('Unable to remove %s -- permissions?' % delete_files[ii])


            if os.path.exists(known_file):
                log_info("Deleting %s" % known_file)
                try:
                    os.remove(known_file)
                except OSError:
                    log_error('Unable to remove %s -- permissions?' % known_file)
        else:
            if base_opts.delete_upload_files and not os.path.exists(preserve_files[ii]) \
               and known_files[ii] != "cmdfile":
                # Remove the uploaded file if it was transferred in the most recent comm session
                # and the size and date criteria are met
                if os.path.exists(known_file):
                    session = comm_log.last_complete_surfacing()
                    if(known_files[ii] in session.file_stats
                       and time.mktime(session.disconnect_ts) > os.stat(known_file).st_mtime):
                        if session.file_stats[known_files[ii]].filesize != os.stat(known_file).st_size:
                            log_info("File %s appear to be uploaded, but file size does not match (%d:%d) - not deleting"
                                     % (known_file, session.file_stats[known_files[ii]].filesize, os.stat(known_file).st_size))
                        else:
                            try:
                                os.unlink(known_file)
                            except:
                                log_error("Could not remove uploaded file %s" % known_file)
                            else:
                                log_info("%s was uploaded and deleted" % known_file)

    if base_opts.make_dive_netCDF:
        # Run FlightModel here and before mission processing so combined data reflects best flight model results
        # Run before alert processing occurs so FM complaints are reported to the pilot
        try:
            FlightModel.main(base_opts=base_opts, sg_calib_file_name=sg_calib_file_name)
        except:
            log_critical("FlightModel failed", 'exc')

    # Run extension scripts for any new logger files
    #TODO GBS - combine ALL logger lists and invoke the extension with the complete list
    #processed_file_names.append(processed_logger_eng_files)
    #processed_file_names.append(processed_logger_other_files)
    for k in list(processed_logger_payload_files.keys()):
        if len(processed_logger_payload_files[k]) > 0:
            run_extension_script(os.path.join(base_opts.mission_dir, ".%s_ext" % k), processed_logger_payload_files[k])

    # Run the post dive processing script
    run_extension_script(os.path.join(base_opts.mission_dir, ".post_dive"), None)

    (dive_num, call_counter) = comm_log.get_last_dive_num_and_call_counter()
    # Process the urls file for the first pass (before mission profile, timeseries, etc).
    if not base_opts.local:
        Utils.process_urls(base_opts, 1, instrument_id, dive_num)

    # Check for sighup here
    if skip_mission_processing:
        log_warning("Caught SIGUSR1 perviously - skipping whole mission processing")
    else:
        dive_nc_file_names = []
        signal.signal(signal.SIGUSR1, signal_handler_abort_processing)
        try:
            # Begin whole mission processing here

            # Collect up the possible files
            if(base_opts.make_mission_profile or base_opts.make_mission_timeseries):
                dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)

            #
            # Create the mission profile file
            #
            if(base_opts.make_mission_profile and len(nc_files_created) > 0):
                if len(nc_dive_file_names) < 1:
                    log_warning("No dive netCDF file created - mission netCDF file will not be updated")
                else:
                    (mp_ret_val, mission_profile_name) = MakeDiveProfiles.make_mission_profile(dive_nc_file_names, base_opts)
                    if mp_ret_val:
                        failed_mission_profile = True
                    else:
                        data_product_file_names.append(mission_profile_name)
            #
            # Create the mission timeseries file
            #
            if(base_opts.make_mission_timeseries and len(nc_files_created) > 0):
                if len(nc_dive_file_names) < 1:
                    log_warning("No dive netCDF file created - mission timeseries file will not be updated")
                else:
                    # Create the timeseries file
                    (mt_retval, mission_timeseries_name) = MakeDiveProfiles.make_mission_timeseries(dive_nc_file_names, base_opts)
                    if mt_retval:
                        failed_mission_timeseries = True
                    else:
                        data_product_file_names.append(mission_timeseries_name)

            # Invoke extensions, if any
            process_extensions('.extensions', base_opts, sg_calib_file_name, dive_nc_file_names, nc_files_created,
                               processed_other_files, known_mailer_tags, known_ftp_tags)

        except AbortProcessingException:
            # Issued the message in the handler
            pass

    # If we get a SIGUSR1 in here, just let it run to the end
    signal.signal(signal.SIGUSR1, signal_handler_defer_end)

    # Alert message and file processing
    alerts_d = log_alerts()
    conversion_alerts_d = log_conversion_alerts()
    pagers_convert_msg = None

    alert_warning_msg = ""

    alert_message_base_name = "alert_message.html"
    (backup_dive_num, backup_call_cycle) = comm_log.get_last_dive_num_and_call_counter()
    if backup_dive_num is not None:
        if(backup_call_cycle is None or int(backup_call_cycle) == 0):
            alert_message_file_name = "%s.%d" % (alert_message_base_name, int(backup_dive_num))
        else:
            alert_message_file_name = "%s.%d.%d" % (alert_message_base_name, int(backup_dive_num), int(backup_call_cycle))
    else:
        log_error("Could not find a dive number in the comm.log - using %s for alerts" % alert_message_base_name)
        alert_message_file_name = alert_message_base_name

    alert_msg_file_name = os.path.join(base_opts.mission_dir, alert_message_file_name)
    if dives_not_processed or selftests_not_processed or incomplete_files or failed_profiles or failed_mission_profile \
       or failed_mission_timeseries or alerts_d:
        # List housekeeping
        incomplete_files = sorted(Utils.flatten(incomplete_files))
        incomplete_files = sorted(Utils.unique(incomplete_files))

        # Recomendations
        for incomplete_file in incomplete_files:
            recomendation = comm_log.check_multiple_sectors(incomplete_file, instrument_id)
            if recomendation:
                log_alert(incomplete_file, recomendation)

        # Construct the pagers_convert_msg and alter_msg_file
        pagers_convert_msg = ""
        if(base_opts.base_log is not None and base_opts.base_log != ""):
            conversion_log = base_opts.base_log
        else:
            conversion_log = "the conversion log"

        try:
            alert_msg_file = open(alert_msg_file_name, "w")
        except:
            log_error("Could not open alert_msg_file_name", 'exc')
            log_info("... skipping")
            alert_msg_file = None

        if dives_not_processed:
            tmp = "Dive %s failed to process completely.\n\n" % dives_not_processed
            if alert_msg_file:
                alert_msg_file.write("<br>%s\n" % tmp)
            pagers_convert_msg = pagers_convert_msg + tmp
        if selftests_not_processed:
            tmp = "Selftest %s failed to process completely.\n\n" % selftests_not_processed
            if alert_msg_file:
                alert_msg_file.write("<br>%s\n" % tmp)
            pagers_convert_msg = pagers_convert_msg + tmp
        if failed_profiles:
            tmp = "Profiles for dive %s had problems during processing.\n\n" % failed_profiles
            if alert_msg_file:
                alert_msg_file.write("<br>%s\n" % tmp)
            pagers_convert_msg = pagers_convert_msg + tmp
        if failed_mission_profile:
            tmp = "The mission profile %s had problems during processing.\n\n" % mission_profile_name
            if alert_msg_file:
                alert_msg_file.write("<br>%s\n" % tmp)
            pagers_convert_msg = pagers_convert_msg + tmp
        if failed_mission_timeseries:
            tmp = "The mission timeseries %s had problems during processing.\n\n" % mission_timeseries_name
            if alert_msg_file:
                alert_msg_file.write("<br>%s\n" % tmp)
            pagers_convert_msg = pagers_convert_msg + tmp
        if incomplete_files:
            pagers_convert_msg = pagers_convert_msg + "The following files were not processed completely:\n"
            for i in incomplete_files:
                incomplete_file_name = os.path.abspath(os.path.join(base_opts.mission_dir, i))
                _, base_file_name = os.path.split(incomplete_file_name)
                pagers_convert_msg = pagers_convert_msg + "    %s\n" % incomplete_file_name
                if alert_msg_file:
                    alert_msg_file.write("<div class=\"%s\">\n<p>File %s was not processed completely\n"
                                         % (os.path.basename(incomplete_file_name), incomplete_file_name))
                    fc = FileMgr.FileCode(incomplete_file_name, instrument_id)
                    if fc.is_seaglider_selftest():
                        alert_msg_file.write("<!--selftest=%d-->\n" % FileMgr.get_dive(incomplete_file_name))
                    else:
                        alert_msg_file.write("<!--diveno=%d-->\n" % FileMgr.get_dive(incomplete_file_name))
                if i in conversion_alerts_d:
                    alert_msg_file.write("<<ul>\n")
                    prev_j = "" # format the text of the alert
                    for j in conversion_alerts_d[i]:
                        if j != prev_j:
                            pagers_convert_msg = pagers_convert_msg + "        %s\n" % j
                            if alert_msg_file:
                                alert_msg_file.write("<li>%s</li>\n" % j)
                            prev_j = j
                    del conversion_alerts_d[i] # clean up after ourselves - not clear this is needed anymore
                    alert_msg_file.write("</ul>\n")
                    pagers_convert_msg = pagers_convert_msg + "\n"
                alert_msg_file.write("</p>\n")
                if alert_msg_file:
                    if comm_log.last_surfacing().logout_seen:
                        alert_msg_file.write("<p>Glider logout seen  - transmissions from glider complete</p>\n")
                    else:
                        alert_msg_file.write("<p>Glider logout not seen - retransmissions from glider possible</p>\n")
                    alert_msg_file.write("</div>\n")

        if pagers_convert_msg:
            if comm_log.last_surfacing().logout_seen:
                pagers_convert_msg = pagers_convert_msg + "Glider logout seen - transmissions from glider complete\n"
            else:
                pagers_convert_msg = pagers_convert_msg + "Glider logout not seen - retransmissions from glider possible\n"

        if alert_msg_file:
            for alert_topic in list(alerts_d.keys()):
                alert_msg_file.write("<div class=\"%s\">\n<p>Alert: %s<ul>\n" % (Utils.ensure_basename(alert_topic), alert_topic))
                alert_warning_msg = alert_warning_msg + "ALERT:%s\n" % alert_topic
                for alert in alerts_d[alert_topic]:
                    alert_msg_file.write("<li>%s</li>\n" % alert)
                    alert_warning_msg = alert_warning_msg + "    %s\n" % alert
                del alerts_d[alert_topic] # clean up
                alert_msg_file.write("</ul></p></div>\n")
            alert_msg_file.write("<p>Consult %s for details</p>\n" % conversion_log)

        if alert_warning_msg:
            alert_warning_msg = alert_warning_msg + "Consult %s for details." % conversion_log
            log_warning(alert_warning_msg)

        if alert_msg_file:
            alert_msg_file.close()

        # Put the alert message into  the logfile
        if pagers_convert_msg != "":
            log_error(pagers_convert_msg)
    else:
        # No alerts - remove the alert file, if it exists
        if os.path.exists(alert_msg_file_name):
            try:
                os.remove(alert_msg_file_name)
            except:
                log_error("Could not remove alert message file %s" % alert_msg_file_name)

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

    processed_files_msg = "Processing complete as of %s\n" % time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))

    if processed_file_names:
        for processed_file_name in processed_file_names:
            if processed_file_name is None:
                continue
            if base_opts.web_file_location:
                #head,tail = os.path.split(processed_file_name)
                #p = os.path.join(base_opts.web_file_location, tail)
                # This handles files that reside in sub-directories of the mission_dir
                p = processed_file_name.replace(base_opts.mission_dir, "")
                processed_files_msg += "%s\n" % p
            else:
                processed_files_msg += "%s\n" % os.path.abspath(processed_file_name)

        log_info("Processed files msg:\n%s" % processed_files_msg)
    else:
        processed_files_msg += "No new files processed\n"

    # Run the post mission processing script
    run_extension_script(os.path.join(base_opts.mission_dir, ".post_mission"), processed_file_names)

    if(base_opts.divetarballs != 0 and processed_file_names):
        dive_nums = []
        dive_tarballs = []
        dn = re.compile(r".*\/p.*\d\d\d(?P<divenum>\d\d\d\d).*")
        # Collect the dive numbers
        for pf in processed_file_names:
            values = dn.search(pf)
            if(values and len(values.groupdict()) == 1):
                dive_nums.append(int(values.groupdict()['divenum']))

        dive_nums = Utils.unique(dive_nums)
        log_info("Found files from dive/selftest %s to build tarball(s)" % dive_nums)
        # Build the list of files for each dive number
        for dive_num in dive_nums:
            for st in ('', 't'):
                tarfile_files = []
                # Find all files that contribute and exist
                for ext in (".eng", ".log", ".cap"):
                    file_name = os.path.join(base_opts.mission_dir, "p%s%03d%04d%s"
                                             % (st, instrument_id, dive_num, ext))
                    if os.path.exists(file_name):
                        tarfile_files.append(file_name)
                    else:
                        log_info("%s does not exists" % file_name)
                if st == '':
                    for logger in ('sc', 'tm'):
                        for profile in ('a', 'b', 'c'):
                            for file_name in glob.glob(os.path.join(base_opts.mission_dir, "%s%04d%s/*eng"
                                                                    % (logger, dive_num, profile))):
                                tarfile_files.append(file_name)

                if len(tarfile_files) == 0:
                    continue
                log_info("Tarfiles for %s %d: %s" % ("selftest" if st == 't' else "dive", dive_num, tarfile_files))
                tar_name = os.path.join(base_opts.mission_dir, "p%s%03d%04d.tar.bz2" % (st, instrument_id, dive_num))
                try:
                    tf = tarfile.open(tar_name, "w:bz2", compresslevel=9)
                except:
                    log_error("Error opening %s - skipping creation" % tar_name, 'exc')
                    continue
                for fn in tarfile_files:
                    tf.add(fn, arcname=fn.replace(base_opts.mission_dir, "./"))
                tf.close()
                processed_file_names.append(tar_name)
                dive_tarballs.append(tar_name.replace(base_opts.mission_dir, ""))

                if base_opts.divetarballs > 0:
                    try:
                        fi = open(tar_name, "rb")
                        buff = fi.read()
                        fi.close()
                    except:
                        log_error("Could not process %s for fragmentation - skipping" % tar_name, 'exc')
                        continue
                    # Create fragments
                    for ii in range(100):
                        if ii * base_opts.divetarballs > len(buff):
                            break
                        tar_frag_name = os.path.join(base_opts.mission_dir,
                                                     "p%s%03d%04d_%02d.tar.bz2" % (st, instrument_id, dive_num, ii))

                        try:
                            fo = open(tar_frag_name, "wb")
                            fo.write(buff[ii * base_opts.divetarballs:
                                          (ii + 1) * base_opts.divetarballs if (ii + 1) * base_opts.divetarballs < len(buff) else len(buff)])
                            fo.close()
                        except:
                            log_error("Could not process %s for fragmentation - skipping" % tar_frag_name, 'exc')
                            break
                        processed_file_names.append(tar_frag_name)
                        dive_tarballs.append(tar_frag_name.replace(base_opts.mission_dir, ""))

        # Send out an alert that the tarball exists
        if len(dive_tarballs):
            tarball_str = "New tarballs "
            for d in dive_tarballs:
                tarball_str += "%s " % d
            process_pagers(base_opts, instrument_id, ('divetar', ), processed_files_message=tarball_str)

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
            except:
                log_error("Unable to open %s (%s) - skipping" % p, 'exc')
            else:
                cap_text = fi.read()
                fi.close()
                if cap_text is None:
                    continue
                line_count = 1
                cap_lines = []
                for ll in cap_text.splitlines():
                    try:
                        ll = ll.decode('utf-8')
                    except:
                        log_warning(f"Could not decode line number {line_count} in {p} - skipping")
                    else:
                        cap_lines.append(ll)
                    line_count += 1
                new_cap_text = '\n'.join(cap_lines)
                crits = prog.findall(new_cap_text)
                num_crits = len(crits)
                if num_crits > 0:
                    if critical_msg == "":
                        critical_msg = "The following capture files contain critical lines:\n"
                    critical_msg += "%s (%d critical)\n" % (p, num_crits)
                    for c in crits:
                        critical_msg += "    %s\n" % c

    if critical_msg:
        log_warning(critical_msg)

    # Process pagers
    if not base_opts.local:
        process_pagers(base_opts, instrument_id, ('alerts', ), crit_other_message=critical_msg)

        process_pagers(base_opts, instrument_id, ('alerts', ), warn_message=alert_warning_msg)

        process_pagers(base_opts, instrument_id, ('alerts', 'comp'), comm_log=comm_log, pagers_convert_msg=pagers_convert_msg,
                       processed_files_message=processed_files_msg)

        process_ftp(processed_file_names, mission_timeseries_name, mission_profile_name)

        mailer_file_name = os.path.join(base_opts.mission_dir, ".mailer")
        if not os.path.exists(mailer_file_name):
            log_info("No .mailer file found - skipping .mailer processing")
        else:
            log_info("Starting processing on .mailer")
            try:
                mailer_file = open(mailer_file_name, "r")
            except IOError as exception:
                log_error("Could not open %s (%s) - no mail sent" % (mailer_file_name, exception.args))
            else:
                mailer_conversion_time = time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                for mailer_line in mailer_file:
                    mailer_line = mailer_line.rstrip()
                    log_debug("mailer line = (%s)" % mailer_line)
                    if mailer_line == "":
                        continue
                    if mailer_line[0] != '#':
                        log_info("Processing .mailer line (%s)" % mailer_line)
                        mailer_tags = mailer_line.split(',')
                        mailer_send_to = mailer_tags[0]
                        mailer_tags = mailer_tags[1:]
                        mailer_send_to_list = []
                        mailer_send_to_list.append(mailer_send_to)

                        temp_tags = mailer_tags
                        for i in range(len(temp_tags)):
                            mailer_tags[i] = temp_tags[i].lower().rstrip().lstrip()

                        # Remove the body tag, if present
                        try:
                            mailer_tags.index('body')
                        except:
                            mailer_file_in_body = False
                        else:
                            mailer_tags.remove('body')
                            mailer_file_in_body = True

                        # Check for msgperfile
                        try:
                            mailer_tags.index('msgperfile')
                        except:
                            mailer_msg_per_file = False
                        else:
                            mailer_tags.remove('msgperfile')
                            mailer_msg_per_file = True

                        # Remove the Navy header tag, if present,
                        try:
                            mailer_tags.index('kkyy_subject')
                        except:
                            mailer_subject = "SG%03d files" % (instrument_id)
                        else:
                            mailer_tags.remove('kkyy_subject')
                            mailer_subject = 'XBTDATA'

                        # Remove the gzip tag, if present
                        try:
                            mailer_tags.index('gzip')
                        except:
                            mailer_gzip_file = False
                        else:
                            mailer_tags.remove('gzip')
                            if mailer_file_in_body:
                                log_error("Options body and gzip incompatibile - skipping gzip")
                                mailer_gzip_file = False
                            else:
                                mailer_gzip_file = True

                        # Check for what file type
                        try:
                            mailer_tags.index('all')
                        except:
                            pass
                        else:
                            mailer_tags = known_mailer_tags

                        # Collect file to send into a list
                        mailer_file_names_to_send = []

                        for mailer_tag in mailer_tags:
                            if mailer_tag.startswith("fnmatch_"):
                                _, m = mailer_tag.split("_", 1)
                                log_info("Match criteria (%s)" % m)
                                for processed_file_name in processed_file_names:
                                    # Case insenitive match since tags were already lowercased
                                    if fnmatch.fnmatchcase(processed_file_name.lower(), m):
                                        mailer_file_names_to_send.append(processed_file_name)
                                        log_info("Matched %s" % processed_file_name)
                            elif not mailer_tag in known_mailer_tags:
                                log_error("Unknown tag (%s) on line (%s) in %s - skipping" % (mailer_tag, mailer_line, mailer_file_name))
                            else:
                                if mailer_tag == 'comm':
                                    mailer_file_names_to_send.append(os.path.join(base_opts.mission_dir, "comm.log"))
                                elif mailer_tag in ('nc', 'mission_ts', 'mission_pro') and mailer_file_in_body:
                                    log_error("Sending netCDF files in the message body not supported")
                                    continue
                                else:
                                    for processed_file_name in processed_file_names:
                                        if processed_file_name == mission_timeseries_name:
                                            if mailer_tag == 'mission_ts':
                                                mailer_file_names_to_send.append(processed_file_name)
                                        elif processed_file_name == mission_profile_name:
                                            if mailer_tag == 'mission_pro':
                                                mailer_file_names_to_send.append(processed_file_name)
                                        else:
                                            head, tail = os.path.splitext(processed_file_name)
                                            if tail.lstrip('.') == mailer_tag.lower():
                                                mailer_file_names_to_send.append(processed_file_name)

                        if mailer_file_names_to_send:
                            log_info("Sending %s" % mailer_file_names_to_send)
                        else:
                            log_info("No files found to send")

                        # Set up messsage here if there is only one message per recipient
                        if not mailer_msg_per_file:
                            if not mailer_file_in_body:
                                mailer_msg = MIMEMultipart()
                            else:
                                mailer_msg = MIMENonMultipart('text', 'plain')

                            #mailer_msg['From'] = "SG%03d" % (instrument_id)
                            if base_opts.domain_name:
                                mailer_msg['From'] = "Seaglider %d <sg%03d@%s>" % (instrument_id, instrument_id, base_opts.domain_name)
                            else:
                                mailer_msg['From'] = "Seaglider %d <sg%03d>" % (instrument_id, instrument_id)
                            mailer_msg['To'] = COMMASPACE.join(list(mailer_send_to_list))
                            mailer_msg['Date'] = formatdate(localtime=True)
                            mailer_msg['Subject'] = mailer_subject
                            if base_opts.reply_addr:
                                mailer_msg['Reply-To'] = base_opts.reply_addr

                            if not mailer_file_in_body:
                                mailer_msg.attach(MIMEText("New/Updated files as of %s conversion\n" % mailer_conversion_time))
                            mailer_text = ""

                        for mailer_file_name_to_send in mailer_file_names_to_send:
                            if mailer_msg_per_file:
                                # Set up message here if there are multiple messages per recipient
                                if not mailer_file_in_body:
                                    mailer_msg = MIMEMultipart()
                                else:
                                    mailer_msg = MIMENonMultipart('text', 'plain')
                                #mailer_msg['From'] = "SG%03d" % (instrument_id)
                                if base_opts.domain_name:
                                    mailer_msg['From'] = "Seaglider %d <sg%03d@%s>" % (instrument_id, instrument_id, base_opts.domain_name)
                                else:
                                    mailer_msg['From'] = "Seaglider %d <sg%03d>" % (instrument_id, instrument_id)
                                mailer_msg['To'] = COMMASPACE.join(list(mailer_send_to_list))
                                mailer_msg['Date'] = formatdate(localtime=True)
                                mailer_msg['Subject'] = mailer_subject
                                if base_opts.reply_addr:
                                    mailer_msg['Reply-To'] = base_opts.reply_addr

                                if not mailer_file_in_body:
                                    mailer_msg.attach(MIMEText("File %s as of %s conversion\n" % (mailer_file_name_to_send, mailer_conversion_time)))
                                mailer_text = ""

                            if mailer_file_in_body:
                                try:
                                    fi = open(mailer_file_name_to_send, 'r')
                                    mailer_text = mailer_text + fi.read()
                                    fi.close()
                                except:
                                    log_error("Unable to include %s in mailer message - skipping" % mailer_file_name_to_send, 'exc')
                                    log_info("Continuing processing...")
                            else:
                                try:
                                    # Message as attachment
                                    head, tail = os.path.splitext(mailer_file_name_to_send)
                                    if mailer_gzip_file:
                                        if tail.lstrip('.').lower() != 'gz':
                                            mailer_gzip_file_name_to_send = mailer_file_name_to_send + '.gz'
                                            gzip_ret_val = BaseGZip.compress(mailer_file_name_to_send, mailer_gzip_file_name_to_send)
                                            if gzip_ret_val > 0:
                                                log_error("Problem compressing %s - skipping" % mailer_file_name_to_send)
                                        else:
                                            gzip_ret_val = 0

                                        if gzip_ret_val <= 0:
                                            mailer_part = MIMEBase('application', 'octet-stream')
                                            mailer_part.set_payload(open(mailer_gzip_file_name_to_send, 'rb').read())
                                            encoders.encode_base64(mailer_part)
                                            mailer_part.add_header('Content-Disposition', 'attachment; filename="%s"'
                                                                   % os.path.basename(mailer_gzip_file_name_to_send))
                                            mailer_msg.attach(mailer_part)
                                    else:
                                        if tail.lstrip('.').lower() == 'nc' or tail.lstrip('.').lower() == 'gz' \
                                           or tail.lstrip('.').lower() == 'bz2':
                                            mailer_part = MIMEBase('application', 'octet-stream')
                                            mailer_part.set_payload(open(mailer_file_name_to_send, 'rb').read())
                                        else:
                                            mailer_part = MIMEBase('text', 'plain')
                                            mailer_part.set_payload(open(mailer_file_name_to_send, 'r').read())
                                        encoders.encode_base64(mailer_part)
                                        mailer_part.add_header('Content-Disposition', 'attachment; filename="%s"'
                                                               % os.path.basename(mailer_file_name_to_send))
                                        mailer_msg.attach(mailer_part)
                                except:
                                    log_error("Error processing %s" % mailer_file_name_to_send, 'exc')
                                    continue

                            if mailer_msg_per_file:
                                # For multiple messages per recipient, send out message here
                                if mailer_file_in_body:
                                    mailer_msg.set_payload(mailer_text)
                                # Send it out
                                if len(mailer_file_names_to_send):
                                    if base_opts.domain_name:
                                        mailer_send_from = "sg%03d@%s" % (instrument_id, base_opts.domain_name)
                                    else:
                                        mailer_send_from = "sg%03d" % (instrument_id)
                                    try:
                                        smtp = smtplib.SMTP(mail_server)
                                        smtp.sendmail(mailer_send_from, mailer_send_to, mailer_msg.as_string())
                                        smtp.close()
                                    except:
                                        log_error("Unable to send message [%s] skipping" % mailer_line, 'exc')
                                        log_info("Continuing processing...")
                                mailer_msg = None

                        if not mailer_msg_per_file:
                            # For single messages per recipient, send out message here
                            if mailer_file_in_body:
                                mailer_msg.set_payload(mailer_text)
                            # Send it out
                            if len(mailer_file_names_to_send):
                                if base_opts.domain_name:
                                    mailer_send_from = "sg%03d@%s" % (instrument_id, base_opts.domain_name)
                                else:
                                    mailer_send_from = "sg%03d" % (instrument_id)
                                log_info("Sending from %s" % mailer_send_from)
                                try:
                                    smtp = smtplib.SMTP(mail_server)
                                    smtp.sendmail(mailer_send_from, mailer_send_to, mailer_msg.as_string())
                                    smtp.close()
                                except:
                                    log_error("Unable to send message [%s] skipping" % mailer_line, 'exc')
                                    log_info("Continuing processing...")
                            mailer_msg = None

            log_info("Finished processing on .mailer")

        # Process the urls file for the second time
        if not base_opts.local:
            Utils.process_urls(base_opts, 2, instrument_id, dive_num)

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
            log_debug("Error (%s) when deleting intermediate files: \n%s" %   (sys.exc_info(), repr(fc.get_intermediate_files())))

    Utils.cleanup_lock_file(base_opts, base_lockfile_name)

    log_info("Finished processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
    return 0

if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove('--profile')
            profile_file_name = os.path.splitext(os.path.split(sys.argv[0])[1])[0] + '_' \
                + Utils.ensure_basename(time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))) + ".cprof"
            # Generate line timings
            retval = cProfile.run("main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats('time', 'calls')
            stats.print_stats()
        else:
            retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
