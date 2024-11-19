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

"""Create simpler per-dive netCDF files"""

import bz2
import collections
import os
import pdb
import sys
import time
import traceback
import warnings

import numpy as np

import BaseOpts
import BaseOptsType
import MakeDiveProfiles
import NetCDFUtils
import QC
import Utils
from BaseLog import BaseLogger, log_debug, log_error, log_info, log_warning

DEBUG_PDB = False
# DEBUG_PDB = "darwin" in sys.platform
if DEBUG_PDB:
    warnings.filterwarnings("error")

var_metadata = collections.namedtuple(
    "var_metadata",
    [
        "qc_name",
        "time_name",
        "depth_name",
        "dimension",
    ],
)

nc_meta = {
    "time": var_metadata(None, "time", "depth", "sg_data_point"),
    "depth": var_metadata(None, "time", "depth", "sg_data_point"),
    "ctd_time": var_metadata(None, "ctd_time", "ctd_depth", "ctd_data_point"),
    "ctd_depth": var_metadata(None, "ctd_time", "ctd_depth", "ctd_data_point"),
    "temperature": var_metadata(
        "temperature_qc", "ctd_time", "ctd_depth", "ctd_data_point"
    ),
    "salinity": var_metadata("salinity_qc", "ctd_time", "ctd_depth", "ctd_data_point"),
    "latitude": var_metadata(None, "ctd_time", "ctd_depth", "ctd_data_point"),
    "longitude": var_metadata(None, "ctd_time", "ctd_depth", "ctd_data_point"),
    # "aa4831_O2": var_metadata(None, "aa4841_time", None, "aa4831_data_point",),
    "aa4831_time": var_metadata(None, "aa4831_time", None, "aa4831_data_point"),
    "aanderaa4831_dissolved_oxygen": var_metadata(
        "aanderaa4831_dissolved_oxygen_qc",
        "aa4831_time",
        None,
        "aa4831_data_point",
    ),
}

for wl_type in ("wlbb2fl", "wlbbfl2", "wlbb3", "wlfl3"):
    nc_meta[f"{wl_type}_time"] = var_metadata(
        None, f"{wl_type}_time", None, f"{wl_type}_data_point"
    )
    for sig in (460, 470, 695, 700):
        nc_meta[f"{wl_type}_sig{sig}nm_adjusted"] = var_metadata(
            None, f"{wl_type}_time", None, f"{wl_type}_data_point"
        )

nc_meta["ocr504i_time"] = var_metadata(None, "ocr504i_time", None, "ocr504i_data_point")
for ii in range(1, 5):
    nc_meta[f"ocr504i_chan{ii}"] = var_metadata(
        None, "ocr504i_time", None, "ocr504i_data_point"
    )

# List of single variables to copy over
single_vars = [
    "depth_avg_curr_qc",
    "depth_avg_curr_error",
    "depth_avg_curr_north_gsm",
    "depth_avg_curr_east_gsm",
    "depth_avg_curr_north",
    "depth_avg_curr_east",
    "surface_curr_qc",
    "surface_curr_east",
    "surface_curr_north",
]

# Binned profile names
depth_dimension_name = "depth_data_point"
profile_dimension_name = "profile_data_point"

nc_var_meta = collections.namedtuple(
    "nc_vars_meta",
    [
        "dtype",
        "attrs",
        "dimensions",
    ],
)

new_nc_vars = {
    "depth": nc_var_meta(
        np.float32,
        {
            "standard_name": "depth",
            "axis": "Z",
            "units": "meters",
            "positive": "down",
            "description": "Depth below the surface, corrected for average latitude",
        },
        (profile_dimension_name, depth_dimension_name),
    ),
    "profile": nc_var_meta(
        # np.byte,
        np.int16,
        # {"description": "Profile - a == dive, b == climb"},
        {"description": "Profile - 0 == dive, 1 == climb"},
        (profile_dimension_name,),
    ),
    "time": nc_var_meta(
        np.float64,
        {
            "standard_name": "time",
            "axis": "T",
            "units": "seconds since 1970-1-1 00:00:00",
            "description": "Time of CTD [P] in GMT epoch format",
        },
        (profile_dimension_name, depth_dimension_name),
    ),
}


