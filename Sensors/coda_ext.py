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

import numpy as np

import BaseNetCDF
import Utils
import Utils2
from BaseLog import log_error, log_warning
from QC import (
    # QC_BAD,
    QC_GOOD,
    QC_UNSAMPLED,
    assert_qc,
    inherit_qc,
    initialize_qc,
    nc_qc_type,
)

instruments = ["codaTODO", "codaTODO2"]
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

    meta_data_adds = {}

    for instrument in instruments:
        # Calibration string
        meta_data_adds[f"{BaseNetCDF.nc_sg_cal_prefix}calibcomm_{instrument}"] = [
            False,
            "c",
            {},
            BaseNetCDF.nc_scalar,
        ]
        meta_data_adds[f"{BaseNetCDF.nc_sg_cal_prefix}{instrument}_c0"] = [
            False,
            "d",
            {},
            BaseNetCDF.nc_scalar,
        ]

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
        results_info = f"{instrument}_results_info"
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
        eng_uncomp_o2_var = f"{instrument}_uncompensated_O2"
        md_var = "%s%s" % (BaseNetCDF.nc_sg_eng_prefix, eng_uncomp_o2_var)
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

        eng_comp_o2_var = f"{instrument}_compensated_O2"
        md_var = f"{BaseNetCDF.nc_sg_eng_prefix}{eng_comp_o2_var}"
        meta_data_adds[md_var] = [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/L",
                "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
                + "assuming coda temperature but with fixed pressure and salinity correction",
                "instrument": instrument,
            },
            (BaseNetCDF.nc_sg_data_info,),
        ]
        meta_data_adds["%s%s_O2_sat" % eng_tuple] = [
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
        scicon_uncomp_o2_var = "%s_uncompensated_O2" % instrument
        meta_data_adds[scicon_uncomp_o2_var] = [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/L",
                "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
                + " assuming coda temperature but without pressure or salinity correction",
                "instrument": instrument,
            },
            (data_info,),
        ]
        scicon_comp_o2_var = "%s_compensated_O2" % instrument
        meta_data_adds[scicon_comp_o2_var] = [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "micromoles/L",
                "description": "Dissolved oxygen as reported by the instument, based on on-board calibration data,"
                + " assuming coda temperature with fixed pressure and salinity correction",
                "instrument": instrument,
            },
            (data_info,),
        ]
        meta_data_adds["%s_O2_sat" % instrument] = [
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
        results_do_var = f"{instrument}_dissolved_oxygen"
        meta_data_adds[results_do_var] = [
            "f",
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "standard_name": "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
                "units": "micromoles/kg",
                "description": "Dissolved oxygen concentration, calculated from code uncompensated OS corrected for salininty and depth",
            },
            (results_info,),
        ]
        results_do_qc_var = "%s_dissolved_oxygen_qc" % instrument
        meta_data_adds[results_do_qc_var] = [
            False,
            nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each coda dissolved oxygen value",
            },
            (results_info,),
        ]

        results_overall_qc_var = f"{instrument}_qc"
        meta_data_adds[results_overall_qc_var] = [
            False,
            nc_qc_type,
            {
                "units": "qc_flag",
                "description": f"Whether to trust the {instrument} results",
            },
            BaseNetCDF.nc_scalar,
        ]

        meta_data_adds |= Utils2.add_scicon_stats(instrument)

        canonical_data_to_results_d[instrument] = [
            data_info,
            data_time_var,
            eng_uncomp_o2_var,
            scicon_time_var,
            scicon_uncomp_o2_var,
            results_time_var,
            results_info,
            results_do_var,
            results_do_qc_var,
            results_overall_qc_var,
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

    instrument = "codaTODO"
    replace_dict = {
        f"{instrument}_doxy21": f"{instrument}_compensated_O2",
        f"{instrument}_doxy22": f"{instrument}_O2_sat",
        f"{instrument}_doxy24": f"{instrument}_uncompensated_O2",
        f"{instrument}_opt05": f"{instrument}_phase",
    }
    return Utils.remap_column_names(replace_dict, column_names)


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
        ancillary_variables = "temperature salinity ctd_pressure density"
    except KeyError:
        required_vars_present = False

    # Now see if we have an instrument aboard
    # if so process its data and exit
    for instrument, cd in canonical_data_to_results_d.items():
        (
            data_info,
            _,  # data_time_var,
            eng_uncomp_o2_var,
            scicon_time_var,
            scicon_uncomp_o2_var,
            results_time_var,
            results_info,
            results_do_var,
            results_do_qc_var,
            results_overall_qc_var,
        ) = cd

        instrument_metadata_d = BaseNetCDF.fetch_instrument_metadata(data_info)
        if "ancillary_variables" in instrument_metadata_d:
            del instrument_metadata_d["ancillary_variables"]  # eliminate

        (eng_coda_present, coda_uncomp_o2_v) = eng_f.find_col([eng_uncomp_o2_var])
        if eng_coda_present:
            if not required_vars_present:
                log_error(
                    f"Missing variables for {instrument} eng correction - bailing out",
                    "exc",
                )
                return -1
            coda_time_s_v = sg_epoch_time_s_v
            coda_results_dim = BaseNetCDF.nc_mdp_data_info[BaseNetCDF.nc_sg_data_info]
        else:
            try:
                # See if we have data from scicon
                coda_uncomp_o2_v = results_d[scicon_uncomp_o2_var]
                coda_time_s_v = results_d[scicon_time_var]
                coda_results_dim = BaseNetCDF.nc_mdp_data_info[data_info]
            except KeyError:
                continue  # no data from this coda

            # We have all the coda data.  Do we have the rest?
            if not required_vars_present:
                log_error(
                    f"Missing variables for {instrument} scicon correction - bailing out",
                    "exc",
                )
                return -1

        # We have coda data
        if f"{instrument}_c0" not in calib_consts:
            log_warning(
                f"Found data {instrument} coda data, but {instrument}_c0 not found in sg_calib_constants.m - not correcting {instrument} data"
            )
            return -1

        # First expand some other data we need for conversions to O2 concentration:
        if coda_results_dim != nc_info_d[BaseNetCDF.nc_ctd_results_info]:
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
                coda_time_s_v,
                kind="linear",
            )
            temp_cor_qc_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                temp_cor_qc_v[sampled_pts_i],
                coda_time_s_v,
                kind="nearest",
            )
            salin_cor_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                salin_cor_v[sampled_pts_i],
                coda_time_s_v,
                kind="linear",
            )
            salin_cor_qc_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                salin_cor_qc_v[sampled_pts_i],
                coda_time_s_v,
                kind="nearest",
            )
            ctd_pressure_v = Utils.interp1d(
                ctd_epoch_time_s_v[sampled_pts_i],
                ctd_pressure_v[sampled_pts_i],
                coda_time_s_v,
                kind="linear",
            )

        coda_np = len(coda_time_s_v)
        BaseNetCDF.assign_dim_info_dim_name(nc_info_d, results_info, coda_results_dim)
        BaseNetCDF.assign_dim_info_size(nc_info_d, results_info, coda_np)

        # Calculate compensated O2

        # Equation 3.a
        Fcp = 1.0 + (ctd_pressure_v * calib_consts[f"{instrument}_c0"])

        # Equation 3.b
        Ts = np.log((298.15 - temp_cor_v) / (273.15 + temp_cor_v))

        # Equation 3.c
        Gb = [-6.24097e-3, -6.93498e-3, -6.90358e-3, -4.29155e-3]
        Gc0 = -3.11680e-7

        tmp = 0.0
        for ii in range(4):
            tmp += Gb[ii] * np.power(Ts, ii)

        Fcs = np.exp((salin_cor_v * tmp) + (Gc0 * np.power(salin_cor_v, 2)))

        # Equation 3
        coda_comp_o2_v = coda_uncomp_o2_v * Fcs * Fcp

        coda_oxygen_qc_v = initialize_qc(coda_np, QC_GOOD)
        # CONSIDER we have seen timed out optode; can/should we distinguish it as QC_MISSING?
        # Test unsampled (nan) before asserting nan on bad points
        assert_qc(
            QC_UNSAMPLED,
            coda_oxygen_qc_v,
            [i for i in range(coda_np) if np.isnan(coda_uncomp_o2_v[i])],
            "unsampled optode oyxgen",
        )
        # bad_i = [i for i in range(coda_np) if coda_tcphase_v[i] < 0]
        # assert_qc(QC_BAD, coda_oxygen_qc_v, bad_i, "bad %s oyxgen" % instrument)
        # coda_tcphase_v[bad_i] = BaseNetCDF.nc_nan
        # coda_o2_v[bad_i] = BaseNetCDF.nc_nan

        ## NOTE: we use CTD temperature, not coda_tempc_v, and we use insitu density, not potential density
        inherit_qc(
            temp_cor_qc_v, coda_oxygen_qc_v, "temperature", "%s oxygen" % instrument
        )
        inherit_qc(
            salin_cor_qc_v, coda_oxygen_qc_v, "salinity", "%s oxygen" % instrument
        )
        coda_qc = QC_GOOD  # CONSIDER if no points sampled, mark overall qc as 'bad'?
        instrument_metadata_d["ancillary_variables"] = ancillary_variables  # update

        results_d.update(
            {
                results_time_var: coda_time_s_v,
                results_do_var: coda_comp_o2_v,
                results_do_qc_var: coda_oxygen_qc_v,
                results_overall_qc_var: coda_qc,
            }
        )

    return 0
