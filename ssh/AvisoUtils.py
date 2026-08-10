#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2023, 2024, 2025, 2026 by University of Washington.  All rights reserved.
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


import argparse
import os
import pathlib
import pdb
import shutil
import sys
import time
import traceback
import warnings

import copernicusmarine
import netCDF4
import numpy as np

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))
import BaseOpts
import BaseOptsType
from BaseLog import BaseLogger, log_critical, log_error, log_info

DEBUG_PDB = False

# The join() call prepends the current working directory, but the documentation
# says that if some path is absolute, all other paths left of it are
# dropped. Therefore, getcwd() is dropped when dirname(__file__) returns an
# absolute path.

# Also, the realpath call resolves symbolic links if any are found. This avoids
# troubles when deploying with setuptools on Linux systems (scripts are
# symlinked to /usr/bin/).
# __location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


def load_array(ncf, var_name):
    """Loads a column vector (var_name) from a netcdf file (ncf)
    Inserts nans for the fill value and applies the scal factor
    """
    a_tmp = ncf.variables[var_name][:]
    a_tmp = np.transpose(a_tmp)
    b_tmp = a_tmp.filled()
    b_tmp[np.where(b_tmp == a_tmp.fill_value)] = np.nan
    return b_tmp


def read_aviso(
    stime, lon_min, lon_max, lat_min, lat_max, ssh_dir, nrt=True, source_mean=1
):
    """Inputs:
    stime = "YYYYMMDD",
    source_mean = 0:  no mean, anomalies only
    source_mean = 1 for Aviso's mean (MDT_CNES_CLS09)  - DEFAULT (now included in the PHYS files, as of July 2017)
    source_mean  = 2 for Maximenko and Niiler's (http://apdrc.soest.hawaii.edu/projects/DOT/) (NYI)

    """
    if source_mean != 1:
        log_error("source_mean %d not yet implimented")
        return None

    # NYI mean_dynamic_topo_file_name = os.path.abspath(os.path.join(__location__, "MeanDynamicTopography.mat"))
    nrt_aviso_file_name = os.path.join(
        ssh_dir, "nrt_global_allsat_phy_l4_%s_%s.nc" % (stime, stime)
    )

    if not os.path.exists(nrt_aviso_file_name):
        log_info("%s does not exist" % nrt_aviso_file_name)
        return None

    if os.stat(nrt_aviso_file_name).st_size == 0:
        log_info("%s is empty" % nrt_aviso_file_name)
        return None

    # NYI mean_dynamic_topo = loadmat(mean_dynamic_topo_file_name)
    try:
        nrt_aviso = netCDF4.Dataset(nrt_aviso_file_name, "r")
    except OSError:
        log_error("Failed to open %s" % nrt_aviso_file_name, "exc")
        return None

        # nrt_aviso.set_auto_mask(False)

    # Sea Level Anomalies
    # sla = load_array(nrt_aviso, 'sla')

    lon = nrt_aviso.variables["longitude"][:]
    lat = nrt_aviso.variables["latitude"][:]

    # Add the mean
    if source_mean == 1:
        # From the original matlab for older versions where
        # there was no adt value
        # load(MeanDynamicTopo,'MDT_20y')
        # adt = sla + MDT_20y;

        adt = np.squeeze(load_array(nrt_aviso, "adt"))
    # elseif source_mean==2
    #    load(MeanDynamicTopo,'MDT_MN')
    #    adt = sla + MDT_MN;
    # elseif source_mean==0
    #    adt = sla;

    date_line = False
    if lon_min < 0 and lon_max > 0 and (lon_max - lon_min) > 180:
        # Region straddles the date line
        # Extend the map by a globe and swap the lon limits
        lon = np.concatenate((lon - 360, lon))
        adt = np.concatenate((adt, adt))
        tmp = lon_max - 360.0
        lon_max = lon_min
        lon_min = tmp
        date_line = True

    lat_b = (lat >= lat_min - 0.5) & (lat <= lat_max + 0.5)
    lon_b = (lon >= lon_min - 0.5) & (lon <= lon_max + 0.5)
    lon = lon[lon_b]
    lat = lat[lat_b]
    # print("shape lon %s" % np.shape(lon))
    # print("shape lat %s" % np.shape(lat))
    # print("shape adt %s %s %s" % np.shape(adt))

    # One might think this form is correct, but it works IFF np.shape(lon_b) == np.shape(lat_b)
    # adt = adt[lon_b, lat_b, 0]
    # This is the form that is needed
    adt = adt[np.ix_(lon_b, lat_b)]
    adt[np.where(adt == 0.0)] = np.nan  # Needed?  Was in the original matlab code

    # print("reduced shape adt %s %s %s" % np.shape(adt))

    if source_mean == 1:
        u = load_array(nrt_aviso, "ugos")  # zonal component
        v = load_array(nrt_aviso, "vgos")  # Meridian componenet

    if date_line:
        u = np.concatenate((u, u))
        v = np.concatenate((v, v))

    # print("shape u %s %s %s" % np.shape(u))
    u = u[np.ix_(lon_b, lat_b)]
    v = v[np.ix_(lon_b, lat_b)]

    # Correct lon if date_line
    # Don't do this here - do it after the countouring
    #    if date_line:
    #        lon[np.squeeze(np.nonzero(lon < -180.0))] += 360.0

    return (lon, lat, adt, u, v, date_line)


