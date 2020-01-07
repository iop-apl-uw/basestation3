#! /usr/bin/env python

##
## Copyright (c) 2006, 2007, 2011, 2012, 2015, 2019, 2020 by University of Washington.  All rights reserved.
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
BaseTime.py: Contains all routines for handling time conversions

"""
from datetime import tzinfo, timedelta, datetime
from BaseLog import *

ZERO = timedelta(0)
HOUR = timedelta(hours=1)

# A UTC class.

class UTC(tzinfo):
    """UTC"""

    def utcoffset(self, dt):
        return ZERO

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return ZERO

utc = UTC()

# A class building tzinfo objects for fixed-offset time zones.
# Note that FixedOffset(0, "UTC") is a different way to build a
# UTC tzinfo object.

class FixedOffset(tzinfo):
    """Fixed offset in minutes east from UTC."""

    def __init__(self, offset, name):
        self.__offset = timedelta(minutes = offset)
        self.__name = name

    def utcoffset(self, dt):
        return self.__offset

    def tzname(self, dt):
        return self.__name

    def dst(self, dt):
        return ZERO

# A class capturing the platform's idea of local time.

import time as _time

STDOFFSET = timedelta(seconds = -_time.timezone)
if _time.daylight:
    DSTOFFSET = timedelta(seconds = -_time.altzone)
else:
    DSTOFFSET = STDOFFSET

DSTDIFF = DSTOFFSET - STDOFFSET

class LocalTimezone(tzinfo):

    def utcoffset(self, dt):
        if self._isdst(dt):
            return DSTOFFSET
        else:
            return STDOFFSET

    def dst(self, dt):
        if self._isdst(dt):
            return DSTDIFF
        else:
            return ZERO

    def tzname(self, dt):
        return _time.tzname[self._isdst(dt)]

    def _isdst(self, dt):
        tt = (dt.year, dt.month, dt.day,
              dt.hour, dt.minute, dt.second,
              dt.weekday(), 0, -1)
        stamp = _time.mktime(tt)
        tt = _time.localtime(stamp)
        return tt.tm_isdst > 0

Local = LocalTimezone()


# A complete implementation of current DST rules for major US time zones.

def first_sunday_on_or_after(dt):
    days_to_go = 6 - dt.weekday()
    if days_to_go:
        dt += timedelta(days_to_go)
    return dt

# In the US, DST starts at 2am (standard time) on the first Sunday in April.
DSTSTART = datetime(1, 4, 1, 2)
# and ends at 2am (DST time; 1am standard time) on the last Sunday of Oct.
# which is the first Sunday on or after Oct 25.
DSTEND = datetime(1, 10, 25, 1)

class USTimeZone(tzinfo):

    def __init__(self, hours, reprname, stdname, dstname):
        self.stdoffset = timedelta(hours=hours)
        self.reprname = reprname
        self.stdname = stdname
        self.dstname = dstname

    def __repr__(self):
        return self.reprname

    def tzname(self, dt):
        if self.dst(dt):
            return self.dstname
        else:
            return self.stdname

    def utcoffset(self, dt):
        return self.stdoffset + self.dst(dt)

    def dst(self, dt):
        if dt is None or dt.tzinfo is None:
            # An exception may be sensible here, in one or both cases.
            # It depends on how you want to treat them.  The default
            # fromutc() implementation (called by the default astimezone()
            # implementation) passes a datetime with dt.tzinfo is self.
            return ZERO
        assert dt.tzinfo is self

        # If there is no DST name specified, then the timezone doesn't have
        # DST
        if(self.dstname is None):
            return ZERO
        else:
            # TODO - need to figure if we are looking at the old or new
            # way to calculate DST

            # New way
            # Find first Sunday in April & the last in October.
            start = first_sunday_on_or_after(DSTSTART.replace(year=dt.year))
            end = first_sunday_on_or_after(DSTEND.replace(year=dt.year))

            # Can't compare naive to aware objects, so strip the timezone from
            # dt first.
            if start <= dt.replace(tzinfo=None) < end:
                return HOUR
            else:
                return ZERO

Eastern  = USTimeZone(-5, "Eastern",  "EST", "EDT")
Central  = USTimeZone(-6, "Central",  "CST", "CDT")
Mountain = USTimeZone(-7, "Mountain", "MST", "MDT")
Pacific  = USTimeZone(-8, "Pacific",  "PST", "PDT")
Hawaii = USTimeZone(-10, "Hawaii", "HST", None)
NewZealand = USTimeZone(13, "NewZeland", "NZST", "NZDT")
UTC = USTimeZone(0, "Greenwich", "UTC", None)

tz_lookup = {
    'EST' : Eastern, 'EDT' : Eastern,
    'CST' : Central, 'CDT' : Central,
    'MST' : Mountain, 'MDT' : Mountain,
    'PST' : Pacific, 'PDT' : Pacific,
    'HST' : Hawaii,
    'NZST': NewZealand, 'NZDT' : NewZealand,
    'UTC' : UTC,
    'GMT' : UTC
    }

def convert_commline_to_utc(ts_string, time_zone):
    '''Given a entry from the comm.log of the form

    %a %b %d %H:%M:%S %Y

    and a specified time zone, as a string, this routine will
    convert that line to a time_struc in utc
    '''

    import time
    import datetime

    loc_t = time.strptime(ts_string, "%a %b %d %H:%M:%S %Y")
    try:
        t_zone = tz_lookup[time_zone.upper()]
    except:
        log_error("Unknown timezone %s - assuming UTC" % time_zone, max_count=5)
        t_zone = tz_lookup['UTC']

    ts = datetime.datetime(loc_t.tm_year, loc_t.tm_mon, loc_t.tm_mday, loc_t.tm_hour, loc_t.tm_min, loc_t.tm_sec, tzinfo=t_zone)
    return ts.utctimetuple()
    
if __name__ == "__main__":
    import os
    import time
    # Force time and date to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()

    base_opts = BaseOpts.BaseOptions(sys.argv)
    BaseLogger("BaseTime", base_opts) # initializes BaseLog
    args = BaseOpts.BaseOptions._args # positional arguments

    ts_string = "Mon Jan 4 12:59:13 2007"
    time_zone = 'FOO'
    ts = convert_commline_to_utc(ts_string, time_zone)
    print(("%s %s" % (ts_string, time_zone)))
    print((time.strftime("%a %b %d %H:%M:%S %Y %Z", ts)))
