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
Commlog.py: Contains all routines for extracting data from a glider's comm logfile.

    Intended to be called from another module (Base.py) OR stand-alone (to generate glider tracking data info).
"""

import argparse
import collections
import contextlib
import copy
import cProfile
import inspect
import io
import json
import math
import os
import pdb
import pstats
import re
import sys
import time
import traceback

import BaseDB
import BaseOpts
import BaseOptsType
import BaseTime
import FileMgr
import GPS
import Utils
import Ver65
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

DEBUG_PDB = False  # Set to True to enter debugger on exceptions

# Named tuples
file_transfered_nt = collections.namedtuple(
    "file_transfered_nt", ["sector_num", "block_len"]
)
file_stats_nt = collections.namedtuple(
    "file_stats_nt",
    [
        "expectedsize",  # Size advertised by protocol - Raw download
        "transfersize",  # Size actually recieved - Raw download
        "receivedsize",  # Bytes received - any protocol
        "bps",  # XModem
    ],
)
file_expected_actual_nt = collections.namedtuple(
    "file_expected_actual_nt",
    [
        "expectedsize",  # Size expected (or fragment size if xmodem)
        "receivedsize",  # Number or bytes actually received
    ],
)


def GPS_lat_lon_and_recov(fmt, dive_prefix, session):
    """Returns the lat/lon for the last GPS fix and reocvery code (if any) as a string, along
    with the actual recovery code, regardless of the sessions completness
    """

    gps_fix = session.gps_fix
    recov_code = session.recov_code
    escape_reason = session.escape_reason

    # log_info("GPS_lat_lon_and_recov dive_prefix:%s dive_num:%s calls_made:%s call_cycle:%s" %
    # (str(dive_prefix), str(session.dive_num), str(session.calls_made), str(session.call_cycle)))

    if dive_prefix:
        prefix = "dive:%s calls_made:%s call_cycle:%s " % (
            str(session.dive_num),
            str(session.calls_made),
            str(session.call_cycle),
        )
    else:
        prefix = ""

    log_info("prefix:%s" % prefix)

    # if(gps_fix):
    #     if(recov_code):
    #         return ("%s%s %s %s UTC %s" % (prefix,
    #                                        Utils.format_lat_lon(gps_fix.lat, fmt, True),
    #                                        Utils.format_lat_lon(gps_fix.lon, fmt, False),
    #                                        time.strftime("%m/%d/%y %H:%M:%S", gps_fix.datetime), recov_code), recov_code, None, prefix)
    #     elif(escape_reason):
    #         return ("%s%s %s %s UTC %s" % (prefix,
    #                                      Utils.format_lat_lon(gps_fix.lat, fmt, True),
    #                                      Utils.format_lat_lon(gps_fix.lon, fmt, False),
    #                                      time.strftime("%m/%d/%y %H:%M:%S", gps_fix.datetime), escape_reason), None, escape_reason, prefix)
    #     else:
    #         return ("%s%s %s %s UTC" % (prefix,
    #                                     Utils.format_lat_lon(gps_fix.lat, fmt, True),
    #                                     Utils.format_lat_lon(gps_fix.lon, fmt, False),
    #                                     time.strftime("%m/%d/%y %H:%M:%S", gps_fix.datetime)), None, None, prefix)
    # else:
    #     return ("No GPS fix available for this call", None, None, None)

    # Removed the prefix from the body of the message to save space in the message payload

    if gps_fix:
        latlon = None
        if fmt:
            if fmt.lower() == "nmea":
                latlon = "$GPRMC,%s,A,%s,%s,%s,%s,%s,0.0,E" % (
                    time.strftime("%H%M%S", gps_fix.datetime),
                    Utils.format_lat_lon(gps_fix.lat, fmt, True),
                    Utils.format_lat_lon(gps_fix.lon, fmt, False),
                    gps_fix.drift_speed,
                    gps_fix.drift_heading,
                    time.strftime("%d%m%y", gps_fix.datetime),
                )
            else:
                latlon = "%s %s %s UTC" % (
                    Utils.format_lat_lon(gps_fix.lat, fmt, True),
                    Utils.format_lat_lon(gps_fix.lon, fmt, False),
                    time.strftime("%m/%d/%y %H:%M:%S", gps_fix.datetime),
                )
        if recov_code:
            return ("%s %s" % (latlon, recov_code), recov_code, None, prefix)
        elif escape_reason:
            return ("%s %s" % (latlon, escape_reason), None, escape_reason, prefix)
        else:
            return (latlon, None, None, prefix)
    else:
        return ("No GPS fix available for this call", None, None, None)


class CommLog:
    """Object representing a seagliders comm log"""

    def __init__(
        self, sessions, raw_lines_with_ts, files_transfered, file_transfer_method
    ):
        self.sessions = sessions
        self.file_stats = {}
        # Dictionay of the most recently used trasnfer mehcanism for each fragment
        self.file_transfer_method = file_transfer_method
        self.raw_lines_with_ts = raw_lines_with_ts
        self.files_transfered = files_transfered

    def find_fragment_transfer_method(self, fragment_name):
        """Returns what transfer protocol has used to transmit a fragment
        "xmodem", "ymodem", "raw" or "unknown"
        """
        if fragment_name in list(self.file_transfer_method.keys()):
            return self.file_transfer_method[fragment_name]
        else:
            return "unknown"

    def get_fragment_dictionary(self):
        """Returns a dictionary that maps a dive num to a fragment size"""
        fragment_dict = {}
        for i in range(len(self.sessions)):
            if (
                self.sessions[i].disconnect_ts
                and self.sessions[i].fragment_size is not None
            ):
                fragment_dict[self.sessions[i].dive_num] = self.sessions[
                    i
                ].fragment_size
        return fragment_dict

    def get_fragment_size_dict(self):
        """Returns a dictionary that maps a fragment name to a tuple of
        expected size and received size

        For RAW and YMODEM files, the recieved size is reported by the protocol for both up and down
        For XMODEM files, the recieved size is reported by the protocol for up only, so this map
        is not useful for determining errors in transmission.

        If the expected size is not known, then fragment size for enclosing session is used or 8192
        none is specified
        """
        # This covers the cases where there are files in the directory, but no
        # entries in the comm.log
        fragment_size_dict = collections.defaultdict(
            lambda: file_expected_actual_nt(8192, -1)
        )
        for ii in range(len(self.sessions)):
            for k in self.sessions[ii].file_stats:
                try:
                    frag_counter = FileMgr.FileCode(k, 0).get_fragment_counter()
                except ValueError:
                    continue
                if len(k) >= 8 and frag_counter >= 0:
                    fs_stats = self.sessions[ii].file_stats[k]
                    if fs_stats.expectedsize >= 0:
                        expected_size = fs_stats.expectedsize
                    elif (
                        fs_stats.expectedsize < 0
                        and self.sessions[ii].fragment_size is not None
                    ):
                        expected_size = self.sessions[ii].fragment_size
                    else:
                        expected_size = 8192

                    fragment_size_dict[k] = file_expected_actual_nt(
                        expected_size, fs_stats.receivedsize
                    )
        return fragment_size_dict

    def last_fragment_size(self):
        """Searches through the complete surfacings in reverse order and returns the last
        valid fragment_size
        """
        for i in reversed(range(len(self.sessions))):
            if (
                self.sessions[i].disconnect_ts
                and self.sessions[i].fragment_size is not None
            ):
                return self.sessions[i].fragment_size
        return None

    def last_software_version(self):
        """Searches through the complete surfacings in reverse order and return the last
        valid software version and software revision
        """
        for i in reversed(range(len(self.sessions))):
            if (
                self.sessions[i].disconnect_ts
                and self.sessions[i].software_version is not None
            ):
                return (
                    self.sessions[i].software_version,
                    self.sessions[i].software_revision,
                )
        return (None, None)

    def last_complete_surfacing(self):
        """Returns the session for the last completed surfacing"""
        # for i in range(-1,-len(self.sessions) + 1, -1):
        for i in reversed(range(len(self.sessions))):
            if self.sessions[i].disconnect_ts:
                return self.sessions[i]
        return None

    def get_instrument_id(self):
        """Find the instrument id by searching backward through the
        sessions, looking for one that has an instrument id

        Returns:
            Instrument ID if found as an int
            None if no ID found
        """
        for i in reversed(range(len(self.sessions))):
            log_debug(f"Instrument ID {self.sessions[i].sg_id}")
            if self.sessions[i].sg_id:
                return self.sessions[i].sg_id
        log_debug("No instrument ID found")
        return None

    def get_last_dive_num_and_call_counter(self):
        """Find the last dive number by searching backward through the
        sessions, looking for one that has a dive number set

        Returns:
            dive number if found as an int and the call cycle (if exists) or calls made (ver 65)
            None if no dive number found
        """
        for i in reversed(range(len(self.sessions))):
            if self.sessions[i].dive_num is not None:
                if self.sessions[i].call_cycle is not None:
                    return (self.sessions[i].dive_num, self.sessions[i].call_cycle)
                else:
                    return (self.sessions[i].dive_num, self.sessions[i].calls_made)
        return (None, None)

    def last_surfacing(self):
        """Returns the session for the last surfacing, regardless of completness"""
        return self.sessions[-1]

    def last_GPS_lat_lon_and_recov(self, fmt, dive_prefix):
        """Returns the lat/lon for the last GPS fix and reocvery code (if any) as a string, along
        with the actual recovery code, regardless of the sessions completness
        """

        try:
            return GPS_lat_lon_and_recov(fmt, dive_prefix, self.sessions[-1])
        except Exception:
            log_error("Failed GPS_lat_lon_and_recov", "exc")
            return ("No GPS fix available for this call", None, None, "")

    def has_glider_rebooted(self):
        """Compares the last two sessions with GPS fixes (regardless of session completeness) to determine if the glider has re
        rebooted.  Only works with version 66 and later glider code that has the reboot count field on the
        GPS line

        Returns:
            None - glider has not rebooted
            String with the two lines if the glider has rebooted
        """
        # Iterate back to find the last two sessions with gps fix
        last_session = None
        previous_session = None
        for i in reversed(range(len(self.sessions))):
            if self.sessions[i].gps_fix:
                if last_session is None:
                    last_session = self.sessions[i]
                elif previous_session is None:
                    previous_session = self.sessions[i]
                else:
                    break

        if (
            last_session is None
            or last_session.reboot_count is None
            or previous_session is None
            or last_session.reboot_count is None
        ):
            return None

        if last_session.reboot_count <= previous_session.reboot_count:
            return None

        msg = "Reboot occured between %s:%s:%s:%s:%s:%s and %s:%s:%s:%s:%s:%s" % (
            str(previous_session.dive_num)
            if previous_session.dive_num is not None
            else "Unknown",
            str(previous_session.call_cycle)
            if previous_session.call_cycle is not None
            else "Unknown",
            str(previous_session.calls_made)
            if previous_session.calls_made is not None
            else "Unknown",
            str(previous_session.no_comm)
            if previous_session.no_comm is not None
            else "Unknown",
            str(previous_session.mission_num)
            if previous_session.mission_num is not None
            else "Unknown",
            str(previous_session.reboot_count)
            if previous_session.reboot_count is not None
            else "Unknown",
            str(last_session.dive_num)
            if last_session.dive_num is not None
            else "Unknown",
            str(last_session.call_cycle)
            if last_session.call_cycle is not None
            else "Unknown",
            str(last_session.calls_made)
            if last_session.calls_made is not None
            else "Unknown",
            str(last_session.no_comm)
            if last_session.no_comm is not None
            else "Unknown",
            str(last_session.mission_num)
            if last_session.mission_num is not None
            else "Unknown",
            str(last_session.reboot_count)
            if last_session.reboot_count is not None
            else "Unknown",
        )
        return msg

    def predict_drift(self, fmt, n_predictions=3, n_fixes=5):
        """Compute a drift prediction message based on the last N fixes in the comm log
        as specified in the fmt. Supports driftNddmmss etc.
        """
        # Format is collapsed to fit on small displays
        secs_per_hour = 3600
        time_fmt = "%H:%M:%SZ"  # bag date; if you are using this it is today
        if len(fmt) and fmt[0] in "23456789":
            n_fixes = ord(fmt[0]) - ord("0")
            fmt = fmt[1:]
        log_info(
            "Drift: %d predictions (%s) based on %d fixes"
            % (n_predictions, fmt, n_fixes)
        )
        last_fix = None
        most_recent_fix = None
        dive_num = None  # ensure the same dive number
        fixes = 0
        delta_lat = 0  # accumulators
        delta_lon = 0
        for session in reversed(self.sessions):
            this_fix = session.gps_fix
            this_dive_num = session.dive_num
            if this_fix is None:
                continue  # no idea where we are
            if last_fix:
                try:
                    if this_dive_num != dive_num:
                        break  # from a previous dive
                    delta_time_h = (
                        time.mktime(last_fix.datetime) - time.mktime(this_fix.datetime)
                    ) / secs_per_hour
                    if delta_time_h == 0:
                        log_info("Zero time delta - repeated GPS - skipping")
                        continue
                    last_lat = Utils.ddmm2dd(last_fix.lat)
                    last_lon = Utils.ddmm2dd(last_fix.lon)
                    this_lat = Utils.ddmm2dd(this_fix.lat)
                    this_lon = Utils.ddmm2dd(this_fix.lon)
                    surface_mean_lon_fac = math.cos(
                        math.radians((last_lat + this_lat) / 2)
                    )
                    delta_lat_d_h = (last_lat - this_lat) / delta_time_h
                    delta_lon_d_h = (
                        (last_lon - this_lon) * surface_mean_lon_fac
                    ) / delta_time_h
                    delta_lat += delta_lat_d_h
                    delta_lon += delta_lon_d_h
                    fixes += 1
                    if fixes >= n_fixes:
                        break
                except ZeroDivisionError:
                    drift_message = "Time delta zero - cannot calculate drift"
                    log_error(drift_message)
                    return drift_message
                except Exception:
                    drift_message = "Error calculating drift"
                    log_error(drift_message, "exc")
                    return drift_message

            last_fix = this_fix  # initialize/update
            if most_recent_fix is None:
                most_recent_fix = this_fix
                dive_num = this_dive_num
        if fixes <= 1:
            drift_message = "Unable to determine drift rate"
            log_info(drift_message)
            return drift_message
        # compute mean drift rates
        delta_lat_d_h = delta_lat / fixes
        delta_lon_d_h = delta_lon / fixes
        log_info("delta_lat:%f delta_lon:%f" % (delta_lat_d_h, delta_lon_d_h))
        # start location
        mrf_lat = Utils.ddmm2dd(most_recent_fix.lat)
        mrf_lon = Utils.ddmm2dd(most_recent_fix.lon)
        mrf_time = most_recent_fix.datetime
        mrf_time_s = time.mktime(mrf_time)

        hrs_since_mrf = (time.time() - mrf_time_s) / secs_per_hour
        elapsed_hours = int(hrs_since_mrf)
        drift_message = "%s %s @ %s" % (
            Utils.format_lat_lon(Utils.dd2ddmm(mrf_lat), fmt, True),
            Utils.format_lat_lon(Utils.dd2ddmm(mrf_lon), fmt, False),
            time.strftime(time_fmt, mrf_time),
        )

        # Compute drift bearing and direction
        try:
            drift_bear_deg_true = 90.0 - math.degrees(
                math.atan2(delta_lat_d_h, delta_lon_d_h)
            )
        except ZeroDivisionError:  # atan2
            drift_bear_deg_true = 0.0
        if drift_bear_deg_true < 0:
            drift_bear_deg_true = drift_bear_deg_true + 360

        surface_mean_lon_fac = math.cos(math.radians(mrf_lat))
        m_per_deg = 111319.9
        nm_per_m = 0.000539957
        drift_speed = math.sqrt(
            math.pow(delta_lat_d_h * m_per_deg, 2)
            + math.pow(delta_lon_d_h * surface_mean_lon_fac * m_per_deg, 2)
        )
        drift_message = drift_message + "\n%.0f deg true, %.2f knots" % (
            drift_bear_deg_true,
            drift_speed * nm_per_m,
        )

        # drift_message = drift_message + "\nBased on last %d fixes:" % fixes
        # CONSIDER return a matrix of fix predictions [lat lon time] for use by caller, e.g., MakeKML
        for hours in range(1, n_predictions + 1):  # predictions ahead from 'now'
            offset_hours = elapsed_hours + hours
            pred_lat = mrf_lat + offset_hours * delta_lat_d_h
            pred_lon = mrf_lon + offset_hours * delta_lon_d_h
            # pred_time = time.gmtime(mrf_time_s + offset_hours*secs_per_hour)
            pred_message = "\n%s %s +%dhr" % (
                Utils.format_lat_lon(Utils.dd2ddmm(pred_lat), fmt, True),
                Utils.format_lat_lon(Utils.dd2ddmm(pred_lon), fmt, False),
                offset_hours,
            )
            drift_message = drift_message + pred_message
        return drift_message

    def dump_lon_lat(self, out_filename):
        """Generates a data file of lon/lat values for this glider's dives.
        Intended for use by GMT (psxy) to track glider's progress.
        """
        try:
            out_filename = os.path.abspath(out_filename)
            out_file = open(out_filename, "w")
        except OSError:
            log_critical("Could not open %s for writing." % out_filename)
            return
        for session in self.sessions:
            if session.gps_fix is not None:
                out_file.write(
                    "%.4f %.4f\n" % (session.gps_fix.lon, session.gps_fix.lat)
                )

        out_file.close()

    def dump_bad_files(self):
        """Lists files that are partial or have sector repeats"""
        if self.files_transfered:
            for file_name in list(self.files_transfered.keys()):
                if (
                    self.files_transfered[file_name]
                    and self.files_transfered[file_name][-1][0] == 0
                ):
                    print("File %s is a partial file" % file_name)
                else:
                    temp_sector = []
                    for i in self.files_transfered[file_name]:
                        try:
                            temp_sector.index(i[0])
                        except Exception:
                            temp_sector.append(i[0])
                        else:
                            print(
                                "File %s, sector_num %d is a repeat" % (file_name, i[0])
                            )

    def check_multiple_sectors(self, incomplete_file_name, instrument_id):
        """Given an incompelte file, check if there are any repeated
        sectors in the contributing fragments

        Returns:
            String, containing the recomendation for the pager mail
            None if there is no recommendation
        """
        ret_val = ""

        incomplete_fc = FileMgr.FileCode(incomplete_file_name, instrument_id)
        if self.files_transfered:
            for file_name in list(self.files_transfered.keys()):
                if (
                    self.files_transfered[file_name]
                    and self.files_transfered[file_name][-1][0] == 0
                ):
                    # Don't report partials - subsequent calls probably send those again
                    pass
                else:
                    try:
                        fragment_fc = FileMgr.FileCode(file_name, instrument_id)
                    except ValueError:
                        # Needs to be a fragment to be of interest
                        continue
                    if incomplete_fc.base_name() == fragment_fc.base_name():
                        temp_sector = []
                        for i in self.files_transfered[file_name]:
                            try:
                                temp_sector.index(i[0])
                            except Exception:
                                temp_sector.append(i[0])
                            else:
                                ret_val = (
                                    ret_val
                                    + "File %s, sector_num %d is a repeat - "
                                    % (file_name, i[0])
                                )
                                if (
                                    fragment_fc.is_seaglider()
                                    or fragment_fc.is_seaglider_selftest()
                                ):
                                    if fragment_fc.is_log():
                                        ret_val = (
                                            ret_val
                                            + "recommend resend_dive /l %d"
                                            % fragment_fc.dive_number()
                                        )
                                    elif fragment_fc.is_data():
                                        ret_val = (
                                            ret_val
                                            + "recommend resend_dive /d %d"
                                            % fragment_fc.dive_number()
                                        )
                                    elif fragment_fc.is_capture():
                                        ret_val = (
                                            ret_val
                                            + "recommend resend_dive /c %d"
                                            % fragment_fc.dive_number()
                                        )
                                    elif fragment_fc.is_tar():
                                        ret_val = (
                                            ret_val
                                            + "recommend resend_dive /t %d"
                                            % fragment_fc.dive_number()
                                        )
                                    else:
                                        # Don't know about this file type
                                        continue
                                    # fragments are in hex but glider code uses atoi(), which expects a decimal integer
                                    frag_num = fragment_fc.get_fragment_counter()
                                    if frag_num >= 0:
                                        ret_val = ret_val + " %d" % frag_num
                                    else:
                                        log_warning(
                                            "Invalid fragment counter (%s)" % file_name,
                                            "exc",
                                        )
                                else:
                                    ret_val = (
                                        ret_val + "recommend resend the entire file"
                                    )
        if len(ret_val):
            return ret_val
        else:
            return None


def get_glider_id(comm_log):
    """Finds glider id in comm.log

    Input:
        comm_log object

    Returns:
        glider id as int, -1 for failure
    """
    for s in comm_log.sessions:
        if s.sg_id is not None:
            return s.sg_id
    return -1


class ConnectSession:
    """Contains the data on a seaglider connection session to the basestation"""

    def __init__(self, connect_ts, time_zone):
        self.connect_ts = connect_ts
        self.time_zone = time_zone
        self.disconnect_ts = None
        self.reconnect_ts = None
        self.gps_fix = None
        # CONSIDER - make this another object?  Or Lat/Lon an object?
        self.phone_fix_lat = None
        self.phone_fix_lon = None
        self.phone_fix_datetime = None
        self.dive_num = None
        self.call_cycle = None
        self.calls_made = None
        self.no_comm = None
        self.mission_num = None
        self.reboot_count = None
        self.last_call_error = None
        self.this_call_error = None
        self.pitch_ad = None
        self.roll_ad = None
        self.vbd_ad = None
        self.obs_pitch = None
        self.depth = None
        self.volt_10V = None
        self.volt_24V = None
        self.int_press = None
        self.rh = None
        self.sea_temperature = None
        self.sea_salinity = None
        self.sea_density = None
        self.temperature = None
        self.launch_time = None
        self.eop_code = None
        self.recov_code = None
        self.escape_reason = None
        self.escape_started = None
        self.sg_id = None
        self.software_version = None
        self.software_revision = None
        self.fragment_size = None
        self.files_transfered = None
        self.logout_seen = False
        self.shutdown_seen = False
        self.file_stats = {}
        self.transfer_method = {}
        self.transfer_direction = {}
        self.transfered_size = {}
        self.crc_errors = {}
        self.cmd_directive = None
        self.logout_status = None
        # Dictionary of the file with send retries with in the sesssion
        # This is a rawrcvb thing only
        self.file_retries = collections.defaultdict(int)

    def to_dict(self):
        """Converts session object to a dict"""
        x = copy.deepcopy(self)
        x.gps_fix = vars(x.gps_fix)
        return vars(x)

    def to_message_dict(self):
        """Creates a dict from a subset of the session object for use in db operations"""
        return {
            "glider": self.sg_id,
            "connected": time.mktime(self.connect_ts),
            "dive": self.dive_num,
            "cycle": self.call_cycle,
            "call": self.calls_made,
            "lat": Utils.ddmm2dd(self.gps_fix.lat),
            "lon": Utils.ddmm2dd(self.gps_fix.lon),
            "epoch": time.mktime(self.gps_fix.datetime),
            "RH": self.rh,
            "intP": self.int_press,
            "temp": self.temperature,
            "volts10": self.volt_10V,
            "volts24": self.volt_24V,
            "pitch": self.obs_pitch,
            "depth": self.depth,
            "pitchAD": self.pitch_ad,
            "rollAD": self.roll_ad,
            "vbdAD": self.vbd_ad,
            "sst": self.sea_temperature,
            "sss": self.sea_salinity,
            "density": self.sea_density,
            "iridLat": Utils.ddmm2dd(self.phone_fix_lat) if self.phone_fix_lat else 0,
            "iridLon": Utils.ddmm2dd(self.phone_fix_lon) if self.phone_fix_lon else 0,
            "irid_t": time.mktime(self.phone_fix_datetime)
            if self.phone_fix_datetime
            else 0,
        }

    def __repr__(self):
        x = io.StringIO()
        self.dump_contents(x)
        x.seek(0)
        return x.read()

    def dump_contents(self, fo):
        """Dumps out the session contents, used when called manually"""
        print("_sg_id %s" % self.sg_id, file=fo)
        print(
            "connect_ts %s" % time.strftime("%a %b %d %H:%M:%S %Z %Y", self.connect_ts),
            file=fo,
        )
        if self.disconnect_ts:
            print(
                "disconnect_ts %s"
                % time.strftime("%a %b %d %H:%M:%S %Z %Y", self.disconnect_ts),
                file=fo,
            )
        if self.reconnect_ts:
            print(
                "reconnect_ts %s"
                % time.strftime("%a %b %d %H:%M:%S %Z %Y", self.reconnect_ts),
                file=fo,
            )
        if self.gps_fix:
            print(
                "gps_fix %s,%s,%s"
                % (
                    self.gps_fix.lat,
                    self.gps_fix.lon,
                    time.strftime("%m/%d/%y %H:%M:%S", self.gps_fix.datetime),
                ),
                file=fo,
            )
        else:
            print("No GPS fix", file=fo)
        if self.phone_fix_lat:
            print("phone_fix %s,%s" % (self.phone_fix_lat, self.phone_fix_lon), file=fo)
        else:
            print("No Phone Fix", file=fo)
        if self.dive_num is not None:
            print("dive_num %d" % self.dive_num, file=fo)
        if self.call_cycle is not None:
            print("call_cycle %d" % self.call_cycle, file=fo)
        if self.calls_made is not None:
            print("calls_made %d" % self.calls_made, file=fo)
        if self.no_comm is not None:
            print("no_comm %d" % self.no_comm, file=fo)
        if self.logout_seen is not None:
            print(f"logout_seen {self.logout_seen}", file=fo)
        if self.shutdown_seen is not None:
            print(f"shutdown_seen {self.shutdown_seen}", file=fo)
        if self.mission_num is not None:
            print("mission_num %d" % self.mission_num, file=fo)
        if self.reboot_count is not None:
            print("reboot_count %d" % self.reboot_count, file=fo)
        if self.last_call_error is not None:
            print("last_call_error %d" % self.last_call_error, file=fo)
        if self.this_call_error is not None:
            print("this_call_error %d" % self.this_call_error, file=fo)
        if self.pitch_ad is not None:
            print("pitch_ad %d" % self.pitch_ad, file=fo)
        if self.roll_ad is not None:
            print("roll_ad %d" % self.roll_ad, file=fo)
        if self.vbd_ad is not None:
            print("vbd_ad %d" % self.vbd_ad, file=fo)
        if self.obs_pitch is not None:
            print("obs_pitch %f" % self.obs_pitch, file=fo)
        if self.depth is not None:
            print("depth %f" % self.depth, file=fo)
        if self.volt_10V is not None:
            print("volt_10V %f" % self.volt_10V, file=fo)
        if self.volt_24V is not None:
            print("volt_24V %f" % self.volt_24V, file=fo)
        if self.int_press is not None:
            print("int_press %f" % self.int_press, file=fo)
        if self.rh is not None:
            print("rh %f" % self.rh, file=fo)
        if self.temperature is not None:
            print("temperature %f" % self.temperature, file=fo)
        if self.sea_temperature is not None:
            print("sea temperature %f" % self.sea_temperature, file=fo)
        if self.sea_salinity is not None:
            print("sea salinity %f" % self.sea_salinity, file=fo)
        if self.sea_density is not None:
            print("sea density %f" % self.sea_density, file=fo)
        if self.logout_status is not None:
            print("logout_status (%s)" % self.logout_status, file=fo)
        if self.launch_time is not None:
            print(
                "launch_time %s"
                % time.strftime("%d%m%y:%H%M%S", time.gmtime(self.launch_time)),
                file=fo,
            )
        if self.eop_code:
            print("eop_code %s" % self.eop_code, file=fo)
        if self.recov_code:
            print("recov_code %s" % self.recov_code, file=fo)
        print(
            "%d files transfered %s"
            % (
                len(list(self.transfered_size.keys())),
                list(self.transfered_size.keys()),
            ),
            file=fo,
        )
        print(
            "%d files with CRC errors %s"
            % (len(list(self.crc_errors.keys())), list(self.crc_errors.keys())),
            file=fo,
        )
        print(self.file_stats, file=fo)
        if self.cmd_directive:
            print(f"cmdfile directive {self.cmd_directive}", file=fo)
        else:
            print("No cmdfile directive found", file=fo)
        # for i in self.files_transfered.keys():
        #    tot_bytes = 0
        #    for j in self.files_transfered[i]:
        #        tot_bytes += j.


def crack_connect_line(input_line):
    """Parses out the time stamp from an input line

    The expected form of the input is:
      XXX at Sat Jul 2 01:54:49 PDT 2005 (optional_payload)
    where XXX is Connected or Reconnected or Disconnected

    There may be optional payload the end - a string enclosed in parens

    Returns a struct_time and timezone
    """
    log_debug(input_line)
    connect_line = input_line.split(sep=None, maxsplit=2)
    connect_ts_string = connect_line[2].lstrip().rstrip()
    log_debug("connect_string = (%s)" % connect_ts_string)
    cts_parts = connect_ts_string.split()
    connect_ts_tstruct = None
    if len(cts_parts) <= 2:
        # UTC ISO8601
        time_zone = None
        try:
            connect_ts_tstruct = time.strptime(
                cts_parts[0].lstrip().rstrip(), "%Y-%m-%dT%H:%M:%SZ"
            )
        except ValueError:
            pass
        else:
            time_zone = "UTC"
    else:
        # Split out the timezone
        if len(cts_parts) < 6:
            return (None, None, None)
        connect_ts_notz_string = "%s %s %s %s %s" % (
            cts_parts[0],
            cts_parts[1],
            cts_parts[2],
            cts_parts[3],
            cts_parts[5],
        )
        time_zone = cts_parts[4]
        with contextlib.suppress(ValueError):
            connect_ts_tstruct = BaseTime.convert_commline_to_utc(
                connect_ts_notz_string, time_zone
            )

    payload = None
    try:
        if len(cts_parts) in (2, 7):
            tmp = cts_parts[-1].rstrip().lstrip()
            if len(tmp) > 3 and tmp[0] == "(" and tmp[-1] == ")":
                payload = tmp[1:-1]
    except Exception:
        log_error("Failed to process connect/disconnect payload")

    return (connect_ts_tstruct, time_zone, payload)


def is_digit(val):
    """Because python doesn't have a built-in solution that handles negative values"""
    try:
        int(val)
    except ValueError:
        return False
    else:
        return True


