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


"""Extension for creating a text file containing glider positions from the comm.log
"""

import sys
import os
import time

import BaseOpts
import CommLog
import Utils
from CalibConst import getSGCalibrationConstants
from BaseLog import BaseLogger, log_info, log_error, log_critical

# pylint: disable=unused-argument
def main(
    instrument_id=None,
    base_opts=None,
    sg_calib_file_name=None,
    dive_nc_file_names=None,
    nc_files_created=None,
    processed_other_files=None,
    known_mailer_tags=None,
    known_ftp_tags=None,
    processed_file_names=None,
):
    """Extension for creating a text file containing glider positions from the comm.log

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    if base_opts is None:
        base_opts = BaseOpts.BaseOptions(
            "Extension for creating a text file containing glider positions from the comm.log"
        )
    BaseLogger(base_opts)  # initializes BaseLog

    # processing_start_time = time.time()
    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if sg_calib_file_name is None:
        sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")

    # Read sg_calib_constants file
    calib_consts = getSGCalibrationConstants(sg_calib_file_name)
    if not calib_consts:
        log_error(
            "Could not process %s - skipping creation of txt file" % sg_calib_file_name
        )
        return 1

    (comm_log, _, _, _, _) = CommLog.process_comm_log(
        os.path.join(base_opts.mission_dir, "comm.log"), base_opts
    )
    if comm_log is None:
        log_critical("Could not process comm.log -- bailing out")
        return 1

    txt_file_name = os.path.join(
        base_opts.mission_dir, "SG_%s_positions.txt" % comm_log.get_instrument_id()
    )

    try:
        fo = open(txt_file_name, "w")
    except:
        log_error("Could not open %s" % txt_file_name, "exc")
        return 1

    predictedLat = predictedLon = predictedTime = None
    glider_predict_position_file = os.path.join(
        base_opts.mission_dir, "predict_position.txt"
    )
    if os.path.isfile(glider_predict_position_file):
        try:
            fi = open(glider_predict_position_file, "r")
            # Expected - "gliderLat,glidertLon,predictedGliderTime\n"
            # header_line = fi.readline()
            splits = fi.readline().split(",")
            predictedTime = float(splits[2])
            predictedLat = float(splits[0])
            predictedLon = float(splits[1])
            fi.close()
            del fi
        except:
            log_error("Unable to read %s" % glider_predict_position_file, "exc")
            glider_predict_position_file = None

    fo.write("%Fixtime,Latitude,Longitude,IsEstimate\n")

    for session in reversed(comm_log.sessions):
        this_fix = session.gps_fix
        if (
            this_fix is None
            or this_fix.lat is None
            or this_fix.lon is None
            or this_fix.datetime is None
        ):
            continue
        try:
            if predictedTime:
                if predictedTime > time.mktime(this_fix.datetime):
                    predicted_ts = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(predictedTime)
                    )
                    fo.write(
                        "%s,%.7f,%.7f,1\n" % (predicted_ts, predictedLat, predictedLon)
                    )
            predictedTime = predictedLat = predictedLon = None
        except:
            log_error("Could not process predicted time", "exc")

        try:
            this_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", this_fix.datetime)
            this_lat = Utils.ddmm2dd(this_fix.lat)
            this_lon = Utils.ddmm2dd(this_fix.lon)
            fo.write("%s,%.7f,%.7f,0\n" % (this_ts, this_lat, this_lon))
        except:
            log_error("Could not process session", "exc")
            continue

    fo.close()

    if processed_other_files is not None:
        processed_other_files.append(txt_file_name)
        if glider_predict_position_file:
            processed_other_files.append(glider_predict_position_file)

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
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
