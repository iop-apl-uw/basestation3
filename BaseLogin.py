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

"""Items to be done at glider login time"""

import os
import sys
import time

import BaseOpts
import Sensors
from Base import run_extension_script
from BaseDotFiles import process_extensions
from BaseLog import BaseLogger, log_error, log_info, log_warning


def main():
    """Basestation script invoked at glider login time

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    ret_val = 0

    base_opts = BaseOpts.BaseOptions("Basestation script invoked at glider login time")
    BaseLogger(base_opts, include_time=True)  # initializes BaseLog

    # log_info("Started processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Run early enough to get into the upload list
    run_extension_script(base_opts.mission_dir / ".pre_login", None)

    # Invoke extensions, if any
    process_extensions(
        ("prelogin",),
        base_opts,
    )

    existing_files = "{"
    base_files = {
        "targets": "T",
        "science": "S",
        "pdoscmds.bat": "P",
        "tcm2mat.cal": "M",
        "rafos.dat": "R",
        "nav1.dat": "r",
        "nav0.scr": "N",
        "nav1.scr": "n",
    }
    for f in list(base_files.keys()):
        if (base_opts.mission_dir / f).exists():
            existing_files = "%s%s" % (existing_files, base_files[f])

    # Now, the loggers
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if "known_files" in d:
            for b in d["known_files"]:
                if (base_opts.mission_dir / b).exists():
                    existing_files = "%s,%s" % (existing_files, b)

    existing_files = "%s}" % existing_files

    log_info("Existing files = %s" % existing_files)

    upload_files_name = base_opts.mission_dir / "upload_files"

    try:
        fo = open(upload_files_name, "w")
    except Exception:
        log_error("Unable to open %s for write" % upload_files_name)
        ret_val = 1
    else:
        fo.write('echo "%s"\n' % existing_files)
        fo.close()

    # log_info("Finished processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

    return ret_val


if __name__ == "__main__":
    os.environ["TZ"] = "UTC"
    time.tzset()

    retval = main()
    sys.exit(retval)
