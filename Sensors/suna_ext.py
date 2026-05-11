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
                "long_name": "Seabird Deep SUNA",
                "make_model": "SUNA Nitrate Sensor",
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
        "suna_nitrate": [
            "f",
            "d",
            {
                "standard_name": "mole_concentration_of_nitrate_in_sea_water",
                "units": "mmol m-3",
                "description": "Concentration of nitrate (in situ) as reported by the instrument",
            },
            (data_info,),
        ],
        "suna_sample_counter": [
            "f",
            "d",
            {"units": "", "description": "Sample number"},
            (data_info,),
        ],
        "suna_power_cycle_counter": [
            "f",
            "d",
            {"units": "", "description": "Number of power cycles since last reset"},
            (data_info,),
        ],
        "suna_error_counter": [
            "f",
            "d",
            {"units": "", "description": "Number of errors since last reset"},
            (data_info,),
        ],
        "suna_int_temp": [
            "f",
            "d",
            {"units": "degrees_Celsius", "description": "Internal temperature of SUNA"},
            (data_info,),
        ],
        "suna_int_humidity": [
            "f",
            "d",
            {"units": "percent", "description": "Internal relative humidity"},
            (data_info,),
        ],
        "suna_supply_V": [
            "f",
            "d",
            {"units": "Volts", "description": "Supply voltage"},
            (data_info,),
        ],
        "suna_supply_I": [
            "f",
            "d",
            {"units": "Amps", "description": "Supply current"},
            (data_info,),
        ],
        "suna_ref_detector_mean": [
            "f",
            "d",
            {"units": "counts", "description": "Mean of reference detector"},
            (data_info,),
        ],
        "suna_ref_detector_std": [
            "f",
            "d",
            {
                "units": "counts",
                "description": "Standard deviation of reference detector",
            },
            (data_info,),
        ],
        "suna_dark_spectrum_mean": [
            "f",
            "d",
            {"units": "counts", "description": "Mean of dark spectrum"},
            (data_info,),
        ],
        "suna_dark_spectrum_std": [
            "f",
            "d",
            {"units": "counts", "description": "Standard deviation of dark spectrum"},
            (data_info,),
        ],
        "suna_absorbance_fit_residual_rms": [
            "f",
            "d",
            {"units": "", "description": "Absorbance fit residual rms"},
            (data_info,),
        ],
        "suna_output_pixel_begin": [
            "f",
            "d",
            {"units": "", "description": "Index of first channel of output spectrum"},
            (data_info,),
        ],
        "suna_output_pixel_end": [
            "f",
            "d",
            {"units": "", "description": "Index of last channel of output spectrum"},
            (data_info,),
        ],
        "suna_seawater_dark": [
            "f",
            "d",
            {"units": "counts", "description": "Mean of Channels 1 to 5"},
            (data_info,),
        ],
    }
    meta_data_adds |= Utils2.add_scicon_stats("suna")
    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}

    return 0
