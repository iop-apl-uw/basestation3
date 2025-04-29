#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2025 by University of Washington.  All rights reserved.
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
Tridente Sensor extension
"""

# For the Tridente, all calibrations are applied on the instrument, so this
# extension simply generates metadata

import BaseNetCDF
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

    scattering_units = "meter^-1 steradian^-1"
    chl_units = "micrograms/liter"
    ppb_units = "1e-9"  # a part per billion

    # See the Tridente instrument and column naming document in the docs directory for a
    # description of the namespace

    channels = {
        "chla470": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": chl_units,
            "description": "chlorophyll-a concentration (470nm excitation/695nm emission) scaled to the fluorescence response from a monoculture of Thalassiosira weissflogii.",
        },
        # "chla435" : {},
        "fdom365": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": ppb_units,
            "description": "fDOM fluorescence (365nm excitation/450m emission)",
        },
        # "pc590" : {},
        # "pe525" : {},
        # "rd550" : {},
        # "fitc470" : {},
        "bb470": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": scattering_units,
            "description": "total volume 470nm scattering coefficient",
        },
        # "bb525" : {},
        # "bb650" : {},
        "bb700": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": scattering_units,
            "description": "total volume 700nm scattering coefficient",
        },
        # "tu650" : {},
        # "tu700" : {}
    }

    meta_data_adds = {}

    # Note: The instrument can be auto generated from the valid channels list, but
    # to conserve memory and runtime, the list is kept the those known variantes, and expanded
    # with the possible instance number
    known_instruments = ("bb700bb470chla470", "bb700chl470fdom365")
    # We keep this list to 3 possible installed instruments, even though the name space allows for up to 9 installed instruments
    instances = ("tridente", "tridente1", "tridente2", "tridente3")
    instruments = []
    for ki in known_instruments:
        for inst in instances:
            instruments.append(f"{inst}_{ki}")

    for instrument in instruments:
        # Calibration string
        meta_data_adds[f"{BaseNetCDF.nc_sg_cal_prefix}calibcomm_{instrument}"] = [
            False,
            "c",
            {},
            BaseNetCDF.nc_scalar,
        ]

        # create data info
        data_info = "%s_data_info" % instrument
        data_time_var = "%s_time" % instrument
        BaseNetCDF.register_sensor_dim_info(
            data_info,
            "%s_data_point" % instrument,
            data_time_var,
            "chemical",
            instrument,
        )
        # create results info
        results_time_var = "%s_results_time" % instrument
        results_info = "%s_results_info" % instrument
        BaseNetCDF.register_sensor_dim_info(
            results_info,
            "%s_result_point" % instrument,
            results_time_var,
            False,
            instrument,
        )

        md = [
            False,
            "c",
            {
                "long_name": "underway tridente",
                "nodc_name": "tridente",
                "make_model": "RBR %s" % instrument,
            },
            BaseNetCDF.nc_scalar,
        ]  # always scalar
        meta_data_adds[instrument] = md

        meta_data_adds[results_time_var] = [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "time for %s in GMT epoch format" % instrument,
            },
            (results_info,),
        ]

        # instrument sensor inputs on truck
        for channel, md in channels.items():
            md["instrument"] = instrument
            meta_data_adds[f"{BaseNetCDF.nc_sg_eng_prefix}{instrument}_{channel}"] = [
                "f",
                "d",
                md,
                (BaseNetCDF.nc_sg_data_info,),
            ]

        # from scicon eng file
        scicon_time_var = "%s_time" % instrument
        meta_data_adds[scicon_time_var] = [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "%s time in GMT epoch format" % instrument,
                "instrument": instrument,
            },
            (data_info,),
        ]

        # Stats for each data file
        for channel, md in channels.items():
            md["instrument"] = instrument
            meta_data_adds[f"{BaseNetCDF.nc_sg_eng_prefix}{instrument}_{channel}"] = [
                "f",
                "d",
                md,
                (data_info,),
            ]

        for cast, tag in (("a", "dive"), ("b", "climb")):
            meta_data_adds["%s_ontime_%s" % (instrument, cast)] = [
                False,
                "d",
                {
                    "description": "%s total time turned on %s" % (instrument, tag),
                    "units": "secs",
                },
                BaseNetCDF.nc_scalar,
            ]
            meta_data_adds["%s_samples_%s" % (instrument, cast)] = [
                False,
                "i",
                {
                    "description": "%s total number of samples taken %s"
                    % (instrument, tag)
                },
                BaseNetCDF.nc_scalar,
            ]
            meta_data_adds["%s_timeouts_%s" % (instrument, cast)] = [
                False,
                "i",
                {
                    "description": "%s total number of samples timed out on %s"
                    % (instrument, tag)
                },
                BaseNetCDF.nc_scalar,
            ]

    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}
    return 0
