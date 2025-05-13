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
Optode aa4XXX basestation sensor extension
"""

import numpy as np

import BaseNetCDF
import Utils
import Utils2
from BaseLog import log_debug, log_error, log_warning
from QC import (
    QC_BAD,
    QC_GOOD,
    QC_UNSAMPLED,
    assert_qc,
    inherit_qc,
    initialize_qc,
    nc_qc_type,
)
from TraceArray import trace_array

# instrument types
instruments = ["aa4330", "aa4831", "aa4831F"]
canonical_data_to_results_d = {}


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
        # unused at the moment
        "sg_cal_optode_TempCoef0": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_TempCoef1": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_TempCoef2": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_TempCoef3": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_TempCoef4": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_TempCoef5": [False, "d", {}, BaseNetCDF.nc_scalar],
        # Used to convert tcphase to calphase
        "sg_cal_optode_PhaseCoef0": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_PhaseCoef1": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_PhaseCoef2": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_PhaseCoef3": [False, "d", {}, BaseNetCDF.nc_scalar],
        # For the aa4330 w/ FW 4.5.7 and above, the PhaseCoef's above should be [0,1,0,0]
        # and these coeffients may be supplied (else assumed to be [0,1])
        "sg_cal_optode_ConcCoef0": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_ConcCoef1": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA0": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA1": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA2": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA3": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA4": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA5": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA6": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA7": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA8": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA9": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA10": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA11": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA12": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefA13": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB0": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB1": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB2": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB3": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB4": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB5": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB6": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB7": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB8": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB9": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB10": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB11": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB12": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_FoilCoefB13": [False, "d", {}, BaseNetCDF.nc_scalar],
        # Aanderaa supports an onboard Stern-Volmer correction for instrument O2
        # record those coefficients in case we want to replicate that correction instead
        "sg_cal_optode_SVUCoef0": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_SVUCoef1": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_SVUCoef2": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_SVUCoef3": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_SVUCoef4": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_SVUCoef5": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_SVUCoef6": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_SVU_enabled": [False, "d", {}, BaseNetCDF.nc_scalar],
        # Support Johnson et al. air oxygen correction for sensor drift (for both aa4330 and aa3830)
        "sg_cal_optode_st_calphase": [
            False,
            "d",
            {
                "description": "Mean calibrated phase value from instrument in air during selftest"
            },
            BaseNetCDF.nc_scalar,
        ],
        "sg_cal_optode_st_temp": [
            False,
            "d",
            {
                "description": "Mean optode temperature from instrument in air during selftest",
                "units": "degrees_Celsius",
            },
            BaseNetCDF.nc_scalar,
        ],
        "sg_cal_optode_st_slp": [
            False,
            "d",
            {
                "description": "Sealevel pressure in air during selftest",
                "units": "mbar",
            },
            BaseNetCDF.nc_scalar,
        ],  # 1013.25 mbar nominal
    }
    for instrument in instruments:
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
        results_time_var = "aander%s_results_time" % instrument
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
                "long_name": "underway optode",
                "nodc_name": "optode",
                "make_model": "Aanderaa %s" % instrument,
            },
            BaseNetCDF.nc_scalar,
        ]  # always scalar
        meta_data_adds[instrument] = md

        # instrument sensor inputs
        # NOTE since we have ml/l this is a volume fraction we have 1e-3 ml/l
        # The new correction will change this to umoles/m^3 so that will change the name
        # to mole_concentration_of_dissolved_molecular_oxygen_in_sea_water
        # Add instrument explicitly for eng file data since they all share the same dim info
        eng_tuple = (BaseNetCDF.nc_sg_eng_prefix, instrument)
        eng_o2_var = "%s_O2" % instrument
        md_var = "%s%s" % (BaseNetCDF.nc_sg_eng_prefix, eng_o2_var)
        meta_data_adds[md_var] = [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/L",
                "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
                + "assuming optode temperature but without depth or salinity correction",
                "instrument": instrument,
            },
            (BaseNetCDF.nc_sg_data_info,),
        ]
        meta_data_adds["%s%s_AirSat" % eng_tuple] = [
            False,
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "description": "As reported by the instrument",
                "instrument": instrument,
            },
            (BaseNetCDF.nc_sg_data_info,),
        ]
        meta_data_adds["%s%s_Temp" % eng_tuple] = [
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
        meta_data_adds["%s%s_CalPhase" % eng_tuple] = [
            False,
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "description": "As reported by the instrument",
                "instrument": instrument,
            },
            (BaseNetCDF.nc_sg_data_info,),
        ]
        eng_tcphase_var = "%s_TCPhase" % instrument
        md_var = "%s%s" % (BaseNetCDF.nc_sg_eng_prefix, eng_tcphase_var)
        meta_data_adds[md_var] = [
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
                "description": "Aanderaa %s time in GMT epoch format" % instrument,
                "instrument": instrument,
            },
            (data_info,),
        ]
        scicon_o2_var = "%s_O2" % instrument
        meta_data_adds[scicon_o2_var] = [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/L",
                "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
                + " assuming optode temperature but without depth or salinity correction",
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
        meta_data_adds["%s_calphase" % instrument] = [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "description": "As reported by the instrument",
                "instrument": instrument,
            },
            (data_info,),
        ]
        scicon_tcphase_var = "%s_tcphase" % instrument
        meta_data_adds[scicon_tcphase_var] = [
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
                "description": "time for Aanderaa %s in GMT epoch format" % instrument,
            },
            (results_info,),
        ]
        results_do_var = "aander%s_dissolved_oxygen" % instrument
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
        results_do_qc_var = "aander%s_dissolved_oxygen_qc" % instrument
        meta_data_adds[results_do_qc_var] = [
            False,
            nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each optode dissolved oxygen value",
            },
            (results_info,),
        ]
        results_instrument_do_var = "aander%s_instrument_dissolved_oxygen" % instrument
        meta_data_adds[results_instrument_do_var] = [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/kg",
                "description": "Dissolved oxygen concentration reported from optode corrected for salinity",
            },
            (results_info,),
        ]
        results_overall_qc_var = "aander%s_qc" % instrument
        meta_data_adds[results_overall_qc_var] = [
            False,
            nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the Aanderaa %s results" % instrument,
            },
            BaseNetCDF.nc_scalar,
        ]
        results_drift_gain_var = "aander%s_drift_gain" % instrument
        meta_data_adds[results_drift_gain_var] = [
            False,
            "d",
            {"description": "Drift gain correction for the Aanderaa %s" % instrument},
            BaseNetCDF.nc_scalar,
        ]

        meta_data_adds = meta_data_adds | Utils2.add_scicon_stats(instrument)

        canonical_data_to_results_d[instrument] = [
            data_info,
            data_time_var,
            eng_o2_var,
            eng_tcphase_var,
            scicon_time_var,
            scicon_o2_var,
            scicon_tcphase_var,
            results_time_var,
            results_info,
            results_do_var,
            results_do_qc_var,
            results_instrument_do_var,
            results_overall_qc_var,
            results_drift_gain_var,
        ]

    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}
    return 0


# No change to canonical remap of old eng columns...only applies to old trunk files
# pylint: disable=unused-argument
def asc2eng(base_opts, module_name, datafile=None):
    """
    asc2eng processor

    returns:
    -1 - error in processing
     0 - success (data found and processed)
     1 - no data found to process
    """

    if datafile is None:
        log_error("No datafile supplied for asc2eng conversion - version mismatch?")
        return -1

    # Old name
    aa4330_O2 = datafile.remove_col("aa4330_O2")
    aa4330_AirSat = datafile.remove_col("aa4330_AirSat")
    aa4330_Temp = datafile.remove_col("aa4330_Temp")
    aa4330_CalPhase = datafile.remove_col("aa4330_CalPhase")
    aa4330_TCPhase = datafile.remove_col("aa4330_TCPhase")

    if aa4330_O2 is None:
        aa4330_O2 = datafile.remove_col("aa4330.O2")
        aa4330_AirSat = datafile.remove_col("aa4330.AirSat")
        aa4330_Temp = datafile.remove_col("aa4330.Temp")
        aa4330_CalPhase = datafile.remove_col("aa4330.CalPhase")
        aa4330_TCPhase = datafile.remove_col("aa4330.TCPhase")

    # iRobot latest naming scheme
    if aa4330_O2 is None:
        aa4330_O2 = datafile.remove_col_regex("aa[0-9][0-9][0-9].O2")
        aa4330_AirSat = datafile.remove_col_regex("aa[0-9][0-9][0-9].AirSat")
        aa4330_Temp = datafile.remove_col_regex("aa[0-9][0-9][0-9].Temp")
        aa4330_CalPhase = datafile.remove_col_regex("aa[0-9][0-9][0-9].CalPhase")
        aa4330_TCPhase = datafile.remove_col_regex("aa[0-9][0-9][0-9].TCPhase")

    if aa4330_O2 is not None:
        aa4330_O2 = aa4330_O2 / 1000.0
        aa4330_AirSat = aa4330_AirSat / 1000.0
        aa4330_Temp = aa4330_Temp / 1000.0
        aa4330_CalPhase = aa4330_CalPhase / 1000.0
        aa4330_TCPhase = aa4330_TCPhase / 1000.0
        datafile.eng_cols.append("aa4330.O2")
        datafile.eng_cols.append("aa4330.AirSat")
        datafile.eng_cols.append("aa4330.Temp")
        datafile.eng_cols.append("aa4330.CalPhase")
        datafile.eng_cols.append("aa4330.TCPhase")
        datafile.eng_dict["aa4330.O2"] = aa4330_O2
        datafile.eng_dict["aa4330.AirSat"] = aa4330_AirSat
        datafile.eng_dict["aa4330.Temp"] = aa4330_Temp
        datafile.eng_dict["aa4330.CalPhase"] = aa4330_CalPhase
        datafile.eng_dict["aa4330.TCPhase"] = aa4330_TCPhase
        return 0

    aa4831_O2 = datafile.remove_col("aa4831.O2")
    aa4831_AirSat = datafile.remove_col("aa4831.AirSat")
    aa4831_Temp = datafile.remove_col("aa4831.Temp")
    aa4831_CalPhase = datafile.remove_col("aa4831.CalPhase")
    aa4831_TCPhase = datafile.remove_col("aa4831.TCPhase")

    if aa4831_O2 is not None:
        aa4831_O2 = aa4831_O2 / 1000.0
        aa4831_AirSat = aa4831_AirSat / 1000.0
        aa4831_Temp = aa4831_Temp / 1000.0
        aa4831_CalPhase = aa4831_CalPhase / 1000.0
        aa4831_TCPhase = aa4831_TCPhase / 1000.0
        datafile.eng_cols.append("aa4831.O2")
        datafile.eng_cols.append("aa4831.AirSat")
        datafile.eng_cols.append("aa4831.Temp")
        datafile.eng_cols.append("aa4831.CalPhase")
        datafile.eng_cols.append("aa4831.TCPhase")
        datafile.eng_dict["aa4831.O2"] = aa4831_O2
        datafile.eng_dict["aa4831.AirSat"] = aa4831_AirSat
        datafile.eng_dict["aa4831.Temp"] = aa4831_Temp
        datafile.eng_dict["aa4831.CalPhase"] = aa4831_CalPhase
        datafile.eng_dict["aa4831.TCPhase"] = aa4831_TCPhase
        return 0

    return 1


# pylint: disable=too-many-locals
def sensor_data_processing(
    base_opts, module, l_dict=None, eng_f=None, calib_consts=None
):
    """
    Called from MakeDiveProfiles.py to do sensor specific processing

    Arguments:
    l_dict - MakeDiveProfiles locals() dictionary
    eng_f - engineering file
    calib_constants - sg_calib_constants object

    Returns:
    -1 - error in processing
     0 - data found and processed
     1 - no appropriate data found
    """

    if (
        l_dict is None
        or eng_f is None
        or calib_consts is None
        or "results_d" not in l_dict
    ):
        log_error("Missing arguments for sensor_data_processing - version mismatch?")
        return -1

    required_vars_present = True
    try:
        results_d = l_dict["results_d"]
        nc_info_d = l_dict["nc_info_d"]

        sg_epoch_time_s_v = l_dict["sg_epoch_time_s_v"]

        ctd_epoch_time_s_v = l_dict["ctd_epoch_time_s_v"]
        temp_cor_v = l_dict["temp_cor_v"]
        temp_cor_qc_v = l_dict["temp_cor_qc_v"]
        # NOTE: the use of corrected salinity means we don't get salinities (hence o2)
        # at QC_BAD points, notably at apogee but elsewhere in the water column
        # should we use raw temp and salin (and density?)
        salin_cor_v = l_dict["salin_cor_v"]
        salin_cor_qc_v = l_dict["salin_cor_qc_v"]
        ctd_pressure_v = l_dict["ctd_press_v"]
        ctd_density_v = l_dict[
            "density_v"
        ]  # Use potential density (per Uchida, et al. 2008)
        ancillary_variables = "temperature salinity ctd_pressure density"
    except KeyError:
        required_vars_present = False

    # Now see if we have an instrument aboard
    # if so process its data and exit
    for instrument, cd in canonical_data_to_results_d.items():
        (
            data_info,
            _,  # data_time_var,
            eng_o2_var,
            eng_tcphase_var,
            scicon_time_var,
            scicon_o2_var,
            scicon_tcphase_var,
            results_time_var,
            results_info,
            results_do_var,
            results_do_qc_var,
            results_instrument_do_var,
            results_overall_qc_var,
            results_drift_gain_var,
        ) = cd

        instrument_metadata_d = BaseNetCDF.fetch_instrument_metadata(data_info)
        if "ancillary_variables" in instrument_metadata_d:
            del instrument_metadata_d["ancillary_variables"]  # eliminate

        (eng_optode_present, optode_o2_v) = eng_f.find_col([eng_o2_var])
        if eng_optode_present:
            if not required_vars_present:
                log_error(
                    "Missing variables for %s eng correction - bailing out"
                    % instrument,
                    "exc",
                )
                return -1
            tcphase_var = eng_tcphase_var
            _, optode_tcphase_v = eng_f.find_col([tcphase_var])
            optode_time_s_v = sg_epoch_time_s_v
            optode_results_dim = BaseNetCDF.nc_mdp_data_info[BaseNetCDF.nc_sg_data_info]
        else:
            try:
                # See if we have data from scicon
                optode_o2_v = results_d[scicon_o2_var]
                tcphase_var = scicon_tcphase_var
                optode_tcphase_v = results_d[tcphase_var]
                optode_time_s_v = results_d[scicon_time_var]
                optode_results_dim = BaseNetCDF.nc_mdp_data_info[data_info]
            except KeyError:
                continue  # no data from this type of optode

            # We have all the optode data.  Do we have the rest?
            if not required_vars_present:
                log_error(
                    "Missing variables for %s scicon correction - bailing out"
                    % instrument,
                    "exc",
                )
                return -1

        # MDP automatically asserts instrument when writing
        # DEAD results_d[instrument] = instrument # CONSIDER add calibcomm_oxygen
        ancillary_variables = ancillary_variables + " %s" % tcphase_var

        # We have data from an instrument; do we have some the optode calibration constants?
        try:
            # Since we use the CT temp rather aa4330_temp we don't actually use optode_TempCoefX coeffients
            # but we do recalculate calphase from tcphase
            CalPhase_coef = [
                calib_consts["optode_PhaseCoef0"],
                calib_consts["optode_PhaseCoef1"],
                calib_consts["optode_PhaseCoef2"],
                calib_consts["optode_PhaseCoef3"],
            ]
        except KeyError:
            # New versions of optode FW don't use phase coefficients
            # these defaults maintain tcphase_v values
            CalPhase_coef = [0.0, 1.0, 0.0, 0.0]

        # The conversion of phase data for the AA4330 is like the AA3830 but with more parameters that are not used...to wit
        # On the aa3830 the Tphase in general would be calculated by the eqn:
        #   Tphase = A*(Bphase - Rphase) + B
        # where Bphase is the blue phase data collected and Rphase is a 'reference' phase
        # In the aa3830, Rphase was never recorded and treated as 0.  Further A = 1 and B = 0
        # so we had Tphase = Bphase
        # For the aa4330, Rphase is now recorded and A is explicitly 1 and B == 0
        # so we have Tphase = Bphase - Rphase
        # (This is recorded as tcphase (or TCPhase depending on naming))

        # Then in the aa3830 we derive Dphase from Tphase using a set of 4 coefficients:
        #   Dphase = A0 + A1*Tphase + A2*Tphase^2 + A3*Tphase^3
        # but in the aa3830 only A0 and A1 were used.
        # For the aa4330 this same calculation yields CalPhase and in
        # only A0 and A1 are used and called PhaseCoef0 and PhaseCoef1.
        # Thus Dphase and CalPhase are the 'same'
        CalPhase_coef.reverse()
        calphase_v = np.polyval(CalPhase_coef, optode_tcphase_v)

        # JSB It comes from the factory with these concentration scale changes set to [0 1] (e.g., no change)
        # I think they are for people like Argo who recalibrate locally and determine linear changes to output in case of drift etc.
        # They can then assert them aboard the FW and/or use them in post-processing...
        try:
            Conc_coef = [
                calib_consts["optode_ConcCoef0"],
                calib_consts["optode_ConcCoef1"],
            ]
            ancillary_variables = (
                ancillary_variables + " sg_cal_optode_ConcCoef0 sg_cal_optode_ConcCoef1"
            )
        except KeyError:
            Conc_coef = [0.0, 1.0]  # default -- no change, no complain
        Conc_coef.reverse()

        # First expand some other data we need for conversions to O2 concentration:
        if optode_results_dim != nc_info_d[BaseNetCDF.nc_ctd_results_info]:
            # Eliminate unsampled data points from the CTD data
            sampled_pts_i = np.squeeze(
                np.nonzero(
                    np.logical_not(
                        np.logical_or(
                            temp_cor_qc_v == QC_UNSAMPLED,
                            salin_cor_qc_v == QC_UNSAMPLED,
                        )
                    )
                )
            )
            # interpolate the CTD data we need
            temp_cor_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                temp_cor_v[sampled_pts_i],
                optode_time_s_v,
                kind="linear",
            )
            temp_cor_qc_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                temp_cor_qc_v[sampled_pts_i],
                optode_time_s_v,
                kind="nearest",
            )
            salin_cor_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                salin_cor_v[sampled_pts_i],
                optode_time_s_v,
                kind="linear",
            )
            salin_cor_qc_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                salin_cor_qc_v[sampled_pts_i],
                optode_time_s_v,
                kind="nearest",
            )
            ctd_pressure_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                ctd_pressure_v[sampled_pts_i],
                optode_time_s_v,
                kind="linear",
            )
            ctd_density_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                ctd_density_v[sampled_pts_i],
                optode_time_s_v,
                kind="linear",
            )

        optode_np = len(optode_time_s_v)
        BaseNetCDF.assign_dim_info_dim_name(nc_info_d, results_info, optode_results_dim)
        BaseNetCDF.assign_dim_info_size(nc_info_d, results_info, optode_np)

        # Shouldn't we compute the difference of temp over optode temp (and salinity over fresh (0), which is salinity)
        (
            oxygen_sat_sea_water_um_kg_v,
            _,  # oxygen_sat_fresh_water_um_kg_v,
            oxygen_sat_salinity_adjustment_v,
        ) = Utils.compute_oxygen_saturation(temp_cor_v, salin_cor_v)

        try:
            SVU_enabled = calib_consts["optode_SVU_enabled"]
        except KeyError:
            SVU_enabled = False  # assume it isn't enabled

        # Get the appropriate calibration coefficients
        coefficients_available = False
        if SVU_enabled:
            # Using the Stern-Volmer Uchida method
            # See Uchida et al.  SVU == Stern-Volmer Uchida
            # if the foil method failed or if the instrument was doing this onboard, in which case we should follow suit.
            # 4th edition: Craig Neill (CSIRO) and Argo Brest 2011 suggest this method works better interpolating between points
            # and extrapolating beyond the data.
            try:
                SVUCoef0 = calib_consts["optode_SVUCoef0"]
                SVUCoef1 = calib_consts["optode_SVUCoef1"]
                SVUCoef2 = calib_consts["optode_SVUCoef2"]
                SVUCoef3 = calib_consts["optode_SVUCoef3"]
                SVUCoef4 = calib_consts["optode_SVUCoef4"]
                SVUCoef5 = calib_consts["optode_SVUCoef5"]
                SVUCoef6 = calib_consts["optode_SVUCoef6"]
                ancillary_variables = ancillary_variables + " sg_cal_optode_SVUCoef*"
            except KeyError:
                log_warning(
                    "Optode data found but SVU calibration constant(s) missing - skipping Stern-Volmer optode corrections"
                )
            else:
                coefficients_available = True
        else:
            # Assume they are using the foil method...
            try:
                # So, where do these arrays of foil calibration constants come from?
                # On the cal sheet there are FoilCoefA and FoilCoefB constants 0-13
                # And there is a set of monomial degrees of FoilPolyDegT and FoilPolyDegO
                # These later values *DO NOT CHANGE* and are effectively indicies for the (sum of) FoilCoef constants into an upper-triangular matrix
                # that is used to compute the temperature compensated coefficients.  These Aanderaa people, really...

                # In particular we assume that the FoilPolyDegT and FoilPolyDegO assignments do not change from the following:
                # (FoilPolyDegT is the column index and FoilPolyDegO is the row index)

                # FoilPolyDegT:  1  0  0  0  1  2  0  1  2  3   0   1   2   3   4   0   1   2   3   4   5   0   0   0    0   0   0   0
                # FoilPolyDegO:  4  5  4  3  3  3  2  2  2  2   1   1   1   1   1   0   0   0   0   0   0   0   0   0    0   0   0   0

                # Index:         0  1  2  3  4  5  6  7  8  9  10  11  12  13  14  15  16  17  18  19  20  21  22  23   24  25  26  27
                # FoilCoef      A0 A1 A2 A3 A4 A5 A6 A7 A8 A9 A10 A11 A12 A13  B0  B1  B2  B3  B4  B5  B6  B7  B8  B9  B10 B11 B12 B13

                # We really need to sum the coefficients that share any DegT and DegO; using those indices above, there is only one addition, at 0,0
                CoefB1_7_13 = (
                    calib_consts["optode_FoilCoefB1"]
                    + calib_consts["optode_FoilCoefB7"]
                    + calib_consts["optode_FoilCoefB8"]
                    + calib_consts["optode_FoilCoefB9"]
                    + calib_consts["optode_FoilCoefB10"]
                    + calib_consts["optode_FoilCoefB11"]
                    + calib_consts["optode_FoilCoefB12"]
                    + calib_consts["optode_FoilCoefB13"]
                )
                C0_coef = [
                    CoefB1_7_13,
                    calib_consts["optode_FoilCoefB2"],
                    calib_consts["optode_FoilCoefB3"],
                    calib_consts["optode_FoilCoefB4"],
                    calib_consts["optode_FoilCoefB5"],
                    calib_consts["optode_FoilCoefB6"],
                ]
                C1_coef = [
                    calib_consts["optode_FoilCoefA10"],
                    calib_consts["optode_FoilCoefA11"],
                    calib_consts["optode_FoilCoefA12"],
                    calib_consts["optode_FoilCoefA13"],
                    calib_consts["optode_FoilCoefB0"],
                    0.0,
                ]
                C2_coef = [
                    calib_consts["optode_FoilCoefA6"],
                    calib_consts["optode_FoilCoefA7"],
                    calib_consts["optode_FoilCoefA8"],
                    calib_consts["optode_FoilCoefA9"],
                    0.0,
                    0.0,
                ]
                C3_coef = [
                    calib_consts["optode_FoilCoefA3"],
                    calib_consts["optode_FoilCoefA4"],
                    calib_consts["optode_FoilCoefA5"],
                    0.0,
                    0.0,
                    0.0,
                ]
                C4_coef = [
                    calib_consts["optode_FoilCoefA2"],
                    calib_consts["optode_FoilCoefA0"],
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                ]
                C5_coef = [calib_consts["optode_FoilCoefA1"], 0.0, 0.0, 0.0, 0.0, 0.0]
                ancillary_variables = ancillary_variables + " sg_cal_optode_FoilCoef*"
            except KeyError as e:
                log_warning(
                    f"Optode data found but foil calibration constant {e} missing - skipping foil optode corrections"
                )
            else:
                coefficients_available = True
                # reverse is destructive so call this once before use in functions below so they can be called multiple times if need be
                C0_coef.reverse()
                C1_coef.reverse()
                C2_coef.reverse()
                C3_coef.reverse()
                C4_coef.reverse()
                C5_coef.reverse()

        # Johnson, Plant, Riser, Gilbert. 'Air oxygen calibration of oxygen optodes on a profiling float array'
        # submitted, Journal of Atmospheric and Oceanic Technology 2015
        # The optode apparently drifts from its calibration when exposed to air but then stops drifting in (sea)water.
        # Investigation shows this is captured by a gain rather
        # than additive drift, that is, the drift is proportional to the O2 signal. Johnson et al. compute the gain
        # by comparing the output of the sensor in air with the expected
        # O2 concentration given temperature and pressure.
        drift_gain = 1.0  # assume no drift
        try:
            optode_st_calphase = calib_consts[
                "optode_st_calphase"
            ]  # use calphase so we can compute O2 based on foil or SVU
            optode_st_temp = calib_consts[
                "optode_st_temp"
            ]  # optode temperature typically but could be from CT
            optode_st_slp = calib_consts[
                "optode_st_slp"
            ]  # sealevel pressure from a local weather station or NCEP means
        except KeyError:
            pass
        else:
            (
                _,  # st_oxygen_sat_sea_water_um_kg_v,
                st_oxygen_sat_fresh_water_um_kg_v,
                st_oxygen_sat_salinity_adjustment_v,
            ) = Utils.compute_oxygen_saturation(optode_st_temp, 0)
            if coefficients_available:
                if SVU_enabled:
                    optode_st_o2 = optode_oxygen_SVU(
                        optode_st_calphase,
                        optode_st_temp,
                        st_oxygen_sat_salinity_adjustment_v,
                        Conc_coef,
                        SVUCoef0,
                        SVUCoef1,
                        SVUCoef2,
                        SVUCoef3,
                        SVUCoef4,
                        SVUCoef5,
                        SVUCoef6,
                    )
                else:
                    optode_st_o2 = optode_oxygen_foil(
                        optode_st_calphase,
                        optode_st_temp,
                        st_oxygen_sat_fresh_water_um_kg_v,
                        Conc_coef,
                        C0_coef,
                        C1_coef,
                        C2_coef,
                        C3_coef,
                        C4_coef,
                        C5_coef,
                    )
                drift_gain = (st_oxygen_sat_fresh_water_um_kg_v / 1013.25) / (
                    optode_st_o2 / optode_st_slp
                )
                log_debug(
                    "%s drift gain = %f using %s method"
                    % (instrument, drift_gain, "SVU" if SVU_enabled else "foil")
                )

        # Correct the instrument's reported O2 for salinity effects...
        # The optode is normally configured with EnableTemperature yes and a Salinity (typically 0)
        # so that the aa4330_O2 values reflect the optode temp and the assumption of fresh water
        # Adjust instrument O2 reading for measured sea water salinity and (external) temperature from CT.
        # (oxygen_sat_sea_water_um_kg_v/oxygen_sat_fresh_water_um_kg_v)
        # This might not be correct since the aa4330_o2_v was computed onboard using aa4330_temp_v, not temp_cor_v
        optode_o2_adjusted_v = oxygen_sat_salinity_adjustment_v * optode_o2_v
        trace_array("optode_instrument_O2_adjusted", optode_o2_adjusted_v)
        # Correct the instrument's O2 for depth and density effects
        optode_instrument_dissolved_oxygen_v = optode_correct_oxygen(
            optode_time_s_v,
            optode_o2_adjusted_v,
            ctd_pressure_v,
            ctd_density_v,
            drift_gain,
        )
        # At this point we can always return the adjusted instrument reported [O2]
        instrument_metadata_d["ancillary_variables"] = ancillary_variables  # checkpoint
        results_d.update(
            {
                results_time_var: optode_time_s_v,
                results_instrument_do_var: optode_instrument_dissolved_oxygen_v,
                results_drift_gain_var: drift_gain,
            }
        )

        # Finally...
        # Try the various conversions, which demand different calibration coefficients.
        # At least one of these corrections should work or we complain about missing coeffients.
        # We need to decide which one we want to proritize by comparing the results with bottle data
        # According to BATS they return very different values, offset by a large amount
        # In any case, we never fail sensor_data_processing at this point since we fixed the instrument data at least

        if not coefficients_available:
            return 0  # We processed it as best we can...

        if SVU_enabled:
            optode_calphase_oxygen_v = optode_oxygen_SVU(
                calphase_v,
                temp_cor_v,
                oxygen_sat_salinity_adjustment_v,
                Conc_coef,
                SVUCoef0,
                SVUCoef1,
                SVUCoef2,
                SVUCoef3,
                SVUCoef4,
                SVUCoef5,
                SVUCoef6,
            )
            # Apply pressure correction and convert to uM/kg using insitu density
            optode_dissolved_oxygen_v = optode_correct_oxygen(
                optode_time_s_v,
                optode_calphase_oxygen_v,
                ctd_pressure_v,
                ctd_density_v,
                drift_gain,
            )
        else:
            # Compute [O2] based on calphase and the CTD temperature
            optode_calphase_oxygen_v = optode_oxygen_foil(
                calphase_v,
                temp_cor_v,
                oxygen_sat_sea_water_um_kg_v,
                Conc_coef,
                C0_coef,
                C1_coef,
                C2_coef,
                C3_coef,
                C4_coef,
                C5_coef,
            )
            trace_array("optode_calphase_O2", optode_calphase_oxygen_v)
            # NOTE: Wherever ctd_density_v is QC_BAD we have NaN hence NaN in the dissolved_oxygen_v results
            # This *happens* to overlap with the oxygen_qc var above but might not
            # CONSIDER We should explicitly look at the QC_BAD spots and nail those points
            optode_dissolved_oxygen_v = optode_correct_oxygen(
                optode_time_s_v,
                optode_calphase_oxygen_v,
                ctd_pressure_v,
                ctd_density_v,
                drift_gain,
            )

        # Calculate the oxygen qc
        optode_oxygen_qc_v = initialize_qc(optode_np, QC_GOOD)
        # CONSIDER we have seen timed out optode; can/should we distinguish it as QC_MISSING?
        # Test unsampled (nan) before asserting nan on bad points
        assert_qc(
            QC_UNSAMPLED,
            optode_oxygen_qc_v,
            [i for i in range(optode_np) if np.isnan(optode_tcphase_v[i])],
            "unsampled optode oyxgen",
        )
        # Sometimes the airsat and instrument O2 values are large offscale and other data is negative
        # See SG189 dive 37 in SPURS_Sep12, recorded on scicon.  Typically the first and/or last point in the dive or climb file
        bad_i = [i for i in range(optode_np) if optode_tcphase_v[i] < 0]
        assert_qc(QC_BAD, optode_oxygen_qc_v, bad_i, "bad %s oyxgen" % instrument)
        optode_tcphase_v[bad_i] = BaseNetCDF.nc_nan
        optode_o2_v[bad_i] = BaseNetCDF.nc_nan

        ## NOTE: we use CTD temperature, not optode_tempc_v, and we use insitu density, not potential density
        inherit_qc(
            temp_cor_qc_v, optode_oxygen_qc_v, "temperature", "%s oxygen" % instrument
        )
        inherit_qc(
            salin_cor_qc_v, optode_oxygen_qc_v, "salinity", "%s oxygen" % instrument
        )
        optode_qc = QC_GOOD  # CONSIDER if no points sampled, mark overall qc as 'bad'?
        instrument_metadata_d["ancillary_variables"] = ancillary_variables  # update
        results_d.update(
            {
                results_do_var: optode_dissolved_oxygen_v,
                results_do_qc_var: optode_oxygen_qc_v,
                results_overall_qc_var: optode_qc,
            }
        )

        return 0
    return 1  # No data from any optode type to process


#
# Utility functions
# Conversion routines per 'TD269 Operating Manual Oxygen Optode 4330, 4835, 4831 (4th edition August 2012)' Appendix 6
# in addition to clarifications from Dana Swift, Argo
#
def optode_oxygen_foil(
    calphase_v,
    temp_v,
    oxygen_sat_sea_water_um_kg_v,
    conc_coef,
    C0_coef,
    C1_coef,
    C2_coef,
    C3_coef,
    C4_coef,
    C5_coef,
):
    """Calculates the oxygen concentration from the tcphase of the optode
    Input:
        calphase_v - calphase values
        temp_v - temperature readings
        oxygen_sat_sea_water_um_kg_v -- oxygen solubility
        conf_coef, CX_coef - lists of coefficients

    Returns:
        vector of oxygen concentration (uM/l)
    """

    C0 = np.polyval(C0_coef, temp_v)
    C1 = np.polyval(C1_coef, temp_v)
    C2 = np.polyval(C2_coef, temp_v)
    C3 = np.polyval(C3_coef, temp_v)
    C4 = np.polyval(C4_coef, temp_v)
    C5 = np.polyval(C5_coef, temp_v)
    # compute partial pressure of O2 in water (~200hPa near surface, that is, ~20% of 1013.25 hPa of air)
    partial_pressure_o2_v = C0 + calphase_v * (
        C1 + calphase_v * (C2 + calphase_v * (C3 + calphase_v * (C4 + calphase_v * C5)))
    )
    # hPa

    Kelvin_offset = 273.15  # for 0 deg C
    temp_K_v = temp_v + Kelvin_offset
    # vapour pressure of water in standard air at a given temperature (10s hPa)
    p_vapor_v = np.exp(52.57 - (6690.9 / (temp_K_v)) - 4.681 * np.log(temp_K_v))  # hPa
    # air saturation of oxygen given partial pressure of oxygen
    # 1013.25 hPa is nominal air pressure, 0.20946 is fraction of air that is oxygen (e.g, 21%)
    AirSaturation_v = partial_pressure_o2_v / (
        (1013.25 - p_vapor_v) * 0.20946
    )  # percent (hPa/(hPa - hPa)*%)
    oxygen_v = oxygen_sat_sea_water_um_kg_v * AirSaturation_v
    # Apply any linear correction that was logged on the instrument (typically none)
    oxygen_v = np.polyval(conc_coef, oxygen_v)
    return oxygen_v  # [uM/L]


def optode_oxygen_SVU(
    calphase_v,
    temp_cor_v,
    oxygen_sat_salinity_adjustment_v,
    conc_coef,
    SVUCoef0,
    SVUCoef1,
    SVUCoef2,
    SVUCoef3,
    SVUCoef4,
    SVUCoef5,
    SVUCoef6,
):
    """Calculates the oxygen concentration from the tcphase of the optode
    Input:
        calphase_v - calphase values
        temp_cor_v - temperature readings
        oxygen_sat_salinity_adjustment_v -- oxygen salinity adjustment
        conc_coef, SVUCoefX - various coefficients

    Returns:
        vector of oxygen concentration (uM/l)
    """

    # Use phase shift as proxy for luminescence decay time ratio
    # Then apply any linear scaling (post-calibration scaling: typically none)
    # Then pressure and salinity effects
    K_sv_v = SVUCoef0 + SVUCoef1 * temp_cor_v + SVUCoef2 * temp_cor_v * temp_cor_v
    P0_v = SVUCoef3 + SVUCoef4 * temp_cor_v
    PC_v = SVUCoef5 + SVUCoef6 * calphase_v
    # Uchida and Aandera state these units are uM/L so density is needed to convert to uM/kg in optode_correct_oxygen()
    optode_calphase_oxygen_v = (P0_v / PC_v - 1) / K_sv_v
    # [uM/L]
    # Apply any linear correction that was logged on the instrument (typically none)
    optode_calphase_oxygen_v = np.polyval(conc_coef, optode_calphase_oxygen_v)  # [uM/L]
    # Correct for salinity using just the Garcia and Gordon salinity term
    optode_calphase_oxygen_v *= oxygen_sat_salinity_adjustment_v
    return optode_calphase_oxygen_v  # [uM/L]


def optode_correct_oxygen(time_v, oxygen_v, pressure_v, density_v, drift_gain):
    """Corrects the oxygen reading for pressure and density effects

    Input:
        oxygen_v - oxygen concentration (uM/L)
        time_v - time of measurements
        pressure_v - observed pressure (dbar)
        density_v - potential density (kg/L) or None
        drift_gain - Johnson et al. gain factor

    Returns:
        vector of corrected oxygen concentrations (uM/kg)
    """
    p_v = pressure_v / 1000
    # Argo per Dana Swift, 2012 -- perform pressure compensation ala Uchida et al.2008
    # Previous value in aa3830 manual was 0.04, rather than 0.032, now superseded
    # TODO JSB From DG/BATS compare it looks like there is an additional deep pressure quadratic correction as well: ~0.0005 *(p_v*p_v)
    # oxygen_v = oxygen_v * (1.0 + 0.032*p_v) # compensate for pressure (3.2% lower response in 1km of water)
    # The quadratic term in pressure seems to match BATS shipboard casts much better below 2000m.
    oxygen_v = oxygen_v * (
        1.0 + 0.032 * p_v + 0.001 * (p_v * p_v)
    )  # compensate lower response under pressure

    # Account for slow diffusion of O2 across silicone light shield membrane (empirically about 30s)
    # NOTE: The float world never really sees this problem becaues they don't have dive and climb to compare to each other
    # TODO: Does this apply to the aa4330 like it does for the aa3830?
    # oxygen_v = oxygen_v + 30*Utils.ctr_1st_diff(oxygen_v,time_v)

    # Account for density effect to convert from uM/L to uM/kg
    oxygen_v = oxygen_v / (
        density_v / 1000.0
    )  # (uM/L)/(g/L/g/kg) == (uM/L)/(kg/L)== uM/kg
    oxygen_v *= drift_gain
    return oxygen_v


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
    if column_names is None:
        log_error(
            "Missing arguments for optode remap_engfile_columns_netcdf - version mismatch?"
        )
        return -1

    ret_val = 0

    if calib_consts is None:
        # This happens when reading scicon collected WETlabs data
        # unable to specify sg_calib_constants remapping variable
        log_debug(
            "No calib_consts provided - optode remap_engfile_columns_netcdf will skip reading the sg_calib_constants.m file"
        )
    else:
        # Check for any remapping specified in sg_calib_constants.m
        calib_remap_d = Utils.remap_dict_from_sg_calib(
            calib_consts, "remap_optode_eng_cols"
        )
        if calib_remap_d:
            ret_val = Utils.remap_column_names(calib_remap_d, column_names)

    return ret_val
