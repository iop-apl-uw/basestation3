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

"""Contains all routines for extracting data from a glider's data file"""

import collections
import copy
import os
import pdb
import re
import sys
import time
import traceback

import numpy as np

import BaseOpts
import BaseOptsType
import CalibConst
import FileMgr
import Globals
import LogFile
import Sensors
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


# A number that we can clear identify as a standing for "NaN"
# inf = 1e300000
# nan = inf/inf  Alas, this doesn't work
large = 1e300
inf = large * large
nan = inf - inf

# Setup the config file section and contents
data_files_section = "datafiles"
data_files_default_dict = {"sensor_file": [".sensors", None]}
removed_tag = "REMOVED_"
removed_re = re.compile("^%s" % removed_tag)


class DataFile:
    """Object representing a seaglider data file"""

    def __init__(self, file_type, calib_consts):
        if file_type in ("dat", "asc", "eng"):
            self.file_type = file_type
        else:
            raise ValueError(
                "file_type %s not valid - only dat, asc or eng are valid" % file_type
            )
        self.version = None
        self.glider = None
        self.mission = None
        self.dive = None
        self.selftest = None
        self.start_ts = None
        self.columns = []
        # self.data = []
        self.data = None
        self.eng_cols = None
        self.eng_dict = None
        self.calib_consts = calib_consts
        self.timeouts = collections.defaultdict(list)
        self.timeouts_obs = collections.defaultdict(list)
        self.timeouts_times = collections.defaultdict(str)

    def lookup_class_name(self, col_name):
        if col_name in ("heading", "pitch", "roll", "mag.x", "mag.y", "mag.z"):
            return "compass"
        elif "." in col_name:
            return col_name.split(".", 1)[0]
        else:
            return col_name

    def row_time(self, raw_strs):
        time.mktime(self.start_ts) + raw_strs[self.columns.index("")]

    def dat_to_asc(self):
        """Converts a data file to a an ASC file"""
        if self.file_type == "asc":
            return

        if self.file_type != "dat":
            raise ValueError(
                "Only dat types may be converted to asc - current type %s"
                % (self.file_type)
            )

        row, col = self.data.shape
        for i in range(1, row):
            for j in range(col):
                if np.isfinite(self.data[i - 1][j]):
                    self.data[i][j] = self.data[i][j] + self.data[i - 1][j]

        self.file_type = "asc"

    def asc_to_eng(self, log_file):
        """Converts an ASC format to a an ENG format.
        Requires a log_file object

        Returns: 0 success, 1 failure

        Raises:
                Any exceptions raised are considered critical errors and not expected
        """
        if self.file_type == "eng":
            return 0

        if self.file_type != "asc":
            log_error(
                "Only asc types may be converted to eng - current type %s"
                % (self.file_type)
            )
            return 1

        self.eng_dict = {}
        self.eng_cols = []

        #
        # Truck processing
        #

        elaps_t = self.remove_col("elaps_t")
        if elaps_t is None:
            # Check for column marked as milliseconds
            elaps_tms = self.remove_col("elaps_tms")
            if elaps_tms is not None:
                # If present - convert back seconds, retaining precision
                elaps_t = elaps_tms / 1000.0
        depth = self.remove_col("depth")
        heading = self.remove_col("heading")
        pitchAng = self.remove_col("pitch")
        rollAng = self.remove_col("roll")
        AD_pitch = self.remove_col("AD_pitch")
        AD_roll = self.remove_col("AD_roll")
        AD_vbd = self.remove_col("AD_vbd")
        rec = self.remove_col("rec")
        GC_phase = self.remove_col("GC_phase")
        optional_cols = {}
        for c in ("volt1", "volt2", "curr1", "curr2", "GC_state"):
            optional_cols[c] = self.remove_col(c)

        num_rows = len(elaps_t)

        # Conversions - some instruments need conversions from the asc representation
        # to the eng representation

        # Time
        start_time_seconds = (
            log_file.start_ts.tm_hour * 3600
            + log_file.start_ts.tm_min * 60
            + log_file.start_ts.tm_sec
        )
        elaps_t_0000 = elaps_t + start_time_seconds

        pitch_cm_per_ad = log_file.data["$PITCH_CNV"]
        pitch_center = log_file.data["$C_PITCH"]
        roll_deg_per_ad = log_file.data["$ROLL_CNV"]
        roll_center_climb = log_file.data["$C_ROLL_CLIMB"]
        roll_center_dive = log_file.data["$C_ROLL_DIVE"]
        vbd_cc_per_ad = log_file.data["$VBD_CNV"]
        vbd_center = log_file.data["$C_VBD"]

        head = heading / 10.0
        pitchAng = pitchAng / 10.0
        rollAng = rollAng / 10.0

        # For version 67.00 and later, the pitchCtl rollCtl (both misnamed) and vbdCC are
        # not reported in the .eng file because the correstponding .dat file. vbdCC will
        # need to be derived from the GC table in the logfile
        #
        # GC_phase is dropped because it has little meaning in the new code base
        if AD_pitch is not None:
            pitchCtl = (AD_pitch - pitch_center) * pitch_cm_per_ad

            rollCtl = np.zeros(num_rows, float)
            for i in range(num_rows):
                if pitchAng[i] > 0.0:
                    rollCtl[i] = (AD_roll[i] - roll_center_climb) * roll_deg_per_ad
                else:
                    rollCtl[i] = (AD_roll[i] - roll_center_dive) * roll_deg_per_ad

            vbdCC = (AD_vbd - vbd_center) * vbd_cc_per_ad
            # Set up the eng columns - order matters
            self.eng_cols = [
                "elaps_t_0000",
                "elaps_t",
                "depth",
                "head",
                "pitchAng",
                "rollAng",
                "pitchCtl",
                "rollCtl",
                "vbdCC",
                "rec",
                "GC_phase",
            ]
            self.eng_dict["pitchCtl"] = pitchCtl
            self.eng_dict["rollCtl"] = rollCtl
            self.eng_dict["vbdCC"] = vbdCC
            self.eng_dict["GC_phase"] = GC_phase
        else:
            # Set up the eng columns - order matters
            self.eng_cols = [
                "elaps_t_0000",
                "elaps_t",
                "depth",
                "head",
                "pitchAng",
                "rollAng",
                "rec",
            ]

        # Scale with reported pressure if using a kistler.cnf file
        pressure = self.remove_col("pressure")
        press_counts = self.remove_col("press_counts")
        if pressure is not None:
            self.eng_cols.append("pressure")
            self.eng_dict["pressure"] = pressure / 10.0
            self.eng_cols.append("press_counts")
            self.eng_dict["press_counts"] = press_counts

        # Add common columns to the output dictionary
        self.eng_dict["elaps_t_0000"] = elaps_t_0000
        self.eng_dict["elaps_t"] = elaps_t
        self.eng_dict["depth"] = depth
        self.eng_dict["head"] = head
        self.eng_dict["pitchAng"] = pitchAng
        self.eng_dict["rollAng"] = rollAng
        self.eng_dict["rec"] = rec
        for c in ("volt1", "volt2", "curr1", "curr2", "GC_state"):
            if (c in optional_cols) and (optional_cols[c] is not None):
                self.eng_dict[c] = optional_cols[c]
                self.eng_cols.append(c)

        #
        # Sensor processing
        #
        Sensors.process_sensor_extensions("asc2eng", self)

        unhandled_cols = []
        for x in self.columns:
            if not self.removed_col(x) and len(x) > 0:
                unhandled_cols.append(x)

        # Default handler
        if len(unhandled_cols) > 0:
            log_info(
                "asc2eng - no handler found for columns %s - using default handler (no scaling or offset applied)"
                % unhandled_cols
            )
            for x in unhandled_cols:
                self.eng_cols.append(x)
                self.eng_dict[x] = self.remove_col(x)

        self.data = np.zeros((num_rows, len(self.eng_cols)), np.float64)

        for i in range(num_rows):
            for j in range(len(self.eng_cols)):
                self.data[i][j] = self.eng_dict[self.eng_cols[j]][i]

        self.columns = self.eng_cols
        self.eng_cols = None
        self.eng_dict = None

        # Process timeouts

        # Remap the class names
        old_cls_names = list(self.timeouts_obs.keys())
        new_cls_names = copy.deepcopy(old_cls_names)
        Sensors.process_sensor_extensions(
            "remap_engfile_columns_netcdf", self.calib_consts, new_cls_names
        )
        for old_cls, new_cls in zip(old_cls_names, new_cls_names, strict=True):
            self.timeouts_obs[new_cls] = self.timeouts_obs.pop(old_cls)

        # Convert obs to epoch times and count up timeouts
        start_time = time.mktime(self.start_ts)
        for cls, obs in self.timeouts_obs.items():
            self.timeouts[cls] = len(obs)
            try:
                for ob in obs:
                    self.timeouts_times[cls] += (
                        f"{start_time + self.data[ob,self.columns.index('elaps_t')]:.3f},"
                    )
            except Exception:
                log_error(f'Failed processing timeouts for instrument "{cls}"', "exc")

        # Mark the new data type
        self.file_type = "eng"
        return 0

    def dump(self, fo=sys.stdout, header_only=0, matlab_comment_override=0):
        """Dumps the file back out - or optionally, just the header data
        matlab_comment_override:
        -1 don't use it
        0 do whatever the file format says to
        1 use
        """
        if matlab_comment_override > 0:
            prefix = "%"
        elif matlab_comment_override < 0:
            prefix = ""
        elif self.file_type == "eng":
            prefix = "%"
        else:
            prefix = ""
        fo.write("%sversion: %2.2f\n" % (prefix, self.version))
        fo.write("%sglider: %d\n" % (prefix, self.glider))
        fo.write("%smission: %d\n" % (prefix, self.mission))
        if self.dive is not None:
            fo.write("%sdive: %d\n" % (prefix, self.dive))
        elif self.selftest is not None:
            fo.write("%sselftest: %d\n" % (prefix, self.selftest))
        else:
            log_error("Neither dive nor selftest was set")
        fo.write("%sbasestation_version: %s\n" % (prefix, Globals.basestation_version))
        # Timeouts
        for cls, timeouts in self.timeouts.items():
            fo.write(f"%{cls}_timeouts:{timeouts}\n")
        for cls, obs in self.timeouts_obs.items():
            fo.write(f"%{cls}_timeouts_obs:{','.join([str(x) for x in obs])}\n")
        for cls, times in self.timeouts_times.items():
            fo.write(f"%{cls}_timeouts_times:{times}\n")
        time_string = time.strftime("%m %d %y %H %M %S", self.start_ts)
        time_parts = time_string.split()
        fo.write(
            "%sstart: %s %s %3d %s %s %s\n"
            % (
                prefix,
                time_parts[0],
                time_parts[1],
                int(time_parts[2]) + 100,
                time_parts[3],
                time_parts[4],
                time_parts[5],
            )
        )
        if not header_only:
            fo.write(
                "%scolumns: " % (prefix),
            )
            for i in range(len(self.columns) - 1):
                # print >>fo, "%s," % i.lstrip().rstrip(),
                fo.write("%s," % self.columns[i].lstrip().rstrip())
            # Write the last one out
            fo.write("%s" % self.columns[-1].lstrip().rstrip())
            fo.write("\n")
            fo.write("%sdata:\n" % (prefix))
            row, col = self.data.shape
            for i in range(row):
                for j in range(col):
                    if np.isfinite(self.data[i][j]):
                        # print >>fo, '%0.f' % self.data[i][j],
                        if self.file_type == "eng":
                            fo.write("%.3f " % self.data[i][j])
                        else:
                            fo.write("%0.f " % self.data[i][j])
                    else:
                        if self.file_type == "dat":
                            fo.write("N")
                        else:
                            fo.write("NaN ")
                fo.write("\n")

    def remove_col(self, label):
        """Fetches the column of data matching the label
        If successful, removes the column label from the colums list
        """
        try:
            ret_val = np.array(self.data[:, self.columns.index(label)], float)
            # we don't delete the data itself so make it inaccessible later
            # this also has the advantage that it is clear who is responsible
            self.columns[self.columns.index(label)] = "%s%s" % (removed_tag, label)
        except ValueError:
            ret_val = None

        return ret_val

    def remove_col_regex(self, regex):
        """Fetches the first column of data matching the label regex
        If successful, removes the column label from the colums list
        """
        for c in self.columns:
            if re.match(regex, c):
                return self.remove_col(c)

        return None

    def removed_col(self, label):
        """Tests whether the label refers to a removed column,
        which really isn't removed, just labeled as such.
        """
        return removed_re.search(label)

    def get_col(self, label):
        """Fetches the column of data matching the label"""
        try:
            ret_val = np.array(self.data[:, self.columns.index(label)], float)
        except ValueError:
            ret_val = None

        return ret_val

    def update_col(self, label, data):
        """Updates the data in an existing column"""
        self.data[:, self.columns.index(label)] = data

    def find_col(self, alternative_columns):
        """Find one of the alternative_column names and returns the column name and the values"""
        for column_name in alternative_columns:
            values_v = self.get_col(column_name)
            if values_v is not None:
                return (column_name, values_v)
        return (None, None)

    def remap_engfile_columns(self):
        """Remaps column header names on self to canonical forms suitable for other languages
        Including ourselves when we re-read in MDP:load_dive_profile_data()
        Converts instrument.datacol and the general issue of '.' in netCDF names
        Not every programming language supports these variables, specifically some Matlab toolbox functions

        Returns: None

        Raises:
        """
        new_columns = []
        for column_name in self.columns:
            # Remove the . separator for sensor.column preserving order
            new_columns.append(column_name.replace(".", "_"))

        # See if a sensor column name needs to be remapped for output
        Sensors.process_sensor_extensions(
            "remap_engfile_columns_netcdf", self.calib_consts, new_columns
        )
        # update
        self.columns = new_columns
        return None

    def eliminate_rows(self, bad_rows):
        """Removes the listed rows from the data set"""
        # (row,col) = self.data.shape
        # temp = array ()
        pass