# pylint: disable=unused-argument
def crack_counter_line(
    base_opts, session, raw_strs, comm_log_file_name, line_count, raw_line
):
    """Determines if a line is a counter line and fills out the session object if it is

    Returns:
       True - line is a counter line
       False - line is not a counter line
    """
    # Check for valid counter
    cnt_vals = raw_strs[0].split(":")

    if len(cnt_vals) >= 3 and len(cnt_vals) <= 20:
        for i in range(len(cnt_vals)):
            cnt_vals[i] = cnt_vals[i].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

        # Looks like a counter line
        if is_digit(cnt_vals[0]) and is_digit(cnt_vals[1]) and is_digit(cnt_vals[2]):
            # Differences in counter lines
            #
            # First - counter line with optional GPS string on end
            # Final - counter line with logout at end
            #
            # 67.00 (r7322): First: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, last_open_error,
            #       pitch_ad, roll_ad, vbd_ad, angle, depth, temperature, v10, v24, int_press, rh, sst, sss, ssd
            # 67.00 (r6718) First: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, last_open_error,
            #       pitch_ad, roll_ad, vbd_ad, angle, depth, temperature, v10, v24, int_press, rh
            # 67.00 (r6718) Final: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, status
            # 66.10 First: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, last_open_error,
            #       pitch_ad, roll_ad, vbd_ad, angle, depth, v10, v24, int_press, rh
            # 66.10 Final: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, status
            #
            # 66.09 First: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, last_open_error,
            #       pitch_ad, roll_ad, vbd_ad, angle, depth, v10, v24, int_press, rh
            # 66.09 Final: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, status
            #
            # 66.08 First: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, last_open_error,
            #       pitch_ad, roll_ad, vbd_ad
            # 66.08 Final: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count, status
            #
            # 66.07 First and Final: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count
            # 66.06 First and Final: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num, NVStore.boot_count
            # 66.05 First and Final: dive_num, callCycle, callsMade, cnt_NoComm, p_mission_num
            # 66.04 First and Final: dive_num, callCycle, callsMade, cnt_NoComm
            # 66.03 First and Final: dive_num, callCycle, callsMade, cnt_NoComm
            # 66.02 First and Final: dive_num, callCycle, callsMade, cnt_NoComm
            # 66.01 First and Final: dive_num, callCycle, callsMade, cnt_NoComm
            # 66.00 First and Final: dive_num, callCycle, callsMade, cnt_NoComm
            # 65.03 First and Final: dive_num, callsMade, cnt_NoComm
            # 65.02 First and Final: dive_num, callsMade, cnt_NoComm
            # 65.01 First and Final: dive_num, callsMade, cnt_NoComm
            # 65.00 First and Final: dive_num, callsMade, cnt_NoComm

            def convert_f(counter_vals, position, cnv_type):
                try:
                    return cnv_type(counter_vals[position])
                except ValueError:
                    log_error(
                        f"Failed to convert {counter_vals[position]} to {str(cnv_type)} line_num:{line_count}, position:{position}"
                    )
                    return None

            if len(cnt_vals) == 20 and Utils.is_float(cnt_vals[16]):
                # fmt: off
                # first counter r7312 (added sea surface T,S,density)
                session.dive_num        = convert_f(cnt_vals, 0, int)
                session.call_cycle      = convert_f(cnt_vals, 1, int)
                session.calls_made      = convert_f(cnt_vals, 2, int)
                session.no_comm         = convert_f(cnt_vals, 3, int)
                session.mission_num     = convert_f(cnt_vals, 4, int)
                session.reboot_count    = convert_f(cnt_vals, 5, int)
                session.last_call_error = convert_f(cnt_vals, 6, int)
                session.pitch_ad        = convert_f(cnt_vals, 7, int)
                session.roll_ad         = convert_f(cnt_vals, 8, int)
                session.vbd_ad          = convert_f(cnt_vals, 9, int)
                session.obs_pitch       = convert_f(cnt_vals, 10, float)
                session.depth           = convert_f(cnt_vals, 11, float)
                session.temperature     = convert_f(cnt_vals, 12, float)
                session.volt_10V        = convert_f(cnt_vals, 13, float)
                session.volt_24V        = convert_f(cnt_vals, 14, float)
                session.int_press       = convert_f(cnt_vals, 15, float)
                session.rh              = convert_f(cnt_vals, 16, float)
                session.sea_temperature = convert_f(cnt_vals, 17, float)
                session.sea_salinity    = convert_f(cnt_vals, 18, float)
                session.sea_density     = convert_f(cnt_vals, 19, float)
                # fmt:on
            elif len(cnt_vals) == 17 and Utils.is_float(cnt_vals[16]):
                # Version 66.09 - 66.10 First counter
                session.dive_num = convert_f(cnt_vals, 0, int)
                session.call_cycle = convert_f(cnt_vals, 1, int)
                session.calls_made = convert_f(cnt_vals, 2, int)
                session.no_comm = convert_f(cnt_vals, 3, int)
                session.mission_num = convert_f(cnt_vals, 4, int)
                session.reboot_count = convert_f(cnt_vals, 5, int)
                session.last_call_error = convert_f(cnt_vals, 6, int)
                session.pitch_ad = convert_f(cnt_vals, 7, int)
                session.roll_ad = convert_f(cnt_vals, 8, int)
                session.vbd_ad = convert_f(cnt_vals, 9, int)
                session.obs_pitch = convert_f(cnt_vals, 10, float)
                session.depth = convert_f(cnt_vals, 11, float)
                session.temperature = convert_f(cnt_vals, 12, float)
                session.volt_10V = convert_f(cnt_vals, 13, float)
                session.volt_24V = convert_f(cnt_vals, 14, float)
                session.int_press = convert_f(cnt_vals, 15, float)
                session.rh = convert_f(cnt_vals, 16, float)
            elif len(cnt_vals) == 16 and Utils.is_float(cnt_vals[15]):
                # Version 66.09 - 66.10 First counter
                session.dive_num = convert_f(cnt_vals, 0, int)
                session.call_cycle = convert_f(cnt_vals, 1, int)
                session.calls_made = convert_f(cnt_vals, 2, int)
                session.no_comm = convert_f(cnt_vals, 3, int)
                session.mission_num = convert_f(cnt_vals, 4, int)
                session.reboot_count = convert_f(cnt_vals, 5, int)
                session.last_call_error = convert_f(cnt_vals, 6, int)
                session.pitch_ad = convert_f(cnt_vals, 7, int)
                session.roll_ad = convert_f(cnt_vals, 8, int)
                session.vbd_ad = convert_f(cnt_vals, 9, int)
                session.obs_pitch = convert_f(cnt_vals, 10, float)
                session.depth = convert_f(cnt_vals, 11, float)
                session.volt_10V = convert_f(cnt_vals, 12, float)
                session.volt_24V = convert_f(cnt_vals, 13, float)
                session.int_press = convert_f(cnt_vals, 14, float)
                session.rh = convert_f(cnt_vals, 15, float)
            elif len(cnt_vals) == 10 and Utils.is_integer(cnt_vals[9]):
                # Version 66.08 First counter
                session.dive_num = convert_f(cnt_vals, 0, int)
                session.call_cycle = convert_f(cnt_vals, 1, int)
                session.calls_made = convert_f(cnt_vals, 2, int)
                session.no_comm = convert_f(cnt_vals, 3, int)
                session.mission_num = convert_f(cnt_vals, 4, int)
                session.reboot_count = convert_f(cnt_vals, 5, int)
                session.last_call_error = convert_f(cnt_vals, 6, int)
                session.pitch_ad = convert_f(cnt_vals, 7, int)
                session.roll_ad = convert_f(cnt_vals, 8, int)
                session.vbd_ad = convert_f(cnt_vals, 9, int)
            elif len(cnt_vals) == 7 and Utils.is_integer(cnt_vals[6]):
                # Version 66.08 - 66.10 Final counter
                session.dive_num = convert_f(cnt_vals, 0, int)
                session.call_cycle = convert_f(cnt_vals, 1, int)
                session.calls_made = convert_f(cnt_vals, 2, int)
                session.no_comm = convert_f(cnt_vals, 3, int)
                session.mission_num = convert_f(cnt_vals, 4, int)
                session.reboot_count = convert_f(cnt_vals, 5, int)
                session.this_call_error = convert_f(cnt_vals, 6, int)
            elif len(cnt_vals) == 6 and Utils.is_integer(cnt_vals[5]):
                # Version 66.06 - 66.07 counter
                session.dive_num = convert_f(cnt_vals, 0, int)
                session.call_cycle = convert_f(cnt_vals, 1, int)
                session.calls_made = convert_f(cnt_vals, 2, int)
                session.no_comm = convert_f(cnt_vals, 3, int)
                session.mission_num = convert_f(cnt_vals, 4, int)
                session.reboot_count = convert_f(cnt_vals, 5, int)
            elif len(cnt_vals) == 5 and Utils.is_integer(cnt_vals[4]):
                # Version 66.05 counter
                session.dive_num = convert_f(cnt_vals, 0, int)
                session.call_cycle = convert_f(cnt_vals, 1, int)
                session.calls_made = convert_f(cnt_vals, 2, int)
                session.no_comm = convert_f(cnt_vals, 3, int)
                session.mission_num = convert_f(cnt_vals, 4, int)
            elif len(cnt_vals) == 4 and Utils.is_integer(cnt_vals[3]):
                # Version 66.00 - 66.04
                session.dive_num = convert_f(cnt_vals, 0, int)
                session.call_cycle = convert_f(cnt_vals, 1, int)
                session.calls_made = convert_f(cnt_vals, 2, int)
                session.no_comm = convert_f(cnt_vals, 3, int)
            else:
                # Version 65 counter
                log_info("Version 65 counter (%s)" % raw_strs[0])
                session.dive_num = convert_f(cnt_vals, 0, int)
                session.calls_made = convert_f(cnt_vals, 1, int)
                session.no_comm = convert_f(cnt_vals, 2, int)

            # if(session.calls_made == 0):
            #    print cnt_vals
            #    print raw_strs[0]
            #    print raw_strs[0].split(":")

            # Now, figure out what comes after the line

            if len(raw_strs) > 1:
                if raw_strs[1] == "logout":
                    session.logout_seen = True
                elif (raw_strs[1].split("="))[0] == "ver":
                    # Found the details of the form "ver=66.00,rev=753M,frag=4" or
                    # ver=66.06,rev=1893:1900M,frag=4,launch=310709:035925
                    tmp = raw_strs[1].split(",")
                    # ver = tmp[0]
                    rev = tmp[1]
                    if rev == "rev=Unversioned":
                        # A version of software not yet checked in...'Unversioned directory'
                        tmp2 = raw_strs[2].split(",")
                        tmp.extend(tmp2[1:])  # drop directory, and add the rest to tmp
                    frag = tmp[2]
                    # TODO - Add parsing for launch time and add to session
                    ver_tmp = tmp[0].split("=")[1]
                    try:
                        session.software_version = float(ver_tmp)
                    except ValueError:
                        # Might be an iRobot version - major.minor.rev1.rev2
                        tmp2 = ver_tmp.rsplit(".", 2)[0]
                        try:
                            session.software_version = float(tmp2)
                        except ValueError:
                            log_error("Unknown version %s = assuming 66.00" % ver_tmp)
                    session.software_revision = rev.split("=")[1]
                    session.fragment_size = (
                        int(frag.split("=")[1]) * 1024
                    )  # Base.py expects this in bytes
                elif GPS.is_valid_gps_line(raw_strs[1]):
                    if session.reconnect_ts is not None:
                        start_time = time.strftime("%m %d %y", session.reconnect_ts)
                    else:
                        start_time = time.strftime("%m %d %y", session.connect_ts)
                    session.gps_fix = GPS.GPSFix(raw_strs[1], start_date_str=start_time)
                else:
                    log_warning(
                        "Unknown line after counter: file %s, lineno %d, line %s"
                        % (comm_log_file_name, line_count, raw_line)
                    )
            else:
                log_warning(
                    "Counter line appears with no trailing data: file %s, lineno %d, line %s"
                    % (comm_log_file_name, line_count, raw_line)
                )
            return True

    return False


