#! /usr/bin/env python
## 
## Copyright (c) 2006 - 2017, 2019, 2020 by University of Washington.  All rights reserved.
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

"""FileMgr.py: contains classes for naming conventions & listing version 65/66 basestation files
"""

import glob
import os
import BaseOpts
from BaseLog import *
import Utils
import re
import string
import functools

# regular expressions to verify generic seaglider file with sgid+diveno or just diveno
dive_name_pattern = re.compile("\D{2}\d{4}\D*[.].*")
sgid_dive_name_pattern = re.compile("\D{1,2}\d{7}[.].*") # all p<sgid><dive>.* and ar<sgid><dive>.* files
sgid_name_pattern = re.compile("\D*\d{3}[^\d].*[.].*")

# These extensions are known to the core basestation processing and are constant
post_proc_extensions = [".log", ".cap", ".dat", ".asc", ".eng", ".pro", ".bpo", ".prm", ".pdos", ".pvt", ".pvtst", ".nc", ".gz", ".dn_kkyy", ".up_kkyy"]

# These lists may be extended by loggers
pre_proc_glob_list = ["sg[0-9][0-9][0-9][0-9][ldkp][uztg].[xa0-9]??",   # seaglider file fragments,
                      "sg[0-9][0-9][0-9][0-9][ldkp][uztg].[xa0-9]??.PARTIAL.[0-9]",  # seaglider partial file fragments
                      "sg[0-9][0-9][0-9][0-9][ldkp][uztg].[x]",         # seaglider selftest complete files
                      "sg0000kl.x",                                     # seaglider param file
                      "st[0-9][0-9][0-9][0-9][ldkp][uztg].[xa0-9]??",   # seaglider selftest file fragments
                      "st[0-9][0-9][0-9][0-9][ldkp][uztg].[xa]"]        # seaglider selftest complete files


int_or_postproc_glob_list = ["sg*", "st*"]

post_proc_glob_list = ["p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].??", # .nc NetCDF files 
                       "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].??.??", # nc.gz NetCDF per-dive compressed files
                       "sg*_timeseries.??", "sg*_timeseries.??.??",
                       "sg*_profile.??", "sg*_profile.??.??",
                       "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].???", # .log .eng ... .bpo .pro
                       "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].????", # .pdos
                       "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].??_kkyy", # .up_kkyy .dn_kkyy
                       "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].[0-9][0-9][0-9].????",
                       "pt[0-9][0-9][0-9][0-9][0-9][0-9][0-9].???",
                       "pt[0-9][0-9][0-9][0-9][0-9][0-9][0-9].?????"] # This gets .pvtst files

# These lists are built from the installed loggers
logger_prefixes = []

logger_strip_files = []

def logger_init(init_dict):
    """Updates global structures based on configured loggers

    @param init_dict: A dictionary of initialization dictionaries
    
    """
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if('logger_prefix' in d):
            log_debug("%s prefix is %s" % (key, d['logger_prefix']))
            logger_prefixes.append(d['logger_prefix'])
            if 'strip_files' in d and d['strip_files']:
                logger_strip_files.append(d['logger_prefix'])
            pre_proc_glob_list.append("%s[0-9][0-9][0-9][0-9]??.???" % d['logger_prefix']) # looks for X00, etc.
            pre_proc_glob_list.append("%s[0-9][0-9][0-9][0-9]??.x" % d['logger_prefix'])
            pre_proc_glob_list.append("%s[0-9][0-9][0-9][0-9]??.PARTIAL.[0-9]" % d['logger_prefix'])
            int_or_postproc_glob_list.append(d['logger_prefix'])
            post_proc_glob_list.append("p%s[0-9][0-9][0-9][0-9][0-9][0-9][0-9][ab].???" % d['logger_prefix'])
            post_proc_glob_list.append("p%s[0-9][0-9][0-9][0-9][0-9][0-9][0-9].log" % d['logger_prefix'])
            post_proc_glob_list.append("p%s[0-9][0-9][0-9][0-9][0-9][0-9][0-9].tar" % d['logger_prefix'])
            post_proc_glob_list.append("p%s[0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9].log" % d['logger_prefix'])
            post_proc_glob_list.append("p%s[0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9].tar" % d['logger_prefix'])

