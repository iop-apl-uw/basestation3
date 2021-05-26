#! /usr/bin/env python

##
## Copyright (c) 2006, 2007, 2009, 2012, 2013, 2015, 2016, 2018, 2020, 2021 by University of Washington.  All rights reserved.
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

""" Create simpler per-dive netCDF files
"""


import bz2
import collections
import os
import pdb
import sys
import time
import traceback

import numpy as np
import scipy.interpolate
from scipy.stats import binned_statistic

import BaseOpts
import Conf
import MakeDiveProfiles
import QC
import Utils

from BaseLog import BaseLogger, log_info, log_warning, log_error, log_debug

# Local config
DEBUG_PDB = True

simp_cdf_conf_default_dict = {
    "bin_width": [0.0, 0.0, 1000.0],
    "compress_output": [0, 0, 1],
}

var_metadata = collections.namedtuple(
    "var_metadata", ["qc_name", "time_name", "depth_name", "dimension",],
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
        "aanderaa4831_dissolved_oxygen_qc", "aa4831_time", None, "aa4831_data_point",
    ),
}

nc_meta["wlbb2fl_time"] = var_metadata(None, "wlbb2fl_time", None, "wlbb2fl_data_point")
for sig in (470, 700, 695):
    nc_meta[f"wlbb2fl_sig{sig}nm_adjusted"] = var_metadata(
        None, "wlbb2fl_time", None, "wlbb2fl_data_point"
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
]

# Binned profile names
depth_dimension_name = "depth_data_point"
profile_dimension_name = "profile_data_point"

nc_var_meta = collections.namedtuple("nc_vars_meta", ["dtype", "attrs", "dimensions",],)

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
    """ Creates a nc varable and sets meta data
    Returns:
        nc_var
    """
    nc_var = ncf.createVariable(
        var_name, new_nc_vars[var_name].dtype, new_nc_vars[var_name].dimensions
    )
    for a, v in new_nc_vars[var_name].attrs.items():
        nc_var.__setattr__(a, v)
    return nc_var


