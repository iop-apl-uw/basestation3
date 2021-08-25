#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2021 by University of Washington.  All rights reserved.
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

"""Contains all routines for extracting data from a glider's comm logfile.
"""

import sys
import time

import Utils
from BaseLog import log_error, log_debug, log_info

#
# Optional components
#

def is_valid_gps_line(gps_line):
    """Determines is a line is a valid GPS line

    Valid formats:
    >>> is_valid_gps_line("GPS,260506,151750,4807.211,-12223.095,34,1.1,34,18.0")
    1

    returns 1 if the line is a valid GPS line, 0 if not
    """
    gps_fields = gps_line.split(",")
    if(gps_fields[0] == "GPS" or gps_fields[0] == "$GPS"
       or gps_fields[0] == "$GPS1" or gps_fields[0] == "$GPS2"):
        # The form in the comm log
        return 1

    log_error("Bad GPS line " + gps_line)
    return 0

class GPSFix:
    """A wrapper for a single GPS fix
    """

    def __init__(self, gps_line, start_date_str='01 01 70'):
        """Requires a valid gps_line, from which we parse date and time.

        start_date_str, if provided and needed, should be of the form %m %d %y
        Default to start of UNIX epoch if none given.  Happens for very old GPS failures that left the following in comm.log:
           GPS,,,0.000,0.000,901,99.0,901,0.0

        >>> g = GPSFix("GPS,260506,151750,4807.211,-12223.095,34,1.1,34,18.0")
        """
        log_debug("GPS line = " + gps_line)

        self.raw_line = gps_line

        if is_valid_gps_line(gps_line):
            gps_fields = gps_line.split(",")

            self.isvalid         = True
            self.lat             = None
            self.lon             = None
            self.first_fix_time  = None
            self.hdop            = None
            self.final_fix_time  = None
            self.magvar          = None

            self.drift_speed   = -1
            self.drift_heading = -1
            self.n_satellites  = -1
            self.HPE           = -1

            if(((gps_fields[0] == "GPS" or gps_fields[0] == "$GPS") and len(gps_fields) >= 6)
               or ((gps_fields[0] == "$GPS1" or gps_fields[0] == "$GPS2") and len(gps_fields) >= 9)):
                if(gps_fields[1] != "" and gps_fields[2] != ""):
                    try:
                        self.datetime = Utils.fix_gps_rollover(time.strptime(gps_fields[1]+gps_fields[2][:6], "%d%m%y%H%M%S"))
                        log_debug("GPS = %f (%s)" % (time.mktime(self.datetime), self.datetime))
                    except:
                        self.datetime = None
                        log_error("Could not process %s" % gps_fields[1]+gps_fields[2], 'exc')
                else:
                    # This happens with old tank dives when we can't get a good GPS fix
                    # Make up something plausible

                    # Also happens in some RevE code
                    start_datetime = time.strptime(start_date_str, "%m %d %y")
                    start_datetag = "%02d%02d%03d" % (start_datetime.tm_mday, start_datetime.tm_mon, start_datetime.tm_year)
                    if gps_fields[0] == "$GPS1":
                        start_datetag = "%s000000" % start_datetag # dive starts at midnight
                    elif gps_fields[0] == "$GPS2":
                        start_datetag = "%s001500" % start_datetag # 15 minutes later
                    else: # GPS
                        start_datetag = "%s010000" % start_datetag # 45 minutes later at 1am
                    self.datetime = time.strptime(start_datetag, "%d%m%Y%H%M%S")
                    # deliberately report in raw_line format so you can edit the log file if this was a tank dive...
                    log_info("No datetime for %s; assuming %s" % (gps_fields[0], time.strftime("%m%d%y,%H%M%S", self.datetime)))
                try:
                    if len(gps_fields) == 7:
                        # This is from a SMS message
                        self.lat             = float(gps_fields[3])
                        self.lon             = float(gps_fields[4])
                        self.hdop            = float(gps_fields[5])
                        self.final_fix_time  = float(gps_fields[6])
                    else:
                        self.lat             = float(gps_fields[3])
                        self.lon             = float(gps_fields[4])
                        self.first_fix_time  = float(gps_fields[5])
                        self.hdop            = float(gps_fields[6])
                        self.final_fix_time  = float(gps_fields[7])
                        self.magvar          = float(gps_fields[8])
                        try:
                            # As of August, 2014 we report this additional data
                            #  9 - drift speed (m/s)
                            # 10 - drift heading (degrees true)
                            # 11 - number of satellites
                            # 12 - horizontal prediction of error (m)
                            self.drift_speed   = float(gps_fields[9])
                            self.drift_heading = float(gps_fields[10])
                            self.n_satellites  = int(gps_fields[11])
                            self.HPE           = float(gps_fields[12])
                        except (ValueError, IndexError):
                            pass # old GPS string
                except ValueError:
                    log_error("Invalid GPS line (%s) (%s)" % (gps_line, gps_fields), 'exc')
                    self.isvalid = False

            elif(gps_fields[0] == "$GPS1" or gps_fields[0] == "$GPS2" and len(gps_fields) >= 6):
                log_debug("%s,%s,%s" % (gps_fields[0], gps_fields[1], start_date_str))
                try:
                    self.datetime = Utils.fix_gps_rollover(time.strptime(gps_fields[1] + start_date_str, "%H%M%S%m %d %y"))
                    self.lat             = float(gps_fields[2])
                    self.lon             = float(gps_fields[3])
                    self.first_fix_time  = int(gps_fields[4])
                    self.hdop            = float(gps_fields[5])
                    self.final_fix_time  = int(gps_fields[6])
                    if gps_fields[0] == "$GPS2":
                        self.magvar      = float(gps_fields[7])
                    else:
                        self.magvar      = None
                except ValueError:
                    log_error("Invalid GPS line (%s) (%s)" % (gps_line, gps_fields), 'exc')
                    self.isvalid = False
            else:
                log_error("Invalid GPS (%s)" % gps_line)
                print("Invalid GPS (%s)" % gps_line)
                self.isvalid = False

        else:
            log_error("Invalid GPS (%s)" % gps_line)
            print("Invalid GPS (%s)" % gps_line)
            self.isvalid = False

    def dump(self, fo=sys.stdout):
        """ Prints out a GPS object in readable format
        """
        if self.isvalid:
            print("  DateTime %s" % time.strftime("%m %d %y %H:%M:%S", self.datetime), file=fo)
            print("       Lat %f" % self.lat, file=fo)
            print("       Lat %f" % self.lon, file=fo)
            print(" First Fix %d" % self.first_fix_time, file=fo)
            print(" HDOP      %f" % self.hdop, file=fo)
            print(" HPE       %f" % self.HPE, file=fo)
            print(" Final Fix %d" % self.final_fix_time, file=fo)
            if self.magvar:
                print("   Mag Var %f" % self.magvar, file=fo)
        else:
            print("Invalid GPS fix", file=fo)


# if __name__ == '__main__':
#     import doctest
#     import sys

#     # Force time and date to be in UTC
#     os.environ['TZ'] = 'UTC'
#     time.tzset()


#     base_opts = BaseOpts.BaseOptions(sys.argv)
#     BaseLogger("DataFiles", base_opts) # initializes BaseLog
#     log_info("performing testmod")

#     doctest.testmod(sys.modules[__name__])
