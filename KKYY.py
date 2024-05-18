#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024  University of Washington.
##
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are met:
##
## 1. Redistributions of source code must retain the above copyright notice, this
##    list of conditions and the following disclaimer.
##
## 2. Redistributions in binary form must reproduce the above copyright notice,
##    this list of conditions and the following disclaimer in the documentation
##    and/or other materials provided with the distribution.
##
## 3. Neither the name of the University of Washington nor the names of its
##    contributors may be used to endorse or promote products derived from this
##    software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE UNIVERSITY OF WASHINGTON AND CONTRIBUTORS “AS
## IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
## DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF WASHINGTON OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
## GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
## HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
## LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
## OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Routines for creating Navy data products"""

import math
import os
import pdb
import sys
import time
import traceback

import numpy as np

import BaseOpts
import MakeDiveProfiles
import MakeMissionProfile
import QC
import Utils
from BaseLog import BaseLogger, log_debug, log_error, log_info, log_warning
from Globals import WhichHalf

# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False


def print_kkyy(
    depth_reduced_v,
    tempc_reduced_v,
    salin_reduced_v,
    timestamp,
    ddlat,
    ddlon,
    instrument_id,
    kkyy_file,
):
    """Populates a KKYY file

    Input:
        depth_reduced_v, tempc_reduced_v, salin_reduced_v - arrays with a reduced number of observations
        timestamp -
        ddlat,ddtlon - decimal degrees for the location of the profile
        instrument_id  - Seaglider serial number
        kkyy_file - output file, already opened for write

    Output:
        None
    """
    kkyy_file.write(
        "KKYY %02d%02d%1d %02d%02d%1s %1d%05ld %06ld 888%1s%1s %03d%02d\n"
        % (
            timestamp.tm_mday,
            timestamp.tm_mon,
            timestamp.tm_year % 10,
            timestamp.tm_hour,
            timestamp.tm_min,
            "/",  # Encode in metric (meters/degC)
            WMO_3333(ddlat, ddlon),  # quadrant encoding
            int(math.fabs(ddlat * 1000)),  # GPS is this accurate
            int(math.fabs(ddlon * 1000)),
            "7",  # Values at significant depths (code table 2262)
            "2",  # in-situ sensor, accuracy less tahn 0.02 PSU (code table 2263)
            830,  # WMO 1770 instrument type 'CTD'
            99,  # WMO 4770 recorder code 'inconnu'
        )
    )

    size = len(depth_reduced_v)

    # Section 2 data
    for i in range(size):
        # Depth in meters (only when changing?)
        depth = depth_reduced_v[i]

        # Navy wants temp in 100'ths of degree C, and rounded
        tempc = math.floor(tempc_reduced_v[i] * 100.0)

        # For negative temperatures, 5000 shall be added to the absolute value of the
        # temperature in hundredths of a degree Celsius
        if tempc < 0.0:
            tempc = math.fabs(tempc) + 5000.0

        # Salin 100'th of PSU
        salin = salin_reduced_v[i] * 100.0

        try:
            kkyy_file.write(
                "2%04d 3%04d 4%04d\n" % (int(depth), int(tempc), int(salin))
            )
        except ValueError:
            log_warning(
                f"Error writing KKYY output ({depth} {tempc} {salin}) - skipping"
            )

    # TODO What about hitting the bottom? write_jjvv_field("00000")?

    # Section 3 data
    # NONE

    # Section 4 data
    # call sign -- encode hull number
    kkyy_file.write("SG%03d\n" % instrument_id)


#
# Untility functions
#


def WMO_3333(lat, lon):
    """Enncode quadrant of globe

    Input:
        lat,lon - latitude and longitude in dd

    Output:
        Encoding
    """
    if lat > 0:
        if lon > 0:
            # NE
            return 1
        else:
            # NW
            return 7
    else:
        if lon > 0:
            # SE
            return 3
        else:
            # SW
            return 5


def load_additional_arguments():
    """Defines and extends arguments related to this extension.
    Called by BaseOpts when the extension is set to be loaded
    """
    return (
        # Add this module to these options defined in BaseOpts
        ["mission_dir", "netcdf_filename"],
        # Option groups
        {},
        # Additional arguments
        {},
    )


