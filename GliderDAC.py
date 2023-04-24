#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023  University of Washington.
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

""" Create a file for submission to the GliderDAC from an existing netCDF file
"""

from functools import reduce
import os
import pdb
import stat
import sys
import time
import traceback

import gsw
import yaml

import numpy as np
import xarray as xr

import BaseOpts
import MakeDiveProfiles
import NetCDFUtils
import QC

from BaseLog import BaseLogger, log_info, log_warning, log_error, log_debug

# Local config
DEBUG_PDB = True


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


def create_nc_var(dso, template, var_name, data, qc_val=None):
    """Creates a nc variable and sets meta data
    Input:
        dso - output dataset
        template - dictionary of metadata
        var_name - name of variable as appears in teamplate
        data - input data
        qc_val - the qc value to use

    Returns:
        dataarray for variable and matching qc variable

    """
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
        if inp_data == np.nan:
            inp_data = template["variables"][var_name]["attributes"]["_FillValue"]
    else:
        inp_data[inp_data == np.nan] = template["variables"][var_name]["attributes"][
            "_FillValue"
        ]

    # GBS 2022/02/09 In what can only be a bug, if the time_qc variable is written out after the time variable,
    # time variables attributes are deleted, leaving an empty dict.  No other variables have
    # this issue.  If the order is reversed - qc before regular variable - no problems.  This
    # may be related to the fact that the time variable has the same name as the time dimension,
    # and is there for picked up as an indexing coordinate by xarray.

    # QC array
    qc_name = f"{var_name}_qc"
    if qc_name in template["variables"]:
        if np.ndim(data) == 0:
            qc_v = np.dtype(template["variables"][qc_name]["type"]).type(qc_val)
        else:
            qc_v = np.zeros((np.size(inp_data)), dtype="b") + np.dtype(
                template["variables"][qc_name]["type"]
            ).type(qc_val)
        da_q = xr.DataArray(
            qc_v,
            dims=template["variables"][qc_name]["dimensions"],
            attrs=fix_ints(np.byte, template["variables"][qc_name]["attributes"]),
        )
        dso[qc_name] = da_q
    else:
        da_q = None

    da = xr.DataArray(
        inp_data,
        dims=template["variables"][var_name]["dimensions"] if not is_str else None,
        attrs=fix_ints(np.int32, template["variables"][var_name]["attributes"]),
        # coords=None,
    )
    dso[var_name] = da

    return (da, da_q)


def load_var(
    dci,
    var_name,
):
    """
    Input:
        dci - dataset
        var_name - name of the variable
    Returns
        var - netcdf array, with QC applied (QC_GOOD only)
    """
    var = dci[var_name]
    qc_name = f"{var_name}_qc"
    if qc_name and qc_name in dci.variables:
        var_q = dci[qc_name].data
        try:
            qc_vals = QC.decode_qc(var_q)
        except:
            log_warning(f"Could not decode QC for {var_name} - not applying", "exc")
        else:
            var[qc_vals != QC.QC_GOOD] = np.nan

    return var