def find_dive_logger_eng_files(dive_list, base_opts, instrument_id, init_dict):
    """Given a list of dive files (basenames, log or eng files) to be processed
    Returns a dict, keyed to each input dive file, with list of any associated logger files,
    by type and in their proper order, along with their appropriate reader function
    """
    
    logger_eng_readers = {}  # Mapping from logger prefix to eng_file readers
    
    # Update local lists from loggers
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if('eng_file_reader' in d and 'logger_prefix' in d):
            logger_eng_readers[d['logger_prefix']] = d['eng_file_reader']

    log_debug("logger_eng_readers = %s" % logger_eng_readers)

    # How eng files are labeled by the logger interface for dive and climb, etc.
    # order is critical here to get dive (a) files before climb (b)
    c_list = ('', 'a', 'b')

    # Patterns take a bit to compile so cache in addition to determining if they are needed
    logger_basename_pattern_d = {}
    loggers_present = [];
    for l in logger_prefixes:
        for c in c_list:
            # [0] is sg# and dive_num
            # [1] is sensor_type, if it exists

            # To avoid excessive and very slow per-dive glob'ing for logger files below
            # look for hints that there may be *any* logger files present at all for this pair of l and c
            # If so, add the pattern, which tells to the dive_list mapping below
            # that it should spend the time to glob and get the individual files in different locations
            g1 = glob.glob("%sp%s%03d*%s[_\.]*eng" % (base_opts.mission_dir, l, instrument_id, c)) # any direct logger files for any dive?
            g2 = glob.glob("%s%s*%s" % (base_opts.mission_dir, l, c)) # any logger subdirs for any dive?
            if len(g1) + len(g2) > 0:
                logger_basename_pattern_d[l+c] = [len(g1), len(g2), re.compile('p' + l +'\d+' + c + '(.+)')]
                loggers_present.append(l)

    if len(loggers_present) > 0 and len(dive_list) > 1:
        # Give a hint this could take a while
        log_info("Looking for %s logger engfiles for %d dives" % (Utils.Oxford_comma(Utils.unique(loggers_present)), len(dive_list)))

    # A dictionary mapping dive base names to collections of logger eng files
    logger_eng_files = {}
    for dive_path in dive_list:
        _, tail = os.path.split(dive_path)
        d = int(tail[4:8]) # dive number
        # Now add on all possible contributions from loggers and add to the list
        # along with the eng file reader
        logger_eng_files[dive_path] = []
        for l in logger_prefixes:
            typed_files = {} # {type: [ordered files], ...}
            for c in c_list:
                try:
                    ng1, ng2, logger_basename_pattern = logger_basename_pattern_d[l+c]
                except KeyError:
                    continue # no files or subdirs

                globs = []
                # We know from above that there are files for this logger type
                # Lookup the individual files and organize into groups by type and dive/climb order
                # We call glob.glob for every dive number individually, which is slow but unavoidable
                # since glob doesn't expand directories if you use * in dir names, sigh
                # e.g., <mission_dir/>pctGGGDDDDa[_.]*eng (for different sensors)
                # /home/seagliders/sg099/psc0990022a_depth_depth.eng
                if ng1:
                    globs.append("%sp%s%03d%04d%s[_\.]*eng" % (base_opts.mission_dir, l, instrument_id, d, c))
                # e.g., <mission_dir/>scDDDDa/pscGGGDDDDa[_.]*eng (for different sensors)
                # /home/seagliders/sg099/sc0022a/psc0990022a_depth_depth.eng
                if ng2:
                    globs.append("%s%s%04d%s/p%s%03d%04d%s[_\.]*eng" % (base_opts.mission_dir, l, d, c, l, instrument_id, d, c))
                for glob_expr in globs:
                    for logger_eng_filename in glob.glob(glob_expr):
                        #log_info("Considering %s" % logger_eng_filename)
                        _, base = os.path.split(logger_eng_filename)
                        base, _ = os.path.splitext(base) # remove extension
                        base_match = re.match(logger_basename_pattern, base)
                        if (base_match):
                            sensor_type = base_match.group(1)
                            sensor_type = sensor_type.split('_')[1] # extract the type
                        else:
                            sensor_type = l
                        try:
                            file_list = typed_files[sensor_type]
                        except KeyError:
                            file_list = []
                            typed_files[sensor_type] = file_list
                        if(c == ''):
                            cast = 3
                        elif(c == 'a'):
                            cast = 1
                        else:
                            cast = 2
                        file_list.append({'cast' : cast, 'file_name' : logger_eng_filename})

            # One entry, per logger
            if(len(list(typed_files.keys())) > 0):
                logger_eng_files[dive_path].append({'logger_prefix' : l,
                                                    'eng_files': typed_files,
                                                    'eng_file_reader' : logger_eng_readers[l]})
    if False: # report the results for debugging
        log_info("Logger eng list")
        for k in list(logger_eng_files.keys()):
            log_info("%s:%s" % (k, logger_eng_files[k]))

    return logger_eng_files

