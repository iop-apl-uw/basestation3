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

"""Create a file for submission to the GliderDAC from an existing netCDF file"""
#
# Notes:
#
# Overall, this code can produce timeseries data (--gliderdac_bin_width == 0.0) or
# binned output (--gliderdac_bin_width > 0.0)
#
# netcdf files without a ctd_time or ctd_depth vector are rejected
#
# 1) For input timeseries vectors with associated QC vectors, only points marked QC_GOOD are
#    accepted.  All other points are converted to nans
# 2) If timeseries vectors are associated with multiple time basis, there is a single
#    time basis constructed contain all observations (obviously, this can be very sparse
#    table for a scicon instrument)
# 3) If --gliderdac_reduce_output is set (default is True), all timeseries vectors are
#    reduced such that all rows are contain all valid observations.  Obviously, this
#    is only useful for CTD only profiles.
# 4) For output, timeseries variables time, depth, latitude, longitude and pressure are
#    marked no_qc_performed (QC_NOCHANGE) for non-nan data and missing_value (QC_MISSING)
#    for nan.
#    All other timeseries variables are marked good_data (QC_GOOD) for non-nan and
#    missing_value (QC_MISSING) for nan data.

import argparse
import collections
import os
import pdb
import stat
import sys
import time
import traceback
from functools import reduce

import gsw
import numpy as np
import xarray as xr
import yaml

import BaseOpts
import BaseOptsType
import MakeDiveProfiles
import NetCDFUtils
import QC
from BaseLog import BaseLogger, log_debug, log_error, log_info, log_warning

# Local config
DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


dim_map_t = collections.namedtuple("dim_map_t", ["first_i", "last_i"])


# Util functions
def fix_ints(data_type, attrs):
    """Convert int values from LL (json format) to appropriate size per gliderdac specs"""
    new_attrs = {}
    for k, v in attrs.items():
        if isinstance(type(v), int):
            new_attrs[k] = data_type(v)
        elif k == "flag_values":
            new_attrs[k] = [data_type(li) for li in v]
        else:
            new_attrs[k] = v
    return new_attrs


def lookup_qc_val(value):
    for k, v in QC.qc_name_d.items():
        if value.rstrip().lstrip() == v:
            return np.int8(k)
    log_warning(f"Unkown QC string {value} - ignoring")
    return None


def create_nc_var(
    dso,
    template,
    var_name,
    data,
    qc_val=None,
    qc_missing_val=None,
):
    """Creates a nc variable and sets meta data
    Input:
        dso - output dataset
        template - dictionary of metadata
        var_name - name of variable as appears in teamplate
        data - input data
        qc_val - override the qc value to use (normally comes from the template)
        qc_missing_val - override the qc value to use

    Returns:
        dataarray for variable and matching qc variable

    """

    if qc_val is None and "qc_data" in template["variables"][var_name]:
        qc_val = lookup_qc_val(template["variables"][var_name]["qc_data"])

    if qc_missing_val is None:
        if "qc_missing_data" in template["variables"][var_name]:
            qc_missing_val = lookup_qc_val(
                template["variables"][var_name]["qc_missing_data"]
            )
        else:
            # Only has impact if qc_val is not None
            qc_missing_val = QC.QC_MISSING

    is_str = False
    if isinstance(data, str):
        inp_data = np.array(data, dtype=np.dtype(("S", len(data))))
        is_str = True
    elif np.ndim(data) == 0:
        # Scalar data
        inp_data = np.dtype(template["variables"][var_name]["type"]).type(data)
    else:
        inp_data = data.astype(template["variables"][var_name]["type"])

    if "num_digits" in template["variables"][var_name]:
        inp_data = inp_data.round(template["variables"][var_name]["num_digits"])

    # Check for scalar variables
    if np.ndim(inp_data) == 0:
        if np.issubdtype(inp_data.dtype, np.number) and np.isnan(inp_data):
            inp_data = template["variables"][var_name]["attributes"]["_FillValue"]
    else:
        inp_data[np.isnan(inp_data)] = template["variables"][var_name]["attributes"][
            "_FillValue"
        ]

    # GBS 2022/02/09 In what can only be a bug, if the time_qc variable is written out after the time variable,
    # time variables attributes are deleted, leaving an empty dict.  No other variables have
    # this issue.  If the order is reversed - qc before regular variable - no problems.  This
    # may be related to the fact that the time variable has the same name as the time dimension,
    # and is there for picked up as an indexing coordinate by xarray.

    # QC array

    qc_name = f"{var_name}_qc"
    if qc_name in template["variables"] and qc_val is not None:
        if np.ndim(data) == 0:
            qc_v = np.dtype(template["variables"][qc_name]["type"]).type(qc_val)
        else:
            # Populate the initial vector with qc_val...
            qc_v = np.zeros((np.size(inp_data)), dtype="b") + np.dtype(
                template["variables"][qc_name]["type"]
            ).type(qc_val)
            # ...and mark the missing data
            if qc_missing_val is not None:
                qc_v[
                    inp_data
                    == template["variables"][var_name]["attributes"]["_FillValue"]
                ] = qc_missing_val
        da_q = xr.DataArray(
            qc_v,
            dims=template["variables"][qc_name]["dimensions"],
            attrs=fix_ints(np.byte, template["variables"][qc_name]["attributes"]),
        )
        if "nc_varname" in template["variables"][qc_name]:
            dso[template["variables"][qc_name]["nc_varname"]] = da_q
        else:
            dso[qc_name] = da_q
    else:
        da_q = None

    da = xr.DataArray(
        inp_data,
        dims=template["variables"][var_name]["dimensions"] if not is_str else None,
        attrs=fix_ints(np.int32, template["variables"][var_name]["attributes"]),
        # coords=None,
    )
    if "nc_varname" in template["variables"][var_name]:
        dso[template["variables"][var_name]["nc_varname"]] = da
    else:
        dso[var_name] = da

    return (da, da_q)