def fetch_aviso_nrt(stime, target_dir) -> pathlib.Path | None:
    """Fetches near real time ssh netcdf from server and places it in the target_directory
    stime - yyyymmdd

    """
    from config import copernicus_passwd, copernicus_user
    
    file_name = "nrt_global_allsat_phy_l4_%s_%s.nc" % (stime, stime)
    local_file = "%s/%s" % (target_dir, file_name)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    if os.path.exists(local_file):
        return None

    try:
        copernicusmarine.get(
            # dataset_id="cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.25deg_P1D",
            dataset_id="cmems_obs-sl_glo_phy-ssh_nrt_allsat-l4-duacs-0.125deg_P1D",
            filter=f"*{stime}_{stime}.nc",
            output_directory=target_dir,
            no_directories=True,
            username=copernicus_user,
            password=copernicus_passwd,
        )
    except Exception:
        log_error(f"Failed fetching file {file_name}", "exc")
        try:
            if os.path.exists(local_file):
                os.unlink(local_file)
            return None
        except Exception:
            log_error(f"Failed to remove {local_file}")
            return None
    return pathlib.Path(local_file)


def decimate_nrt_netcdf(
    inp_file_name: pathlib.Path, out_file_name: pathlib.Path
) -> None:
    """Decimates a 0.125 grid spacing file to a 0.25 grid spacing file.
    Minimal sanity check is done to the data

    """
    try:
        dsi = netCDF4.Dataset(inp_file_name, "r")
        dsi.set_auto_mask(False)
    except OSError:
        log_error("Failed to open %s" % inp_file_name, "exc")
        return None

    try:
        dso = netCDF4.Dataset(out_file_name, "w")
        dso.set_auto_mask(False)
    except OSError:
        log_error("Failed to open %s" % out_file_name, "exc")
        return None

    # Copy over the variables
    for dim_name in dsi.dimensions:
        dim_size = dsi.dimensions[dim_name].size
        if dim_name in ("latitude", "longitude"):
            dso.createDimension(dim_name, dim_size // 2)
        else:
            dso.createDimension(dim_name, dim_size)

    # Copy over the variables
    for var_name in dsi.variables:
        nc_var = dsi.variables[var_name]

        nco_v = dso.createVariable(
            var_name,
            nc_var.dtype,
            nc_var.dimensions,
            fill_value=nc_var.get_fill_value(),
            compression="zlib",
            complevel=9,
        )

        acc = []
        for dim_name in nc_var.dimensions:
            if dim_name in ("latitude", "longitude"):
                acc.append(slice(None, None, 2))
            else:
                acc.append(slice(None, None, None))

        for a in nc_var.ncattrs():
            if a != "_FillValue":
                nco_v.setncattr(a, nc_var.getncattr(a))

        # netCDF4 1.7.4 (latest as of this writing) internally reshapes arrays via
        # `data.shape = ...` on a view, which NumPy 2.5 deprecated in favor of
        # np.reshape(copy=False). This is upstream (Unidata/netcdf4-python), not our
        # code - already suppressed for tests via pyproject.toml's filterwarnings.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Setting the shape on a NumPy array has been deprecated",
                category=DeprecationWarning,
            )
            if acc:
                nco_v[:] = nc_var.__getitem__(acc)
            else:
                nco_v[:] = nc_var[:]

    # Copy over global variables
    for a in dsi.ncattrs():
        dso.setncattr(a, dsi.getncattr(a))

    dsi.close()
    dso.sync()
    dso.close()