def load_templates(base_opts):
    """Load configuration template files and merge into one"""

    # Check for all variables being set
    if (
        not base_opts.gliderdac_base_config
        or not base_opts.gliderdac_project_config
        or not base_opts.gliderdac_deployment_config
    ):
        log_error("Needed config file not specified")
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
        except:
            log_error(f"Could not procss {file_name}", "exc")
            return None

    # Merge templates together
    try:
        reduce(NetCDFUtils.merge_dict, templates)
    except:
        log_error("Error merging config templates", "exc")
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
        base_opts = BaseOpts.BaseOptions(
            "Basestation extension for creating GliderDAC netCDF files",
        )

    BaseLogger(base_opts)

    if base_opts.delayed_submission:
        delayed_str = "_delayed"
    else:
        delayed_str = ""

    # TODO: Make these configurable
    master_time_name = "ctd_time"
    master_depth_name = "ctd_depth"

    processing_start_time = time.gmtime(time.time())
    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", processing_start_time)
    )

    if not base_opts.mission_dir and base_opts.netcdf_filename:
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
        except:
            log_error(f"Could not create {base_opts.gliderdac_directory}", "exc")
            log_info("Bailing out")
            return 1

    template = load_templates(base_opts)
    if not template:
        return 1

    for dive_nc_file_name in dive_nc_file_names:
        log_info("Processing %s" % dive_nc_file_name)
        try:
            dsi = xr.open_dataset(dive_nc_file_name)
        except:
            log_error(f"Errror opening {dive_nc_file_name}", "exc")
            continue

        dso = xr.Dataset()

        if master_time_name not in dsi or master_depth_name not in dsi:
            log_error("Could not load variables - skipping", "exc")
            continue

        master_depth = dsi[master_depth_name].data
        # Xarray converts to numpy.datetime64(ns) - get it back to something useful
        master_time = dsi[master_time_name].data.astype(np.float64) / 1000000000.0

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

        timeseries_vars = {
            "temperature": "temperature",
            "salinity": "salinity",
            "conductivity": "conductivity",
            "latitude": "lat",
            "longitude": "lon",
            "ctd_pressure": "pressure",
        }

        # Note: for non-binned, this variable is just a copy of the data straight from
        # the netcdf file
        binned_vars = {}
        for var_name in timeseries_vars:
            log_debug(f"Adding variable {var_name}")
            data = load_var(
                dsi,
                var_name,
            )
            if base_opts.gliderdac_bin_width:
                max_depth_i = find_deepest_bin_i(
                    master_depth, bin_edges, base_opts.gliderdac_bin_width
                )

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
                binned_vars[var_name] = (data.data, np.isfinite(data))

        # Locate the good points
        good_pts_i = np.squeeze(
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
            reduced_vars[var_name] = val[0][good_pts_i]
            create_nc_var(
                dso,
                template,
                timeseries_vars[var_name],
                reduced_vars[var_name],
                qc_val=QC.QC_GOOD
                if var_name not in ("latitude", "longitude", "pressure")
                else QC.QC_NO_CHANGE,
            )
            # This is just for debugging
            if base_opts.gliderdac_bin_width and var_name == "temperature":
                create_nc_var(dso, template, "temperature_n", val[2][good_pts_i])

        if base_opts.gliderdac_bin_width:
            reduced_depth = bin_centers[good_pts_i]
            reduced_time = t_profile[good_pts_i]
            del (
                bin_centers,
                t_profile,
            )
        else:
            reduced_depth = master_depth[good_pts_i]
            reduced_time = master_time[good_pts_i]

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
        create_nc_var(dso, template, "density", density, qc_val=QC.QC_GOOD)

        del binned_vars, good_pts_i

        # Depth and time
        create_nc_var(dso, template, "depth", reduced_depth, qc_val=QC.QC_NO_CHANGE)
        create_nc_var(dso, template, "time", reduced_time, qc_val=QC.QC_NO_CHANGE)

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
            qc_val=QC.QC_NO_CHANGE,
        )
        create_nc_var(
            dso,
            template,
            "profile_lat",
            reduced_vars["latitude"][median_time_i],
            qc_val=QC.QC_NO_CHANGE,
        )
        create_nc_var(
            dso,
            template,
            "profile_lon",
            reduced_vars["longitude"][median_time_i],
            qc_val=QC.QC_NO_CHANGE,
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
            qc_val=QC.QC_NO_CHANGE,
        )
        create_nc_var(
            dso,
            template,
            "lat_uv",
            reduced_vars["latitude"][median_time_i],
            qc_val=QC.QC_NO_CHANGE,
        )
        create_nc_var(
            dso,
            template,
            "lon_uv",
            reduced_vars["longitude"][median_time_i],
            qc_val=QC.QC_NO_CHANGE,
        )

        # This varibles are just to hold the attched metadata
        create_nc_var(
            dso,
            template,
            "platform",
            template["variables"]["instrument_ctd"]["attributes"]["_FillValue"],
        )
        create_nc_var(
            dso,
            template,
            "instrument_ctd",
            template["variables"]["instrument_ctd"]["attributes"]["_FillValue"],
        )

        # attributes
        dso.attrs[
            "history"
        ] = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', processing_start_time)}: GliderDac.py"
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
    except:
        if DEBUG_PDB:
            extype, value, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        sys.stderr.write("Exception in main (%s)\n" % traceback.format_exc())

    sys.exit(retval)
