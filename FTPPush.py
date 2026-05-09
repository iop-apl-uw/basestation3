#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2025, 2026  University of Washington.
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

"""Push batch of files to sites specified in .ftp"""

import glob
import os
import sys
import time

import BaseDotFiles
import BaseOpts
import BaseOptsType
import Globals
from BaseLog import BaseLogger, log_error, log_info


def process_ftp(
    base_opts,
    processed_file_names,
    mission_timeseries_name=None,
    mission_profile_name=None,
):
    """Process the .ftp file and push the data to a ftp server"""
    ftp_file_name = base_opts.mission_dir / ".ftp"
    if not ftp_file_name.exixts():
        log_info("No .ftp file found - skipping .ftp processing")
        return

    log_info("Starting processing on .ftp")
    try:
        ftp_file = open(ftp_file_name, "r")
    except OSError as exception:
        log_error(
            "Could not open %s (%s) - no mail sent" % (ftp_file_name, exception.args)
        )
    else:
        for ftp_line in ftp_file:
            try:
                BaseDotFiles.process_ftp_line(
                    base_opts,
                    processed_file_names,
                    mission_timeseries_name,
                    mission_profile_name,
                    ftp_line,
                    Globals.known_ftp_tags,
                )
            except Exception:
                log_error("Could not process %s - skipping" % ftp_line, "exc")
    log_info("Finished processing on .ftp")


def main():
    """Basestation helper for pushing files

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    base_opts = BaseOpts.BaseOptions(
        "Basestation helper for pushing files",
        additional_arguments={
            "ftp_type": BaseOptsType.options_t(
                "ftp",
                ("FTPPush",),
                ("--ftp_type",),
                str,
                {
                    "help": "Unix-style glob spec for files to push",
                    "choices": ("ftp", "sftp"),
                },
            ),
            "file_spec": BaseOptsType.options_t(
                "",
                ("FTPPush",),
                ("file_spec",),
                str,
                {
                    "help": "Unix-style glob spec for files to push",
                },
            ),
        },
    )
    BaseLogger(base_opts)  # initializes BaseLog

    if not base_opts.mission_dir:
        log_error("mission_dir not defined")
        return 1

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    match_spec = os.path.join(base_opts.mission_dir, base_opts.file_spec)
    log_info(f"Match spec {match_spec}")
    files_to_send = []
    for m in glob.glob(match_spec):
        files_to_send.append(os.path.abspath(os.path.expanduser(m)))

    BaseDotFiles.process_ftp(
        base_opts,
        files_to_send,
        None,
        None,
        Globals.known_ftp_tags,
        ftp_type=f".{base_opts.ftp_type}",
    )

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    return 0


if __name__ == "__main__":
    retval = main()
    sys.exit(retval)