def remove_older_files(data_dir, earliest_time):
    data_path = pathlib.Path(data_dir)
    if data_path.exists() and data_path.is_dir():
        for ff in data_path.iterdir():
            if (
                ff.is_file()
                and ff.suffix == ".nc"
                and ff.stat().st_mtime < earliest_time
            ):
                log_info(f"Removing {ff}")
                ff.unlink()
    else:
        log_error(f"{data_path} does not exits or is not a directory")


def main():
    """Command line app for fetching ssh data

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    base_opts = BaseOpts.BaseOptions(
        "Command line app for creating kml/kmz files of ssh contours",
        additional_arguments={
            "fetch_ssh": BaseOptsType.options_t(
                True,
                ("AvisoUtils",),
                ("--fetch_ssh",),
                bool,
                {
                    "help": "Fetch the most recent ssh data",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "decimate_data": BaseOptsType.options_t(
                True,
                ("AvisoUtils",),
                ("--decimate_data",),
                bool,
                {
                    "help": "Decimate the ssh data by half",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "data_dir": BaseOptsType.options_t(
                None,
                ("AvisoUtils",),
                ("data_dir",),
                BaseOpts.FullPathlib,
                {
                    "help": "Location of Aviso data",
                },
            ),
            "start_time": BaseOptsType.options_t(
                None,
                ("AvisoUtils",),
                ("start_time",),
                str,
                {
                    "help": "Earliest accepted data",
                    "nargs": "?",
                },
            ),
            "delete_older": BaseOptsType.options_t(
                0.0,
                ("AvisoUtils",),
                ("--delete_older",),
                float,
                {
                    "help": "Delete files with earlier modification older then this number of days",
                },
            ),
        },
    )

    BaseLogger(base_opts, include_time=True)

    processing_start_time = time.time()

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if base_opts.start_time:
        stime = base_opts.start_time
    else:
        stime = time.strftime("%Y%m%d")

    earliest_time = None
    if base_opts.delete_older:
        earliest_time = time.mktime(time.strptime(stime, "%Y%m%d")) - (
            3600 * 24 * base_opts.delete_older
        )

    nc_file_name = fetch_aviso_nrt(stime, base_opts.data_dir)

    # inp_file_name = pathlib.Path(base_opts.data_dir).joinpath(
    #     "nrt_global_allsat_phy_l4_%s_%s.nc" % (stime, stime)
    # )
    # out_file_name = pathlib.Path(base_opts.data_dir).joinpath("foo.nc")

    if base_opts.decimate_data and nc_file_name:
        backup_nc_file_name = nc_file_name.with_suffix(".orig")
        shutil.copyfile(nc_file_name, backup_nc_file_name)

        decimate_nrt_netcdf(backup_nc_file_name, nc_file_name)
        os.unlink(backup_nc_file_name)

    if earliest_time:
        remove_older_files(base_opts.data_dir, earliest_time)

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    log_info("Run time %f seconds" % (time.time() - processing_start_time))
    return 0


if __name__ == "__main__":
    os.environ["TZ"] = "UTC"
    time.tzset()

    retval = 1
    try:
        retval = main()
    except SystemExit:
        retval = 0
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