def load_var(dci, var_name, dims_map, sort_i):
    """
    Input:
        dci - dataset
        var_name - name of the variable
        dims_map - mapping of the dimensions to the unsorted time space
        sort_i  - mapping of unsorted time space to sorted time space
    Returns
        var - netcdf array, with QC applied (QC_GOOD only)
    """
    var = dci[var_name]
    qc_name = f"{var_name}_qc"
    if qc_name and qc_name in dci.variables:
        var_q = dci[qc_name].data
        try:
            qc_vals = QC.decode_qc(var_q)
        except Exception:
            log_warning(f"Could not decode QC for {var_name} - not applying", "exc")
        else:
            var[qc_vals != QC.QC_GOOD] = np.nan

    if len(var) != dims_map[var.dims].last_i - dims_map[var.dims].first_i:
        log_error(f"Mismatch in sizes for {var_name} and {dims_map[var.dims]}")
        return None

    # Create new var, same type as var that is all nan, size of sort_i and map var into this space
    expanded_var = np.zeros(len(sort_i), var.dtype) * np.nan
    temp_var = expanded_var.copy()
    temp_var[dims_map[var.dims].first_i : dims_map[var.dims].last_i] = var
    expanded_var = temp_var[sort_i]

    return expanded_var


def load_templates(base_opts):
    """Load configuration template files and merge into one"""

    # Check for all variables being set
    if not base_opts.gliderdac_base_config:
        log_error("gliderdac_base_config file not specified")
        return None

    if not base_opts.gliderdac_project_config:
        log_error("gliderdac_project_config file not specified")
        return None

    if not base_opts.gliderdac_deployment_config:
        log_error("gliderdac_deployment_config file not specified")
        return None

    templates = [{}]
    for file_name, option_name in (
        (base_opts.gliderdac_base_config, "gliderdac_base_config"),
        (base_opts.gliderdac_project_config, "gliderdac_project_config"),
        (base_opts.gliderdac_deployment_config, "gliderdac_deployment_config"),
    ):
        if not file_name:
            log_warning(f"GliderDAC option --{option_name} not specified")
            continue
        if not os.path.exists(file_name):
            log_info(f"{file_name} does not exist - skipping")
            continue
        try:
            with open(file_name, "r") as fi:
                templates.append(yaml.safe_load(fi.read()))
        except Exception:
            log_error(f"Could not procss {file_name}", "exc")
            return None

    # Merge templates together
    try:
        reduce(NetCDFUtils.merge_dict, templates)
    except Exception as e:
        log_error(f"Error merging config templates - {e.args}")
        return None

    return templates[0]


def find_deepest_bin_i(depth, bin_centers, bin_width):
    """Finds the last index within the deepest bin"""

    max_i = np.argmax(depth)
    while depth[max_i] >= bin_centers[-1] - (bin_width / 2.0):
        max_i += 1

    # Return the first shallower max_i
    # max_i -= 1
    return max_i