# Util functions
def create_nc_var(ncf, var_name):
    """Creates a nc varable and sets meta data
    Returns:
        nc_var
    """
    nc_var = ncf.createVariable(
        var_name,
        new_nc_vars[var_name].dtype,
        new_nc_vars[var_name].dimensions,
        compression="zlib",
        complevel=9,
    )
    for a, v in new_nc_vars[var_name].attrs.items():
        nc_var.setncattr(a, v)
    return nc_var


def load_var(
    ncf,
    var_name,
    var_meta,
    master_time_name,
    master_depth_name,
):
    """
    Input:
        ncf - netcdf file object
        var_name - name of the variable
        var_meta - associated columns
        master_depth_name - name of the master depth variable (usually ctd_depth)
        master_time_name - name fo the master time varible (usually ctd_time)
    Returns
        var - netcdf array, with QC applied (QC_GOOD only)
        depth - netcdf array for the matching depth (interpolated if need be)
    """
    var = ncf.variables[var_name][:]
    if var_meta.qc_name and var_meta.qc_name in ncf.variables:
        var_q = ncf.variables[var_meta.qc_name][:]
        try:
            qc_vals = QC.decode_qc(var_q)
        except Exception:
            log_warning(f"Could not decode QC for {var_name} - not applying")
        else:
            # This code doesn't work - find_qc for the mask needs to be fixed and propagated to
            # the basestation.

            # var[
            #    np.logical_not(find_qc(qc_vals, QC.only_good_qc_values, mask=True))
            # ] = nc_nan

            var[qc_vals != QC.QC_GOOD] = np.nan

    if var_meta.depth_name is not None:
        depth = ncf.variables[var_meta.depth_name][:]
    else:
        depth = NetCDFUtils.interp1_extend(
            ncf.variables[master_time_name][:],
            ncf.variables[master_depth_name][:],
            ncf.variables[var_meta.time_name][:],
        )

    return (var, depth)


def cp_attrs(in_var, out_var):
    """Copies the netcdf attributes from the in_var
    to the out_var
    """
    for a in in_var.ncattrs():
        if a != "_FillValue":
            out_var.setncattr(a, in_var.getncattr(a))