def process_comm_log(
    comm_log_file_name,
    base_opts,
    known_commlog_files=None,
    start_pos=-1,
    call_back=None,
    session=None,
    line_count=0,
    scan_back=False,
):
    """Processes a Seagliders comm log

    Returns a CommLog object
    """

    if not known_commlog_files:
        known_commlog_files = ["cmdfile", "science", "targets", "pdoscmds.bat"]

    if not os.path.exists(comm_log_file_name):
        log_error(f"{comm_log_file_name} does not exist")
        return (None, None, None, None, 1)

    try:
        # Look backward through the file for the last line starting with "Connected" as starting point
        # If found, any start_pos supplied will be ignored
        if scan_back:
            log_debug("Scanning backwards")
            try:
                comm_log_file = open(comm_log_file_name, "rb")
            except OSError:
                log_error("Could not open %s for reading." % comm_log_file_name)
                return (None, None, None, None, 1)

            try:
                comm_log_file.seek(-2, os.SEEK_END)
                while True:
                    while comm_log_file.read(1) != b"\n":
                        comm_log_file.seek(-2, os.SEEK_CUR)

                    curr_pos = comm_log_file.tell()
                    curr_line = comm_log_file.readline().decode()
                    print((curr_line, curr_pos))
                    if curr_line.startswith("Connected"):
                        log_info(
                            f"Scan back found connected line pos:{curr_pos} {curr_line}"
                        )
                        start_pos = curr_pos
                        comm_log_file.close()
                        break
                    else:
                        comm_log_file.seek(curr_pos - 2, os.SEEK_SET)
            except OSError:
                # Didn't find a line starting with connected - fall through
                start_pos = 0
            comm_log_file.close()

        statinfo = os.stat(comm_log_file_name)
        if start_pos >= 0 and statinfo.st_size < start_pos:
            # File got smaller - reparse
            log_info(
                f"File got samller - resetting starting position from ({statinfo.st_size}, {start_pos})"
            )
            start_pos = 0

        # Start of regular processing
        try:
            comm_log_file = open(comm_log_file_name, "rb")
        except OSError:
            log_error("Could not open %s for reading." % comm_log_file_name)
            return (None, None, None, None, 1)

        log_debug("process_comm_log starting")
        if start_pos >= 0:
            statinfo = os.stat(comm_log_file_name)
            if statinfo.st_size > start_pos:
                log_debug(f"Resetting to file pos ({statinfo.st_size}, {start_pos})")
                if comm_log_file.seek(start_pos, 0) != start_pos:
                    log_warning(f"Seek to {start_pos} failed")
            elif statinfo.st_size == start_pos:
                log_debug(
                    f"size and start are the same ({statinfo.st_size}, {start_pos})"
                )
                # Start pos is the same as filesize - nothing to do
                return (None, start_pos, session, line_count, 0)

        sessions = []
        raw_file_lines = []
        files_transfered = {}

        file_transfered = []
        file_crc_errors = []

        file_transfer_method = {}

        for raw_line in comm_log_file:
            line_count = line_count + 1
            try:
                raw_line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                log_warning(f"Could not decode line number {line_count} - skipping")
                continue
            raw_line = raw_line.rstrip()

            if raw_line == "":
                continue

            raw_file_lines.append([None, raw_line])

            # Figure out what line we are looking at
            raw_strs = raw_line.split()

            # Partially transmitted files are addressed out of the patched lrzsz executables and
            # appear in the comm log as a pair of files in lines like this:
            #
            # Renamed partial file sg0143dz.x02 to sg0143dz.x02.PARTIAL.1
            # Fri Nov 10 09:17:10 2006 [sg109] processed partial file sg0143dz.x02 (0x0)
            #
            # Due to some poorly understood interaction between the glider login shell and the
            # execution of the .logout script, these lines may appear before or after the Disconnected
            # message.  As we do not use this data from the comm log for data processing, we filter these
            # lines out here, to reduce the noise in the conversion logs.
            if raw_line.startswith("Renamed partial file"):
                continue
            if raw_line.find("processed partial file") >= 0:
                continue
            if raw_line.startswith("Missing expected basestation prompt"):
                continue

            if raw_strs[0] == "Parsed" and raw_strs[2] == "from":
                if session:
                    session.cmd_directive = raw_strs[1]
                cmd_run = None
                if len(raw_strs) >= 4 and raw_strs[3] == "./callend":
                    cmd_run = "callend"
                elif len(raw_strs) >= 5 and raw_strs[3] == "cmdfile":
                    cmd_run = "cmdfile"
                if cmd_run:
                    try:
                        # In either of these cases, there are no transfer stats in the comm.log,
                        # so just use the file size for all (assumes best case of file
                        # actually transferring)
                        statinfo = os.stat(os.path.join(base_opts.mission_dir, cmd_run))
                        file_transfer_method[cmd_run] = "raw"
                        session.transfer_method[cmd_run] = "raw"
                        session.transfered_size[cmd_run] = statinfo.st_size
                        session.transfer_direction[cmd_run] = "sent"
                        session.file_stats[cmd_run] = file_stats_nt(
                            -1, statinfo.st_size, statinfo.st_size, 0.0
                        )
                    except Exception:
                        log_error(
                            "Could not process %s: lineno %d" % (raw_strs, line_count),
                            "exc",
                        )
                    else:
                        if call_back and "received" in call_back.callbacks:
                            try:
                                call_back.callbacks["received"](
                                    cmd_run, statinfo.st_size
                                )
                            except Exception:
                                log_error("received callback failed", "exc")

                continue

            # XMODEM to glider
            if raw_strs[0] == "Sent":
                if session:
                    session.transfer_direction[raw_strs[1]] = "sent"
                continue

            if raw_strs[0] == "Connected":
                if scan_back:
                    log_debug("In Connected")
                if session:
                    log_warning(
                        "Found Connected with no previous Disconnect: file %s, lineno %d"
                        % (comm_log_file_name, line_count)
                    )
                connect_ts, time_zone, username = crack_connect_line(raw_line)
                if connect_ts is None:
                    log_warning(f"Connected line did not have a timestamp ({raw_line})")
                    continue
                session = ConnectSession(connect_ts, time_zone)
                if (
                    username is not None
                    and len(username) >= 5
                    and username.lower()[0:2] == "sg"
                ):
                    try:
                        sg_id = int(username[2:5])
                    except ValueError:
                        pass
                    else:
                        session.sg_id = sg_id
                # log_info(f"sgid:{session.sg_id} {username} {line_count}")
                if not session.sg_id:
                    # Try to deduce the glider id from the housing directory
                    # This will be updated during the call if any files are transferred
                    try:
                        m_dir, _ = os.path.split(comm_log_file_name)
                        _, sg_id = os.path.split(m_dir)
                        sg_id = int(sg_id[2:])
                    except Exception:
                        pass
                    else:
                        session.sg_id = sg_id

                raw_file_lines[-1][0] = time.mktime(session.connect_ts)

                if call_back and "connected" in call_back.callbacks:
                    try:
                        call_back.callbacks["connected"](connect_ts)
                    except Exception:
                        log_error("Connected callback failed", "exc")
                continue
            elif raw_strs[0] == "Reconnected":
                reconnect_ts, time_zone, username = crack_connect_line(raw_line)
                if reconnect_ts is None:
                    continue
                raw_file_lines[-1][0] = time.mktime(reconnect_ts)

                if session:
                    session.reconnect_ts = reconnect_ts
                    if (
                        username is not None
                        and len(username) >= 5
                        and username.lower()[0:2] == "sg"
                    ):
                        try:
                            sg_id = int(username[2:5])
                        except ValueError:
                            pass
                        else:
                            session.sg_id = sg_id

                else:
                    log_warning(
                        "Found ReConnected outside Connected: file %s, lineno %d "
                        % (comm_log_file_name, line_count)
                    )
                if call_back and "reconnected" in call_back.callbacks:
                    try:
                        call_back.callbacks["reconnected"](reconnect_ts)
                    except Exception:
                        log_error("Reconnected callback failed", "exc")
                continue
            elif raw_strs[0] == "Disconnected":
                disconnect_ts, time_zone, logout_status = crack_connect_line(raw_line)
                if disconnect_ts is None:
                    continue
                raw_file_lines[-1][0] = time.mktime(disconnect_ts)

                if session:
                    session.disconnect_ts = disconnect_ts
                    session.logout_status = logout_status
                    sessions.append(session)
                else:
                    log_warning(
                        "Found Disconnect with no previous Connected: file %s, lineno %d"
                        % (comm_log_file_name, line_count)
                    )

                if call_back and "disconnected" in call_back.callbacks:
                    try:
                        call_back.callbacks["disconnected"](session)
                    except Exception:
                        log_error("Disconnected callback failed", "exc")
                session = None
                continue
            elif raw_strs[0] == "shutdown":
                if session:
                    session.shutdown_seen = True
                continue
            elif session:
                if crack_counter_line(
                    base_opts,
                    session,
                    raw_strs,
                    comm_log_file_name,
                    line_count,
                    raw_line,
                ):
                    if call_back and "counter_line" in call_back.callbacks:
                        try:
                            call_back.callbacks["counter_line"](session)
                        except Exception:
                            log_error("counter_line callback failed", "exc")
                    continue

                # Check for recovery
                parse_strs = raw_strs[0].split("=")
                if parse_strs[0] == "EOP_CODE":
                    session.eop_code = parse_strs[1]
                    continue
                if parse_strs[0] == "RECOV_CODE":
                    session.recov_code = parse_strs[1]
                    if call_back and "recovery" in call_back.callbacks:
                        if session.eop_code:
                            msg = "%s:%s" % (session.recov_code, session.eop_code)
                        else:
                            msg = parse_strs[1]
                        try:
                            call_back.callbacks["recovery"](msg)
                        except Exception:
                            log_error("recovery callback failed", "exc")
                    continue
                else:
                    if call_back and "recovery" in call_back.callbacks:
                        try:
                            call_back.callbacks["recovery"](None)
                        except Exception:
                            log_error("recovery callback failed", "exc")
                if parse_strs[0] == "ESCAPE_REASON":
                    session.escape_reason = parse_strs[1]
                    continue
                if parse_strs[0] == "STARTED":
                    session.escape_started = int(parse_strs[1])
                    continue

                # Check for Iridium
                try:
                    iridium_strs = raw_line.split(":")
                    if iridium_strs[0] == "Iridium bars":
                        if len(iridium_strs) < 3:
                            continue
                        lat_lon = iridium_strs[2].lstrip().split(",")
                        session.phone_fix_lat = float(lat_lon[0])
                        session.phone_fix_lon = float(lat_lon[1])
                        session.phone_fix_datetime = time.strptime(
                            lat_lon[2] + lat_lon[3], "%d%m%y%H%M%S"
                        )

                        if call_back and "iridium" in call_back.callbacks:
                            try:
                                call_back.callbacks["iridium"](session)
                            except Exception:
                                log_error("iridium callback failed", "exc")
                        continue
                    elif iridium_strs[0] == "Iridium geolocation":
                        lat_lon = iridium_strs[1].lstrip().split(" ")
                        if len(lat_lon) == 2:
                            session.phone_fix_lat = float(lat_lon[0])
                            session.phone_fix_lon = float(lat_lon[1])
                        else:
                            lat_lon = iridium_strs[1].lstrip().split(",")
                            session.phone_fix_lat = float(lat_lon[0])
                            session.phone_fix_lon = float(lat_lon[1])
                        continue
                except Exception:
                    pass

                # Files uploaded to the glider via X/Y MODEM are of the form
                # Received cmdfile 322 bytes
                if raw_strs[0] == "Received":
                    if len(raw_strs) > 3:
                        try:
                            filename = raw_strs[1]
                            receivedsize = int(raw_strs[2])
                            session.transfer_direction[raw_strs[1]] = "received"
                            if filename in session.file_stats:
                                # The Received line alwasy follows a /XYMODEM line, so add in the
                                # already collected stats
                                expectedsize, transfersize, _, bps = session.file_stats[
                                    filename
                                ]
                            else:
                                log_warning(
                                    "Found Received for %s with out matching X/Y MODEM line"
                                    % filename
                                )
                                expectedsize = -1
                                transfersize = -1
                                bps = -1
                            session.file_stats[filename] = file_stats_nt(
                                expectedsize, transfersize, receivedsize, bps
                            )
                        except Exception:
                            log_error(
                                "Could not process %s: lineno %d"
                                % (raw_strs, line_count),
                                "exc",
                            )
                        else:
                            if call_back and "received" in call_back.callbacks:
                                try:
                                    call_back.callbacks["received"](
                                        filename, receivedsize
                                    )
                                except Exception:
                                    log_error("received callback failed", "exc")
                    continue

                # Look for the [sg(id)] tag -- marks file transfer info
                sgid_re = re.compile(r"\[sg(\d+)\]")
                sg_id_tmp = sgid_re.findall(raw_line)
                if sg_id_tmp:
                    # Crack the leading date
                    ts_line = raw_line.split("[")
                    ts_string = ts_line[0].lstrip().rstrip()
                    # Try ISO8601 first
                    utc_time_stamp = None
                    with contextlib.suppress(ValueError):
                        utc_time_stamp = time.mktime(
                            time.strptime(ts_string, "%Y-%m-%dT%H:%M:%SZ")
                        )
                    if utc_time_stamp:
                        raw_file_lines[-1][0] = utc_time_stamp
                    else:
                        # Old version with local time
                        raw_file_lines[-1][0] = time.mktime(
                            BaseTime.convert_commline_to_utc(
                                ts_string, session.time_zone
                            )
                        )

                    session.sg_id = int(sg_id_tmp[0])

                    # RAW or YMODEM files uploaded to the glider
                    # Thu Aug  4 19:48:52 2016 [sg203] Sent 192 bytes of cmdfile
                    # or
                    # 2023-01-23T23:33:33Z [sg095] Sent 15 bytes of pdoscmds.bat

                    # Find the end of the [sgXXX] tag, and work on the end of the string

                    action_strs = raw_line[sgid_re.search(raw_line).end() :].split()

                    if len(action_strs) > 4:
                        if action_strs[0] == "Sending":
                            try:
                                filename = action_strs[4]
                                session.file_stats[filename] = file_stats_nt(
                                    int(action_strs[1]), -1, -1, -1
                                )
                            except Exception:
                                log_error(
                                    "Could not process %s: lineno %d"
                                    % (raw_strs, line_count),
                                    "exc",
                                )
                            continue

                        if (
                            action_strs[0] == "Sent"
                            and "/YMODEM" not in raw_line
                            and "/XMODEM" not in raw_line
                        ):
                            # Raw send
                            try:
                                filename = action_strs[4]
                                file_transfer_method[filename] = "raw"
                                session.transfer_method[filename] = "raw"
                                session.transfered_size[filename] = int(action_strs[1])
                                session.transfer_direction[filename] = "received"
                                session.file_stats[filename] = file_stats_nt(
                                    -1, int(action_strs[1]), int(action_strs[1]), -1
                                )
                            except Exception:
                                log_error(
                                    "Could not process %s: lineno %d"
                                    % (raw_strs, line_count),
                                    "exc",
                                )

                            if call_back and "received" in call_back.callbacks:
                                try:
                                    call_back.callbacks["received"](
                                        action_strs[4], int(action_strs[1])
                                    )
                                except Exception:
                                    log_error("received callback failed", "exc")
                            continue

                    # RAW or YMODEM files downloaded from the glider
                    if len(action_strs) >= 5:
                        # Tue Oct  6 07:37:38 2020 [sg236] Receiving 8192 bytes of sc0041bg.x02
                        if action_strs[0] == "Receiving":
                            try:
                                filename = action_strs[4]
                                if filename in session.file_stats:
                                    session.file_retries[filename] += 1
                                session.file_stats[filename] = file_stats_nt(
                                    int(action_strs[1]), -1, -1, -1
                                )
                            except Exception:
                                log_error(
                                    "Could not process %s: lineno %d"
                                    % (raw_strs, line_count),
                                    "exc",
                                )
                            continue

                        # Thu Aug  4 19:49:42 2016 [sg203] Received 386 bytes of br0003lp.x03 (366.2 Bps)
                        if action_strs[0] == "Received" and "/YMODEM" not in raw_line:
                            try:
                                filename = action_strs[4]
                                if filename not in session.file_stats:
                                    log_warning(
                                        "Found Received for %s with out matching Receiving line"
                                        % filename
                                    )
                                    expected_size = -1
                                else:
                                    expected_size = session.file_stats[
                                        filename
                                    ].expectedsize
                                file_transfer_method[filename] = "raw"
                                session.transfer_method[filename] = "raw"
                                session.transfer_direction[filename] = "sent"
                                session.transfered_size[filename] = int(action_strs[1])
                                if len(action_strs) == 5:
                                    session.file_stats[filename] = file_stats_nt(
                                        expected_size,
                                        int(action_strs[1]),
                                        int(action_strs[1]),
                                        0.0,
                                    )
                                elif len(action_strs) == 7:
                                    session.file_stats[filename] = file_stats_nt(
                                        expected_size,
                                        int(action_strs[1]),
                                        int(action_strs[1]),
                                        float(action_strs[5].lstrip("(")),
                                    )
                                else:
                                    log_warning(
                                        f"Could not process sent lineno {line_count} - skipping"
                                    )
                                    # Do not issue the callback
                                    continue

                            except Exception:
                                log_error(
                                    "Could not process %s: lineno %d"
                                    % (raw_strs, line_count),
                                    "exc",
                                )

                            if call_back and "transfered" in call_back.callbacks:
                                try:
                                    call_back.callbacks["transfered"](
                                        action_strs[4], int(action_strs[1])
                                    )
                                except Exception:
                                    log_error("transfered callback failed", "exc")

                            continue

                    # Files uploaded or Downloaded via X/Y MODEM -
                    # Fri Aug  5 17:17:48 2016 [sg075] cmdfile/XMODEM: 384 Bytes, 75 BPS
                    if raw_line.find("Bytes") > -1:
                        # X/Y MODEM transfer
                        front, end = raw_line.split(
                            "/XMODEM:" if "/XMODEM:" in raw_line else "/YMODEM:"
                        )
                        filename = front.split(" ")[
                            -1
                        ].strip()  # last string is filename
                        if base_opts and base_opts.ver_65:
                            tempname = Ver65.ver_65_to_ver_66_filename(filename)
                            if tempname is not None:
                                filename = tempname

                        if filename is not None:
                            if "/YMODEM:" in raw_line:
                                try:
                                    transfersize = int(action_strs[1].strip())
                                    bps = int(
                                        end.lstrip().split(" ")[2].strip()
                                    )  # bytes per second third string
                                except ValueError:
                                    log_error(
                                        "Error processing: %s lineno %d, line %s"
                                        % (comm_log_file_name, line_count, raw_line),
                                        "exc",
                                    )
                                    transfersize = bps = -1

                                if filename not in session.file_stats:
                                    # The /YMODEM line follows a Receiving line for a download,
                                    # but proceeds the Received line for an upload, so there may
                                    # or may not be existing stats to add to
                                    log_debug(
                                        "Found Received for %s with out matching Receiving line"
                                        % filename
                                    )
                                    expected_size = -1
                                else:
                                    expected_size = session.file_stats[
                                        filename
                                    ].expectedsize
                                # Since there is no padding with YMODEM, the transfersize
                                # is the receivedsize
                                receivedsize = transfersize
                            else:
                                # XMODEM
                                transfersize = int(
                                    end.lstrip().split(" ")[0].strip()
                                )  # first string is transfer size
                                bps = int(
                                    end.lstrip().split(" ")[2].strip()
                                )  # bytes per second third string
                                expected_size = -1
                                receivedsize = -1

                            session.file_stats[filename] = file_stats_nt(
                                expected_size, transfersize, receivedsize, bps
                            )
                            files_transfered[filename] = file_transfered
                            session.transfered_size[filename] = file_transfered
                            if "/YMODEM:" in raw_line:
                                session.transfer_method[filename] = "ymodem"
                                file_transfer_method[filename] = "ymodem"
                            else:
                                session.transfer_method[filename] = "xmodem"
                                file_transfer_method[filename] = "xmodem"
                            file_transfered = []
                            if file_crc_errors:
                                session.crc_errors[filename] = file_crc_errors
                                file_crc_errors = []

                            if known_commlog_files is not None:
                                if filename in known_commlog_files:
                                    k = "received"
                                else:
                                    k = "transfered"
                                if call_back and k in call_back.callbacks:
                                    try:
                                        call_back.callbacks[k](filename, transfersize)
                                    except Exception:
                                        log_error("%s callback failed" % k, "exc")

                        continue

                    if raw_line.find("got error") > -1:
                        front, end = raw_line.split(
                            "/XMODEM:" if "/XMODEM:" in raw_line else "/YMODEM:"
                        )
                        filename = front.split(" ")[
                            -1
                        ].strip()  # last string is filename
                        if base_opts and base_opts.ver_65:
                            tempname = Ver65.ver_65_to_ver_66_filename(filename)
                            if tempname is not None:
                                filename = tempname
                        # 0,0 indicates XModem error
                        if "/YMODEM:" in raw_line:
                            session.transfer_method[filename] = "ymodem"
                            file_transfer_method[filename] = "ymodem"
                        else:
                            session.transfer_method[filename] = "xmodem"
                            file_transfer_method[filename] = "xmodem"
                        file_transfered.append(file_transfered_nt(0, 0))
                        files_transfered[filename] = file_transfered
                        file_transfered = []
                        if file_crc_errors:
                            session.crc_errors[filename] = file_crc_errors
                            file_crc_errors = []
                        continue

                    if "sector number = " in raw_line:
                        if "block length" in raw_line:
                            try:
                                front, end = raw_line.split(", block length = ")
                                sector_num = int(front.split("=")[1])
                            except Exception:
                                log_warning(
                                    "Malformed line %d in comm.log (%s) - skipping"
                                    % (line_count, raw_line)
                                )
                            else:
                                block_len = int(end)
                                file_transfered.append(
                                    file_transfered_nt(sector_num, block_len)
                                )
                        elif "CRC error" in raw_line:
                            try:
                                sector_num = int(raw_line.split("=")[1])
                            except Exception:
                                log_warning(
                                    "Malformed line %d in comm.log (%s) - skipping"
                                    % (line_count, raw_line)
                                )
                            else:
                                block_len = int(sector_num)
                                file_crc_errors.append(sector_num)

                        continue

                    # Assume that the XModem: got error processing above is enough to deal with partials
                    continue

                if (raw_strs[0].split("="))[0] == "ver":
                    # Found the details of the form "ver=66.00,rev=753M,frag=4"
                    tmp = raw_strs[0].split(",")
                    ver_tmp = tmp[0].split("=")[1]
                    try:
                        session.software_version = float(ver_tmp)
                    except ValueError:
                        # Might be an iRobot version - major.minor.rev1.rev2
                        tmp2 = ver_tmp.rsplit(".", 2)[0]
                        try:
                            session.software_version = float(tmp2)
                        except ValueError:
                            log_error("Unknown version %s = assuming 66.00" % ver_tmp)
                            session.software_version = 66.00

                    try:
                        # Base.py expects this in bytes
                        session.fragment_size = int(tmp[2].split("=")[1]) * 1024
                    except Exception:
                        log_error(
                            "Could not parse fragment size out of %s - assuming 4 "
                            % raw_strs[0]
                        )
                        session.fragment_size = 4

                    try:
                        session.software_revision = tmp[1].split("=")[1]
                        if session.software_revision == "Unversioned":
                            # A version of software not yet checked in...'Unversioned directory'
                            tmp2 = raw_strs[1].split(",")
                            tmp.extend(
                                tmp2[1:]
                            )  # drop directory, and add the rest to tmp
                    except Exception:
                        log_error(
                            "Could not parse software revision out of %s - assuming 0 "
                            % raw_strs[0]
                        )
                        session.software_revision = 0

                    try:
                        session.fragment_size = (
                            int(tmp[2].split("=")[1]) * 1024
                        )  # Base.py expects this in bytes
                    except Exception:
                        log_error(
                            "Could not parse fragment size out of %s - assuming 4 "
                            % raw_strs[0]
                        )
                        session.fragment_size = 4

                    if len(tmp) > 3:
                        try:
                            session.launch_time = time.mktime(
                                time.strptime(tmp[3].split("=")[1], "%d%m%y:%H%M%S")
                            )
                        except ValueError:
                            log_error(
                                f"Could not parse launch time - line {line_count} in comm.log"
                            )
                            continue

                    if call_back and "ver" in call_back.callbacks:
                        try:
                            call_back.callbacks["ver"](session)
                        except Exception:
                            log_error("ver callback failed", "exc")
                    continue

                if raw_strs[0] == "logged" and raw_strs[1] == "in":
                    continue

                if (
                    known_commlog_files is not None
                    and raw_strs[0] in known_commlog_files
                ):
                    continue

                if raw_strs[0] == "Sent":
                    continue

                # Insert code here to pick off the transmitted files
                log_debug(
                    "Unknown line: file %s, lineno %d, line %s"
                    % (comm_log_file_name, line_count, raw_line)
                )
            else:
                log_debug(
                    "Line outside session: file %s, lineno %d, line %s"
                    % (comm_log_file_name, line_count, raw_line)
                )
        start_pos = comm_log_file.tell()
        comm_log_file.close()

        commlog = CommLog(
            sessions, raw_file_lines, files_transfered, file_transfer_method
        )
        log_debug("process_comm_log finished")
        return (commlog, start_pos, session, line_count, 0)
    except Exception:
        if DEBUG_PDB:
            _, _, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)

        log_error("process_comm_log failed with unexpected exception", "exc")
        return (None, None, session, line_count, 1)


