#! /usr/bin/env python

##
## Copyright (c) 2006, 2007, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2020 by University of Washington.  All rights reserved.
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

"""Routines for creating plots that span multiple dives
"""

import sys
import os
from scipy.io import netcdf
from numpy import *
import time
import glob
import BaseOpts
from BaseLog import *
import CommLog
import FileMgr
from CalibConst import getSGCalibrationConstants
import MakeDiveProfiles
import BaseGZip
import Utils
import PlotUtils
import string


def main(instrument_id=None, base_opts=None, sg_calib_file_name=None, dive_nc_file_names=None, nc_files_created=None,
         processed_other_files=None, known_mailer_tags=None, known_ftp_tags=None):
    """Command line app for creating an text containing glider positions from the comm.log (and possible future positions)

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    if(base_opts is None):
        base_opts = BaseOpts.BaseOptions(sys.argv, 'k',
                                         usage="%prog [Options] ")
    BaseLogger("MakePositions", base_opts) # initializes BaseLog

    if(not base_opts.mission_dir):
        print((main.__doc__))
        return 1

    processing_start_time = time.time()
    log_info("Started processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

    if(sg_calib_file_name is None):
        sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")

    # Read sg_calib_constants file
    calib_consts = getSGCalibrationConstants(sg_calib_file_name)
    if(not calib_consts):
        log_error("Could not process %s - skipping creation of txt file" % sg_calib_file_name)
        return 1

    (comm_log, _, _, _) = CommLog.process_comm_log(os.path.join(base_opts.mission_dir, 'comm.log'), base_opts)
    if(comm_log is None):
        log_critical("Could not process comm.log -- bailing out")
        return 1

    txt_file_name = os.path.join(base_opts.mission_dir, "sg%s_positions.txt" % comm_log.get_instrument_id())
    
    try:
        fo = open(txt_file_name, "w")
    except:
        log_error("Could not open %s" % txt_file_name, 'exc')
        return 1

    predictedLat = predictedLon = predictedTime = None
    glider_predict_position_file = os.path.join(base_opts.mission_dir, "predict_position.txt")
    if os.path.isfile(glider_predict_position_file) :
        try:
            fi = open(glider_predict_position_file, "r")
            # Expected - "gliderLat,glidertLon,predictedGliderTime\n"
            header_line = fi.readline()
            splits = fi.readline().split(',')
            predictedTime = float(splits[2])
            predictedLat = float(splits[0])
            predictedLon = float(splits[1])
            fi.close()
            del fi
        except:
            log_error("Unable to read %s" % glider_predict_position_file, 'exc')
            glider_predict_position_file = None

    fo.write("Fixtime\tLatitude\tLongitude\tIsEstimate\n")

    for session in reversed(comm_log.sessions):
        this_fix = session.gps_fix
        if this_fix is None or this_fix.lat is None or this_fix.lon is None or this_fix.datetime is None:
            continue
        try:
            if predictedTime:
                if predictedTime > time.mktime(this_fix.datetime):
                    predicted_ts = time.strftime("%Y/%m/%d %H:%M:%S", time.gmtime(predictedTime))
                    fo.write("%s UTC\t%.7f\t%.7f\t1\n" % (predicted_ts, predictedLat, predictedLon))
            predictedTime = predictedLat = predictedLong = None
        except:
            log_error("Could not process predicted time", 'exc')
            
        try:
            this_ts = time.strftime("%Y/%m/%d %H:%M:%S", this_fix.datetime)
            this_lat = Utils.ddmm2dd(this_fix.lat)
            this_lon = Utils.ddmm2dd(this_fix.lon)
            fo.write("%s UTC\t%.7f\t%.7f\t0\n" % (this_ts, this_lat, this_lon))
        except:
            log_error("Could not process session", 'exc')
            continue
        
    fo.close()
                 
    if(processed_other_files is not None):
        processed_other_files.append(txt_file_name)
        if glider_predict_position_file:
            processed_other_files.append(glider_predict_position_file)

    return 0

if __name__ == "__main__":
    import time, sys, os.path

    retval = 1

    # Force to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()

    try:
        retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