# Utility functions

def sort_dive(a, b):
    """Sorts list items in dive number major order 
    """
    # Sort on the dive number first
    dive_a = get_dive(a) # int(os.path.basename(a)[2:6])
    dive_b = get_dive(b) # int(os.path.basename(b)[2:6])
    if(dive_a > dive_b):
        return 1
    elif(dive_a < dive_b):
        return -1
    else:
        # Now, remove the dive number from the name and sort the
        # remaining piece normally

        tmp_divea = os.path.basename(a).replace(str(dive_a), "", 1)
        tmp_diveb = os.path.basename(b).replace(str(dive_b), "", 1)

        return (tmp_divea > tmp_diveb) - (tmp_divea < tmp_diveb)
    
def sort_fragments(a, b):
    """Sorts a list of fragments.

    In version 66, fragments are indexed with hexidecimal numbers, with C being
    replaced by a K.
    """
    # Sort on the dive number first
    counter_a = get_counter(a) # int(os.path.basename(a)[2:6])
    counter_b = get_counter(b) # int(os.path.basename(b)[2:6])
    if(counter_a > counter_b):
        return 1
    elif(counter_a < counter_b):
        return -1
    else:
        # Equivelent counters - get partial count
        partial_count_a = get_partial_count(a)
        partial_count_b = get_partial_count(b)
        if(partial_count_a > partial_count_b):
            return 1
        else:
            return -1

def get_instrument_id(filename):
    name, ext = os.path.splitext(os.path.basename(filename))
    if (name):
        try:
            return int(name[1:4])
        except:
            return -1
    return -1


def get_dive(filename):
    """Gets the dive number form a glider file
    """
    if filename is None:
        return -1
    
    name = os.path.basename(filename)
    if (name):
        if dive_name_pattern.match(name):
            return int(name[2:6])
        elif sgid_dive_name_pattern.match(name):
            return int(name.lstrip(string.ascii_letters)[3:7])

    return -1

def get_counter(filename):
    """Gets the counter from a fragment file name
    """
    head, ext = os.path.splitext(get_non_partial_filename(filename))
    if(ext):
        ext = ext.upper()
        if(ext[0:2] == '.X' and len(ext) == 4):
            cnt = ext[2:4]
            cnt = cnt.replace('K', 'C')
            return int(cnt, 16)
    return -1

def get_partial_count(filename):
    """Returns the partial file counter.
    Returns -1 if there is no partial count
    """
    if(filename.find("PARTIAL") >= 0):
        head, partial_counter = os.path.splitext(filename)
        return int(partial_counter[1:])
    else:
        # Bigger then any other fragment
        return 1000

def get_non_partial_filename(filename):
    """Returns the root of the file,
    trimming any PARTIAL.X extensions
    """
    if(filename.find("PARTIAL") >= 0):
        head, partial_counter = os.path.splitext(filename)
        head, tmp = os.path.splitext(head)
        return head
    else:
        return filename