def process_data_file(in_filename, file_type, calib_consts):
    """Processes any Seaglider data file

    Returns a DataFile object or None for an error
    """

    try:
        raw_data_file = open(in_filename, "r")
    except OSError:
        log_error("Could not open " + in_filename + " for reading")
        return None

    line_count = 0
    rows = []
    # Process the header
    while True:
        raw_line_temp = raw_data_file.readline()
        log_debug("[%s]" % raw_line_temp)
        raw_line = raw_line_temp.rstrip()
        line_count += 1
        if raw_line == "":
            log_error("No valid header found in %s" % in_filename)
            return None

        raw_strs = raw_line.split(":")
        log_debug("Line parsed %s" % raw_line)

        if line_count == 1:
            if raw_strs[0] == "version" or raw_strs[0] == "%version":
                data_file = DataFile(file_type, calib_consts)
                try:
                    data_file.version = float(raw_strs[1])
                except ValueError:
                    # Might be an iRobot version - major.minor.rev1.rev2
                    tmp2 = raw_strs[1].rsplit(".", 2)[0]
                    try:
                        data_file.version = float(tmp2)
                    except ValueError:
                        log_error("Unknown version %s = assuming 66.00" % raw_strs[1])
                        data_file.version = 66.00
                continue
            else:
                log_error("first line did not contain a version string %s" % raw_line)
                return None

        if raw_strs[0] == "glider" or raw_strs[0] == "%glider":
            data_file.glider = int(raw_strs[1])
            continue
        elif raw_strs[0] == "mission" or raw_strs[0] == "%mission":
            data_file.mission = int(raw_strs[1])
            continue
        elif raw_strs[0] == "dive" or raw_strs[0] == "%dive":
            data_file.dive = int(raw_strs[1])
            continue
        elif raw_strs[0] == "selftest" or raw_strs[0] == "%selftest":
            data_file.selftest = int(raw_strs[1])
            continue
        elif raw_strs[0] == "start" or raw_strs[0] == "%start":
            time_parts = raw_strs[1].split()
            if int(time_parts[2]) - 100 < 0:
                year_part = int(time_parts[2])
            else:
                year_part = int(time_parts[2]) - 100
            time_string = "%s %s %02d %s %s %s" % (
                time_parts[0],
                time_parts[1],
                year_part,
                time_parts[3],
                time_parts[4],
                time_parts[5],
            )
            try:
                data_file.start_ts = Utils.fix_gps_rollover(
                    time.strptime(time_string, "%m %d %y %H %M %S")
                )
            except ValueError:
                log_error(f"Bad time string found {time_string}")
                data_file.start_ts = time.strptime("1 1 70 0 0 0", "%m %d %y %H %M %S")
        elif raw_strs[0] == "columns" or raw_strs[0] == "%columns":
            for i in raw_strs[1].rstrip().split(","):
                if len(i):
                    data_file.columns.append(i.lstrip().rstrip(chr(0x1A)))
            continue
        elif (
            "timeouts_obs" in raw_strs[0]
            or "timeouts_times" in raw_strs[0]
            or "timeouts" in raw_strs[0]
        ):
            try:
                tmp = raw_strs[0]
                if tmp.startswith("%"):
                    tmp = tmp[1:]
                cls, ttype = tmp.split("_", 1)
                if "obs" in ttype:
                    data_file.timeouts_obs[cls] = [
                        int(x) for x in raw_strs[1].rstrip().split(",")
                    ]
                elif "times" in ttype:
                    data_file.timeouts_times[cls] = raw_strs[1]
                else:
                    data_file.timeouts[cls] = raw_strs[1]
            except Exception:
                log_error(f"Problems processing timeouts line {line_count}", "exc")
            continue
        elif raw_strs[0] == "data" or raw_strs[0] == "%data":
            break

    # Process the data
    prev_len = -1
    timeout_count = 0
    data_row = -1
    while True:
        raw_line = raw_data_file.readline().rstrip()
        line_count += 1
        data_row += 1
        if raw_line == "" or raw_line[-1] == "\x1a":
            break
        raw_strs = raw_line.split()
        row = []
        l_timeouts_obs = collections.defaultdict(int)
        for i in range(len(raw_strs)):
            if (raw_strs[i])[0:1] == "N":
                row.append(nan)
            elif (raw_strs[i])[0:1] == "T":
                timeout_count += 1
                l_timeouts_obs[data_file.lookup_class_name(data_file.columns[i])] = (
                    data_row
                )
                row.append(nan)
            else:
                try:
                    row.append(float(raw_strs[i]))
                except Exception:
                    log_error(
                        "Problems converting [%s] to float from line [%s] (%s, line %d) -- skipping"
                        % (raw_strs[i], raw_line, in_filename, line_count)
                    )
                    row = []
                    break

        if len(row):
            rows.append(row)
            for k, v in l_timeouts_obs.items():
                data_file.timeouts_obs[k].append(v)

            if prev_len > -1 and len(row) != prev_len:
                log_error(
                    "line length problem line %d,%d,%d"
                    % (line_count, prev_len, len(row))
                )
            prev_len = len(row)

    if timeout_count > 0:
        log_warning(
            "%d timeout(s) seen in %s" % (timeout_count, in_filename), alert="TIMEOUT"
        )

    raw_data_file.close()
    try:
        data_file.data = np.array(rows, float)
    except Exception:
        log_error(
            "Not all data rows the same length in %s - skipping (%d)"
            % (in_filename, line_count),
            "exc",
        )
        return None
    else:
        return data_file