def process_history_log(history_log_file_name):
    """Processes a Seagliders history log

    Returns an array of epoch times and commands
    """
    try:
        history_log_file = open(history_log_file_name, "rb")
    except OSError:
        log_critical("Could not open %s for reading." % history_log_file_name)
        return None

    line_count = 0
    command_history = []

    for raw_line in history_log_file:
        try:
            raw_line_tmp = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            log_debug(f"Could not decode {raw_line} - skipping")
            continue
        raw_line = raw_line_tmp

        raw_line = raw_line.rstrip()
        line_count = line_count + 1
        if raw_line == "":
            continue
        if raw_line[0] == "#" and raw_line[1] == "+":
            ts_line = raw_line.split("+")
            try:
                ts = float(ts_line[1].rstrip())
            except ValueError:
                log_warning(
                    f"Could not process line {line_count} in {history_log_file_name} - skipping"
                )
            else:
                command_history.append([ts, None])
            continue
        # Next line is the command
        command_history[-1][1] = "%s (%s)" % (
            time.strftime(
                "%a %b %d %H:%M:%S %Y", time.localtime(command_history[-1][0])
            ),
            raw_line,
        )

    return command_history


def merge_lists_with_ts(list1, list2):
    """Assumes list 1 much longer then list 2
    new_list = None
    """
    # Clean up lists
    last_time = 0
    new_list = []
    for i in range(len(list1)):
        if list1[i][0] is not None:
            last_time = list1[i][0]
        else:
            list1[i][0] = last_time
        new_list.append((list1[i][0], list1[i][1]))

    last_time = 0
    for i in range(len(list2)):
        if list2[i][0] is not None:
            last_time = list2[i][0]
        else:
            list2[i][0] = last_time
        new_list.append((list2[i][0], list2[i][1]))

    new_list.sort(key=lambda x: x[0])

    return new_list


