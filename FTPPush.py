#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006, 2007, 2009, 2012, 2013, 2015, 2016, 2020, 2021, 2022 by University of Washington.  All rights reserved.
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

"""Push batch of files to sites specified in .ftp
"""

import glob
import os
import sys
import time

import BaseDotFiles
import BaseOpts
import Globals
from BaseLog import BaseLogger, log_info, log_error



def process_ftp(
    base_opts,
    processed_file_names,
    mission_timeseries_name=None,
    mission_profile_name=None,
):
    """Process the .ftp file and push the data to a ftp server"""
    ftp_file_name = os.path.join(base_opts.mission_dir, ".ftp")
    if not os.path.exists(ftp_file_name):
        log_info("No .ftp file found - skipping .ftp processing")
        return

    log_info("Starting processing on .ftp")
    try:
        ftp_file = open(ftp_file_name, "r")
    except IOError as exception:
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
            except:
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
            "ftp_type": BaseOpts.options_t(
                "ftp",
                ("FTPPush",),
                ("--ftp_type",),
                str,
                {
                    "help": "Unix-style glob spec for files to push",
                    "choices": ("ftp", "sftp"),
                },
            ),
            "file_spec": BaseOpts.options_t(
                None,
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
        base_opts, files_to_send, None, None, Globals.known_ftp_tags, ftp_type=f".{base_opts.ftp_type}"
    )

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    return 0


if __name__ == "__main__":
    retval = main()
    sys.exit(retval)
