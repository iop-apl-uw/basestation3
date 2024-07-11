#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024  University of Washington.
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

"""Contains all routines for extracting data from a glider's comm logfile."""

# TODO
# MODEM_MSG, EKF, FINISH, RAFOS, FREEZE INTR WARN

import collections
import os
import pdb
import sys
import time
import traceback

import BaseNetCDF
import BaseOpts
import BaseOptsType
import FileMgr
import GPS
import Utils
from BaseLog import (
    BaseLogger,
    log_debug,
    log_info,
    log_error,
    log_warning,
)

# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False

# Handles message GC table entries
# Matching type definitions are in BaseNetCDF

# Each tuple must include a msgtype and a secs field
newhead_gc = collections.namedtuple(
    "newhead_gc", ["msgtype", "heading", "depth", "secs"]
)
# If there is no secs(time) in the msg, then supply NaN for the value
# Note: this table is walked in Sensors.init_extensions to register all the possible variable dimensions
msg_gc_entries = {
    "NEWHEAD": lambda x: newhead_gc("NEWHEAD", *[float(y) for y in x.split(",")])
}


def map_state_code(state_str):
    """Converts a state string to a state code"""
    state_strs = [
        "begin dive",
        "end dive",
        "begin climb",
        "end climb",
        "begin apogee",
        "end apogee",
        "begin loiter",
        "end loiter",
        "begin surface coast",
        "end surface coast",
        "begin subsurface finish",
        "end subsurface finish",
        "begin recovery",
        "end recovery",
        "begin surface",
        "end surface",
    ]

    for ii in range(len(state_strs)):
        if state_str == state_strs[ii]:
            return ii
    return -1


def map_eop_code(eop_str):
    """Converts an end of phase string to a code"""
    # Copied from glider constant.h - order is very important
    eop_strs = [
        "CONTROL_FINISHED_OK",
        "TARGET_DEPTH_EXCEEDED",
        "SURFACE_DEPTH_REACHED",
        "FINISH_DEPTH_REACHED",
        "ABORT_DEPTH_EXCEEDED",
        "FLARE_DEPTH_REACHED",
        "NO_VERTICAL_VELOCITY",
        "HALF_MISSION_TIME_EXCEEDED",
        "UNCOMMANDED_BLEED_DETECTED",
        "MOTOR_MAX_ERRORS_EXCEEDED",
        "CF8_MAX_ERRORS_EXCEEDED",
        "BOTTOM_OBSTACLE_DETECTED",
        "SURFACE_OBSTACLE_DETECTED",
        "ABORT_TIME_EXCEEDED",
        "LOITER_COMPLETE",
        "POWER_ERROR_DETECTED",
        "SENSOR_ERROR_DETECTED",
        "LOGGER_MESSAGE_DELIMITER",
        "LOGGER_WANTS_CLIMB",
        "LOGGER_WANTS_RECOVERY",
        "LOGGER_WANTS_SURFACE",
        "LOGGER_WANTS_LOITER",
        "LOGGER_WANTS_FINISH",
    ]

    for ii in range(len(eop_strs)):
        if eop_str == eop_strs[ii]:
            return ii
    return -1


class LogFile:
    """Object representing a seaglider log file"""

    def __init__(self):
        self.version = None
        self.glider = None
        self.mission = None
        self.dive = None
        self.start_ts = None
        self.columns = []
        self.data = None
        self.gc_data = None
        self.gc_state_data = None
        self.gc = []
        self.state = []
        self.warn = []
        self.gc_msg_list = []  # All message entries
        self.gc_msg_dict = {}  # Message entries as arrays

    def dump(self, fo=sys.stdout):
        """Dumps out the logfile"""
        print("version: %2.2f" % (self.version), file=fo)
        print("glider: %d" % (self.glider), file=fo)
        print("mission: %d" % (self.dive), file=fo)
        print("dive: %d" % (self.dive), file=fo)
        time_string = time.strftime("%m %d %y %H %M %S", self.start_ts)
        time_parts = time_string.split()
        print(
            "start: %s %s %3d %s %s %s"
            % (
                time_parts[0],
                time_parts[1],
                int(time_parts[2]) + 100,
                time_parts[3],
                time_parts[4],
                time_parts[5],
            ),
            file=fo,
        )
        print("data:", file=fo)
        for key, item in list(self.data.items()):
            if key in ("$GPS", "$GPS1", "$GPS2"):
                print("%s" % key, file=fo)
                item.dump(fo)
            else:
                print("%s,%s" % (key, item), file=fo)
        for x, values in self.gc_msg_dict.items():
            print(x, values)


