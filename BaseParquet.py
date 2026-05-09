#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2026  University of Washington.
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
import collections
import cProfile
import os
import pathlib
import pdb
import pstats
import sys
import time
import traceback
from functools import reduce

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import BaseDotFiles
import BaseNetCDF
import BaseOpts
import BaseOptsType
import MakeDiveProfiles
import MakeKML
import NetCDFUtils
import QC
import Sensors
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

# TODO - test with variables to migrate dimensions - latitude_gsm and longitude_gsm and legatos

DEBUG_PDB = True


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


def write_parquet_file(dive_nc_file_name, base_opts, timeseries_cfg_d):
    output_files = []
    try:
        dsi = Utils.open_netcdf_file(dive_nc_file_name, "r")
    except Exception:
        log_error(f"Unable to open {dive_nc_file_name} for read")
        return (1, output_files)

    # Strictly for debugging
    unknown_vars = []
    included_vars = []
    not_included_vars = []

    common_dims = collections.defaultdict(dict)
    for dive_nc_varname in dsi.variables:
        try:
            md = BaseNetCDF.nc_var_metadata[dive_nc_varname]
        except KeyError:
            log_warning(
                "Unknown variable (%s) in %s - skipping"
                % (dive_nc_varname, dive_nc_file_name)
            )
            unknown_vars.append(dive_nc_varname)
            continue

        include_in_mission_profile, _, _, mdp_dim_info = md
        if dive_nc_varname.startswith("gc_"):
            not_included_vars.append(dive_nc_varname)
            continue
        if dive_nc_varname in timeseries_cfg_d:
            if not timeseries_cfg_d[dive_nc_varname]:
                not_included_vars.append(dive_nc_varname)
                continue
        elif not include_in_mission_profile:
            not_included_vars.append(dive_nc_varname)
            continue

        included_vars.append(dive_nc_varname)

        if len(mdp_dim_info) > 1:
            continue

        if len(dsi[dive_nc_varname].dimensions) == 0 or dsi[dive_nc_varname].dimensions[
            0
        ].startswith("string"):
            common_dims["global"][dive_nc_varname] = dsi[dive_nc_varname]
        else:
            common_dims[dsi[dive_nc_varname].dimensions[0]][dive_nc_varname] = dsi[
                dive_nc_varname
            ]

    # for v in included_vars:
    #    log_info(f"included:({v})")
    # for v in not_included_vars:
    #    log_info(f"not_included:({v})")
    # for v in unknown_vars:
    #    log_info(f"unknown_vars:({v})")

    # Apply _qc vars, type conversions and delete singleton time vectors
    dims = list(common_dims.keys())
    for dim_name in dims:
        # Discard any that are just time vectors with no associated data
        ncvars = common_dims[dim_name]
        if len(ncvars) == 1 and next(iter(ncvars)).endswith("_time"):
            # log_info(f"Dropping {dim_name}")
            common_dims.pop(dim_name)
            continue
        for var_name in list(common_dims[dim_name]):
            # TODO - special handling needed
            if var_name in ("latlong_qc", "depth_avg_curr_qc"):
                common_dims[dim_name].pop(var_name)
                continue
            if var_name.endswith("_qc"):
                continue
            var = common_dims[dim_name][var_name][:]
            qc_name = f"{var_name}_qc"
            if qc_name in common_dims[dim_name]:
                var_q = dsi.variables[qc_name][:]
                try:
                    qc_vals = QC.decode_qc(var_q)
                except Exception:
                    log_warning(f"Could not decode QC for {var_name} - not applying")
                else:
                    var[qc_vals != QC.QC_GOOD] = np.nan
                common_dims[dim_name].pop(qc_name)

            def lookup_typecode(string_val):
                if string_val == "d":
                    return np.float64
                elif string_val == "f":
                    return np.float32
                elif string_val == "i":
                    return np.int32
                elif string_val == "c":
                    return "c"
                else:
                    log_warning(f"Unknown type code {string_val}")
                    return None

            timeseries_val = timeseries_cfg_d.get(var_name, True)
            include_in_mission_profile = BaseNetCDF.nc_var_metadata[var_name][0]
            if isinstance(timeseries_val, str):
                typecode = lookup_typecode(timeseries_val)
            elif isinstance(include_in_mission_profile, str):
                typecode = lookup_typecode(include_in_mission_profile)
            else:
                typecode = np.float64
            if typecode == "c":
                common_dims[dim_name][var_name] = var[:].tobytes().decode("utf-8")
            else:
                common_dims[dim_name][var_name] = var.astype(typecode)

    log_debug(common_dims.keys())

    for dim_name, ncvars in common_dims.items():
        out_dict = {"trajectory": dsi.variables["trajectory"][0], "dimension": dim_name}

        for k, v in ncvars.items():
            out_dict[k] = v
        if dim_name == "global":
            df = pd.DataFrame(out_dict, index=[0])
        else:
            df = pd.DataFrame(out_dict)
        table = pa.Table.from_pandas(df)
        out_dir = dive_nc_file_name.parent.joinpath("parquet")
        if not out_dir.exists():
            out_dir.mkdir()

        out_path = out_dir.joinpath(f"{dive_nc_file_name.stem}_{dim_name}.parquet")
        pq.write_table(table, out_path, compression="gzip")
        output_files.append(out_path)

    return (0, output_files)


