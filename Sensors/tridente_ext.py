#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2025, 2026 by University of Washington.  All rights reserved.
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

import collections

import BaseNetCDF
import Utils2
from BaseLog import log_error

scale_off_pts = collections.namedtuple("scale_off_pts", ("scale", "off", "pts"))

# The collection of scale, offset (for truck) and decimal pts needed for .eng file output
# Note: scale/off must match .cnf file on glider
scale_off_pt_dict = {
    "chla470": scale_off_pts(1000, 0, 3),
    "chla435": scale_off_pts(1000, 0, 3),
    "fdom365": scale_off_pts(1000, 0, 3),
    # "pc590": scale_off_pts(0, 0, 3),
    # "pc525": scale_off_pts(0, 0, 3),
    # "rd550": scale_off_pts(0, 0, 3),
    # "fitc470": scale_off_pts(0, 0, 3),
    "bb470": scale_off_pts(100000, 0, 5),
    "bb525": scale_off_pts(100000, 0, 5),
    "bb650": scale_off_pts(100000, 0, 5),
    "bb700": scale_off_pts(100000, 0, 5),
    "tu650": scale_off_pts(1000, 0, 3),
    "tu700": scale_off_pts(1000, 0, 3),
}


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
    turbidity_units = "FTU"  # Formazin Turbidity Units

    # See the Tridente instrument and column naming document in the docs directory for a
    # description of the namespace

    channels = {
        "chla470": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": chl_units,
            "description": "chlorophyll-a concentration (470nm excitation/695nm emission) scaled to the fluorescence response from a monoculture of Thalassiosira weissflogii.",
        },
        "chla435": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": chl_units,
            "description": "chlorophyll-a concentration (435nm excitation/695nm emission) scaled to the fluorescence response from a monoculture of Thalassiosira weissflogii.",
        },
        "fdom365": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": ppb_units,
            "description": "fDOM fluorescence (365nm excitation/450m emission)",
        },
        "pc590": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": chl_units,
            "description": "Phycocyanin (590nm excitation/654nm emission)",
        },
        "pc525": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": chl_units,
            "description": "Phycoerythrin (525nm excitation/600nm emission)",
        },
        "rd550": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": chl_units,
            "description": "Rhodamine (550nm excitation/600nm emission)",
        },
        "fitc470": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": chl_units,
            "description": "Fluorescein (470nm excitation/550nm emission)",
        },
        "bb470": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": scattering_units,
            "description": "total volume 470nm scattering coefficient",
        },
        "bb525": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": scattering_units,
            "description": "total volume 525nm scattering coefficient",
        },
        "bb650": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": scattering_units,
            "description": "total volume 650nm scattering coefficient",
        },
        "bb700": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": scattering_units,
            "description": "total volume 700nm scattering coefficient",
        },
        "tu650": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": turbidity_units,
            "description": "Turbidity (650nm)",
        },
        "tu700": {
            "_FillValue": BaseNetCDF.nc_nan,
            "units": turbidity_units,
            "description": "Turbidity (700nm)",
        },
    }

    meta_data_adds = {}

    # Centeralized list of known channel combinations
    known_instruments = Utils2.known_tridente_channels()
    # We keep this list to 3 possible installed instruments, even though the name space allows for up to 9 installed instruments
    instances = ("tridente", "tridente1", "tridente2", "tridente3")
    instruments = []
    for ki in known_instruments:
        for inst in instances:
            instruments.append(f"{inst}{ki}")

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

        # Instrument sensor inputs on truck and scicon
        for prefix, d_i in (
            (BaseNetCDF.nc_sg_eng_prefix, BaseNetCDF.nc_sg_data_info),
            ("", data_info),
        ):
            for channel, md in channels.items():
                md["instrument"] = instrument
                meta_data_adds[f"{prefix}{instrument}_{channel}"] = [
                    "f",
                    "d",
                    md,
                    (d_i,),
                ]

        # Time var for scicon
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

        meta_data_adds |= Utils2.add_scicon_stats(instrument)

    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}
    return 0


def eng_decimal_pts(
    base_opts,
    module_name,
    eng_col_names: list[str] | None = None,
    eng_decimal_pts: dict[str, int] | None = None,
) -> int:
    """
    eng_decimal_pts mapper

    returns:
    -1 - error in processing
     0 - success (data found and processed)
     1 - no data found to process
    """
    import pdb

    if eng_col_names is None:
        log_error(
            "No eng_col_names list supplied for eng_decimal_pts conversion - version mismatch?"
        )
        pdb.set_trace()
        return -1

    if eng_decimal_pts is None:
        log_error(
            "No eng_decimal_pts dict supplied for eng_decimal_pts conversion - version mismatch?"
        )
        pdb.set_trace()
        return -1

    # TODO - this needs to be expanded to get the full name space - instance digit
    known_tridente_channels = Utils2.known_tridente_channels()
    for eng_col_name in eng_col_names:
        if "." not in eng_col_name:
            continue
        instrument_name, col_name = eng_col_name.split(".", 1)
        if any(ii in instrument_name for ii in known_tridente_channels):
            eng_decimal_pts[eng_col_name] = scale_off_pt_dict[col_name].pts
    return 0