def parse_log_file(in_filename, issue_warn=False):
    """Parses a Seaglider log file

    Returns a logile object or None for an error
    TODO: bubble up exceptions
    """

    # Check filetype before processing
    fc = FileMgr.FileCode(
        in_filename, 0
    )  # instrument_id = 0 b/c we don't care about it here
    if fc.is_seaglider() and fc.is_log():
        log_debug("Input file is a raw seaglider log file: %s" % (in_filename))
    elif fc.is_processed_seaglider_log() or fc.is_processed_seaglider_selftest_log():
        log_debug("Input file is a processed seaglider log file: %s" % (in_filename))
    else:
        log_error("Invalid seaglider logfile: %s" % (in_filename))
        return None
    # TODO: Add handling for .asc and .eng files

    try:
        raw_log_file = open(in_filename, "rb")
    except IOError:
        log_error("Could not open " + in_filename + " for reading")
        return None

    line_count = 0
    # Process the header
    while True:
        line_count = line_count + 1
        try:
            raw_line = raw_log_file.readline().decode()
        except UnicodeDecodeError:
            log_error("Could not process line %d of %s" % (line_count, in_filename))
            continue
        raw_line = raw_line.rstrip()
        if raw_line == "":
            log_error("no valid header found")
            return None

        raw_strs = raw_line.split(":")

        if line_count == 1:
            if raw_strs[0] == "version" or raw_strs[0] == "%version":
                log_file = LogFile()
                try:
                    log_file.version = float(raw_strs[1])
                except ValueError:
                    # Might be an iRobot version - major.minor.rev1.rev2
                    tmp2 = raw_strs[1].rsplit(".", 2)[0]
                    try:
                        log_file.version = float(tmp2)
                    except ValueError:
                        log_error("Unknown version %s = assuming 66.00" % raw_strs[1])
                        log_file.version = 66.00
                continue
            else:
                log_error("first line did not contain an version string %s" % raw_line)
                return None

        if raw_strs[0] == "glider" or raw_strs[0] == "%glider":
            log_file.glider = int(raw_strs[1])
            continue
        elif raw_strs[0] == "mission" or raw_strs[0] == "%mission":
            log_file.mission = int(raw_strs[1])
            continue
        elif raw_strs[0] == "dive" or raw_strs[0] == "%dive":
            log_file.dive = int(raw_strs[1])
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
            log_file.start_ts = Utils.fix_gps_rollover(
                time.strptime(time_string, "%m %d %y %H %M %S")
            )

            log_debug(
                "%s %s %s"
                % (
                    log_file.start_ts.tm_mon,
                    log_file.start_ts.tm_mday,
                    log_file.start_ts.tm_year,
                )
            )
            log_debug(
                "%s %s %s"
                % (
                    log_file.start_ts.tm_hour,
                    log_file.start_ts.tm_min,
                    log_file.start_ts.tm_sec,
                )
            )

        elif (
            raw_strs[0] == "columns" or raw_strs[0] == "%columns"
        ):  # REALLY in a logfile?
            for i in raw_strs[1].rstrip().split(","):
                if len(i):
                    log_file.columns.append(i)
            continue
        elif raw_strs[0] == "data" or raw_strs[0] == "%data":
            break

    # Process the paramters
    log_file.data = {}
    while True:
        line_count = line_count + 1
        try:
            raw_line = raw_log_file.readline().decode().rstrip()
        except UnicodeDecodeError:
            log_error("Could not process line %d of %s" % (line_count, in_filename))
            continue

        if raw_line == "":
            break  # done with the file? BUG continue?

        raw_strs = raw_line.split(",", 1)
        if len(raw_strs) != 2:  # we expect $PARM,value[,value]+
            log_error(
                "Could not parse line %d %s in %s" % (line_count, raw_line, in_filename)
            )
        else:
            parm_name = raw_strs[0]
            value = raw_strs[1]
            if parm_name in ("$GPS1", "$GPS2", "$GPS"):
                # For old style GPS entries, pass log starting date since we only have HHMMSS in those records
                # This is insufficient for dives that cross midnight but we have better conversion tools for that...
                log_file.data[parm_name] = GPS.GPSFix(
                    raw_line,
                    start_date_str=time.strftime("%m %d %y", log_file.start_ts),
                )
            elif parm_name == "$GC":
                log_file.gc.append(value)
            elif parm_name == "$FINISH":
                pass  # drop for now
            elif parm_name == "$STATE":
                log_file.state.append(value)
            elif parm_name == "$RAFOS":
                pass  # drop for now
            elif parm_name == "$FREEZE":
                pass  # drop for now
            elif parm_name == "$INTR":  # interrupt details
                pass  # drop for now
            elif parm_name == "$WARN":  # various warnings (PPS, flight parms, etc.)
                if issue_warn:
                    log_file.warn.append(value)
                    log_warning(
                        "WARN:(%s) in %s" % (value, in_filename), alert="LOGFILE_WARN"
                    )
            elif parm_name == "MODEM":  # Handle like RAFOS
                pass
            elif parm_name == "MODEM_MSG":
                pass
            elif parm_name == "EKF":
                pass
            # Message GC entries
            elif parm_name.lstrip("$") in ("NEWHEAD",):
                try:
                    log_file.gc_msg_list.append(
                        msg_gc_entries[parm_name.lstrip("$")](value)
                    )
                except TypeError:
                    log_warning("Could not process {parm_name} {value}", "exc")
            else:
                # parse the value
                nc_var_name = BaseNetCDF.nc_sg_log_prefix + parm_name.lstrip("$")
                try:
                    md = BaseNetCDF.nc_var_metadata[nc_var_name]
                except:
                    log_error("Missing metadata for log entry %s" % parm_name)
                    md = BaseNetCDF.form_nc_metadata(
                        nc_var_name, nc_data_type="c"
                    )  # default metadata: treat as scalar string
                _, nc_data_type, _, _ = md
                if nc_data_type == "d":
                    try:
                        value = float(value)
                    except ValueError:
                        log_error(
                            "Improperly formatted floating point log entry %s = %s"
                            % (parm_name, value)
                        )
                        value = None
                elif nc_data_type == "i":
                    try:
                        value = int(round(float(value)))
                    except ValueError:
                        log_error(
                            "Improperly formatted integer log entry (%s = %s)"
                            % (parm_name, value)
                        )
                        value = None
                # else: it is a string, fall through
                log_file.data[parm_name] = value

    # If GPS2 is earlier the GPS1, midnight happend between these times - correct GPS1
    if "$GPS1" in log_file.data and "$GPS2" in log_file.data:
        if time.mktime(log_file.data["$GPS2"].datetime) < time.mktime(
            log_file.data["$GPS1"].datetime
        ):
            log_info(
                "%s: GPS2 = %f (%s) less then GPS1 = %f (%s), subtracting a day from GPS1 (midnight rollover between GPS1 and GPS2)"
                % (
                    in_filename,
                    time.mktime(log_file.data["$GPS2"].datetime),
                    log_file.data["$GPS2"].datetime,
                    time.mktime(log_file.data["$GPS1"].datetime),
                    log_file.data["$GPS1"].datetime,
                )
            )
            log_file.data["$GPS1"].datetime = time.gmtime(
                time.mktime(log_file.data["$GPS1"].datetime) - 86400
            )
            log_info(
                "New GPS1 = %f (%s)"
                % (
                    time.mktime(log_file.data["$GPS1"].datetime),
                    log_file.data["$GPS1"].datetime,
                )
            )

    # There is a slight chance that the midnight roll over happened between the GPS2 and the logfile start time - in which case,
    # the two readings need to be set back a day.  Detect based on the both GPS1 and GPS2 being later then GPS
    if "$GPS" in log_file.data and "$GPS1" in log_file.data:
        if time.mktime(log_file.data["$GPS"].datetime) < time.mktime(
            log_file.data["$GPS1"].datetime
        ):
            log_info(
                "%s: GPS = %f (%s) less then GPS1 = %f (%s), subtracting a day from GPS1 (midnight rollover between GPS2 and log start - very rare)"
                % (
                    in_filename,
                    time.mktime(log_file.data["$GPS"].datetime),
                    log_file.data["$GPS"].datetime,
                    time.mktime(log_file.data["$GPS1"].datetime),
                    log_file.data["$GPS1"].datetime,
                )
            )
            log_file.data["$GPS1"].datetime = time.gmtime(
                time.mktime(log_file.data["$GPS1"].datetime) - 86400
            )
            log_info(
                "New GPS1 = %f (%s)"
                % (
                    time.mktime(log_file.data["$GPS1"].datetime),
                    log_file.data["$GPS1"].datetime,
                )
            )

    if "$GPS" in log_file.data and "$GPS2" in log_file.data:
        if time.mktime(log_file.data["$GPS"].datetime) < time.mktime(
            log_file.data["$GPS2"].datetime
        ):
            log_info(
                "%s: GPS = %f (%s) less then GPS2 = %f (%s), subtracting a day from GPS2 (midnight rollover between GPS2 and log start - very rare)"
                % (
                    in_filename,
                    time.mktime(log_file.data["$GPS"].datetime),
                    log_file.data["$GPS"].datetime,
                    time.mktime(log_file.data["$GPS2"].datetime),
                    log_file.data["$GPS2"].datetime,
                )
            )
            log_file.data["$GPS2"].datetime = time.gmtime(
                time.mktime(log_file.data["$GPS2"].datetime) - 86400
            )
            log_info(
                "New GPS2 = %f (%s)"
                % (
                    time.mktime(log_file.data["$GPS2"].datetime),
                    log_file.data["$GPS2"].datetime,
                )
            )

    gc_data = {}
    log_file_start_time = int(
        time.mktime(log_file.start_ts)
    )  # make st_secs and end_secs 'i'
    try:
        gc_header_parts = log_file.data["$GCHEAD"].split(",")
    except:
        # pre-version 65 columns or no gc section (i.e. dive 0)
        log_warning("Missing $GCHEAD in %s - assuming old version" % in_filename)
        #
        ##                   1       2          3       4    5        6        7        8          9         10       11    12      13      14     15       16      17
        # gc_header_parts = 'st_secs,pitch_ctl,vbd_ctl,depth,ob_vertv,data_pts,end_secs,pitch_secs,roll_secs,vbd_secs,vbd_i,gcphase' # subset pre v65
        # gc_header_parts = 'st_secs,pitch_ctl,vbd_ctl,depth,ob_vertv,data_pts,end_secs,pitch_secs,roll_secs,vbd_secs,vbd_i,gcphase,pitch_i,roll_i,pitch_ad,roll_ad,vbd_ad'.split(',');
        gc_header_parts = "st_secs,pitch_ctl,vbd_ctl,ob_vertv,data_pts,end_secs,pitch_secs,roll_secs,vbd_secs,vbd_i,gcphase,pitch_i,roll_i,pitch_ad,roll_ad,vbd_ad".split(
            ","
        )

    # We could have a bolluxed logfile with truncated lines because of transmission issues (labrador/apr05/sg016 dive 416)
    # or we could have an older file where we guessed about the header but the number of entries is actually different
    # In the former case we want to drop the bad line(s); in the later case we want to preserve the data we think we trust
    # as long as the number of entries are consistent
    indices = list(range(len(gc_header_parts)))  # assume the best
    indices_tmp = None
    for gc_line in log_file.gc:  # these are the string data lines, in an array
        gc_line_parts = gc_line.split(",")
        if indices_tmp is None:
            if len(gc_line_parts) < len(gc_header_parts):
                log_warning(
                    "GC line (%s) contains fewer columns then header calls for - only processing the first %d columns"
                    % (gc_line, len(gc_line_parts))
                )
                indices_tmp = list(range(len(gc_line_parts)))
            else:
                # BUG what if there are more entries than header items? -- the code below drops them all
                indices_tmp = indices  # expect a full line
        elif len(gc_line_parts) != len(indices_tmp):
            log_warning(
                "GC line (%s) contains a different number of columns (%d) then expected (%d) -- skipping"
                % (gc_line, len(gc_line_parts), len(indices_tmp))
            )
            continue  # bolluxed file

        for index in indices_tmp:
            column_name = gc_header_parts[index]
            try:
                values = gc_data[column_name]
            except KeyError:
                values = []  # initialize
                gc_data[column_name] = values
            try:
                value = gc_line_parts[index]
            except IndexError:
                log_error("Missing data for GC column (%s)" % column_name)
                value = None

            try:
                md = BaseNetCDF.nc_var_metadata[BaseNetCDF.nc_gc_prefix + column_name]
            except:
                log_error("Missing metadata for GC column (%s)" % column_name)
                value = None
            else:
                (
                    _,
                    nc_data_type,
                    _,
                    _,
                ) = md
                if nc_data_type == "d":
                    try:
                        value = float(value)
                    except ValueError:
                        log_error(
                            "Improperly formatted floating point entry (%s = %s) found in $GC line (%s)"
                            % (column_name, value, gc_line)
                        )
                        value = None
                    except TypeError:
                        log_error(
                            "Improperly formatted floating point entry (%s = %s) found in $GC line (%s)"
                            % (column_name, value, gc_line)
                        )
                        value = None

                else:  ## Must be integer
                    try:
                        value = int(value)
                    except ValueError:
                        log_error(
                            "Improperly formatted integer entry (%s = %s) found in $GC line"
                            % (column_name, value)
                        )
                        value = None
            if column_name in ["st_secs", "end_secs"]:
                value += (
                    log_file_start_time  # adjust st_secs and end_secs to be epoch times
                )
            values.append(value)

    log_file.gc_data = gc_data

    state_data = {"secs": [], "state": [], "eop_code": []}
    # State
    for state_line in log_file.state:  # these are the string data lines, in an array
        state_line_parts = state_line.split(",")
        try:
            t = float(state_line_parts[0])
            s = state_line_parts[1].rstrip().lstrip()

            if len(state_line_parts) > 2:
                e = state_line_parts[2].rstrip().lstrip()

            else:
                e = ""
        except:
            pass

        s_code = map_state_code(s)
        if s_code < 0:
            log_warning("Unknown gc state %s - skipping" % s)
            continue
        eop_code = map_eop_code(e)

        state_data["secs"].append(
            t + log_file_start_time
        )  # adjust st_secs and end_secs to be epoch times)
        state_data["state"].append(s_code)
        state_data["eop_code"].append(eop_code)

    log_file.gc_state_data = state_data

    # Convert list of paramaterized gc messages to
    # dict of type of messages, as dicts of arrays of values
    if log_file.gc_msg_list:
        msg_types = {y.msgtype for y in log_file.gc_msg_list}
        for mt in msg_types:
            for msg in log_file.gc_msg_list:
                if msg.msgtype == mt:
                    if mt not in log_file.gc_msg_dict:
                        # Init arrays
                        log_file.gc_msg_dict[mt] = {}
                        for field in msg._fields:
                            if field == "msgtype":
                                continue
                            log_file.gc_msg_dict[mt][field] = []
                    for field in msg._fields:
                        if field == "msgtype":
                            continue
                        log_file.gc_msg_dict[mt][field].append(msg._asdict()[field])
                        if field == "secs":
                            log_file.gc_msg_dict[mt][field][-1] += log_file_start_time

    return log_file


def main():
    """Test entry point for logfile processing"""
    base_opts = BaseOpts.BaseOptions(
        "Test entry point for logfile processing",
        additional_arguments={
            "log_file": BaseOptsType.options_t(
                None,
                ("LogFile",),
                ("log_file",),
                str,
                {
                    "help": "Seaglider logfile to process",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )
    BaseLogger(base_opts)  # initializes BaseLog

    log_info("Processing file: %s" % base_opts.log_file)

    log_file = parse_log_file(base_opts.log_file)
    # You can dump the whole processed object using this method

    if log_file is not None:
        log_file.dump(sys.stdout)

    # Each row in the data is a dictionary, so you index it via the column header name
    # For example, to show the depth:
    # for i in data_file.data:
    #    print i['depth']

    return 0


if __name__ == "__main__":
    # Force time and date to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    retval = 0
    try:
        retval = main()
    except SystemExit:
        pass
    except:
        if DEBUG_PDB:
            _, _, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)

    sys.exit(retval)
