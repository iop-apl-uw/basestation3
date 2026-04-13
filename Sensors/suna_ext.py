#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2011, 2012, 2013, 2015, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 by University of Washington.  All rights reserved.
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
suna basestation sensor extension
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

    data_info = "suna_data_info"

    BaseNetCDF.register_sensor_dim_info(
        data_info,
        "suna_data_point",
        "suna_time",
        True,
        "suna",
    )

    meta_data_adds = {
        "suna": [
            False,
            "c",
            {
                #"long_name": "underway thermosalinograph",
                #"nodc_name": "thermosalinograph",
                #"make_model": "unpumped RBR Legato",
            },
            BaseNetCDF.nc_scalar,
        ],  # always scalar
        "suna_time": [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "legato time in GMT epoch format",
            },
            (data_info,),
        ],
        "suna_temperature": [
            "f",
            "d",
            {
                "standard_name": "sea_water_temperature",
                "units": "degrees_Celsius",
                "description": "Termperature (in situ) as reported by the instrument",
            },
            (data_info,),
        ],
        "suna_nitrate": [
            "f",
            "d",
            {
                "standard_name": "mole_concentration_of_nitrate_in_sea_water",
                #"units": "degrees_Celsius",
                # either mol m-3 or mmol m-3
                "description": "Concnetration of nitrate (in situ) as reported by the instrument",
            },
            (data_info,),
        ],
    }
    meta_data_adds |= Utils2.add_scicon_stats("suna")
    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}

    return 0