class TestCommLogCallback:
    """
    Called from the comm log parser
    """

    cmd_prefix = "callback_"

    def __init__(self):
        self.cmds = {}
        for name, val in inspect.getmembers(self):
            if inspect.ismethod(val) and name.startswith(self.cmd_prefix):
                self.cmds[name[len(self.cmd_prefix) :]] = val

    # pylint: disable=R0201
    def callback_connected(self, connect_ts):
        """connected test callback"""
        msg = "Connected: %s\n" % time.strftime("%a %b %d %H:%M:%S %Z %Y", connect_ts)
        sys.stdout.write(msg)

    def callback_counter_line(self, session):
        """counter line test callback"""
        sys.stdout.write("Counter line found\n")
        session.dump_contents(sys.stdout)

    def callback_reconnected(self, reconnect_ts):
        """reconnected test callback"""
        msg = "Reconnected: %s\n" % time.strftime(
            "%a %b %d %H:%M:%S %Z %Y", reconnect_ts
        )
        sys.stdout.write(msg)

    def callback_disconnected(self, session):
        """disconnected test callback"""
        if session:
            if session.logout_seen:
                logout_msg = "Logout received"
            else:
                logout_msg = "Did not see a logout"
            msg = "Disconnected: %s %s\n" % (
                time.strftime("%a %b %d %H:%M:%S %Z %Y", session.disconnected_ts),
                logout_msg,
            )
            sys.stdout.write(msg)
        else:
            sys.stdout.write("dissconnect:no session\n")

    def callback_transfered(self, filename, receivedsize):
        """transfered test callback"""
        msg = "Transfered %d bytes of %s\n" % (receivedsize, filename)
        sys.stdout.write(msg)

    def callback_received(self, filename, receivedsize):
        """received test callback"""
        msg = "Received file %s (%d bytes)\n" % (filename, receivedsize)
        sys.stdout.write(msg)

    # pylint: enable=R0201


