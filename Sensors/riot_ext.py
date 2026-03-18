#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2010, 2011, 2012, 2013, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2025, 2026 by University of Washington.  All rights reserved.
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
RIOT basestation extension
"""

import pathlib
import shutil

import BaseNetCDF
from BaseLog import log_debug, log_error, log_info

# Globals
ri_prefix = "ri"


def init_logger(module_name, init_dict=None):
    """
    init_logger
    Input:
         module_name - fully qualified path to the name of this module

    Returns:
        -1 - error in processing
        0 - success (data found and processed)
    """

    log_debug(f"module_name:{module_name}")

    if init_dict is None:
        log_error("No datafile supplied for init_loggers - version mismatch?")
        return -1

    init_dict[module_name] = {
        "logger_prefix": ri_prefix,
        "known_files": ["atm.cfg", "riot.cfg", "rtcc.cfg"],
        "netcdf_metadata_adds": {
            "log_RI_RECORDABOVE": [
                False,
                "d",
                {
                    "description": "Depth above above which data is recorded",
                    "units": "meters",
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RI_PROFILE": [
                False,
                "d",
                {
                    "description": "Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RI_XMITPROFILE": [
                False,
                "d",
                {
                    "description": "Which profile to transmit back to the basestation - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RI_UPLOADMAX": [
                False,
                "d",
                {"description": "Max size of file to upload"},
                BaseNetCDF.nc_scalar,
            ],
            "log_RI_FREE": [
                False,
                "d",
                {"description": "Free diskspace on CP, in bytes"},
                BaseNetCDF.nc_scalar,
            ],
            "log_RI_STARTS": [
                False,
                "d",
                {"description": "Number of times instrument was started"},
                BaseNetCDF.nc_scalar,
            ],
            "log_RI_NDIVE": [
                False,
                "d",
                {"description": "Instrumet active every nth dive"},
                BaseNetCDF.nc_scalar,
            ],
        },
    }

    return 0


# pylint: disable=unused-argument
def process_data_files(
    base_opts,
    modules_name,
    calib_consts,
    fc,
    processed_logger_eng_files,
    processed_logger_other_files,
):
    """Processes other files
    Input:
        base_opts - options object
        calib_conts - calibration consts dict
        fc - file code object for file being processed
        processed_logger_eng_files - list of eng files to add to
        processed_logger_other_files - list of other processed files to add to

    Returns:
        0 - success
        1 - failure
    """

    if fc.is_down_data() or fc.is_up_data():
        dst_file = pathlib.Path(fc.mk_base_engfile_name()).with_suffix(".csv")
        log_info(f"Processing {fc.full_filename()} to {dst_file}")
        # Copy to the correct extension
        shutil.copy(fc.full_filename(), dst_file)
        processed_logger_other_files.append(dst_file)
    return 0


# pylint: disable=unused-argument