def main():
    """Processes seaglider data files from dat to asc

    returns:
        0 for success
        1 for failure

    raises:
        Any exceptions raised are considered critical errors and not expected

    """
    # Get options
    base_opts = BaseOpts.BaseOptions(
        "Processes seaglider data files from dat to asc",
        additional_arguments={
            "data_file": BaseOptsType.options_t(
                None,
                ("DataFiles",),
                ("data_file",),
                str,
                {
                    "help": "Seaglider .dat file to process",
                    # "action": BaseOpts.FullPathAction,
                },
            ),
            "log_file": BaseOptsType.options_t(
                None,
                ("DataFiles",),
                ("log_file",),
                str,
                {
                    "help": "Seaglider .log file matching the .dat file",
                    # "action": BaseOpts.FullPathAction,
                    "nargs": "?",
                },
            ),
        },
    )
    BaseLogger(base_opts)  # initializes BaseLog

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    datafile_name = os.path.join(base_opts.mission_dir, base_opts.data_file)
    if base_opts.log_file:
        logfile_name = os.path.join(base_opts.mission_dir, base_opts.log_file)
    else:
        logfile_name = None

    sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")

    calib_consts = CalibConst.getSGCalibrationConstants(sg_calib_file_name)
    if not calib_consts:
        log_warning("Could not process %s" % sg_calib_file_name)

    (_, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    log_info("Processing file: %s" % datafile_name)

    fc = FileMgr.FileCode(datafile_name, 0)

    if fc.is_seaglider() or fc.is_seaglider_selftest():
        if fc.is_gzip() or fc.is_tar() or fc.is_tgz():
            log_info("Handling compressed or tar files NYI: %s" % datafile_name)
            return 0
        elif not fc.is_received():
            log_info("Don't know how to handle %s" % datafile_name)
            return 1
        elif fc.is_data():
            log_info("Processing %s from a data to asc format" % datafile_name)
            data_file = process_data_file(datafile_name, "dat", calib_consts)
            if not data_file:
                return 1

            data_file.dat_to_asc()

            if logfile_name:
                log_file = LogFile.parse_log_file(
                    logfile_name,
                    issue_warn=True,
                )
                if not log_file:
                    return 1
                if data_file.asc_to_eng(log_file):
                    log_error("%s failed in conversion from asc to eng" % datafile_name)

            data_file.dump(sys.stdout)
        else:
            log_info("Don't know how to process %s" % datafile_name)
            return 1
    else:
        # Assume its an eng file
        data_file = process_data_file(datafile_name, "eng", calib_consts)
        data_file.dump(sys.stdout)
        return 1

    #     log_file = LogFile.parse_log_file(logfile_name, base_opts.mission_dir)

    #     if (data_file is not None and log_file is not None):
    #         data_file.asc_to_eng(log_file)
    #         data_file.dump(sys.stdout)
    #     else:
    #         log_error("cannot generate eng file, error with asc and/or log")

    # Each row in the data is a dictionary, so you index it via the column header name
    # For example, to show the depth:
    # for i in data_file.data:
    #    print i['depth']

    return 0


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        retval = main()
    except SystemExit:
        pass
    except Exception:
        DEBUG_PDB_F()
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
