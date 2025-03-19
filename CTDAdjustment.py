#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025  University of Washington.
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

"""Extension to adjust CTD final output"""

import pathlib
import pdb
import shutil
import sys
import time
import traceback

import BaseDotFiles
import BaseNetCDF
import BaseOpts
import BaseOptsType
import FileMgr
import MakeDiveProfiles
import QC
import Sensors
import Utils
from BaseLog import BaseLogger, log_error, log_info, log_warning

DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


def load_additional_arguments() -> None:
    """Defines and extends arguments related to this extension.
    Called by BaseOpts when the extension is set to be loaded
    """
    return (
        # Add this module to these options defined in BaseOpts
        [
            "mission_dir",
            "netcdf_filename",
        ],
        # Option groups
        {"ctdadjustment": "Final CTD adjustments"},
        # Additional arguments
        {
            "adjust_final_temperature": BaseOptsType.options_t(
                0.0,
                (
                    "Base",
                    "Reprocess",
                    "CTDAdjustment",
                ),
                ("--adjust_final_temperature",),
                float,
                {
                    "help": "Adds an additional data column with the adjusted temperature",
                    "section": "ctdadjustment",
                    "option_group": "ctdadjustment",
                },
            ),
            "adjust_final_salinity": BaseOptsType.options_t(
                0.0,
                (
                    "Base",
                    "Reprocess",
                    "CTDAdjustment",
                ),
                ("--adjust_final_salinity",),
                float,
                {
                    "help": "Adds an additional data column with the adjusted salinity",
                    "section": "ctdadjustment",
                    "option_group": "ctdadjustment",
                },
            ),
        },
    )


def init_extension(
    module_name: str, base_opts: BaseOpts.BaseOptions | None = None, init_dict=None
) -> int:
    """
    init_sensor

    Returns:
        -1 - error in processing
         0 - success
    """

    if init_dict is None:
        log_error("No datafile supplied for init_extension - version mismatch?")
        return -1

    init_dict[module_name] = {
        "netcdf_metadata_adds": {
            "temperature_adjusted": [
                "f",
                "d",
                {
                    "standard_name": "sea_water_temperature",
                    "units": "degrees_Celsius",
                    "description": "Termperature (in situ) corrected for thermistor first-order lag, with offset applied",
                },
                (BaseNetCDF.nc_ctd_results_info,),
            ],
            "salinity_adjusted": [
                "f",
                "d",
                {
                    "standard_name": "sea_water_salinity",
                    "units": "PSU",
                    "description": "Salinity corrected for thermal-inertia effects (PSU)",
                },
                (BaseNetCDF.nc_ctd_results_info,),
            ],
            "temperature_adjusted_qc": [
                True,
                QC.nc_qc_type,
                {
                    "units": "qc_flag",
                    "description": "Whether to trust each corrected temperature_adjusted value",
                },
                (BaseNetCDF.nc_ctd_results_info,),
            ],
            "salinity_adjusted_qc": [
                True,
                QC.nc_qc_type,
                {
                    "units": "qc_flag",
                    "description": "Whether to trust each corrected salinity_adjusted value",
                },
                (BaseNetCDF.nc_ctd_results_info,),
            ],
        }
    }

    return 0