def load_additional_arguments():
    """Defines and extends arguments related to this extension.
    Called by BaseOpts when the extension is set to be loaded
    """
    return (
        # Add this module to these options defined in BaseOpts
        ["mission_dir", "netcdf_filename"],
        # Description for any option_group tags used below
        {"gliderdac": "NetCDF file generation for submission to the Glider DAC"},
        # Add these options that are local to this extension
        {
            "gliderdac_base_config": BaseOptsType.options_t(
                "",
                (
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                ),
                ("--gliderdac_base_config",),
                BaseOpts.FullPath,
                {
                    "help": "GliderDAC base configuration YAML file - common for all Seagliders",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOpts.FullPathAction,
                },
            ),
            "gliderdac_project_config": BaseOptsType.options_t(
                "",
                (
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                ),
                ("--gliderdac_project_config",),
                BaseOpts.FullPath,
                {
                    "help": "GliderDAC project configuration YAML file - common for single study area",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOpts.FullPathAction,
                },
            ),
            "gliderdac_deployment_config": BaseOptsType.options_t(
                "",
                (
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                ),
                ("--gliderdac_deployment_config",),
                BaseOpts.FullPath,
                {
                    "help": "GliderDAC deployoment configuration YAML file - specific to the current glider deoployment",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOpts.FullPathAction,
                },
            ),
            "gliderdac_directory": BaseOptsType.options_t(
                "",
                (
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                ),
                ("--gliderdac_directory",),
                BaseOpts.FullPath,
                {
                    "help": "Directory to place output files in",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOpts.FullPathAction,
                },
            ),
            "delayed_submission": BaseOptsType.options_t(
                False,
                (
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                ),
                ("--delayed_submission",),
                BaseOpts.FullPath,
                {
                    "help": "Generated files for delayed submission",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "gliderdac_bin_width": BaseOptsType.options_t(
                0.0,
                (
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                ),
                ("--gliderdac_bin_width",),
                float,
                {
                    "help": "Width of bins for GliderDAC file (0.0 indicates timeseries)",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                },
            ),
            "gliderdac_reduce_output": BaseOptsType.options_t(
                True,
                (
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                ),
                ("--gliderdac_reduce",),
                bool,
                {
                    "help": "Reduce the output to only non-nan observations (not useful with non-CT data)",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
        },
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
    """Basestation extension for creating simplified netCDF files

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
            "Basestation extension for creating GliderDAC netCDF files",
            additional_arguments=additional_arguments,
            add_option_groups=add_option_groups,
            add_to_arguments=add_to_arguments,
        )

        global DEBUG_PDB
        DEBUG_PDB = base_opts.debug_pdb

    BaseLogger(base_opts)

    if base_opts.delayed_submission:
        delayed_str = "_delayed"
    else:
        delayed_str = ""

    processing_start_time = time.gmtime(time.time())
    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", processing_start_time)
    )

    if (
        not base_opts.mission_dir
        and hasattr(base_opts, "netcdf_filename")
        and base_opts.netcdf_filename
    ):
        dive_nc_file_names = [base_opts.netcdf_filename]
        if not base_opts.gliderdac_directory:
            base_opts.gliderdac_directory = os.path.join(
                os.path.split(dive_nc_file_names[0])[0], "gliderdac"
            )
    elif base_opts.mission_dir:
        if nc_files_created is not None:
            dive_nc_file_names = nc_files_created
        elif not dive_nc_file_names:
            # Collect up the possible files
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
        if not base_opts.gliderdac_directory:
            base_opts.gliderdac_directory = os.path.join(
                base_opts.mission_dir, "gliderdac"
            )
    else:
        log_error("Either mission_dir or netcdf_file must be specified")
        return 1

    if not os.path.exists(base_opts.gliderdac_directory):
        try:
            os.mkdir(base_opts.gliderdac_directory)
            # Ensure that MoveData can move it as pilot if not run as the glider account
            os.chmod(
                base_opts.gliderdac_directory,
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR
                | stat.S_IRGRP
                | stat.S_IXGRP
                | stat.S_IWGRP
                | stat.S_IROTH
                | stat.S_IXOTH,
            )
        except Exception:
            log_error(f"Could not create {base_opts.gliderdac_directory}", "exc")
            log_info("Bailing out")
            return 1

    template = load_templates(base_opts)
    if not template:
        return 1

    # Default timeseries variables and the name mapping
    # Can be overridden by same names in the "config" dictionary from the template(s)
    requested_timeseries_vars = {
        "temperature": "temperature",
        "salinity": "salinity",
        "conductivity": "conductivity",
        "latitude": "lat",
        "longitude": "lon",
        "ctd_pressure": "pressure",
    }

    # Update anything overridden by config
    if "config" in template and "timeseries_vars" in template["config"]:
        requested_timeseries_vars = template["config"]["timeseries_vars"]

    for dive_nc_file_name in dive_nc_file_names:
        log_info("Processing %s" % dive_nc_file_name)
        try:
            dsi = xr.open_dataset(dive_nc_file_name, decode_times=False)
        except Exception:
            log_error(f"Error opening {dive_nc_file_name}", "exc")
            continue

        dso = xr.Dataset()

        if "ctd_time" not in dsi or "ctd_depth" not in dsi:
            log_error("Could not load variables - skipping", "exc")
            continue

        # Inventory timeseries variables - construct a master time vector and interpolate missing depth points
        time_vars = set()
        # Reset this every time in case of processing multiple files
        timeseries_vars = {}
        for var_name, var_content in requested_timeseries_vars.items():
            if var_name not in dsi.variables:
                log_warning(
                    f"Requested variable {var_name} not in {dive_nc_file_name} - skipping"
                )
                continue
            timeseries_vars[var_name] = var_content
            dims = dsi[var_name].dims
            for vv in dsi.variables:
                if (
                    dsi[vv].dims == dims
                    and vv.endswith("_time")
                    and "_results_" not in vv
                ):
                    time_vars.add((vv, dims))

        unsorted_master_time = np.zeros(0)
        dims_map = {}
        last_i = 0
        for t_var, t_dim in time_vars:
            # Xarray converts to numpy.datetime64(ns) - get it back to something useful
            # new_time_v = dsi[t_var].data.astype(np.float64) / 1000000000.0
            new_time_v = dsi[t_var]
            dims_map[t_dim] = dim_map_t(last_i, last_i + len(new_time_v))
            last_i += len(new_time_v)
            unsorted_master_time = np.concatenate((unsorted_master_time, new_time_v))
        sort_i = np.argsort(unsorted_master_time)
        # NOTE: A possible issue is if there are repeated time values in different time_vars.
        # A solution is to wrap the call below with np.unique(), but is not tested
        master_time = unsorted_master_time[sort_i]

        master_depth = NetCDFUtils.interp1_extend(
            # dsi["ctd_time"].data.astype(np.float64) / 1000000000.0,
            dsi["ctd_time"].data,
            dsi["ctd_depth"].data,
            master_time,
        )

        if base_opts.gliderdac_bin_width:
            max_depth = np.floor(np.nanmax(master_depth))
            # This is actually bin edges, so one more point then actual bins
            bin_edges = np.arange(
                -base_opts.gliderdac_bin_width / 2.0,
                max_depth + base_opts.gliderdac_bin_width / 2.0 + 0.01,
                base_opts.gliderdac_bin_width,
            )

            # Do this to ensure everything is caught in the binned statistic
            bin_edges[0] = -20.0
            bin_edges[-1] = max_depth + 50.0

            bin_centers_down = np.arange(
                0.0, max_depth + 0.01, base_opts.gliderdac_bin_width
            )
            max_depth_i = find_deepest_bin_i(
                master_depth, bin_centers_down, base_opts.gliderdac_bin_width
            )

            bin_centers = np.concatenate(
                (bin_centers_down, bin_centers_down[:-1][::-1])
            )

            t_profile = np.zeros(len(bin_centers))

            t_profile[: len(bin_centers_down)] = NetCDFUtils.interp1_extend(
                master_depth[:max_depth_i], master_time[:max_depth_i], bin_centers_down
            )
            t_profile[len(bin_centers_down) :] = NetCDFUtils.interp1_extend(
                master_depth[max_depth_i:],
                master_time[max_depth_i:],
                bin_centers_down[1:][::-1],
            )

        # Note: for non-binned, this variable is just a copy of the data straight from
        # the netcdf file
        binned_vars = {}
        reduced_pts_i = None
        for var_name in timeseries_vars:
            log_debug(f"Adding variable {var_name}")
            data = load_var(
                dsi,
                var_name,
                dims_map,
                sort_i,
            )
            if base_opts.gliderdac_bin_width:
                # Calculated above
                # max_depth_i = find_deepest_bin_i(
                #    master_depth, bin_edges, base_opts.gliderdac_bin_width
                # )

                var_v = np.zeros(np.size(bin_centers)) * np.nan
                n_obs = np.zeros(np.size(bin_centers))
                (
                    var_v[: np.size(bin_centers_down)],
                    n_obs[: np.size(bin_centers_down)],
                    *_,
                ) = NetCDFUtils.bindata(
                    master_depth[:max_depth_i], data[:max_depth_i], bin_edges
                )

                var_tmp, n_obs_tmp, *_ = NetCDFUtils.bindata(
                    master_depth[max_depth_i:], data[max_depth_i:], bin_edges
                )
                var_v[np.size(bin_centers_down) :] = var_tmp[:-1][::-1]
                n_obs[np.size(bin_centers_down) :] = n_obs_tmp[:-1][::-1]
                binned_vars[var_name] = (var_v, np.isfinite(var_v), n_obs)
            else:
                # With the new remapping code, data isn't a xarray object, but a numpy object
                # binned_vars[var_name] = (data.data, np.isfinite(data))
                binned_vars[var_name] = (data, np.isfinite(data))
            if reduced_pts_i is None:
                reduced_pts_i = np.arange(len(binned_vars[var_name][0]))

        if base_opts.gliderdac_reduce_output:
            # Locate the good points
            reduced_pts_i = np.squeeze(
                np.nonzero(
                    np.logical_and.reduce(
                        [
                            v[1]
                            for k, v in binned_vars.items()
                            if k not in ("latitude", "longitude", "pressure")
                        ]
                    )
                )
            )

        # Create variables with only good points, based on the mask
        reduced_vars = {}
        for var_name, val in binned_vars.items():
            reduced_vars[var_name] = val[0][reduced_pts_i]
            create_nc_var(
                dso,
                template,
                timeseries_vars[var_name],
                reduced_vars[var_name],
            )
            # This is just for debugging
            # if base_opts.gliderdac_bin_width and var_name == "temperature":
            #    create_nc_var(dso, template, "temperature_n", val[2][reduced_pts_i])

        if base_opts.gliderdac_bin_width:
            reduced_depth = bin_centers[reduced_pts_i]
            reduced_time = t_profile[reduced_pts_i]
            del (
                bin_centers,
                t_profile,
            )
        else:
            reduced_depth = master_depth[reduced_pts_i]
            reduced_time = master_time[reduced_pts_i]

        salinity_absolute = gsw.SA_from_SP(
            reduced_vars["salinity"],
            np.zeros(reduced_vars["salinity"].size),
            reduced_vars["longitude"],
            reduced_vars["latitude"],
        )
        density = gsw.rho_t_exact(
            salinity_absolute,
            reduced_vars["temperature"],
            np.zeros(salinity_absolute.size),
        )
        create_nc_var(
            dso,
            template,
            "density",
            density,
        )

        del binned_vars, reduced_pts_i

        # Depth and time
        create_nc_var(
            dso,
            template,
            "depth",
            reduced_depth,
        )
        create_nc_var(
            dso,
            template,
            "time",
            reduced_time,
        )

        # Singleton variables

        # Time related
        start_ts = time.strftime("%Y%m%dT%H%M", time.gmtime(dsi.attrs["start_time"]))
        trajectory_name = f"{dsi.attrs['platform_id'].lower()}-{start_ts}"
        dso.attrs["trajectory"] = trajectory_name
        create_nc_var(dso, template, "trajectory", trajectory_name)
        dso.attrs["time_coverage_start"] = f"{start_ts}Z"
        dso.attrs["time_coverage_end"] = time.strftime(
            "%Y%m%dT%H%MZ", time.gmtime(np.nanmax(reduced_time))
        )
        dso.attrs["id"] = trajectory_name

        # Variables
        create_nc_var(dso, template, "profile_id", dsi.attrs["dive_number"])

        median_time_i = np.abs(reduced_time - np.median(reduced_time)).argmin()
        create_nc_var(
            dso,
            template,
            "profile_time",
            reduced_time[median_time_i],
        )

        # Lat and Lon may not be dense - interpolate the missing points
        # for use in median location variables
        full_lat = reduced_vars["latitude"].copy()
        lat_nan_v = np.isnan(reduced_vars["latitude"])
        if np.nonzero(lat_nan_v)[0].size:
            full_lat[lat_nan_v] = NetCDFUtils.interp1_extend(
                reduced_time[np.logical_not(lat_nan_v)],
                full_lat[np.logical_not(lat_nan_v)],
                reduced_time[lat_nan_v],
            )

        full_lon = reduced_vars["longitude"].copy()
        lon_nan_v = np.isnan(reduced_vars["longitude"])
        if np.nonzero(lon_nan_v)[0].size:
            full_lon[lon_nan_v] = NetCDFUtils.interp1_extend(
                reduced_time[np.logical_not(lon_nan_v)],
                full_lon[np.logical_not(lon_nan_v)],
                reduced_time[lon_nan_v],
            )

        create_nc_var(
            dso,
            template,
            "profile_lat",
            full_lat[median_time_i],
        )
        create_nc_var(
            dso,
            template,
            "profile_lon",
            full_lon[median_time_i],
        )
        create_nc_var(
            dso,
            template,
            "v",
            dsi["depth_avg_curr_north"],
            qc_val=dsi["depth_avg_curr_qc"],
        )
        create_nc_var(
            dso,
            template,
            "u",
            dsi["depth_avg_curr_east"],
            qc_val=dsi["depth_avg_curr_qc"],
        )
        create_nc_var(
            dso,
            template,
            "time_uv",
            reduced_time[median_time_i],
        )
        create_nc_var(
            dso,
            template,
            "lat_uv",
            full_lat[median_time_i],
        )
        create_nc_var(
            dso,
            template,
            "lon_uv",
            full_lon[median_time_i],
        )

        # This varibles are just to hold the attched metadata
        metadata_vars = ["platform"]
        for var_n in template["variables"]:
            if var_n.startswith("instrument_"):
                metadata_vars.append(var_n)

        for var_n in metadata_vars:
            create_nc_var(
                dso,
                template,
                var_n,
                template["variables"][var_n]["attributes"]["_FillValue"],
            )

        # attributes
        dso.attrs["history"] = (
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', processing_start_time)}: GliderDac.py"
        )
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))
        dso.attrs["date_created"] = now_ts
        dso.attrs["date_issued"] = now_ts
        dso.attrs["date_modified"] = now_ts

        #
        # These are not required by the spec
        #
        # per-profile "date_created": "2021-07-16T15:16:27.037189",
        # per-profile "date_modified": "2021-07-19T15:44:11.181969",
        # per-profile "date_issued": "2021-07-19T15:44:57.933159",
        # per-profile "geospatial_bounds": "POLYGON ((-117.6545 33.2183, -117.6833 33.2308, -117.6761 33.227675, -117.6545 33.2183))",
        # for a in (
        #     "geospatial_lat_min",
        #     "geospatial_lat_max",
        #     "geospatial_lon_min",
        #     "geospatial_lon_max",
        # ):
        #     dso.attrs[a] = np.format_float_positional(
        #         dsi.attrs[a], precision=4, unique=False
        #     )

        # dso.attrs["geospatial_vertical_min"] = np.format_float_positional(
        #     np.floor(np.nanmin(reduced_depth)), precision=2, unique=False
        # )
        # dso.attrs["geospatial_vertical_max"] = np.format_float_positional(
        #     np.ceil(np.nanmax(reduced_depth)), precision=2, unique=False
        # )

        # Apply global attributes from template
        for k, v in template["global_attributes"].items():
            dso.attrs[k] = v

        netcdf_out_filename = os.path.join(
            base_opts.gliderdac_directory,
            f"{trajectory_name}Z{delayed_str}.nc".replace("-", "_"),
        )
        comp = dict(zlib=True, complevel=9)
        # encoding = {var: comp for var in dso.data_vars}
        encoding = {}
        for var in dso.data_vars:
            encoding[var] = comp.copy()
            if template["variables"][var]["type"] == "c":
                encoding[var]["char_dim_name"] = template["variables"][var][
                    "dimensions"
                ][0]
        dso.to_netcdf(
            netcdf_out_filename,
            "w",
            encoding=encoding,
            # engine="netcdf4",
            format="netCDF4",
        )

        if processed_other_files is not None:
            processed_other_files.append(netcdf_out_filename)

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
        sys.stderr.write("Exception in main (%s)\n" % traceback.format_exc())

    sys.exit(retval)
