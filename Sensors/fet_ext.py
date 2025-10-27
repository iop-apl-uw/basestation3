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
GliderFET basestation sensor extension
"""

import collections

import BaseNetCDF
import Utils2
from BaseLog import log_error

nc_fet_data_info = "fet_data_info"  # from eng/scicon
nc_dim_fet_data_point = "fet_data_point"
nc_fet_data_time = "fet_time"

# nc_fet_results_info = "fet_results_info"
# nc_dim_fet_results = "fet_result_data_point"
# nc_fet_time_var = "aanderfet_results_time"


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
        nc_fet_data_info,
        nc_dim_fet_data_point,
        nc_fet_data_time,
        "chemical",
        "fet",
    )
    meta_data_adds = {
        "sg_cal_calibcomm_fet": [
            False,
            "c",
            {},
            BaseNetCDF.nc_scalar,
        ],
        # instrument
        "fet": [
            False,
            "c",
            {
                "long_name": "GliderFET",
                # "nodc_name": "optode",
                "make_model": "Glider FET",
            },
            BaseNetCDF.nc_scalar,
        ],
        # from scicon eng file
        nc_fet_data_time: [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "FET time in GMT epoch format",
            },
            (nc_fet_data_info,),
        ],
    }
    # fet sensor inputs
    fet_tuple = collections.namedtuple("fet_tuple", ("units", "description"))
    fet_columns = {}
    fet_columns["biasBatt"] = fet_tuple("V", "")
    fet_columns["Vrse"] = fet_tuple("V", "")
    fet_columns["Vrsestd"] = fet_tuple("V", "")
    fet_columns["Vk"] = fet_tuple("V", "")
    fet_columns["Vkstd"] = fet_tuple("V", "")
    fet_columns["Ik"] = fet_tuple("nI", "")
    fet_columns["Ib"] = fet_tuple("nI", "")

    for tag, dimension in (
        ("eng_", BaseNetCDF.nc_sg_data_info),
        ("", nc_fet_data_info),
    ):
        for var_n, var_meta in fet_columns.items():
            temp_dict = {
                "_FillValue": BaseNetCDF.nc_nan,
                "description": var_meta.description,
                "instrument": "fet",
            }
            if var_meta.units:
                temp_dict["units"] = var_meta.units
            if var_meta.description:
                temp_dict["description"] = var_meta.description

            meta_data_adds[f"{tag}fet_{var_n}"] = [
                "d",
                "d",
                temp_dict,
                (dimension,),
            ]

    meta_data_adds |= Utils2.add_scicon_stats("fet")
    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}

    return 0
