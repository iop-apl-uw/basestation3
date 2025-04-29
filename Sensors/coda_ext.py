#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2019, 2021, 2022, 2023, 2024, 2025 by University of Washington.  All rights reserved.
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
RBR codeTODO basestation sensor extension
"""

import BaseNetCDF
import Utils
from BaseLog import log_error
from QC import (
#     QC_BAD,
#     QC_GOOD,
#     QC_UNSAMPLED,
#     assert_qc,
#     inherit_qc,
#     initialize_qc,
     nc_qc_type,
)

instrument = "codatodo"

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
    # initialize with the *single* set of calibration constants
    # BUG: in this version of the extension, in the case of two or more optodes aboard,
    # exactly one optode's data will be processed and the choice is random
    meta_data_adds = {
    }

    # create data info
    data_info = f"{instrument}_data_info"
    data_time_var = f"{instrument}_time" 
    BaseNetCDF.register_sensor_dim_info(
        data_info,
        f"{instrument}_data_point",
        data_time_var,
        "chemical",
        instrument,
    )
    # create results info
    results_time_var = f"{instrument}_results_time"
    results_info = "%s_results_info" % instrument
    BaseNetCDF.register_sensor_dim_info(
        results_info,
        f"{instrument}_result_point",
        results_time_var,
        False,
        instrument,
    )

    md = [
        False,
        "c",
        {
            "long_name": f"underway {instrument}",
            "nodc_name": instrument,
            "make_model": f"RBR {instrument}",
        },
        BaseNetCDF.nc_scalar,
    ]  # always scalar
    meta_data_adds[instrument] = md

    # instrument sensor inputs
    eng_tuple = (BaseNetCDF.nc_sg_eng_prefix, instrument)
    eng_o2_var = f"{instrument}_uncompensated_O2"
    md_var = "%s%s" % (BaseNetCDF.nc_sg_eng_prefix, eng_o2_var)
    meta_data_adds[md_var] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": "micromoles/L",
            "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
            + "assuming optode temperature but without pressure or salinity correction",
            "instrument": instrument,
        },
        (BaseNetCDF.nc_sg_data_info,),
    ]
            
    eng_o2_var = f"{instrument}_compensated_O2"
    md_var = f"{BaseNetCDF.nc_sg_eng_prefix}{eng_o2_var}"
    meta_data_adds[md_var] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": "micromoles/L",
            "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
            + "assuming optode temperature but with fixed pressure and salinity correction",
            "instrument": instrument,
        },
        (BaseNetCDF.nc_sg_data_info,),
    ]
    meta_data_adds["%s%s_airsat" % eng_tuple] = [
        False,
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "description": "As reported by the instrument",
            "instrument": instrument,
        },
        (BaseNetCDF.nc_sg_data_info,),
    ]
    meta_data_adds["%s%s_temp" % eng_tuple] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": "degrees_Celsius",
            "description": "As reported by the instrument",
            "instrument": instrument,
        },
        (BaseNetCDF.nc_sg_data_info,),
    ]
    meta_data_adds["%s%s_phase" % eng_tuple] = [
        False,
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "description": "As reported by the instrument",
            "instrument": instrument,
        },
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
    scicon_o2_var = "%s_uncompensated_O2" % instrument
    meta_data_adds[scicon_o2_var] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": "micromoles/L",
            "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
            + " assuming optode temperature but without pressure or salinity correction",
            "instrument": instrument,
        },
        (data_info,),
    ]
    scicon_o2_var = "%s_compensated_O2" % instrument
    meta_data_adds[scicon_o2_var] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": "micromoles/L",
            "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
            + " assuming optode temperature with fixed pressure and salinity correction",
            "instrument": instrument,
        },
        (data_info,),
    ]
    meta_data_adds["%s_airsat" % instrument] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "description": "As reported by the instrument",
            "instrument": instrument,
        },
        (data_info,),
    ]
    # NOTE scicon renaming: not, e.g., aa4330_Temp
    meta_data_adds["%s_temp" % instrument] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": "degrees_Celsius",
            "description": "As reported by the instrument",
            "instrument": instrument,
        },
        (data_info,),
    ]
    meta_data_adds["%s_phase" % instrument] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "description": "As reported by the instrument",
            "instrument": instrument,
        },
        (data_info,),
    ]

    # derived results
    # Why, oh why, didn't we name these, e.g., aa4330_dissolved_oxygen etc rather than aanderaa4330_dissolved_oxygen?
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
    results_do_var = "%s_dissolved_oxygen" % instrument
    meta_data_adds[results_do_var] = [
        "f",
        "d",
        {
            "_FillValue": BaseNetCDF.nc_nan,
            "standard_name": "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
            "units": "micromoles/kg",
            "description": "Dissolved oxygen concentration, calculated from optode tcphase corrected for salininty and depth",
        },
        (results_info,),
    ]
    results_do_qc_var = "%s_dissolved_oxygen_qc" % instrument
    meta_data_adds[results_do_qc_var] = [
        False,
        nc_qc_type,
        {
            "units": "qc_flag",
            "description": "Whether to trust each optode dissolved oxygen value",
        },
        (results_info,),
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


def remap_engfile_columns_netcdf(
    base_opts, module, calib_consts=None, column_names=None
):
    """
    Called from MakeDiveProfiles.py to remap column headers from older .eng files to
    current naming standards for netCDF output

    Returns:
    0 - match found and processed
    1 - no match found
    """

    replace_dict = {
        "codaTODO_temp" : f"{instrument}_temp",
        "codaTODO_doxy21" : f"{instrument}_compensated_O2",
        "codaTODO_doxy22" : f"{instrument}_airsat",
        "codaTODO_doxy24" : f"{instrument}_uncompensated_O2",
        "codaTODO_opt05" : f"{instrument}_phase", 
    }
    return Utils.remap_column_names(replace_dict, column_names)