def main(
    instrument_id=None,
    base_opts=None,
    sg_calib_file_name=None,
    dive_nc_file_names=None,
    nc_files_created=None,
    processed_other_files=None,
    known_mailer_tags=None,
    known_ftp_tags=None,
    processed_file_names=None,
):
    """Basestation extension for creating KKYY file

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    # pylint: disable=unused-argument
    if base_opts is None:
        add_to_arguments, add_option_groups, additional_arguments = (
            load_additional_arguments()
        )

        base_opts = BaseOpts.BaseOptions(
            "Basestation extension for creating simplified netCDF files",
            additional_arguments=additional_arguments,
            add_option_groups=add_option_groups,
            add_to_arguments=add_to_arguments,
        )

    BaseLogger(base_opts)  # initializes BaseLog

    log_info(
        f"Started processing {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(time.time()))}"
    )

    if hasattr(base_opts, "netcdf_filename") and base_opts.netcdf_filename:
        dive_nc_file_names = [base_opts.netcdf_filename]
    elif base_opts.mission_dir:
        if nc_files_created is not None:
            dive_nc_file_names = nc_files_created
        elif not dive_nc_file_names:
            # Collect up the possible files
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
    else:
        log_error("Either mission_dir or netcdf_file must be specified")
        return 1

    for dive_nc_file_name in dive_nc_file_names:
        log_info(f"Processing {dive_nc_file_name}")

        nci = Utils.open_netcdf_file(dive_nc_file_name, "r")

        try:
            ctd_depth = nci.variables["ctd_depth"][:]
            temperature = nci.variables["temperature"][:]
            salinity = nci.variables["salinity"][:]

            temperature_qc = QC.decode_qc(nci.variables["temperature_qc"][:])
            temperature[temperature_qc != QC.QC_GOOD] = np.nan
            salinity_qc = QC.decode_qc(nci.variables["salinity_qc"][:])
            salinity[salinity_qc != QC.QC_GOOD] = np.nan
            good_points = np.logical_not(
                np.logical_or.reduce(
                    (np.isnan(ctd_depth), np.isnan(temperature), np.isnan(salinity))
                )
            )
            ctd_depth = ctd_depth[good_points]
            temperature = temperature[good_points]
            salinity = salinity[good_points]

            instrument_id = nci.variables["log_ID"].getValue()
            _, down_timestamp, up_timestamp = map(
                time.gmtime, nci.variables["log_gps_time"][:]
            )
            _, down_ddlat, up_ddlat = nci.variables["log_gps_lat"][:]
            _, down_ddlon, up_ddlon = nci.variables["log_gps_lon"][:]
        except KeyError:
            log_error("Problems loading needed variables", "exc")
            continue

        # Navy file formats
        kkyy_up_file_name = os.path.splitext(dive_nc_file_name)[0] + ".up_kkyy"
        kkyy_down_file_name = os.path.splitext(dive_nc_file_name)[0] + ".dn_kkyy"

        try:
            kkyy_up_file = open(kkyy_up_file_name, "w")
        except OSError:
            log_error(
                f"Could not open {kkyy_up_file_name} for writing - skipping output",
                "exc",
            )
            continue
        else:
            log_debug(f"Started processing {kkyy_up_file_name}")
            data_cols = (temperature, salinity)
            # per kkyy specification bin width must be 1m
            obs_up_kkyy, depth_m_up_kkyy, data_cols_bin = MakeMissionProfile.bin_data(
                1.0, WhichHalf.up, False, ctd_depth, data_cols
            )
            temp_cor_up_kkyy = data_cols_bin[0]
            Salinity_up_kkyy = data_cols_bin[1]
            # Need to sort the data in ascending depth order - since this is binned data, we can just reverse the vectors
            obs_up_kkyy = obs_up_kkyy[::-1]
            depth_m_up_kkyy = depth_m_up_kkyy[::-1]
            temp_cor_up_kkyy = temp_cor_up_kkyy[::-1]
            Salinity_up_kkyy = Salinity_up_kkyy[::-1]
            print_kkyy(
                depth_m_up_kkyy,
                temp_cor_up_kkyy,
                Salinity_up_kkyy,
                up_timestamp,
                up_ddlat,
                up_ddlon,
                instrument_id,
                kkyy_up_file,
            )
            kkyy_up_file.close()
            log_debug("Obs, Depth, Temp, Salin")
            for i in range(len(depth_m_up_kkyy)):
                log_debug(
                    "%f,%f,%f,%f"
                    % (
                        obs_up_kkyy[i],
                        depth_m_up_kkyy[i],
                        temp_cor_up_kkyy[i],
                        Salinity_up_kkyy[i],
                    )
                )
            log_debug(f"Finished processing {kkyy_up_file_name}")
            if processed_other_files is not None:
                processed_other_files.append(kkyy_up_file_name)

        try:
            kkyy_down_file = open(kkyy_down_file_name, "w")
        except OSError:
            log_error(
                f"Could not open {kkyy_down_file_name} for writing - skipping output",
                "exc",
            )
            continue
        else:
            log_debug(f"Started processing {kkyy_down_file_name}")
            data_cols = (temperature, salinity)
            (
                obs_down_kkyy,
                depth_m_down_kkyy,
                data_cols_bin,
            ) = MakeMissionProfile.bin_data(
                1.0, WhichHalf.down, False, ctd_depth, data_cols
            )
            print_kkyy(
                depth_m_down_kkyy,
                data_cols_bin[0],
                data_cols_bin[1],
                down_timestamp,
                down_ddlat,
                down_ddlon,
                instrument_id,
                kkyy_down_file,
            )
            log_debug("Obs, Depth, Temp, Salin")
            for i in range(len(depth_m_down_kkyy)):
                log_debug(
                    "%f,%f,%f,%f"
                    % (
                        obs_down_kkyy[i],
                        depth_m_down_kkyy[i],
                        data_cols_bin[0][i],
                        data_cols_bin[1][i],
                    )
                )
            kkyy_down_file.close()
            log_debug(f"Finished processing {kkyy_down_file_name}")

            if processed_other_files is not None:
                processed_other_files.append(kkyy_down_file_name)

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    return 0


if __name__ == "__main__":
    retval = 0
    try:
        retval = main()
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            extype, value, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        sys.stderr.write(f"Exception in main ({traceback.format_exc()})\n")

    sys.exit(retval)