def write_parquet_files(dive_nc_file_names, base_opts):
    """Creates a single time series from a list of dive netCDF files

    Input:
        dive_nc_profile_names - A list of fully qualified dive profile filenames.
        base_opts - command-line options structure

    Returns:
        tuple(ret_val, mission_timeseries_name)
        ret_val
            0 - success
            1 - failure
        mission_timeseries_name - the name possibly changed from the input parameter
    """

    ret_val = 0
    out_files = []

    if base_opts.dump_whole_mission_config:
        Utils.dump_mission_cfg(sys.stdout, BaseNetCDF.nc_var_metadata)
        return (0, None)

    _, timeseries_cfg_d = Utils.whole_mission_cfg(
        base_opts.whole_mission_config, BaseNetCDF.nc_var_metadata
    )

    cfg_dicts = [timeseries_cfg_d, MakeKML.kml_cfg_d]
    # Override settings from config file with needed fields for KML generation
    try:
        reduce(NetCDFUtils.merge_dict, cfg_dicts)
    except Exception:
        log_error("Error merging config templates", "exc")
        return None

    # TODO - need to harvest the names of files created and return that
    for dive_nc_file_name in dive_nc_file_names:
        try:
            return_val, output_files = write_parquet_file(
                dive_nc_file_name, base_opts, cfg_dicts[0]
            )
            ret_val |= return_val
        except Exception:
            log_error("Problem writing out parquet files", "exc")
            ret_val |= 1
        else:
            out_files.extend(output_files)
    return (ret_val, out_files)


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Command line driver for creating mission timeseries from single dive netCDF files

    Returns:
        0 - success
        1 - failure

    Raises:
        None - all exceptions are caught and logged

    """
    base_opts = BaseOpts.BaseOptions(
        "Command line driver for creating parquet files from a mission directory or a list of dive netcdf files",
        cmdline_args=cmdline_args,
        additional_arguments={
            "netcdf_files": BaseOptsType.options_t(
                None,
                ("BaseParquet",),
                ("netcdf_files",),
                str,
                {
                    "help": "List of per-dive netcdf files to process",
                    "nargs": "*",
                    "section": "parquet",
                },
            ),
        },
    )

    BaseLogger(base_opts)  # initializes BaseLog

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    # These functions reset large blocks of global variables being used in other modules that
    # assume an initial value on first load, then are updated throughout the run.  The call
    # here sets back to the initial state to handle multiple runs under pytest
    Sensors.set_globals()
    BaseNetCDF.set_globals()

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    # logger_init(init_dict)

    # Any initialization from the extensions
    BaseDotFiles.process_extensions(("init_extension",), base_opts, init_dict=init_dict)

    # Initialze the netCDF tables
    BaseNetCDF.init_tables(init_dict)

    if Utils.setup_parquet_directory(base_opts):
        log_error("Unable to setup/find parquet directory")
        return 1

    # Collect up the possible files
    if base_opts.netcdf_files:
        dive_nc_file_names = [base_opts.mission_dir / x for x in base_opts.netcdf_files]
    else:
        dive_nc_file_names = [
            pathlib.Path(x)
            for x in MakeDiveProfiles.collect_nc_perdive_files(base_opts)
        ]

    ret_val, out_files = write_parquet_files(dive_nc_file_names, base_opts)
    log_debug(f"Generated {out_files}")
    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    return ret_val


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove("--profile")
            profile_file_name = (
                os.path.splitext(os.path.split(sys.argv[0])[1])[0]
                + "_"
                + Utils.ensure_basename(
                    time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                + ".cprof"
            )
            # Generate line timings
            retval = cProfile.run("main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats("time", "calls")
            stats.print_stats()
        else:
            retval = main()
    except Exception:
        DEBUG_PDB_F()
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
