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


"""
Minimum package versions and common class definitions
"""

from enum import IntEnum

# These document file format versions
# All recorded as globals.file_version in their respective files
mission_profile_nc_fileversion = "2.71"
mission_timeseries_nc_fileversion = "2.71"
mission_per_dive_nc_fileversion = "2.71"
# These document level of functionality
basestation_version = "3.0.2"
quality_control_version = "1.12"

# The oldest format version this code supports
required_nc_fileversion = "2.7"  #  (August, 2011)

# Version stamps for various packages
required_python_version = (3, 10, 9)
recommended_python_version = (3, 10, 10)
required_numpy_version = "1.19.1"
recommended_numpy_version = "1.19.1"

required_scipy_version = "1.9.0"
recommended_scipy_version = "1.9.0"
# need at least 0.11.0 for proper sparse matrix support (scipy.sparse.diags)
required_scipy_sparse_version = "1.4.1"


# pylint: disable=E0239
class WhichHalf(IntEnum):
    """Used for various profile processing routines"""

    down = 1
    up = 2
    both = 3
    combine = 4


required_seawater_version = "3.3.4"
required_gsw_version = "3.3.1"

# Moved here from Base to allow other files to access without re-import of Base.py
known_files = [
    "cmdfile",
    "pdoscmds.bat",
    "targets",
    "science",
    "tcm2mat.cal",
    "rafos.dat",
    "nav1.dat",
    "nav0.scr",
    "nav1.scr",
]
known_mailer_tags = [
    "eng",
    "log",
    "asc",
    "cap",
    "comm",
    "dn_kkyy",
    "up_kkyy",
    "nc",
    "ncf",
    "ncfb",
    "ncdf",
    "mission_ts",
    "mission_pro",
    "bz2",
    "kml",
    "kmz",
]
known_ftp_tags = known_mailer_tags

# Flight model related - here to avoid circular ref during load
flight_variables = [
    "volmax",  # this is vehicle-specific; computed based on observed data over various dives
    "abs_compress",  # this can be vehicle-specific or dive-specific; compute mean based on observed data over various dives
    "hd_a",
    "hd_b",
    "vbdbias",  # these are dive-specific; computed based on observed dive data and assumed (a/b) over related dives
    "rho0",
    "glider_length",
    "hd_c",
    "hd_s",
    "therm_expan",
    "temp_ref",  # various constants based on vehicle type assumptions and calculations
]
ignore_tag = "FM_ignore"  # if we have already ignored the line, don't do it again (in case of copy)
ignore_tags = ["vbdbias_drift", "override."]  # other problem children
ignore_tags.extend(flight_variables)
