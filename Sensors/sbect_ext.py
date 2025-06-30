#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2011, 2012, 2013, 2015, 2019, 2021, 2023, 2025 by University of Washington.  All rights reserved.
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
sbect basestation sensor extension
"""

import BaseNetCDF
import Utils2
from BaseLog import log_error


def init_sensor(module_name, init_dict=None):
    """
    init_sensor

    Returns:
        -1 - error in processing
         0 - success (data found and processed)
    """

    if init_dict is None:
        log_error("No datafile supplied for init_sensors - version mismatch?")
        return -1

    BaseNetCDF.register_sensor_dim_info(
        BaseNetCDF.nc_sbect_data_info, "sbect_data_point", "sbect_time", True, "sbe41"
    )
    # results are computed in MDP
    init_dict[module_name] = {
        "netcdf_metadata_adds": {
            "sbe41": [
                False,
                "c",
                {
                    "long_name": "underway thermosalinograph",
                    "nodc_name": "thermosalinograph",
                    "make_model": "unpumped Seabird SBE41",
                },
                BaseNetCDF.nc_scalar,
            ],  # always scalar
            # TODO do we want to include these in MMP/MMT? NO, because there is derived data instead
            # add 'As reported by instrument'?
            # add 'comment':'Values are reported freqences'
            # standard unpumped CT in eng file
            "eng_condFreq": [
                False,
                "d",
                {"description": "As reported by the instrument", "instrument": "sbe41"},
                (BaseNetCDF.nc_sg_data_info,),
            ],
            "eng_tempFreq": [
                False,
                "d",
                {"description": "As reported by the instrument", "instrument": "sbe41"},
                (BaseNetCDF.nc_sg_data_info,),
            ],
            # SailCT in eng file (only a few missions, rarely used. now part of scicon)
            "eng_sbect_condFreq": [
                False,
                "d",
                {"description": "As reported by the instrument", "instrument": "sbe41"},
                (BaseNetCDF.nc_sg_data_info,),
            ],
            "eng_sbect_tempFreq": [
                False,
                "d",
                {"description": "As reported by the instrument", "instrument": "sbe41"},
                (BaseNetCDF.nc_sg_data_info,),
            ],
            # SailCT via scicon
            "sbect_time": [
                True,
                "d",
                {
                    "standard_name": "time",
                    "units": "seconds since 1970-1-1 00:00:00",
                    "description": "sbe41 time in GMT epoch format",
                },
                (BaseNetCDF.nc_sbect_data_info,),
            ],
            "sbect_condFreq": [
                False,
                "d",
                {"description": "As reported by the instrument"},
                (BaseNetCDF.nc_sbect_data_info,),
            ],
            "sbect_tempFreq": [
                False,
                "d",
                {"description": "As reported by the instrument"},
                (BaseNetCDF.nc_sbect_data_info,),
            ],
            # gpctd (pumped sbect) variables are declared in Sensors/payload_ext.py
            # derived results from CT are declared in BaseNetCDF.py
        }
    }

    init_dict[module_name]["netcdf_metadata_adds"] |= Utils2.add_scicon_stats("sbect")

    return 0


# pylint: disable=unused-argument
def asc2eng(base_opts, module_name, datafile=None):
    """
    Asc2eng processor

    returns:
    -1 - error in processing
     0 - success (data found and processed)
     1 - no data found to process
    """

    if datafile is None:
        log_error("No datafile supplied for asc2eng conversion - version mismatch?")
        return -1

    #  TT8 freq counting algorithm uses a 4Mhz clock source which increments a
    #  counter. Counting is enabled by the first positive edge of the signal to
    #  be measured.  255 positive edges are counted or 255 cycles of the signal are
    #  measured with the 4Mhz clock.

    # Thus the values of raw data for conductivity, temperature, and oxygen are in units
    # of 4MHz.  255 cycles and 24bit counter permit measured frequencies 2-7kHz.

    # From first basestation code:
    #   We have observed conductivity readings of zero, which crashes the script
    #   Current theory is that they are caused by a bubble in the sensor.
    #
    #   We change those values to a small (and distinctive) value so they are clear but benign
    #   Changing to small value make the range nonsense.  Duplicate last non-zero value

    is_scct = False

    # Seabird CT - old name
    sbect_condFreq = datafile.remove_col("CondFreq")
    sbect_tempFreq = datafile.remove_col("TempFreq")

    # Seabird CT - new name
    if sbect_condFreq is None:
        sbect_condFreq = datafile.remove_col("sbect.CondFreq")
        sbect_tempFreq = datafile.remove_col("sbect.TempFreq")

    # iRobot latest naming scheme
    if sbect_condFreq is None:
        sbect_condFreq = datafile.remove_col_regex("sbect[0-9][0-9][0-9].CondFreq")
        sbect_tempFreq = datafile.remove_col_regex("sbect[0-9][0-9][0-9].TempFreq")

    # SCCT - Scicon used as pass through for CT
    if sbect_condFreq is None:
        sbect_condFreq = datafile.remove_col("scct.condFreq")
        sbect_tempFreq = datafile.remove_col("scct.tempFreq")
        is_scct = True

    if sbect_condFreq is not None:
        # Rev E (67.00 and later) - just divide by 1000.
        if datafile.version >= 67.0 or is_scct:
            sbect_condFreq = sbect_condFreq / 1000.0
            sbect_tempFreq = sbect_tempFreq / 1000.0
        else:
            sbect_condFreq = 4000000.0 / (sbect_condFreq / 255.0)
            sbect_tempFreq = 4000000.0 / (sbect_tempFreq / 255.0)

        datafile.eng_cols.append("sbect.condFreq")
        datafile.eng_cols.append("sbect.tempFreq")

        datafile.eng_dict["sbect.condFreq"] = sbect_condFreq
        datafile.eng_dict["sbect.tempFreq"] = sbect_tempFreq
        return 0

    return 1
