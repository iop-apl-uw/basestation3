#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2019, 2020, 2023 by University of Washington.  All rights reserved.
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
sbe43 basestation sensor extension
"""

import numpy as np

import BaseNetCDF
import QC
import Utils

from BaseLog import log_error, log_info, log_warning

nc_sbe43_data_info = "sbe43_data_info"  # from eng/scicon/gpctd
nc_sbe43_results_info = "sbe43_results_info"
nc_dim_sbe43_results = "sbe43_result_data_point"
nc_sbe43_time_var = "sbe43_results_time"


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
        nc_sbe43_data_info, "sbe43_data_point", "sbe43_time", "chemical", "sbe43"
    )
    BaseNetCDF.register_sensor_dim_info(
        nc_sbe43_results_info, nc_dim_sbe43_results, nc_sbe43_time_var, False, None
    )  # no instrument since it could be pumped
    init_dict[module_name] = {
        "netcdf_metadata_adds": {
            "sbe43": [
                False,
                "c",
                {
                    "long_name": "underway oxygen sensor",
                    "nodc_name": "oxygen sensor",
                    "make_model": "unpumped Seabird SBE43",
                },
                BaseNetCDF.nc_scalar,
            ],  # always scalar
            # SBE 43 O2 sensor coefficients (calib constants)
            "sg_cal_calibcomm_oxygen": [False, "c", {}, BaseNetCDF.nc_scalar],
            "sg_cal_Foffset": [
                False,
                "d",
                {"description": "SBE43 O2 frequency offset", "units": "Hz"},
                BaseNetCDF.nc_scalar,
            ],
            "sg_cal_Soc": [False, "d", {}, BaseNetCDF.nc_scalar],
            # for new style calibation alg
            "sg_cal_A": [False, "d", {}, BaseNetCDF.nc_scalar],
            "sg_cal_B": [False, "d", {}, BaseNetCDF.nc_scalar],
            "sg_cal_C": [False, "d", {}, BaseNetCDF.nc_scalar],
            "sg_cal_E": [False, "d", {}, BaseNetCDF.nc_scalar],
            # These are synonyms for A,B,C,E
            "sg_cal_o_a": [False, "d", {}, BaseNetCDF.nc_scalar],
            "sg_cal_o_b": [False, "d", {}, BaseNetCDF.nc_scalar],
            "sg_cal_o_c": [False, "d", {}, BaseNetCDF.nc_scalar],
            "sg_cal_o_e": [False, "d", {}, BaseNetCDF.nc_scalar],
            # for original calibration alg
            # See note about PCor (note capitalization) below
            "sg_cal_Pcor": [
                False,
                "d",
                {"description": "SBE43 pressure correction factor"},
                BaseNetCDF.nc_scalar,
            ],
            "sg_cal_Tcor": [
                False,
                "d",
                {"description": "SBE43 temperature correction factor"},
                BaseNetCDF.nc_scalar,
            ],
            "sg_cal_Boc": [False, "d", {}, BaseNetCDF.nc_scalar],
            "sg_cal_Voffset": [False, "d", {}, BaseNetCDF.nc_scalar],  # UNUSED
            # for the SBE43f (see AppNote 64)
            "sg_cal_tau20": [
                False,
                "d",
                {},
                BaseNetCDF.nc_scalar,
            ],  # Sensor time constant tau at 20defC, STP
            "sg_cal_D1": [
                False,
                "d",
                {},
                BaseNetCDF.nc_scalar,
            ],  # Pressure correction factor for tau calculation
            "sg_cal_D2": [
                False,
                "d",
                {},
                BaseNetCDF.nc_scalar,
            ],  # Temperature correction factor for tau calculation
            # NG: H1, H2, and H3 are hysteresis corrections factors but SBE does not describe how to use them...
            "sg_cal_comm_oxy_type": [False, "c", {}, BaseNetCDF.nc_scalar],
            "sbe43_ontime_a": [
                False,
                "d",
                {"description": "sbe43 total time turned on dive", "units": "secs"},
                BaseNetCDF.nc_scalar,
            ],
            "sbe43_samples_a": [
                False,
                "i",
                {"description": "sbe43 total number of samples taken dive"},
                BaseNetCDF.nc_scalar,
            ],
            "sbe43_timeouts_a": [
                False,
                "i",
                {"description": "sbe43 total number of samples timed out on dive"},
                BaseNetCDF.nc_scalar,
            ],
            "sbe43_ontime_b": [
                False,
                "d",
                {"description": "sbe43 total time turned on climb", "units": "secs"},
                BaseNetCDF.nc_scalar,
            ],
            "sbe43_samples_b": [
                False,
                "i",
                {"description": "sbe43 total number of samples taken climb"},
                BaseNetCDF.nc_scalar,
            ],
            "sbe43_timeouts_b": [
                False,
                "i",
                {"description": "sbe43 total number of samples timed out on climb"},
                BaseNetCDF.nc_scalar,
            ],
            # SBE43 sensor inputs
            # DEAD (v66) 'eng_sbe43_o2_freq' : [False, 'd', {'_FillValue':nc_nan, 'units':'Hz', 'description':'As reported by instrument'}, (nc_sg_data_info,)], # transient name for O2Freq
            "eng_sbe43_O2Freq": [
                False,
                "d",
                {
                    "_FillValue": BaseNetCDF.nc_nan,
                    "units": "Hz",
                    "description": "As reported by instrument",
                    "instrument": "sbe43",
                },
                (BaseNetCDF.nc_sg_data_info,),
            ],
            # NOTE gpctd sbe43 is declared as in payload_ext.py
            # The gpctd does all the ml/L corrections itself so sbe43_dissolved_oxygen is a copy of gpctd_oxygen
            # scicon
            "sbe43_o2Freq": [
                False,
                "d",
                {
                    "_FillValue": BaseNetCDF.nc_nan,
                    "units": "Hz",
                    "description": "As reported by instrument",
                    "instrument": "sbe43",
                },
                (nc_sbe43_data_info,),
            ],
            "sbe43_time": [
                True,
                "d",
                {
                    "standard_name": "time",
                    "units": "seconds since 1970-1-1 00:00:00",
                    "description": "SBE43 time in GMT epoch format",
                },
                (nc_sbe43_data_info,),
            ],
            # SBE43 sensor outputs
            nc_sbe43_time_var: [
                True,
                "d",
                {
                    "standard_name": "time",
                    "units": "seconds since 1970-1-1 00:00:00",
                    "description": "SBE43 time in GMT epoch format",
                },
                (nc_sbe43_results_info,),
            ],
            "sbe43_dissolved_oxygen": [
                True,
                "d",
                {
                    "_FillValue": BaseNetCDF.nc_nan,
                    "standard_name": "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
                    "units": "micromoles/kg",
                    "description": "Oxygen concentration corrected for salinity",
                },
                (nc_sbe43_results_info,),
            ],
            "sbe43_dissolved_oxygen_qc": [
                False,
                QC.nc_qc_type,
                {
                    "units": "qc_flag",
                    "description": "Whether to trust each SBE43 dissolved oxygen value",
                },
                (nc_sbe43_results_info,),
            ],
            "SBE43_qc": [
                False,
                QC.nc_qc_type,
                {
                    "units": "qc_flag",
                    "description": "Whether to trust the SBE43 results",
                },
                BaseNetCDF.nc_scalar,
            ],
        }
    }
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

    # Old name(s)
    sbe43_o2_freq = datafile.remove_col("O2Freq")

    if sbe43_o2_freq is None:
        sbe43_o2_freq = datafile.remove_col("o2_freq")

    if sbe43_o2_freq is None:
        sbe43_o2_freq = datafile.remove_col("sbe43.o2_freq")

    # New name
    if sbe43_o2_freq is None:
        sbe43_o2_freq = datafile.remove_col("sbe43.O2Freq")

    if sbe43_o2_freq is not None:
        for i in range(len(sbe43_o2_freq)):
            if np.isfinite(sbe43_o2_freq[i]):
                sbe43_o2_freq[i] = 4000000.0 / (sbe43_o2_freq[i] / 255.0)

        datafile.eng_cols.append("sbe43.O2Freq")

        datafile.eng_dict["sbe43.O2Freq"] = sbe43_o2_freq
        return 0

    return 1


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
        "O2Freq": "sbe43_O2Freq",
        "sbe43_o2_freq": "sbe43_O2Freq",
        "o2_freq": "sbe43_O2Freq",
    }
    return Utils.remap_column_names(replace_dict, column_names)


def sensor_data_processing(base_opts, module, l=None, eng_f=None, calib_consts=None):
    """
    Called from MakeDiveProfiles.py to do sensor specific processing

    Arguments:
    l - MakeDiveProfiles locals() dictionary
    eng_f - engineering file
    calib_constants - sg_calib_constants object

    Returns:
     0 - match found and processed
     1 - no match found
    -1 - error during processing
    """
    if (
        l is None
        or eng_f is None
        or calib_consts is None
        or "results_d" not in l
        or "nc_info_d" not in l
    ):
        log_error("Missing arguments for sensor_data_processing - version mismatch?")
        return -1

    results_d = l["results_d"]
    nc_info_d = l["nc_info_d"]
    sbe43_instrument_metadata_d = BaseNetCDF.fetch_instrument_metadata(
        nc_sbe43_data_info
    )
    if "ancillary_variables" in sbe43_instrument_metadata_d:
        del sbe43_instrument_metadata_d["ancillary_variables"]  # eliminate

    # needed on most paths below
    # sg_np = l["sg_np"]
    sg_epoch_time_s_v = l["sg_epoch_time_s_v"]

    SBE43_qc = QC.QC_GOOD  # assume the best
    (eng_SBE43_present, sbe43_o2_freq) = eng_f.find_col(
        ["o2_freq", "sbe43_o2_freq", "sbe43_O2Freq"]
    )
    if eng_SBE43_present:
        sbe43_time_s_v = sg_epoch_time_s_v
        sbe43_results_dim = BaseNetCDF.nc_mdp_data_info[BaseNetCDF.nc_sg_data_info]
    elif "gpctd_oxygen" in results_d:
        if "valid_gpctd_oxygen_v" in l:
            # reduced against reduced
            sbe43_o2_freq = l["valid_gpctd_oxygen_v"]
            sbe43_time_s_v = l["ctd_epoch_time_s_v"]
            sbe43_results_dim = BaseNetCDF.nc_mdp_data_info[
                BaseNetCDF.nc_ctd_results_info
            ]
        else:
            # raw against raw
            sbe43_o2_freq = results_d["gpctd_oxygen"]
            sbe43_time_s_v = results_d["gpctd_time"]
            sbe43_results_dim = BaseNetCDF.nc_mdp_data_info[
                BaseNetCDF.nc_gpctd_data_info
            ]
        eng_SBE43_present = True
    else:
        log_error("SBE43 on scicon NYI")
        return 1
        # try:
        #     sbe43_o2_freq = results_d["sbe43_o2Freq"]  # try from scicon
        #     sbe43_time_s_v = results_d["sbe43_time"]
        #     sbe43_results_dim = BaseNetCDF.nc_mdp_data_info[
        #         BaseNetCDF.nc_sbe43_data_info
        #     ]
        #     eng_SBE43_present = True
        # except KeyError:
        #     return 1  # nothing to do....

    if eng_SBE43_present:
        sbe43_np = len(sbe43_time_s_v)
        try:
            # ctd_np = l["ctd_np"]
            ctd_epoch_time_s_v = l["ctd_epoch_time_s_v"]
            temp_cor_v = l["temp_cor_v"]
            temp_cor_qc_v = l["temp_cor_qc_v"]
            # NOTE: SBE43 corrections use  44.6596 rather than 44.6145 as o2_molar_mass
            oxygen_sat_um_kg_v = results_d["dissolved_oxygen_sat"]
            ctd_press_v = l["ctd_press_v"]
            # hdm_qc = results_d["hdm_qc"]
            speed_cm_s_v = results_d["speed"]
            # speed_qc_v = results_d[
            #     "speed_qc"
            # ]  # unused but should drop bad points below?
            # See addition of speed below, if used
            ancillary_variables = "temperature ctd_press dissolved_oxygen_sat density"
        except KeyError:
            log_error("Missing variables for SBE43 conversion - bailing out", "exc")
            return -1
        # no need to restrict data to ctd_epoch_time_s_v
        # this was done in MDP

        if sbe43_results_dim != nc_info_d[BaseNetCDF.nc_ctd_results_info]:
            temp_cor_v = Utils.interp1d(
                ctd_epoch_time_s_v, temp_cor_v, sbe43_time_s_v, kind="linear"
            )
            temp_cor_qc_v = Utils.interp1d(
                ctd_epoch_time_s_v, temp_cor_qc_v, sbe43_time_s_v, kind="nearest"
            )
            oxygen_sat_um_kg_v = Utils.interp1d(
                ctd_epoch_time_s_v, oxygen_sat_um_kg_v, sbe43_time_s_v, kind="linear"
            )
            ctd_press_v = Utils.interp1d(
                ctd_epoch_time_s_v, ctd_press_v, sbe43_time_s_v, kind="linear"
            )
            # Are the NaNs from QC_BAD points interpolated properly?
            speed_cm_s_v = Utils.interp1d(
                ctd_epoch_time_s_v, speed_cm_s_v, sbe43_time_s_v, kind="linear"
            )
            ctd_epoch_time_s_v = sbe43_time_s_v

        Kelvin_offset = 273.15  # for 0 deg C
        temp_cor_K_v = temp_cor_v + Kelvin_offset
        oxygen_qc_v = QC.initialize_qc(sbe43_np, QC.QC_GOOD)
        QC.assert_qc(
            QC.QC_UNSAMPLED,
            oxygen_qc_v,
            [i for i in range(sbe43_np) if np.isnan(sbe43_o2_freq[i])],
            "unsampled SBE43 oyxgen",
        )
        QC.inherit_qc(
            temp_cor_qc_v, oxygen_qc_v, "temperature", "SBE43 oxygen"
        )  # really?
        # NOTE: See note about PCor in MDP:load_dive_profile_data()

        try:
            Soc = calib_consts["Soc"]
            Foffset = calib_consts["Foffset"]
            try:
                coefs = [1.0, calib_consts["A"], calib_consts["B"], calib_consts["C"]]
                E = calib_consts["E"]
                ancillary_variables = (
                    ancillary_variables
                    + " sg_cal_Soc sg_cal_Foffset sg_cal_A sg_cal_B sg_cal_C sg_cal_E"
                )
            except KeyError:
                try:  # try for the synonyms...
                    coefs = [
                        1.0,
                        calib_consts["o_a"],
                        calib_consts["o_b"],
                        calib_consts["o_c"],
                    ]
                    E = calib_consts["o_e"]
                    ancillary_variables = (
                        ancillary_variables
                        + " sg_cal_Soc sg_cal_Foffset sg_cal_o_a sg_cal_o_b sg_cal_o_c sg_cal_o_e"
                    )
                except KeyError as exc:
                    raise KeyError from exc  # try the old style conversion below

            tau_T_P_v = np.zeros(
                sbe43_np, np.float64
            )  # no improvement to O2 response in large gradients
            try:
                tau20 = calib_consts["Tau20"]
                D1 = calib_consts["D1"]
                D2 = calib_consts["D2"]
                ancillary_variables = (
                    ancillary_variables + " sg_cal_Tau20 sg_cal_D1 sg_cal_D2"
                )
                ctd_time_s_v = (
                    ctd_epoch_time_s_v - ctd_epoch_time_s_v[0]
                )  # elapsed time of measurement
                # See SBE appnote 64.2
                log_info(
                    f"{np.shape(ctd_press_v)} {np.shape(ctd_time_s_v)} {np.shape(sbe43_o2_freq)}"
                )
                tau_T_P_v = (
                    tau20
                    * np.exp(D1 * ctd_press_v + D2 * (ctd_time_s_v - 20))
                    * Utils.ctr_1st_diff(sbe43_o2_freq, ctd_time_s_v)
                )
            except KeyError:
                pass  # typical case...no worries and no warning?
            except KeyError:
                log_warning(
                    "SBE43 O2 data found but calibration constant(s) missing - skipping SBE43 O2 corrections"
                )
                return -1
            SBE43_qc = QC.QC_GOOD
            coefs.reverse()
            try:
                oxygen_um_kg_v = (
                    Soc
                    * (sbe43_o2_freq + Foffset + tau_T_P_v)
                    * np.polyval(coefs, temp_cor_v)
                    * (oxygen_sat_um_kg_v * np.exp(E * ctd_press_v / temp_cor_K_v))
                )
            except:
                log_error(
                    "Failed to process SBE43 O2 data skipping SBE43 O2 corrections",
                    "exc",
                )
                return -1

        except KeyError:
            try:  # old style
                Soc = calib_consts["Soc"]
                Foffset = calib_consts["Foffset"]
                # NOTE in some old CCE sg_calib_constants PCor=0 (sic) is a flag to use the new alg above
                # We remap PCor to Pcor in the upgrade code
                # but in both cases TCor/Tcor is missing so this code would fail, as we would want
                Pcor = calib_consts["Pcor"]
                Tcor = calib_consts["Tcor"]
                Boc = calib_consts["Boc"]
                ancillary_variables = (
                    ancillary_variables
                    + " sg_cal_Soc sg_cal_Foffset sg_cal_Pcor sg_cal_Tcor sg_cal_Boc"
                )

                SBE43_qc = QC.QC_GOOD
                oxygen_um_kg_v = (
                    (Soc * (sbe43_o2_freq + Foffset) + Boc * np.exp(-0.03 * temp_cor_v))
                    * np.exp(Tcor * temp_cor_v)
                    * oxygen_sat_um_kg_v
                    * np.exp(Pcor * ctd_press_v)
                )
            except KeyError:
                log_warning(
                    "SBE43 O2 data found but calibration constant(s) missing - skipping SBE43 O2 corrections"
                )
                return -1

        # if False and hdm_qc == QC_GOOD:
        #     # Disabled until more investigation can confirm and characterize the effect
        #     # per Nicholson 2009 find speeds slower than 10cm/s (or bad) and eliminate them, marking oxygen_qc bad
        #     too_slow_i_v = [i for i in range(sbe43_np) if speed_cm_s_v[i] < 10]
        #     assert_qc(QC_BAD, oxygen_qc_v, too_slow_i_v, "slow flow in SBE43")
        #     # per Nicolson 2009 and CCE correct for boundary layer effects in the SBE43 tube
        #     r_meas_v = oxygen_um_kg_v / oxygen_sat_um_kg_v
        #     # Original coefficients were 0.25 and 20.0 from CCE
        #     # These are from Noel's reworking of the data
        #     # These coefficients will likely change after Stn P investigation against optode data
        #     r_act_v = r_meas_v / (1 - 0.35 * exp(-speed_cm_s_v / 18.7573))
        #     oxygen_um_kg_v = r_act_v * oxygen_sat_um_kg_v
        #     ancillary_variables = ancillary_variables + " speed"

    BaseNetCDF.assign_dim_info_dim_name(
        nc_info_d, nc_sbe43_results_info, sbe43_results_dim
    )
    BaseNetCDF.assign_dim_info_size(nc_info_d, nc_sbe43_results_info, sbe43_np)
    sbe43_instrument_metadata_d["ancillary_variables"] = ancillary_variables
    results_d.update(
        {
            nc_sbe43_time_var: sbe43_time_s_v,
            "sbe43_dissolved_oxygen": oxygen_um_kg_v,  # uM/kg
            "sbe43_dissolved_oxygen_qc": oxygen_qc_v,
            "SBE43_qc": SBE43_qc,
        }
    )
    return 0