def main(
    cmdline_args: list[str] = sys.argv[1:],
    instrument_id=None,
    base_opts=None,
    sg_calib_file_name=None,
    dive_nc_file_names=None,
    nc_files_created=None,
    processed_other_files=None,
    known_mailer_tags=None,
    known_ftp_tags=None,
    processed_file_names=None,
    session=None,
):
    """Basestation extension to add adjusted temperature and/or salinity columns

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
            "Basestation extension to add adjusted temperature and/or salinity columns",
            additional_arguments=additional_arguments,
            add_option_groups=add_option_groups,
            add_to_arguments=add_to_arguments,
            cmdline_args=cmdline_args,
        )

        BaseLogger(base_opts)

        global DEBUG_PDB
        DEBUG_PDB = base_opts.debug_pdb

        # All needed since this extension is making contributions to the
        # metadata table
        Sensors.set_globals()
        BaseNetCDF.set_globals()
        # Sensor extensions
        (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
        if init_ret_val > 0:
            log_warning("Sensor initialization failed")
        # Initialize the FileMgr with data on the installed loggers
        FileMgr.logger_init(init_dict)
        # Any initialization from the extensions
        BaseDotFiles.process_extensions(
            ("init_extension",), base_opts, init_dict=init_dict
        )
        # Initialze the netCDF tables
        BaseNetCDF.init_tables(init_dict)
    else:
        BaseLogger(base_opts)

    if not base_opts.adjust_final_temperature and not base_opts.adjust_final_salinity:
        # No adjustment specified - nothing to do
        return 0

    if (
        not base_opts.mission_dir
        and hasattr(base_opts, "netcdf_filename")
        and base_opts.netcdf_filename
    ):
        # Called from CLI with a single argument
        dive_nc_file_names = [base_opts.netcdf_filename]
    elif base_opts.mission_dir:
        if nc_files_created is not None:
            # Called from MakeDiveProfiles as extension
            dive_nc_file_names = nc_files_created
        elif not dive_nc_file_names:
            # Called from CLI to process whole mission directory
            # Collect up the possible files
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
    else:
        log_error("Either mission_dir or netcdf_file must be specified")
        return 1

    log_info(
        f"Started processing {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(time.time()))}"
    )

    for dive_nc_file_name in dive_nc_file_names:
        dive_nc_file_name = pathlib.Path(dive_nc_file_name)

        try:
            dsi = Utils.open_netcdf_file(dive_nc_file_name)
        except Exception:
            log_error(f"Could not open {dive_nc_file_name} - bailing out", "exc")
            continue

        # Check for columns that match option
        new_columns = {}
        for var_name, adjustment, units in (
            ("temperature", base_opts.adjust_final_temperature, "degrees_Celsius"),
            ("salinity", base_opts.adjust_final_salinity, "PSU"),
        ):
            if var_name in dsi.variables and adjustment:
                try:
                    # Make the adjustment based on the option.
                    new_columns[f"{var_name}_adjusted"] = (
                        dsi.variables[var_name][:] + adjustment,
                        dsi.variables[var_name].dimensions,
                        {"comment": f"Adjusted by {adjustment:.4f} {units}"},
                    )
                    # Copy over QC vector
                    new_columns[f"{var_name}_adjusted_qc"] = (
                        dsi.variables[f"{var_name}_qc"][:],
                        dsi.variables[f"{var_name}_qc"].dimensions,
                        {},
                    )
                except Exception:
                    log_error("Could not apply adjustment to {var_name}", "exc")

        if not new_columns:
            dsi.close()
            continue

        # Create the new (temp) file
        tmp_filename = dive_nc_file_name.with_suffix(".tmpnc")
        try:
            dso = Utils.open_netcdf_file(tmp_filename, "w")
        except Exception:
            log_error(
                f"Failed to open tempfile {tmp_filename} - skipping update to {dive_nc_file_name}",
                "exc",
            )
            dsi.close()
            continue

        # Copy over contents, stripping out previous versions of the columns
        Utils.strip_vars(dsi, dso, [i for i in new_columns])

        # Add the new columns
        for nc_var_name, values in new_columns.items():
            value, nc_dim, additional_meta_data_d = values
            BaseNetCDF.create_nc_var(
                dso,
                nc_var_name,
                nc_dim,
                False,
                value,
                additional_meta_data_d=additional_meta_data_d,
            )
        # Close out and move new file to old location
        dsi.close()
        dso.sync()
        dso.close()
        shutil.move(tmp_filename, dive_nc_file_name)

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
        DEBUG_PDB_F()
        sys.stderr.write(f"Exception in main ({traceback.format_exc()})\n")

    sys.exit(retval)
