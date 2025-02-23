#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2023, 2025 by University of Washington.  All rights reserved.
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
Rockland Micropod logdev basestation sensor extension
"""

import os
import shutil

import BaseNetCDF
import Strip1A
from BaseLog import log_error


def init_logger(module_name, init_dict=None):
    """
    init_loggers

    returns:
    -1 - error in processing
     0 - success (data found and processed)
    """
    if init_dict is None:
        log_error("No datafile supplied for init_loggers - version mismatch?")
        return -1

    # results are computed in MDP
    init_dict[module_name] = {
        "logger_prefix": "rs",
        "netcdf_metadata_adds": {
            "log_RS_RECORDABOVE": [
                False,
                "d",
                {
                    "description": "Depth above above which data is recorded",
                    "units": "meters",
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RS_PROFILE": [
                False,
                "d",
                {
                    "description": "Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RS_XMITPROFILE": [
                False,
                "d",
                {
                    "description": "Which profile to transmit back to the basestation - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RS_UPLOADMAX": [
                False,
                "d",
                {"description": "Max size in bytes to uplaod to the basestation"},
                BaseNetCDF.nc_scalar,
            ],
            "log_RS_STARTS": [False, "d", {}, BaseNetCDF.nc_scalar],
            "log_RS_NDIVE": [False, "d", {}, BaseNetCDF.nc_scalar],
        },
    }

    return 1


def process_data_files(
    base_opts,
    module_name,
    calib_consts,
    fc,
    processed_logger_eng_files,
    processed_logger_other_files,
):
    """Processes other files

    Returns:
        0 - success
        1 - failure
    """

    if fc.is_down_data() or fc.is_up_data():
        root, ext = os.path.splitext(fc.full_filename())
        fragment_1a = root + ".1a" + ext
        ret_val = Strip1A.strip1A(fc.full_filename(), fragment_1a)
        if ret_val:
            log_error("Couldn't strip1a %s" % fc.full_filename())
            shutil.move(fc.full_filename(), fc.mk_base_datfile_name())
        else:
            shutil.move(fragment_1a, fc.mk_base_datfile_name())

        return ret_val
    else:
        log_error(
            "Don't know how to deal with Rockand Micropod file (%s)"
            % fc.full_filename()
        )
        return 1