def load_var(
    ncf, var_name, var_meta, master_time_name, master_depth_name,
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
        except:
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
        depth = interp1_extend(
            ncf.variables[master_time_name][:],
            ncf.variables[master_depth_name][:],
            ncf.variables[var_meta.time_name][:],
        )

    return (var, depth)


def cp_attrs(in_var, out_var):
    """ Copies the netcdf attributes from the in_var
    to the out_var
    """
    # pylint: disable=protected-access
    for a in list(in_var._attributes.keys()):
        out_var.__setattr__(a, in_var._attributes[a])
    # pylint: enable=protected-access


def interp1_extend(t1, data, t2):
    """ Interpolates t1/data onto t2, extending t1/data to cover the range
    of t2
    """
    # add 'nearest' data item to the ends of data and t1
    if t2[0] < t1[0]:
        # Copy the first value below the interpolation range
        data = np.append(np.array([data[0]]), data)
        t1 = np.append(np.array([t2[0]]), t1)

    if t2[-1] > t1[-1]:
        # Copy the last value above the interpolation range
        data = np.append(data, np.array([data[-1]]))
        t1 = np.append(t1, np.array([t2[-1]]))

    return scipy.interpolate.interp1d(t1, data)(t2)


def bindata(x, y, bins, sigma=False):
    """
    Bins y(x) onto bins by averaging, when bins define the right hand side of the bin
    NaNs are ignored.  Values less then bin[0] LHS are included in bin[0],
    values greater then bin[-1] RHS are included in bin[-1]

    Input:
        x: values to be binned
        y: data upon which the averaging will be calculated
        bins: right hand side of the bins
        sigma: boolean to indicated if the standard deviation should also be calculated

    Returns:
        b: binned data (averaged)
        n: number of points in each bin
        sigma: standard deviation of the data (if so requested)

    Notes:
        Current implimentation only handles the 1-D case
    """
    idx = np.logical_not(np.isnan(y))
    if not idx.any():
        nan_return = np.empty(bins.size - 1)
        nan_return[:] = np.nan
        if sigma:
            return (nan_return, nan_return.copy(), nan_return.copy())
        else:
            return (nan_return, nan_return.copy())

    # Only consider the non-nan data
    x = x[idx]
    y = y[idx]

    # Note - this treats things to the left of the first bin edge as in "bin[0]",
    # but does not include it in the first bin statistics - that is avgs[0], which is considered
    # bin 1.  Same logic on the right.
    avgs, _, inds = binned_statistic(x, y, statistic="mean", bins=bins)

    bin_count = np.bincount(inds, minlength=bins.size)
    # Bin number zero number len(bins) are not in the stats, so remove them
    bin_count = bin_count[1 : bins.size]
    bin_count = bin_count * 1.0  # Convert to float
    bin_count[bin_count == 0] = np.nan

    if sigma:
        sigma, _, _ = binned_statistic(x, y, statistic="std", bins=bins)
        return (avgs, bin_count, sigma)
    else:
        return (avgs, bin_count)


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
        base_opts = BaseOpts.BaseOptions(sys.argv, "g", usage="%prog [Options] ")

    BaseLogger("SimpleNetCDF", base_opts)  # initializes BaseLog

    args = base_opts.get_args()  # positional arguments

    simp_cdf_conf = Conf.conf("simplenetcdf", simp_cdf_conf_default_dict)
    if simp_cdf_conf.parse_conf_file(base_opts.config_file_name) > 2:
        log_error(
            "Count not process %s - continuing with defaults"
            % base_opts.config_file_name
        )
    simp_cdf_conf.dump_conf_vars()

    # These may need to be configurable, but for most cases, they should be constant
    master_time_name = "ctd_time"
    master_depth_name = "ctd_depth"

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if not base_opts.mission_dir and len(args) == 1:
        dive_nc_file_names = [os.path.expanduser(args[0])]
    else:
        if nc_files_created is not None:
            dive_nc_file_names = nc_files_created
        elif not dive_nc_file_names:
            # Collect up the possible files
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)

    for dive_nc_file_name in dive_nc_file_names:
        log_info("Processing %s" % dive_nc_file_name)

        netcdf_in_filename = dive_nc_file_name
        head = os.path.splitext(netcdf_in_filename)[0]
        if simp_cdf_conf.bin_width:
            netcdf_out_filename = "%s.ncfb" % (head)
        else:
            netcdf_out_filename = "%s.ncf" % (head)

        log_info("Output file = %s" % netcdf_out_filename)

        if not os.path.exists(netcdf_in_filename):
            sys.stderr.write("File %s does not exists\n" % netcdf_in_filename)
            return 1

        nci = Utils.open_netcdf_file(netcdf_in_filename, "r", mmap=False)
        nco = Utils.open_netcdf_file(netcdf_out_filename, "w", mmap=False)
        if (
            master_time_name not in nci.variables
            or master_depth_name not in nci.variables
        ):
            log_error("Could not load variables - skipping", "exc")
            continue

        for var_name, var_meta in nc_meta.items():
            if var_name not in nci.variables:
                continue
            new_dimension = var_meta.dimension
            new_time = var_meta.time_name
            if var_meta.dimension not in nci.dimensions:
                new_dimension = "sg_data_point"
            if var_meta.time_name not in nci.variables:
                new_time = "time"
            nc_meta[var_name] = var_metadata(var_meta.qc_name, new_time, var_meta.depth_name, new_dimension)

        nc_dims = set()
        nc_vars = set()
        for var_name, var_meta in nc_meta.items():
            if var_name not in nci.variables:
                continue
            
            nc_dims.add(var_meta.dimension)
            nc_vars.add(var_name)
            nc_vars.add(var_meta.time_name)

        if not simp_cdf_conf.bin_width:
            # If not binning, copy over dimensions and variables,
            # converting the doubles to floats
            for d in nc_dims:
                log_debug(f"Adding dimesion {d}")
                nco.createDimension(d, nci.dimensions[d])
            # pylint: disable=protected-access
        else:
            master_depth = nci.variables[master_depth_name][:]
            max_depth = np.floor(np.nanmax(master_depth))
            bin_centers = np.arange(0.0, max_depth + 0.01, simp_cdf_conf.bin_width)
            # This is actually bin edges, so one more point then actual bins
            bin_edges = np.arange(
                -simp_cdf_conf.bin_width / 2.0,
                max_depth + simp_cdf_conf.bin_width / 2.0 + 0.01,
                simp_cdf_conf.bin_width,
            )
            # Do this to ensure everything is caught in the binned statistic
            bin_edges[0] = -20.0
            bin_edges[-1] = max_depth + 50.0

            # Create the depth vector and time vector (down/up)
            nco.createDimension(depth_dimension_name, len(bin_centers))
            nco.createDimension(profile_dimension_name, 2)
            depth = create_nc_var(nco, "depth")
            depth[0, :] = bin_centers
            depth[1, :] = bin_centers
            profile = create_nc_var(nco, "profile")
            # profile[:] = np.array((ord("a"), ord("b")), np.byte)
            profile[:] = np.array((0, 1), np.int16)

            # Set the time variable for the depth vector
            master_time = nci.variables[master_time_name][:]
            max_depth_i = np.argmax(master_depth)
            t_down = interp1_extend(
                master_depth[:max_depth_i], master_time[:max_depth_i], bin_centers
            )
            t_up = interp1_extend(
                master_depth[max_depth_i:], master_time[max_depth_i:], bin_centers[::-1]
            )
            ttime = create_nc_var(nco, "time")
            ttime[0, :] = t_down
            ttime[1, :] = t_up

        for var_name in nc_vars:
            var_meta = nc_meta[var_name]
            log_debug(f"Adding variable {var_name}")
            data, depth = load_var(
                nci, var_name, var_meta, master_time_name, master_depth_name,
            )
            if not simp_cdf_conf.bin_width:
                vv = nco.createVariable(
                    var_name, np.float32, nci.variables[var_name].dimensions
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
                binned_data_down, n_obs_down, *_ = bindata(
                    depth[:max_depth_i], data[:max_depth_i], bin_edges
                )
                binned_data_up, n_obs_up, *_ = bindata(
                    depth[max_depth_i:], data[max_depth_i:], bin_edges
                )
                obs_max = max(np.nanmax(binned_data_down), np.nanmax(binned_data_up))
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
                )
                n_obs.__setattr__("description", "Number of observations for each bin")
                n_obs[0, :] = n_obs_down
                n_obs[1, :] = n_obs_up

                vv = nco.createVariable(
                    var_name, np.float32, (profile_dimension_name, depth_dimension_name)
                )
                vv[0, :] = binned_data_down
                vv[1, :] = binned_data_up

            cp_attrs(nci.variables[var_name], vv)

        single_var_dims = set()
        for var_name in single_vars:
            if nci.variables[var_name].dimensions:
                for dim_name in nci.variables[var_name].dimensions:
                    single_var_dims.add(dim_name)
        for dim_name in single_var_dims:
            nco.createDimension(dim_name, nci.dimensions[dim_name])
        for var_name in single_vars:
            nco.variables[var_name] = nci.variables[var_name]

        # pylint: disable=protected-access
        for a in list(nci._attributes.keys()):
            if not (simp_cdf_conf.bin_width and a == "history"):
                nco.__setattr__(a, nci._attributes[a])
        # pylint: enable=protected-access

        nci.close()
        nco.sync()
        nco.close()

        if processed_other_files is not None:
            processed_other_files.append(netcdf_out_filename)

        if simp_cdf_conf.compress_output:
            netcdf_out_filename_bzip = netcdf_out_filename + ".bz2"
            try:
                with open(netcdf_out_filename, "rb") as fi, bz2.open(
                    netcdf_out_filename_bzip, "wb"
                ) as fo:
                    fo.write(fi.read())
            except:
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
    try:
        retval = main()
    except:
        if DEBUG_PDB:
            extype, value, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        sys.stderr.write("Exception in main (%s)\n" % traceback.format_exc())

    sys.exit(retval)
