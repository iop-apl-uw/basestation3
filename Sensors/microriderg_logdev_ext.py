#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2023, 2026 by University of Washington.  All rights reserved.
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
MicroRiderG basestation sensor extension
"""

import shutil

import numpy as np
from q2netcdf.q2netcdf import loadQfile

import BaseNetCDF
import LogFile
from BaseLog import log_debug, log_error, log_info


def init_logger(module_name, init_dict=None):
    """
    init_loggers

    returns:
    -1 - error in processing
     0 - success (data found and processed)
    """
    if init_dict is None:
        log_error("No datafile supplied for init_dict - version mismatch?")
        return -1

    nc_microriderg_time_info = "microriderg_time_info"
    nc_microriderg_freq_info = "microriderg_freq_info"
    nc_microriderg_despike_info = "microriderg_despike_info"
    nc_microriderg_ftime_info = "microriderg_ftime_info"

    BaseNetCDF.register_sensor_dim_info(
        nc_microriderg_time_info,
        "microriderg_time_point",
        None,
        True,
        None,
    )
    BaseNetCDF.register_sensor_dim_info(
        nc_microriderg_freq_info,
        "microriderg_freq_point",
        None,
        True,
        None,
    )
    BaseNetCDF.register_sensor_dim_info(
        nc_microriderg_despike_info,
        "microriderg_despike_point",
        None,
        True,
        None,
    )
    BaseNetCDF.register_sensor_dim_info(
        nc_microriderg_ftime_info,
        "microriderg_ftime_point",
        None,
        True,
        None,
    )
    LogFile.add_to_table_vars("$MR_0", "$MR_0_HEAD", ("msg",))
    # results are computed in MDP
    init_dict[module_name] = {
        "logger_prefix": "mr",
        "eng_file_reader": eng_file_reader,
        "netcdf_metadata_adds": {
            "microriderg": [
                False,
                "c",
                {
                    "long_name": "MicroRider-G",
                    # "nodc_name": "thermosalinograph",
                    # "make_model": "RBR Legato",
                },
                BaseNetCDF.nc_scalar,
            ],  # always scalar
            "log_MR_0__msg": [
                False,
                "c",
                {"description": "odas stats"},
                ("log_MR_0_info",),
            ],
            "log_MR_RECORDABOVE": [
                False,
                "d",
                {
                    "description": "Depth above above which data is recorded",
                    "units": "meters",
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_MR_PROFILE": [
                False,
                "d",
                {
                    "description": "Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_MR_XMITPROFILE": [
                False,
                "d",
                {
                    "description": "Which profile to transmit snippet file back to the basestation - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            # "log_MR_INTERVAL": [
            #     False,
            #     "d",
            #     {"description": "Sampling rate (seconds)"},
            #     BaseNetCDF.nc_scalar,
            # ],
            "log_MR_UPLOADMAX": [
                False,
                "d",
                {"description": "Max upload size (bytes)"},
                BaseNetCDF.nc_scalar,
            ],
            "log_MR_STARTS": [
                False,
                "d",
                {"description": "Numbers of times started"},
                BaseNetCDF.nc_scalar,
            ],
            "log_MR_NDIVE": [
                False,
                "d",
                {"description": "Dive multiplier"},
                BaseNetCDF.nc_scalar,
            ],
            #
            "microriderg_time": [
                False,
                "d",
                {
                    "standard_name": "time",
                    "units": "seconds since 1970-1-1 00:00:00",
                    "description": "Sample time in GMT epoch format",
                },
                (nc_microriderg_time_info,),
            ],
            "microriderg_ftime": [
                False,
                "d",
                {
                    "standard_name": "time",
                    "units": "seconds since 1970-1-1 00:00:00",
                    "description": "Sample time in GMT epoch format",
                },
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_despike": [
                False,
                "d",
                {},
                (nc_microriderg_despike_info,),
            ],
            "microriderg_freq": [
                False,
                "d",
                {},
                (nc_microriderg_freq_info,),
            ],
            #
            "microriderg_t1": [
                False,
                "d",
                {
                    "standard_name": "time",
                    "units": "seconds since 1970-1-1 00:00:00",
                },
                (nc_microriderg_time_info,),
            ],
            "microriderg_record": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_error": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_CI_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_T_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_MAD_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_diagnostic_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_K_max_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_FM_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_speed": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_T_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_e_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_sh_passes_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_var_res_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_CI_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_pressure": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_MAD_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_Incl_Y": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_e_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_var_res_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_K_max_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_Incl_X": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_diagnostic_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_sh_passes_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_visc": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_sh_fraction_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_sh_fraction_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_FM_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info,),
            ],
            "microriderg_shear_gfd_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info, nc_microriderg_freq_info),
            ],
            "microriderg_gradT_gfd_1": [
                False,
                "d",
                {},
                (nc_microriderg_time_info, nc_microriderg_freq_info),
            ],
            "microriderg_gradT_gfd_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info, nc_microriderg_freq_info),
            ],
            "microriderg_shear_gfd_2": [
                False,
                "d",
                {},
                (nc_microriderg_time_info, nc_microriderg_freq_info),
            ],
            "microriderg_fileVersion": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_hp_cut": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_ucond_despiking": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info, nc_microriderg_despike_info),
            ],
            "microriderg_overlap": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_fit_order": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_band_averaging": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_q": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_tau": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_num_frequency": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_scalar_processing": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_order": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_file": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_fp07_response": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_inertial_sr": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_diss_length": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_algorithm": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_goodman_spectra": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_shear_despiking": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info, nc_microriderg_despike_info),
            ],
            "microriderg_aoa": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_f_aa": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_goodman_length": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_scalar_spectra_ref": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_Nv": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_instrument": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
            "microriderg_fft_length": [
                False,
                "d",
                {},
                (nc_microriderg_ftime_info,),
            ],
        },
    }

    return 1


# pylint: disable=unused-argument
def process_data_files(
    base_opts,
    module_name,
    calib_consts,
    fc,
    processed_logger_eng_files,
    processed_logger_other_files,
):
    """Processes other files
    Input:
        base_opts - options object
        calib_conts - calibration consts dict
        fc - file code object for file being processed
        processed_logger_eng_files - list of eng files to add to
        processed_logger_other_files - list of other processed files to add to

    Returns:
        0 - success
        1 - failure
    """

    log_info(f"Processing {fc.full_filename()} to {fc.mk_base_engfile_name()}")
    if fc.is_down_data() or fc.is_up_data():
        # Copy to the correct extension
        eng_file = fc.mk_base_engfile_name()
        shutil.copy(fc.full_filename(), eng_file)
        processed_logger_other_files.append(eng_file)
        return 0
    else:
        # These should be non-existent
        log_error(
            "Don't know how to deal with MicroRiderG file (%s)" % fc.full_filename()
        )
        return 1


def eng_file_reader(eng_files, nc_info_d, calib_consts):
    """Reads the eng files"""

    ret_list = []

    # Make sure these are in order (a, c, b, d)
    accums = {}
    for ef in eng_files:
        eng_filename = ef["file_name"]
        ds = loadQfile(eng_filename)
        if ds is None:
            log_error(f"Could not open {eng_filename}")
            continue
        # variables is both vars and coords
        for var_name, da in ds.variables.items():
            # Drop these - not set up to handle arrays of strings
            if var_name in (
                "file",
                "fp07",
                "fp07_response",
                "algorithm",
                "scalar",
                "instrument",
                "response",
                "scalar_spectra_ref",
            ):
                continue
            # Deal with time type
            if np.issubdtype(da.dtype, np.datetime64) or np.issubdtype(
                da.dtype, np.timedelta64
            ):
                val = da.to_numpy().astype(float) / 1e9
            else:
                val = da.to_numpy()

            if var_name not in accums:
                accums[var_name] = val
            else:
                if var_name in ("freq", "despike"):
                    # These coord vectors do not accumulate over multiple profiles
                    continue
                if len(da.dims) == 1:
                    # These are actually MxN over multiple profiles
                    if var_name in ("ucond_despiking", "shear_despiking"):
                        accums[var_name] = np.vstack((accums[var_name], val))
                    else:
                        accums[var_name] = np.hstack((accums[var_name], val))
                else:
                    # Multi-dim
                    accums[var_name] = np.vstack((accums[var_name], val))

    for key, val in accums.items():
        log_debug(f"{key}:{val.shape}")
        ret_list.append((f"microriderg_{key}", val))

    return (ret_list, {})
