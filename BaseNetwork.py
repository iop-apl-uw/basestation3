#! /usr/bin/env python
# -*- python-fmt -*-
##
## Copyright (c) 2022 by University of Washington.  All rights reserved.
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
Processes network files
"""

import os
import pdb
import sys
import time
import traceback

from BaseLog import BaseLogger, log_error, log_info, log_critical
import BaseOpts
import Utils

DEBUG_PDB = "darwin" in sys.platform


def convert_network_logfile(in_file_name, out_file_name):
    """Converts a network log/eng file to text output

    Returns:
        0 - success
        1 - failure
    """

    convertor = "/usr/local/bin/log"

    if not os.path.isfile(convertor):
        log_error(
            "Convertor %s does not exits - not processing %s"
            % (convertor, in_file_name)
        )
        return 1

    if not os.access(convertor, os.X_OK):
        log_error(
            "Convertor (%s) is not marked as executable - not processing %s"
            % (convertor, in_file_name)
        )
        return 1

    cmdline = f"{convertor} {in_file_name}"
    log_info("Running %s" % cmdline)
    try:
        (sts, run_output) = Utils.run_cmd_shell(cmdline, timeout=10)
    except:
        log_error("Error running %s" % cmdline, "exc")
        return 1

    if sts is None:
        log_error(
            f"Error running {cmdline} - timeout", "exc", alert="CONVERSION_TIMEOUT"
        )
        return 1

    if sts >> 8:
        error = ""
        for l in run_output:
            error += l.decode()
        log_error(f"Error running {cmdline} - {error}")

        return 1

    try:
        fo = open(out_file_name, "wb")
    except:
        log_error(f"Failed to open {out_file_name}")
        return 1

    for l in run_output:
        fo.write(l)
    fo.close()

    return 0


def convert_network_profile(in_file_name, out_file_name):
    """Converts a network ct profile plain text output

    Returns:
        0 - success
        1 - failure
    """

    convertor = "/usr/local/bin/x3decode_ts"

    if not os.path.isfile(convertor):
        log_error(
            "Convertor %s does not exits - not processing %s"
            % (convertor, in_file_name)
        )
        return 1

    if not os.access(convertor, os.X_OK):
        log_error(
            "Convertor (%s) is not marked as executable - not processing %s"
            % (convertor, in_file_name)
        )
        return 1

    cmdline = "%s -i %s -o %s" % (convertor, in_file_name, out_file_name)
    log_info("Running %s" % cmdline)
    try:
        (sts, fo) = Utils.run_cmd_shell(cmdline, timeout=10)
    except:
        log_error("Error running %s" % cmdline, "exc")
        return 1

    if sts is None:
        log_error(
            f"Error running {cmdline} - timeout", "exc", alert="CONVERSION_TIMEOUT"
        )
        return 1

    if sts >> 8:
        error = ""
        for l in fo:
            error += l.decode()
        log_error(f"Error running {cmdline} - {error}")

        return 1

    return 0


def main():
    """cli test/utility for network file processing

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    # pylint: disable=unused-argument
    base_opts = BaseOpts.BaseOptions(
        "cmdline entry for basestation network file processing",
        additional_arguments={
            "networkfiles_action": BaseOpts.options_t(
                None,
                ("BaseNetwork",),
                ("networkfiles_action",),
                str,
                {
                    "help": "Which action to run",
                    "choices": ("log", "pro"),
                },
            ),
            "inp_file": BaseOpts.options_t(
                None,
                ("BaseNetwork",),
                ("inp_file",),
                str,
                {
                    "help": "Input file",
                    "action": BaseOpts.FullPathAction,
                },
            ),
            "out_file": BaseOpts.options_t(
                None,
                ("BaseNetwork",),
                ("out_file",),
                str,
                {
                    "help": "Output file",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )

    BaseLogger(base_opts, include_time=True)

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    ret_val = 0
    if base_opts.networkfiles_action == "log":
        ret_val = convert_network_logfile(base_opts.inp_file, base_opts.out_file)
    elif base_opts.networkfiles_action == "pro":
        ret_val = convert_network_profile(base_opts.inp_file, base_opts.out_file)

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    return ret_val


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        main()
    except SystemExit:
        pass
    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting", "exc")