def main():
    """main - main entry point"""
    base_opts = BaseOpts.BaseOptions(
        "Test entry for comm.log processing",
        additional_arguments={
            "dump_last": BaseOptsType.options_t(
                False,
                ("CommLog",),
                ("--dump_last",),
                str,
                {
                    "help": "Dump the last comm.log session",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "dump_all": BaseOptsType.options_t(
                False,
                ("CommLog",),
                ("--dump_all",),
                str,
                {
                    "help": "Dump the last comm.log session",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "init_db": BaseOptsType.options_t(
                False,
                ("CommLog",),
                ("--init_db",),
                str,
                {
                    "help": "Initialize (entire) database and load sessions",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "rebuild_db": BaseOptsType.options_t(
                False,
                ("CommLog",),
                ("--rebuild_db",),
                str,
                {
                    "help": "Rebuild sessions database",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
        },
    )
    BaseLogger(base_opts)

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    comm_log_path = os.path.join(base_opts.mission_dir, "comm.log")
    if not os.path.exists(comm_log_path):
        log_error(f"{comm_log_path} does not exist")
        return 1

    (comm_log, _, session, _, _) = process_comm_log(comm_log_path, base_opts)

    if comm_log is None:
        log_error("Could not process comm.log")
        return 1

    if not base_opts.instrument_id:
        base_opts.instrument_id = comm_log.get_instrument_id()

    if base_opts.init_db or base_opts.rebuild_db:
        if base_opts.init_db:
            BaseDB.createDB(base_opts)
        else:
            BaseDB.prepCallsChangesFiles(base_opts)

        if not comm_log.sessions:
            print("No sessions")
        else:
            try:
                se = comm_log.sessions[-1]
                print(json.dumps(se.to_message_dict()))
            except Exception:
                log_error("Couldn't dump last session", "exc")

            print(f"{len(comm_log.sessions)} sessions")
            for session in comm_log.sessions:
                BaseDB.addSession(base_opts, session)
                if session.dive_num is not None and int(session.dive_num) > 0:
                    if session.call_cycle is None:
                        cmdname = f"cmdfile.{int(session.dive_num):04d}"
                    else:
                        cmdname = f"cmdfile.{int(session.dive_num):04d}.{int(session.call_cycle):04d}"

                    BaseDB.logParameterChanges(
                        base_opts, int(session.dive_num), cmdname
                    )

        BaseDB.rebuildControlHistory(base_opts)

    if base_opts.dump_last:
        if not comm_log.sessions:
            print("No sessions")
        else:
            comm_log.sessions[-1].dump_contents(sys.stdout)

    if base_opts.dump_all:
        for session in comm_log.sessions:
            session.dump_contents(sys.stdout)

    # for ii in range(len(comm_log.sessions)):
    #     for k in comm_log.sessions[ii].file_stats.keys():
    #         print(k, comm_log.sessions[ii].file_stats[k])

    # fragment_size_dict = comm_log.get_fragment_size_dict()
    # for kk, vv in fragment_size_dict.items():
    #     print(kk, vv)

    # (comm_log, start_pos, _, line_count) = process_comm_log(os.path.expanduser(args[0]), base_opts, scan_back=False)

    # if comm_log is None:
    #    return 1

    # print comm_log.predict_drift('ddmm')

    # log_info("Number of sessions %s" % str(len(comm_log.sessions)))
    # log_info("Next start position %d" % start_pos)
    # log_info("Number of lines %d" % line_count)
    # for fn in list(comm_log.sessions[-1].file_stats.keys()):
    #    log_info("%s:%s" % (fn, comm_log.sessions[-1].file_stats[fn]))

    return 0


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
