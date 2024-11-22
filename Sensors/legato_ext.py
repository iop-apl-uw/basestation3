#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2011, 2012, 2013, 2015, 2019, 2020, 2021, 2022, 2023, 2024 by University of Washington.  All rights reserved.
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
rbr legato basestation sensor extension
"""

import Utils
from BaseLog import log_error
import BaseNetCDF


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
        BaseNetCDF.nc_legato_data_info,
        "legato_data_point",
        "legato_time",
        True,
        "legato",
    )

    # results are computed in MDP
    init_dict[module_name] = {
        "netcdf_metadata_adds": {
            "legato": [
                False,
                "c",
                {
                    "long_name": "underway thermosalinograph",
                    "nodc_name": "thermosalinograph",
                    "make_model": "unpumped RBR Legato",
                },
                BaseNetCDF.nc_scalar,
            ],  # always scalar
            # legato via truck
            "eng_rbr_conduc": [
                "f",
                "d",
                {
                    "standard_name": "sea_water_electrical_conductivity",
                    "units": "mS/cm",
                    "description": "Conductivity as reported by the instrument",
                },
                (BaseNetCDF.nc_sg_data_info,),
            ],
            "eng_rbr_temp": [
                "f",
                "d",
                {
                    "standard_name": "sea_water_temperature",
                    "units": "degrees_Celsius",
                    "description": "Termperature (in situ) as reported by the instrument",
                },
                (BaseNetCDF.nc_sg_data_info,),
            ],
            "eng_rbr_conducTemp": [
                False,
                "d",
                {
                    "units": "degrees_Celsius",
                    "description": "As reported by the instrument",
                },
                (BaseNetCDF.nc_sg_data_info,),
            ],
            "eng_rbr_pressure": [
                "f",
                "d",
                {
                    "standard_name": "sea_water_pressure",
                    "units": "dbar",
                    "description": "CTD reported pressure",
                },
                (BaseNetCDF.nc_sg_data_info,),
            ],
            # legato via scicon
            "legato_time": [
                True,
                "d",
                {
                    "standard_name": "time",
                    "units": "seconds since 1970-1-1 00:00:00",
                    "description": "sbe41 time in GMT epoch format",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_conduc": [
                "f",
                "d",
                {
                    "standard_name": "sea_water_electrical_conductivity",
                    "units": "mS/cm",
                    "description": "Conductivity as reported by the instrument",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_temp": [
                "f",
                "d",
                {
                    "standard_name": "sea_water_temperature",
                    "units": "degrees_Celsius",
                    "description": "Termperature (in situ) as reported by the instrument",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_conducTemp": [
                False,
                "d",
                {
                    "units": "degrees_Celsius",
                    "description": "As reported by the instrument",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_pressure": [
                "f",
                "d",
                {
                    "standard_name": "sea_water_pressure",
                    "units": "dbar",
                    "description": "CTD reported pressure",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_ontime_a": [
                False,
                "d",
                {"description": "legato total time turned on dive", "units": "secs"},
                BaseNetCDF.nc_scalar,
            ],
            "legato_samples_a": [
                False,
                "i",
                {"description": "legato total number of samples taken dive"},
                BaseNetCDF.nc_scalar,
            ],
            "legato_timeouts_a": [
                False,
                "i",
                {"description": "legato total number of samples timed out on dive"},
                BaseNetCDF.nc_scalar,
            ],
            "legato_errors_a": [
                False,
                "i",
                {
                    "description": "legato total number of errors reported during sampling on dive"
                },
                BaseNetCDF.nc_scalar,
            ],
            "legato_ontime_b": [
                False,
                "d",
                {"description": "legato total time turned on climb", "units": "secs"},
                BaseNetCDF.nc_scalar,
            ],
            "legato_samples_b": [
                False,
                "i",
                {"description": "legato total number of samples taken climb"},
                BaseNetCDF.nc_scalar,
            ],
            "legato_timeouts_b": [
                False,
                "i",
                {"description": "legato total number of samples timed out on climb"},
                BaseNetCDF.nc_scalar,
            ],
            "legato_errors_b": [
                False,
                "i",
                {
                    "description": "legato total number of errors reported during sampling on climb"
                },
                BaseNetCDF.nc_scalar,
            ],
        }
    }
    return 0


# pylint: disable=unused-argument
def remap_engfile_columns_netcdf(base_opts, module, calib_constants, column_names=None):
    """
    Called from MakeDiveProfiles.py to remap column headers from older .eng files to
    current naming standards for netCDF output

    Returns:
    0 - match found and processed
    1 - no match found
    """
    replace_dict = {
        "legatoPoll_time": "legato_time",
        "legatoPoll_conduc": "legato_conduc",
        "legatoPoll_temp": "legato_temp",
        "legatoPoll_pressure": "legato_pressure",
        "legatoPoll_conducTemp": "legato_conducTemp",
        "legatoFast_time": "legato_time",
        "legatoFast_conduc": "legato_conduc",
        "legatoFast_temp": "legato_temp",
        "legatoFast_pressure": "legato_pressure",
        "legatoFast_conducTemp": "legato_conducTemp",
    }
    if (
        "ignore_truck_legato" in calib_constants
        and calib_constants["ignore_truck_legato"]
    ):
        for vval in ["rbr_pressure", "rbr_conduc", "rbr_conducTemp", "rbr_temp"]:
            replace_dict[vval] = f"ignore_{vval}"

    return Utils.remap_column_names(replace_dict, column_names)


instruments_d = {
    "legatoFast": "legato",
    "legatoPoll": "legato",
}


def remap_instrument_names(base_opts, module, current_names=None):
    """Given a list of instrument names, map into the canonical names

    Returns:
    -1 - error in processing
     0 - data found and processed
     1 - no appropriate data found

    """
    if current_names is None:
        log_error(
            "Missing arguments for legato remap_instrument_names - version mismatch?"
        )
        return -1

    ret_val = 1

    for oldname in current_names:
        for k, v in instruments_d.items():
            if oldname == k:
                current_names[current_names.index(oldname)] = v
                ret_val = 0
    return ret_val


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

    ret_val = 1

    sealevel = None
    if "rbr.pressure" in datafile.columns:
        if "legato_sealevel" not in datafile.calib_consts:
            log_error(
                "Missing legato_sealevel in sg_calib_constants - assuming 10082",
                alert="MISSING_SEALEVEL",
            )
            sealevel = 10082.0
            # If you get here reprocessing old missions, the old hardcoded values was 10082.0
        else:
            sealevel = datafile.calib_consts["legato_sealevel"]

    for asc_col_name, eng_col_name, scale, offset in (
        ("rbr.conduc", "rbr_conduc", 10000.0, 0.0),
        ("rbr.conducTemp", "rbr_conducTemp", 10000.0, 0.0),
        ("rbr.temp", "rbr_temp", 10000.0, 0.0),
        ("rbr.pressure", "rbr_pressure", 1000.0, sealevel),
    ):
        column = datafile.remove_col(asc_col_name)
        if column is not None:
            datafile.eng_cols.append(eng_col_name)
            datafile.eng_dict[eng_col_name] = (column - offset) / scale
            ret_val = 0

    return ret_val