def get_non_1a_filename(filename):
    """Returns the root of the file,
    trimming the internal 1a
    """
    if(filename.find('.1a.') >= 0):
        return filename.replace('.1a.', '.', 1)
    else:
        return filename

def get_non_bogue_filename(filename):
    """Returns the root of the file,
    trimming the internal bogue
    """
    if(filename.find('.b.') >= 0):
        return filename.replace('.b.', '.', 1)
    else:
        return filename

# Classes

class FileCode:
    """Given a filename - either a Seaglider transmistted file format, 
    provide details on the encoding from the filename and appropriate conversions
    Optional: given a BaseLog, may log info, warning, errors, etc.
    """
    def __init__(self, filename, instrument_id):
        if(len(os.path.basename(filename)) < 8):
            raise ValueError("File " + filename + " too short to be a valid file to process")
        
        if(filename != get_non_1a_filename(filename)):
            filename = get_non_1a_filename(filename)
            self._1a = True
        else:
            self._1a = False
            
        if(filename != get_non_bogue_filename(filename)):
            filename = get_non_bogue_filename(filename)
            self._Bogue = True
        else:
            self._Bogue = False
            

        self._partial_count = get_partial_count(filename)
        if(self._partial_count < 1000):
            self._partial = True
            filename = get_non_partial_filename(filename)
        else:
            self._partial = False

        if(len(os.path.basename(filename)) > 13):
            raise ValueError("File %s too long to be a valid file to process" % filename)
        self._len = len(os.path.basename(filename))
        self._filename = os.path.basename(filename)
        self._full_filename = filename
        self._instrument_id = instrument_id

    def full_filename(self):
        return self._full_filename
        
    def base_name(self):
        return self._filename[0:8]

    def dive_number(self):
        return int(self._filename[2:6])

    def up_down(self):
        return self._filename[6:7]

    def logger_prefix(self):
        return self._filename[0:2]

    # The following related to tranmitted file formats
    # All such formats follow the convention described in Seaglider
    # File Format document (version 66 and later)

    # Origin
    def is_seaglider(self): # raw seaglider file
        if(self._filename[0:2] == "sg"):
            return True
        else:
            return False
    def is_seaglider_selftest(self): # seaglider self-test
        if(self._filename[0:2] == "st"):
            return True
        else:
            return False

    def is_logger(self):
        if(self._filename[0:2] in logger_prefixes):
            return True
        else:
            return False

    def is_logger_strip_files(self):
        if(self._filename[0:2] in logger_strip_files):
            return True
        else:
            return False
        
    # File packing/compression
    def is_uncompressed(self):
        if(self._filename[7:8] == "u"):
            return True
        else:
            return False
        
    def is_gzip(self):
        if(self._filename[7:8] == "z"):
            return True
        else:
            return False
        
    def is_bzip(self):
        if(self._filename[7:8] == "j"):
            return True
        else:
            return False
        
    def is_tar(self):
        if(self._filename[7:8] == "t"):
            return True
        else:
            return False
        
    def is_tgz(self):
        if(self._filename[7:8] == "g"):
            return True
        else:
            return False

    def is_tjz(self):
        if(self._filename[7:8] == "b"):
            return True
        else:
            return False

    def is_logger_payload(self):
        """This refers to the generic logger payload file,
        not the Seabird ct payload sensor
        """
        if(self._filename[7:8] == "p"):
            return True
        else:
            return False

    # Type of underlying file
    def is_log(self):
        if(self._filename[6:7] == "l"):
            return True
        else:
            return False

    def is_data(self):
        if(self._filename[6:7] == "d"):
            return True
        else:
            return False

    def is_capture(self):
        if(self._filename[6:7] == "k"):
            return True
        else:
            return False

    def is_pdos_log(self):
        if(self._filename[6:7] == "p"):
            return True
        else:
            return False

    # These are only used by loggers
    def is_down_data(self):
        if(self._filename[6:7] == "a"):
            return True
        else:
            return False

    def is_up_data(self):
        if(self._filename[6:7] == "b"):
            return True
        else:
            return False
        
    def up_down_data(self):
        if(self.is_down_data()):
            return "a"
        elif(self.is_up_data()):
            return "b"
        else:
            return ''

    # Hybrid
    def is_parm_file(self):
        """This file type is outside the normal naming conventions - it
        is the parameter capture file that is generated once during the gliders
        very first call during the launch sequence"""
        if(self._filename[6:8] == "kl"):
            return True
        else:
            return False

    # Tranmission state
    def is_xmit(self):
        if(self._len > 9 and self._filename[9:10] == "x"):
            return True
        else:
            return False
        
    def is_archive(self):
        if(self._len > 9 and self._filename[9:10] == "a"):
            return True
        else:
            return False

    def is_received(self):
        if(self._len > 9 and self._filename[9:10] == "r"):
            return True
        else:
            return False

    # Fragments
    def is_fragment(self):
        try:
            counter = self._filename[10:12]
        except:
            return False
        else:
            return True

    def get_fragment_counter(self):
        if len(self._filename) < 12:
            # No counter present
            return -1
        try:
            counter = int(self._filename[10:12], base=16)
        except ValueError:
            return -1
        else:
            return counter


    # Processed files
    def is_processed_seaglider_log(self):
        root, ext = os.path.splitext(self._filename)
        
        if(self._filename[0:1] == "p" and ext == ".log"):
            return True
        else:
            return False

    def is_processed_seaglider_selftest_log(self):
        root, ext = os.path.splitext(self._filename)
        
        if(self._filename[0:1] == "pt" and ext == ".log"):
            return True
        else:
            return False

    # Marker names
    def is_dive_marker(self):
        if(self._len > 9 and self._filename[7:11] == "dive"):
            return True
        else:
            return False

    # Conversion utilities - produce a name of the new form
    def make_uncompressed(self):
        """Returns: file name that is an uncompressed encoding
           of this current file
        """
        head, tail = os.path.split(self._full_filename)
        tail = tail[0:7] + "u" + tail[8:]
        return os.path.join(head, tail)

    def make_data(self):
        """Returns: file name that is an data file encoding
           of this current file
        """
        head, tail = os.path.split(self._full_filename)
        tail = tail[0:6] + "d" + tail[7:]
        return os.path.join(head, tail)

    def mk_base_logfile_name(self):
        """Returns: log file name of the form on the basestation
           - as opposed to the transmission name.

           Raises: ValueError if called for an unrecognized file
        """
        head, tail = os.path.split(self._full_filename)
        log_debug(self._filename + ": " + str(self.dive_number()))
        #print instrument_id
        if(self.is_seaglider()):
            tail = "p%03d%04d.log" % (int(self._instrument_id), int(self.dive_number()))
        elif(self.is_seaglider_selftest()):
            tail = "pt%03d%04d.log" % (int(self._instrument_id), int(self.dive_number()))
        elif(self.is_logger()):
            tail = "p%s%03d%04d.log" % (self.logger_prefix(), self._instrument_id, self.dive_number())
        else:
            raise ValueError("Don't know the logfile encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_capfile_name(self):
        """Returns: capture file name of the form on the basestation
           - as opposed to the transmission name.

           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".cap"
        elif(self.is_seaglider_selftest()):
            tail = "pt" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".cap"
        else:
            raise ValueError("Don't know the capture file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_datfile_name(self):
        """Returns: data file name of the form on the basestation
           - as opposed to the transmission name

           None for error opening the file

           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".dat"
        elif(self.is_seaglider_selftest()):
            tail = "pt" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".dat"
        elif(self.is_logger()):
            if(self.is_up_data() or self.is_down_data):
                tail = "p%s%03d%04d%c.dat" % (self.logger_prefix(), self._instrument_id, self.dive_number(), self.up_down())
            else:
                tail = "p%s%03d%04d.dat" % (self.logger_prefix(), self._instrument_id, self.dive_number())
        else:
            raise ValueError("Don't know the capture file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_ascfile_name(self):
        """Returns: acs file name of the form on the basestation
           - as opposed to the transmission name.

           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".asc"
        elif(self.is_seaglider_selftest()):
            tail = "pt" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".asc"
        else:
            raise ValueError("Don't know the capture file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_engfile_name(self):
        """Returns: eng file name of the form on the basestation

           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".eng"
        elif(self.is_seaglider_selftest()):
            tail = "pt" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".eng"
        elif(self.is_logger()):
            tail = "p%s%03d%04d%c.eng" % (self.logger_prefix(), self._instrument_id, self.dive_number(), self.up_down())
        else:
            raise ValueError("Don't know the eng file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_profile_name(self):
        """Returns: profile file name of the form on the basestation

           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".pro"
        else:
            raise ValueError("Don't know the eng file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_binned_profile_name(self):
        """Returns: binned profile file name of the form on the basestation

           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".bpo"
        else:
            raise ValueError("Don't know the eng file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_netCDF_name(self):
        """Returns: nc file name of the form on the basestation
        (Created during make_netCDF)
        Conforms to CF naming convention, see http://www.cgd.ucar.edu/cms/eaton/cf-metadata/CF-current.html
        
           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".nc"
        else:
            raise ValueError("Don't know the netCDF file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)


    def mk_base_parm_name(self):
        """Returns: parm file name of the form on the basestation
        (Created during the gliders first call in during the launch sequence)

           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number()) + ".prm"
        else:
            raise ValueError("Don't know the prm file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_base_name(self):
        """Returns: a base file name of the form on the basestation
           - used for interop with old basestation code

           Raises: ValueError if called for a non-seaglider file
        """
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider()):
            tail = "p" + "%03d" % (self._instrument_id) + "%04d" % (self.dive_number())
        else:
            raise ValueError("Don't know the capture file encoding for %s" % self._full_filename)
        return os.path.join(head, tail)

    def mk_base_pdos_logfile_name(self):
        """Returns: pdos logfile name of the form on the basestation

           Raises: ValueError if called for a non-seaglider non-pdos file
        """
        root, ext = os.path.splitext(self._full_filename)
        head, tail = os.path.split(self._full_filename)
        if(self.is_seaglider() and self.is_pdos_log()):
            tail = "p%03d%04d%s.pdos" % (int(self._instrument_id), int(self.dive_number()), ext)
        elif(self.is_seaglider_selftest() and self.is_pdos_log()):
            tail = "pt%03d%04d%s.pdos" % (int(self._instrument_id), int(self.dive_number()), ext)
        else:
            raise ValueError("Don't know the pdos logfile encoding for %s" % self._full_filename)
        return os.path.join(head, tail)


class FileCollector:
    """Collects files from a given directory for processing and/or moving
    and maintains the state of what needs to be processed.
    """

    def __init__(self, homedir, instrument_id):
        self._pre_file_list = []
        self._post_file_list = []
        self._intermediate_file_list = []
        self.all_dives = []
        self.all_selftests = []
        self._instrument_id = instrument_id

        log_debug("FileCollector Using static logger")

        # original (raw) data files "pre_proc"
        for glob_expr in pre_proc_glob_list:
            for match in glob.glob(os.path.join(homedir, glob_expr)): 
                self._pre_file_list.append(match)
        #TODO - consider adding the non-transmitted versions here - ie sg[0-9][0-9][0-9][0-9][ldkp][uztg].[xar0-9]
        self._pre_file_list.sort(key=functools.cmp_to_key(sort_dive))

        # intermediate or post-proc files
        filelist = []
        for glob_expr in int_or_postproc_glob_list:
            filelist.append(glob.glob(os.path.join(homedir, "%s*" % glob_expr)))
        Utils.flatten(filelist)

        for filename in filelist:
            if filename not in self._pre_file_list:
                # should it go in the post-production list?
                if sgid_dive_name_pattern.match(os.path.basename(filename)):
                    self._post_file_list.append(filename)
                # should it go in the intermediate list?
                elif dive_name_pattern.match(os.path.basename(filename)):
                    self._intermediate_file_list.append(filename)
                else:
                    log_debug("Unrecognized file: %s" % os.path.basename(filename))

        # specific post-proc files
        for glob_expr in (post_proc_glob_list):
            for filename in glob.glob(os.path.join(homedir, glob_expr)):
                # do we know the extension?
                name, ext = os.path.splitext(filename)
                if ext in post_proc_extensions:
                    self._post_file_list.append(filename)
                else:
                    log_debug("Unrecognized file: %s" % os.path.basename(filename))
                    
        self._intermediate_file_list.sort(key=functools.cmp_to_key(sort_dive))
        self._post_file_list.sort(key=functools.cmp_to_key(sort_dive))

        log_debug("Found the following pre-processed files")
        for filename in self._pre_file_list:
            log_debug(os.path.basename(filename))
        log_debug("Found the following intermediate files") 
        for filename in self._intermediate_file_list:
            log_debug(os.path.basename(filename))
        log_debug("Found the following post-processed files") 
        for filename in self._post_file_list:
            log_debug(os.path.basename(filename))

        # Build a list of all the dives found
        for i in self._pre_file_list:
            fc = FileCode(i, self._instrument_id)
            if(fc.is_seaglider() or fc.is_logger()):
                self.all_dives.append(int(os.path.basename(i)[2:6]))
        self.all_dives = Utils.unique(self.all_dives)

        # Build a list of all the self-tests found
        for i in self._pre_file_list:
            fc = FileCode(i, self._instrument_id)
            if(fc.is_seaglider_selftest()):
                self.all_selftests.append(int(os.path.basename(i)[2:6]))
        self.all_selftests = Utils.unique(self.all_selftests)

    def get_pdoscmd_log_files(self):
        """Returns a glider's pdoscmd logs
        """
        pdoscmd_logs_list = []
        for i in self._pre_file_list:
            fc = FileCode(i, self._instrument_id)
            if ((fc.is_seaglider() or fc.is_seaglider_selftest()) and fc.is_pdos_log()):
                log_debug("pdoslogfile - %s" % i)
                pdoscmd_logs_list.append(i)
        pdoscmd_logs_list.sort()
        return pdoscmd_logs_list

    def get_pre_proc_selftest_files(self, selftest_num):
        """Returns a sorted list of all the pre-processed (original data/log) files related to a given selftest
        """
        selftest_list = []
        for i in self._pre_file_list:
            fc = FileCode(i, self._instrument_id)
            if (fc.is_seaglider_selftest() and int(os.path.basename(i)[2:6]) == selftest_num):
                selftest_list.append(i)
        return selftest_list

    def get_pre_proc_dive_files(self, dive):
        """Returns a sorted list of all the pre-processed (original data/log) files related to a given dive
           Note: seaglider selftest files are excluded
        """
        dive_list = []
        for i in self._pre_file_list:
            if(int(os.path.basename(i)[2:6]) == dive):
                fc = FileCode(i, self._instrument_id)
                if(fc.is_seaglider_selftest()):
                    continue
                dive_list.append(i)
        return dive_list

    def get_intermediate_dive_files(self, dive):
        """Returns a sorted list of all the intermediate files related to a given dive.
        """
        dive_list = []
        for i in self._intermediate_file_list:
            if(get_dive(os.path.basename(i)) == dive):
                dive_list.append(i)
        return dive_list

    def get_post_proc_dive_files(self, dive):
        """Returns a sorted list of all the post-processed files (products) related to a given dive.
        """
        dive_list = []
        for i in self._post_file_list:
            if(get_dive(os.path.basename(i)) == dive):
                dive_list.append(i)
        return dive_list


    def get_pre_proc_files(self):
        """Returns a sorted list of all the pre-processed (original data/log) files
        """
        return self._pre_file_list

    def get_intermediate_files(self):
        """Returns a sorted list of all the pre-processed (original data/log) files
        """
        return self._intermediate_file_list

    def get_post_proc_files(self):
        """Returns a sorted list of all the pre-processed (original data/log) files
        """
        return self._post_file_list

    def list_dives(self):
        """Logs all the dives found by the collector
        """
        log_info("Found the following dives")
        log_info(self.all_dives)