def load_additional_arguments():
    """Defines and extends arguments related to this extension.
    Called by BaseOpts when the extension is set to be loaded
    """
    return (
        # Add this module to these options defined in BaseOpts
        ["mission_dir", "netcdf_filename"],
        # Description for any option_group tags used below
        {"simplenetcdf": "Simple NetCDF file generation"},
        # Add these options that are local to this extension
        {
            "simplencf_bin_width": BaseOptsType.options_t(
                0.0,
                (
                    "Base",
                    "SimpleNetCDF",
                ),
                ("--simplencf_bin_width",),
                float,
                {
                    "help": "Bin SimpleNetCDF output to this size.  0 generates timeseries files.  Negative generates timeseries and binned files",
                    "section": "simplenetcdf",
                    "option_group": "simplenetcdf",
                },
            ),
            "simplencf_compress_output": BaseOptsType.options_t(
                False,
                (
                    "Base",
                    "SimpleNetCDF",
                ),
                ("--simplencf_compress_output",),
                bool,
                {
                    "help": "Compress the SimpleNetCDF file with bzip2",
                    "action": "store_true",
                    "section": "simplenetcdf",
                    "option_group": "simplenetcdf",
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
        (
            add_to_arguments,
            add_option_groups,
            additional_arguments,
        ) = load_additional_arguments()
        base_opts = BaseOpts.BaseOptions(
            "Basestation extension for creating simplified netCDF files",
            additional_arguments=additional_arguments,
            add_option_groups=add_option_groups,
            add_to_arguments=add_to_arguments,
        )

    BaseLogger(base_opts)  # initializes BaseLog

    # These may need to be configurable, but for most cases, they should be constant
    master_time_name = "ctd_time"
    master_depth_name = "ctd_depth"

    log_info(
        f"Started processing {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(time.time()))}"
    )

    if base_opts.simplencf_bin_width < 0:
        simplencf_bin_widths = [0.0, np.abs(base_opts.simplencf_bin_width)]
    else:
        simplencf_bin_widths = [base_opts.simplencf_bin_width]

    for simplencf_bin_width in simplencf_bin_widths:
        log_info(
            f"bin_width:{simplencf_bin_width}, compress_output:{base_opts.simplencf_compress_output}"
        )

        if hasattr(base_opts, "netcdf_filename") and base_opts.netcdf_filename:
            dive_nc_file_names = [base_opts.netcdf_filename]
        elif base_opts.mission_dir:
            if nc_files_created is not None:
                dive_nc_file_names = nc_files_created
            elif not dive_nc_file_names:
                # Collect up the possible files
                dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(
                    base_opts
                )
        else:
            log_error("Either mission_dir or netcdf_file must be specified")
            return 1

        for dive_nc_file_name in dive_nc_file_names:
            log_info("Processing %s" % dive_nc_file_name)

            netcdf_in_filename = dive_nc_file_name
            head = os.path.splitext(netcdf_in_filename)[0]
            if simplencf_bin_width:
                netcdf_out_filename = "%s.ncfb" % (head)
            else:
                netcdf_out_filename = "%s.ncf" % (head)

            log_info("Output file = %s" % netcdf_out_filename)

            if not os.path.exists(netcdf_in_filename):
                sys.stderr.write("File %s does not exists\n" % netcdf_in_filename)
                return 1

            nci = Utils.open_netcdf_file(netcdf_in_filename, "r")
            if (
                master_time_name not in nci.variables
                or master_depth_name not in nci.variables
            ):
                log_error(
                    f"Could not load variables {master_time_name} or {master_depth_name} from {netcdf_in_filename} - skipping"
                )
                continue

            nco = Utils.open_netcdf_file(netcdf_out_filename, "w")
            for var_name, var_meta in nc_meta.items():
                if var_name not in nci.variables:
                    continue
                new_dimension = var_meta.dimension
                new_time = var_meta.time_name
                if var_meta.dimension not in nci.dimensions:
                    new_dimension = "sg_data_point"
                if var_meta.time_name not in nci.variables:
                    new_time = "time"
                nc_meta[var_name] = var_metadata(
                    var_meta.qc_name, new_time, var_meta.depth_name, new_dimension
                )

            nc_dims = set()
            nc_vars = set()
            for var_name, var_meta in nc_meta.items():
                if var_name not in nci.variables:
                    continue

                nc_dims.add(var_meta.dimension)
                nc_vars.add(var_name)
                nc_vars.add(var_meta.time_name)

            if not simplencf_bin_width:
                # If not binning, copy over dimensions and variables,
                # converting the doubles to floats
                for d in nc_dims:
                    log_debug(f"Adding dimesion {d}")
                    nco.createDimension(d, nci.dimensions[d].size)
                # pylint: disable=protected-access
            else:
                master_depth = nci.variables[master_depth_name][:]
                max_depth = np.floor(np.nanmax(master_depth))
                bin_centers = np.arange(0.0, max_depth + 0.01, simplencf_bin_width)
                # This is actually bin edges, so one more point then actual bins
                bin_edges = np.arange(
                    -simplencf_bin_width / 2.0,
                    max_depth + simplencf_bin_width / 2.0 + 0.01,
                    simplencf_bin_width,
                )
                # Do this to ensure everything is caught in the binned statistic
                bin_edges[0] = -20.0
                bin_edges[-1] = max_depth + 50.0

                # Create the depth vector and time vector (down/up)
                nco.createDimension(depth_dimension_name, len(bin_centers))
                nco.createDimension(profile_dimension_name, 2)
                depth = create_nc_var(nco, "depth")
                depth.description += " - center of bin"
                depth[0, :] = bin_centers
                depth[1, :] = bin_centers
                profile = create_nc_var(nco, "profile")
                # profile[:] = np.array((ord("a"), ord("b")), np.byte)
                profile[:] = np.array((0, 1), np.int16)

                # Set the time variable for the depth vector
                master_time = nci.variables[master_time_name][:]
                max_depth_i = np.argmax(master_depth)
                t_down = NetCDFUtils.interp1_extend(
                    master_depth[:max_depth_i],
                    master_time[:max_depth_i],
                    bin_centers,
                    fill_value="extrapolate",
                )
                t_up = NetCDFUtils.interp1_extend(
                    master_depth[max_depth_i:],
                    master_time[max_depth_i:],
                    bin_centers[::-1],
                    fill_value="extrapolate",
                )
                ttime = create_nc_var(nco, "time")
                ttime[0, :] = t_down
                ttime[1, :] = t_up

            for var_name in nc_vars:
                var_meta = nc_meta[var_name]
                log_debug(f"Adding variable {var_name}")
                data, depth = load_var(
                    nci,
                    var_name,
                    var_meta,
                    master_time_name,
                    master_depth_name,
                )
                if not simplencf_bin_width:
                    vv = nco.createVariable(
                        var_name,
                        np.float32,
                        nci.variables[var_name].dimensions,
                        compression="zlib",
                        complevel=9,
                    )
                    if "time" in var_name:
                        nco.variables[var_name] = nci.variables[var_name]
                        vv[:] = data
                    else:
                        # Reduce to float for data fields
                        vv[:] = data.astype(np.float32)
                else:
                    if "time" in var_name or "depth" in var_name:
                        continue
                    max_depth_i = np.argmax(depth)
                    binned_data_down, n_obs_down, *_ = NetCDFUtils.bindata(
                        depth[:max_depth_i], data[:max_depth_i], bin_edges
                    )
                    binned_data_up, n_obs_up, *_ = NetCDFUtils.bindata(
                        depth[max_depth_i:], data[max_depth_i:], bin_edges
                    )
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", category=RuntimeWarning)
                        obs_max = max(
                            np.nanmax(binned_data_down), np.nanmax(binned_data_up)
                        )

                    if obs_max <= np.iinfo(np.int8).max:
                        n_obs_type = np.int8
                    elif obs_max <= np.iinfo(np.int16).max:
                        n_obs_type = np.int16
                    else:
                        n_obs_type = np.int32

                    n_obs = nco.createVariable(
                        f"{var_name}_num_obs",
                        n_obs_type,
                        (profile_dimension_name, depth_dimension_name),
                        fill_value=-1,
                    )
                    n_obs.setncattr(
                        "description", "Number of observations for each bin"
                    )
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", category=RuntimeWarning)

                        n_obs[0, :] = n_obs_down
                        n_obs[1, :] = n_obs_up

                    vv = nco.createVariable(
                        var_name,
                        np.float32,
                        (profile_dimension_name, depth_dimension_name),
                        fill_value=np.nan,
                        compression="zlib",
                        complevel=9,
                    )
                    vv[0, :] = binned_data_down
                    vv[1, :] = binned_data_up

                cp_attrs(nci.variables[var_name], vv)

            single_var_dims = set()
            single_vars_filtered = list(
                filter(lambda i: i in nci.variables, single_vars)
            )
            for var_name in list(filter(lambda i: i not in nci.variables, single_vars)):
                log_warning(f"{var_name} not in {netcdf_in_filename} - skipping")

            for var_name in single_vars_filtered:
                if nci.variables[var_name].dimensions:
                    for dim_name in nci.variables[var_name].dimensions:
                        single_var_dims.add(dim_name)
            for dim_name in single_var_dims:
                nco.createDimension(dim_name, nci.dimensions[dim_name].size)
            for var_name in single_vars_filtered:
                nco.variables[var_name] = nci.variables[var_name]

            for a in nci.ncattrs():
                if not (simplencf_bin_width and a == "history"):
                    nco.setncattr(a, nci.getncattr(a))

            nci.close()
            nco.sync()
            nco.close()

            if processed_other_files is not None:
                processed_other_files.append(netcdf_out_filename)

            if base_opts.simplencf_compress_output:
                netcdf_out_filename_bzip = netcdf_out_filename + ".bz2"
                try:
                    with (
                        open(netcdf_out_filename, "rb") as fi,
                        bz2.open(netcdf_out_filename_bzip, "wb") as fo,
                    ):
                        fo.write(fi.read())
                except Exception:
                    log_error("Could not write out bz output", "exc")
                else:
                    if processed_other_files is not None:
                        processed_other_files.append(netcdf_out_filename_bzip)

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
        sys.stderr.write("Exception in main (%s)\n" % traceback.format_exc())

    sys.exit(retval)
