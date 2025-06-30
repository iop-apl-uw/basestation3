#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2023, 2025 by University of Washington.  All rights reserved.
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
aa3830 basestation sensor extension
"""

import numpy as np

import BaseNetCDF
import QC
import Utils
import Utils2
from BaseLog import log_debug, log_error, log_warning

nc_aa3830_data_info = "aa3830_data_info"  # from eng/scicon
nc_dim_aa3830_data_point = "aa3830_data_point"
nc_aa3830_data_time = "aa3830_time"

nc_aa3830_results_info = "aa3830_results_info"
nc_dim_aa3830_results = "aa3830_result_data_point"
nc_aa3830_time_var = "aanderaa3830_results_time"


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
        nc_aa3830_data_info,
        nc_dim_aa3830_data_point,
        nc_aa3830_data_time,
        "chemical",
        "aa3830",
    )
    BaseNetCDF.register_sensor_dim_info(
        nc_aa3830_results_info,
        nc_dim_aa3830_results,
        nc_aa3830_time_var,
        False,
        "aa3830",
    )
    meta_data_adds = {
        # AA3830 (and some AA4330) optode coefficients
        "sg_cal_calibcomm_optode": [
            False,
            "c",
            {},
            BaseNetCDF.nc_scalar,
        ],  # aa3830 and aa4330
        "sg_cal_optode_C00Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C01Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C02Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C03Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C10Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C11Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C12Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C13Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C20Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C21Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C22Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C23Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C30Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C31Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C32Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C33Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C40Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C41Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C42Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        "sg_cal_optode_C43Coef": [False, "d", {}, BaseNetCDF.nc_scalar],
        # instrument
        "aa3830": [
            False,
            "c",
            {
                "long_name": "underway optode",
                "nodc_name": "optode",
                "make_model": "Aanderaa 3830",
            },
            BaseNetCDF.nc_scalar,
        ],  # always scalar
        # AA3830 sensor inputs
        # NOTE since we have ml/l this is a volume fraction we have 1e-3 ml/l
        # The new correction will change this to umoles/m^3 so that will change the name to mole_concentration_of_dissolved_molecular_oxygen_in_sea_water
        # Add instrument explicitly for eng file data since they all share the same dim info
        "eng_aa3830_O2": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/L",
                "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data, assuming optode temperature but without depth or salinity correction",
                "instrument": "aa3830",
            },
            (BaseNetCDF.nc_sg_data_info,),
        ],
        "eng_aa3830_temp": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "standard_name": "temperature_of_sensor_for_oxygen_in_sea_water",
                "units": "degrees_Celsius",
                "description": "As reported by the instrument",
                "instrument": "aa3830",
            },
            (BaseNetCDF.nc_sg_data_info,),
        ],
        "eng_aa3830_dphase": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "description": "As reported by the instrument",
                "instrument": "aa3830",
            },
            (BaseNetCDF.nc_sg_data_info,),
        ],
        "eng_aa3830_bphase": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "description": "As reported by the instrument",
                "instrument": "aa3830",
            },
            (BaseNetCDF.nc_sg_data_info,),
        ],
        # from scicon eng file
        nc_aa3830_data_time: [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "AA3830 time in GMT epoch format",
            },
            (nc_aa3830_data_info,),
        ],
        "aa3830_O2": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/L",
                "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data, assuming optode temperature but without depth or salinity correction",
            },
            (nc_aa3830_data_info,),
        ],
        "aa3830_temp": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "standard_name": "temperature_of_sensor_for_oxygen_in_sea_water",
                "units": "degrees_Celsius",
                "description": "As reported by the instrument",
            },
            (nc_aa3830_data_info,),
        ],
        "aa3830_dphase": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "description": "As reported by the instrument",
            },
            (nc_aa3830_data_info,),
        ],
        "aa3830_bphase": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "description": "As reported by the instrument",
            },
            (nc_aa3830_data_info,),
        ],
        # derived results
        # Why, oh why, didn't we name these aa3830_dissolved_oxygen etc?
        nc_aa3830_time_var: [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "time for Aanderaa 3830 in GMT epoch format",
            },
            (nc_aa3830_results_info,),
        ],
        "aanderaa3830_dissolved_oxygen": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "standard_name": "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
                "units": "micromoles/kg",
                "description": "Oxygen concentration, calculated from optode dphase, corrected for salinity",
            },
            (nc_aa3830_results_info,),
        ],
        "aanderaa3830_dissolved_oxygen_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each optode dissolved oxygen value",
            },
            (nc_aa3830_results_info,),
        ],
        "aanderaa3830_instrument_dissolved_oxygen": [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/kg",
                "description": "Dissolved oxygen concentration reported from optode corrected for salinity",
            },
            (nc_aa3830_results_info,),
        ],
        "aanderaa3830_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the Aanderaa 3880 results",
            },
            BaseNetCDF.nc_scalar,
        ],
        "aanderaa3830_drift_gain": [
            False,
            "d",
            {"description": "Drift gain correction for the Aanderaa 3880"},
            BaseNetCDF.nc_scalar,
        ],
    }
    meta_data_adds |= Utils2.add_scicon_stats("aa3830")
    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}

    return 0


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
    aa3830_O2 = datafile.remove_col("O2")
    aa3830_temp = datafile.remove_col("temp")
    aa3830_dphase = datafile.remove_col("dphase")

    # New name
    if aa3830_O2 is None:
        aa3830_O2 = datafile.remove_col("aa3830.O2")
        aa3830_temp = datafile.remove_col("aa3830.temp")
        aa3830_dphase = datafile.remove_col("aa3830.dphase")

    if aa3830_O2 is not None:
        aa3830_O2 = aa3830_O2 / 100.0
        aa3830_temp = (aa3830_temp / 100.0) - 10.0
        aa3830_dphase = aa3830_dphase / 100.0
        datafile.eng_cols.append("aa3830.O2")
        datafile.eng_cols.append("aa3830.temp")
        datafile.eng_cols.append("aa3830.dphase")
        datafile.eng_dict["aa3830.O2"] = aa3830_O2
        datafile.eng_dict["aa3830.temp"] = aa3830_temp
        datafile.eng_dict["aa3830.dphase"] = aa3830_dphase
        return 0

    return 1


def remap_engfile_columns_netcdf(base_opts, module, calib_constants, column_names=None):
    """
    Called from MakeDiveProfiles.py to remap column headers from older .eng files to
    current naming standards for netCDF output

    Returns:
    0 - match found and processed
    1 - no match found
    """
    replace_dict = {"O2": "aa3830_O2", "temp": "aa3830_temp", "dphase": "aa3830_dphase"}
    return Utils.remap_column_names(replace_dict, column_names)


# pylint: disable=unused-argument
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
    aa3830_instrument_metadata_d = BaseNetCDF.fetch_instrument_metadata(
        nc_aa3830_data_info
    )
    if "ancillary_variables" in aa3830_instrument_metadata_d:
        del aa3830_instrument_metadata_d["ancillary_variables"]  # eliminate

    required_vars_present = True
    try:
        results_d = l_dict["results_d"]
        nc_info_d = l_dict["nc_info_d"]

        sg_np = l_dict["sg_np"]
        sg_epoch_time_s_v = l_dict["sg_epoch_time_s_v"]

        # these should be ctd_np long
        # ctd_np = l_dict["ctd_np"]
        ctd_epoch_time_s_v = l_dict["ctd_epoch_time_s_v"]
        temp_cor_v = l_dict["temp_cor_v"]
        temp_cor_qc_v = l_dict["temp_cor_qc_v"]
        salin_cor_v = l_dict["salin_cor_v"]
        salin_cor_qc_v = l_dict["salin_cor_qc_v"]
        ctd_depth_m_v = l_dict["ctd_depth_m_v"]
        ctd_density_v = l_dict["density_insitu_v"]
        ancillary_variables = "temperature salinity ctd_depth density_insitu"
    except KeyError:
        required_vars_present = False

    (eng_aa3830_present, aa3830_o2_v) = eng_f.find_col(["O2", "aa3830_O2"])
    if eng_aa3830_present:
        if not required_vars_present:
            log_error(
                "Missing variables for aa3830 eng correction - bailing out", "exc"
            )
            return -1
        (_, aa3830_dphase_v) = eng_f.find_col(["dphase", "aa3830_dphase"])
        # UNUSED (ignore, aa3830_tempc_v)   = eng_f.find_col(['temp','aa3830_temp']) # use CTD temp instead
        ancillary_variables = ancillary_variables + " eng_aa3830_dphase eng_aa3830_O2"
        aa3830_time_s_v = sg_epoch_time_s_v
        aa3830_np = sg_np
        aa3830_results_dim = BaseNetCDF.nc_mdp_data_info[BaseNetCDF.nc_sg_data_info]
    else:
        try:
            # See if we have data from scicon
            aa3830_o2_v = results_d["aa3830_O2"]
            aa3830_dphase_v = results_d["aa3830_dphase"]
            # UNUSED aa3830_tempc_v = results_d['aa3830_temp'] # use CTD temp instead
            aa3830_time_s_v = results_d["aa3830_time"]
            ancillary_variables = ancillary_variables + " aa3830_dphase aa3830_O2"
            aa3830_results_dim = BaseNetCDF.nc_mdp_data_info[nc_aa3830_data_info]
            aa3830_np = len(aa3830_time_s_v)
            # We have all the optode data.  Do we have the rest?
            if not required_vars_present:
                log_error(
                    "Missing variables for aa3830 scicon correction - bailing out",
                    "exc",
                )
                return -1

        except KeyError:
            return 1  # No data to process

    # MDP automatically asserts instrument when writing
    # DEAD results_d['aa3830'] = 'aa3830' # instrument CONSIDER add calibcomm_oxygen

    # We have data from the instrument
    # First expand some other data we need for conversions to O2 concentration:
    if aa3830_results_dim != nc_info_d[BaseNetCDF.nc_ctd_results_info]:
        # interpolate the CTD data we need
        temp_cor_v = Utils.interp1d(
            ctd_epoch_time_s_v, temp_cor_v, aa3830_time_s_v, kind="linear"
        )
        temp_cor_qc_v = Utils.interp1d(
            ctd_epoch_time_s_v, temp_cor_qc_v, aa3830_time_s_v, kind="nearest"
        )
        salin_cor_v = Utils.interp1d(
            ctd_epoch_time_s_v, salin_cor_v, aa3830_time_s_v, kind="linear"
        )
        salin_cor_qc_v = Utils.interp1d(
            ctd_epoch_time_s_v, salin_cor_qc_v, aa3830_time_s_v, kind="nearest"
        )
        ctd_depth_m_v = Utils.interp1d(
            ctd_epoch_time_s_v, ctd_depth_m_v, aa3830_time_s_v, kind="linear"
        )
        ctd_density_v = Utils.interp1d(
            ctd_epoch_time_s_v, ctd_density_v, aa3830_time_s_v, kind="linear"
        )

    BaseNetCDF.assign_dim_info_dim_name(
        nc_info_d, nc_aa3830_results_info, aa3830_results_dim
    )
    BaseNetCDF.assign_dim_info_size(nc_info_d, nc_aa3830_results_info, aa3830_np)
    aa3830_instrument_metadata_d["ancillary_variables"] = (
        ancillary_variables  # checkpoint
    )

    # We have all variables needed; do we have the optode calibration constants?
    try:
        C0_coef = [
            calib_consts["optode_C00Coef"],
            calib_consts["optode_C01Coef"],
            calib_consts["optode_C02Coef"],
            calib_consts["optode_C03Coef"],
        ]
        C1_coef = [
            calib_consts["optode_C10Coef"],
            calib_consts["optode_C11Coef"],
            calib_consts["optode_C12Coef"],
            calib_consts["optode_C13Coef"],
        ]
        C2_coef = [
            calib_consts["optode_C20Coef"],
            calib_consts["optode_C21Coef"],
            calib_consts["optode_C22Coef"],
            calib_consts["optode_C23Coef"],
        ]
        C3_coef = [
            calib_consts["optode_C30Coef"],
            calib_consts["optode_C31Coef"],
            calib_consts["optode_C32Coef"],
            calib_consts["optode_C33Coef"],
        ]
        C4_coef = [
            calib_consts["optode_C40Coef"],
            calib_consts["optode_C41Coef"],
            calib_consts["optode_C42Coef"],
            calib_consts["optode_C43Coef"],
        ]
        ancillary_variables = ancillary_variables + " sg_cal_optode_C**Coef"
    except KeyError:
        log_warning(
            "Optode data found but calibration constant(s) missing - skipping optode corrections"
        )
        return 0

    # reverse is destructive so call this once before use in functions below so they can be called multiple times if need be
    C0_coef.reverse()
    C1_coef.reverse()
    C2_coef.reverse()
    C3_coef.reverse()
    C4_coef.reverse()

    # Johnson, Plant, Riser, Gilbert. 'Air oxygen calibration of oxygen optodes on a profiling float array' submitted, Journal of Atmospheric and Oceanic Technology 2015
    # The optode apparently drifts from its calibration when exposed to air but then stops drifting in (sea)water.  Investigation shows this is captured by a gain rather
    # than additive drift, that is, the drift is proportional to the O2 signal. Johnson et al. compute the gain by comparing the output of the sensor in air with the expected
    # O2 concentration given temperature and pressure.
    drift_gain = 1.0  # assume no drift
    try:
        # See defns in aa4330_ext.py
        optode_st_calphase = calib_consts[
            "optode_st_calphase"
        ]  # use calphase so we can compute O2 based on foil or SVU in case of aa4330
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
            _,
            st_oxygen_sat_fresh_water_um_kg_v,
            _,
        ) = Utils.compute_oxygen_saturation(optode_st_temp, 0)
        optode_st_o2 = aa3830_dphase_oxygen(
            optode_st_calphase,
            optode_st_temp,
            C0_coef,
            C1_coef,
            C2_coef,
            C3_coef,
            C4_coef,
        )
        drift_gain = (st_oxygen_sat_fresh_water_um_kg_v / 1013.25) / (
            optode_st_o2 / optode_st_slp
        )
        log_debug(f"Optode drift gain = {drift_gain:f}")

    aa3830_instrument_dissolved_oxygen_v = aa3830_correct_oxygen(
        aa3830_time_s_v,
        aa3830_o2_v,
        temp_cor_v,
        salin_cor_v,
        ctd_depth_m_v,
        ctd_density_v,
        drift_gain,
    )
    results_d.update(
        {
            nc_aa3830_time_var: aa3830_time_s_v,
            "aanderaa3830_instrument_dissolved_oxygen": aa3830_instrument_dissolved_oxygen_v,
        }
    )

    aa3830_dphase_oxygen_v = aa3830_dphase_oxygen(
        aa3830_dphase_v, temp_cor_v, C0_coef, C1_coef, C2_coef, C3_coef, C4_coef
    )
    # NOTE: Wherever ctd_density_v (and temp/salin_cor_v) is QC_BAD we have NaN hence NaN in the dissolved_oxygen_v results
    # This *happens* to overlap with the oxygen_qc var above but might not
    # TODO We should explicitly look at the QC_BAD spots and nail those point
    aa3830_dissolved_oxygen_v = aa3830_correct_oxygen(
        aa3830_time_s_v,
        aa3830_dphase_oxygen_v,
        temp_cor_v,
        salin_cor_v,
        ctd_depth_m_v,
        ctd_density_v,
        drift_gain,
    )

    # Calculate the oxygen qc
    aa3830_oxygen_qc_v = QC.initialize_qc(aa3830_np, QC.QC_GOOD)
    # TODO we have seen timed out optode; can/should we distinguish it as QC_MISSING?
    QC.assert_qc(
        QC.QC_UNSAMPLED,
        aa3830_oxygen_qc_v,
        [i for i in range(aa3830_np) if np.isnan(aa3830_dphase_v[i])],
        "unsampled aa3830 oyxgen",
    )
    # NOTE: see comment in aa4330 about bad samples observed on scicon; we may need a similar test here but wait until we have an actual example

    ## NOTE: we use CTD temperature, not aa3830_tempc_v, and we use insitu density, not potential density
    QC.inherit_qc(temp_cor_qc_v, aa3830_oxygen_qc_v, "temperature", "optode oxygen")
    QC.inherit_qc(salin_cor_qc_v, aa3830_oxygen_qc_v, "salinity", "optode oxygen")
    aa3830_qc = QC.QC_GOOD

    aa3830_instrument_metadata_d["ancillary_variables"] = ancillary_variables  # update
    results_d.update(
        {
            "aanderaa3830_dissolved_oxygen": aa3830_dissolved_oxygen_v,
            "aanderaa3830_dissolved_oxygen_qc": aa3830_oxygen_qc_v,
            "aanderaa3830_qc": aa3830_qc,
            "aanderaa3830_drift_gain": drift_gain,
        }
    )

    return 1


#
# Utility functions
# Conversion routines per 'TD218 Operating Manual Oxygen Optode 3830 (April 2007)' Chapter 4
#
def aa3830_dphase_oxygen(dphase_v, temp_v, C0_coef, C1_coef, C2_coef, C3_coef, C4_coef):
    """Calculates the oxygen concentration from the dphase of the optode

    Input:
        dphase_v - dphase values
        temp_v - temperature readings
        CX_coef - lists of coeffients

    Returns:
        vector of oxygen concentration (uM/L)
    """
    C0 = np.polyval(C0_coef, temp_v)
    C1 = np.polyval(C1_coef, temp_v)
    C2 = np.polyval(C2_coef, temp_v)
    C3 = np.polyval(C3_coef, temp_v)
    C4 = np.polyval(C4_coef, temp_v)
    coeffs = [C0, C1, C2, C3, C4]
    coeffs.reverse()
    oxygen_v = np.polyval(coeffs, dphase_v)  # uM/L
    return oxygen_v


def aa3830_correct_oxygen(
    time_v, oxygen_v, temp_v, salin_v, depth_v, density_v, drift_gain
):
    """Corrects the oxygen reading for Salinity and Depth

    Input:
        oxygen_v - oxygen concentration (uM/L)
        temp_v - temperature readings
        salin_v - calculated salinity
        depth_v - observed depth, corrected for latitude
        density_v - potential density (kg/L)
        time_v - time of measreuments
        drift_gain - Johnson et al. gain factor

    Returns:
        vector of corrected oxygen concentrations (uM/kg)
    """
    _, _, oxygen_sat_salinity_adjustment_v = Utils.compute_oxygen_saturation(
        temp_v, salin_v
    )  # get scale factor
    oxygen_v = oxygen_v * oxygen_sat_salinity_adjustment_v  # scale for salinity ml/L
    # NOTE: CCE used 4% as the response factor
    oxygen_v = oxygen_v * (
        1.0 + ((0.032 * depth_v) / 1000.0)
    )  # compensate for pressure (3.2% lower response in 1km of water)
    # Account for slow diffusion of O2 across silicone light shield membrane (empirically about 30s)
    oxygen_v = oxygen_v + 30 * Utils.ctr_1st_diff(oxygen_v, time_v)
    oxygen_v = oxygen_v / (
        density_v / 1000.0
    )  # (uM/L)/(g/L/g/kg) == (uM/L)/(kg/L)== uM/kg
    oxygen_v *= drift_gain
    return oxygen_v
