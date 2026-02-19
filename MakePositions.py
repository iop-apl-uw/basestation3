#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025, 2026  University of Washington.
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


"""Extension for creating a text file containing glider positions from the comm.log"""

import os
import pathlib
import sys
import time

import BaseOpts
import CommLog
import Utils
from BaseLog import BaseLogger, log_critical, log_error, log_info


# pylint: disable=unused-argument
def main(
    instrument_id: int | None = None,
    base_opts: BaseOpts.BaseOptions | None = None,
    sg_calib_file_name: pathlib.Path | None = None,
    dive_nc_file_names: list[pathlib.Path] | None = None,
    nc_files_created: list[pathlib.Path] | None = None,
    processed_other_files: list[pathlib.Path] | None = None,
    known_mailer_tags: list[str] | None = None,
    known_ftp_tags: list[str] | None = None,
    processed_file_names: list[pathlib.Path] | None = None,
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

    (comm_log, _, _, _, _) = CommLog.process_comm_log(
        base_opts.mission_dir / "comm.log", base_opts
    )
    if comm_log is None:
        log_critical("Could not process comm.log -- bailing out")
        return 1

    txt_file_name: pathlib.Path = (
        base_opts.mission_dir / f"SG_{comm_log.get_instrument_id()}_positions.txt"
    )

    try:
        fo = txt_file_name.open("w")
    except Exception:
        log_error("Could not open %s" % txt_file_name, "exc")
        return 1

    predictedLat = predictedLon = predictedTime = None
    glider_predict_position_file = base_opts.mission_dir / "predict_position.txt"
    if glider_predict_position_file.is_file():
        try:
            with glider_predict_position_file.open(
                glider_predict_position_file, "r"
            ) as fi:
                # Expected - "gliderLat,glidertLon,predictedGliderTime\n"
                # header_line = fi.readline()
                splits = fi.readline().split(",")
                predictedTime = float(splits[2])
                predictedLat = float(splits[0])
                predictedLon = float(splits[1])
        except Exception:
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
            if predictedTime and predictedTime > time.mktime(this_fix.datetime):
                predicted_ts = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(predictedTime)
                )
                fo.write(
                    "%s,%.7f,%.7f,1\n" % (predicted_ts, predictedLat, predictedLon)
                )
            predictedTime = predictedLat = predictedLon = None
        except Exception:
            log_error("Could not process predicted time", "exc")

        try:
            this_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", this_fix.datetime)
            this_lat = Utils.ddmm2dd(this_fix.lat)
            this_lon = Utils.ddmm2dd(this_fix.lon)
            fo.write("%s,%.7f,%.7f,0\n" % (this_ts, this_lat, this_lon))
        except Exception:
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
