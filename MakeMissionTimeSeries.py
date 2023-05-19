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

"""Routines for creating mission profile from a Seaglider's dive profiles
"""
import cProfile
import functools
import os
import sys
import time
import pstats

import numpy as np

import BaseGZip
import BaseNetCDF
import BaseOpts
import FileMgr
import Globals
import GPS
import MakeDiveProfiles
import QC
import Sensors
import Utils

from BaseLog import (
    BaseLogger,
    log_info,
    log_warning,
    log_critical,
    log_error,
    log_debug,
)


# NOTE this is the closest to a ARGO trajectory data set, a set of dives (cycles)
# with the data presented as 1-D arrays of each measurement concatentated together
# and a parallel array indicating cycle for each measurement and A/D (used as a mask)
# QC masks parallel each as well so all data, good and bad, could be included
# but, at present, we don't add any qc variables here (see declarations in BaseNetCDF).
# They could be added trivially since we do no interpretation, but see comment under MMP.
# Again, ARGO uses PRESSURE as the primary axis (not time, which is aux for us, or depth, which is derived from pressure)
def make_mission_timeseries(dive_nc_profile_names, base_opts):
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

    mission_timeseries_name = None  # not known yet
    BaseNetCDF.reset_nc_char_dims()

    ctd_vars = (
        "salinity_qc",
        "ctd_time",
        "dissolved_oxygen_sat",
        "latitude",
        "temperature_raw_qc",
        "conductivity",
        "ctd_depth",
        "latitude_gsm",
        "conductivity_qc",
        "salinity_raw",
        "temperature_qc",
        "conductivity_raw",
        "temperature",
        "temperature_raw",
        "conductivity_raw_qc",
        "longitude",
        "longitude_gsm",
        "ctd_pressure",
        "salinity_raw_qc",
        "salinity",
        "pressure",
        "depth",
        "time",
        "speed_gsm",
        "horz_speed_gsm",
        "vert_speed_gsm",
        "speed",
        "horz_speed",
        "vert_speed",
        "sound_velocity",
        "conservative_temperature",
        "absolute_salinity",
        "gsw_sigma0",
        "gsw_sigma3",
        "gsw_sigma4",
    )

    rename_ctd_dim = False
    new_ctd_data_point = "new_ctd_data_point"
    new_ctd_data_info = "new_ctd_data_info"

    ret_val = 0
    if dive_nc_profile_names is None or dive_nc_profile_names == []:
        log_error(
            "No dive profile names provided to make_mission_timeseries - bailing out"
        )
        return (1, mission_timeseries_name)

    add_dive_number_coordinates = False
    master_nc_info_d = {}
    master_globals_d = {}
    master_instruments_d = {}
    platform_var = "Seaglider"
    reviewed = True  # assume the best

    # Here's the algorithm:
    # 1) Sort the list of netcdf files per the dive number
    dive_nc_profile_names.sort(key=functools.cmp_to_key(FileMgr.sort_dive))

    # 2) Walk through each netcdf file, open it up and extract the columns needed,
    #    adding to lists as we go
    # One entry per dive; these go onto mission_nc_dive_d
    # These are derived/computed quantities per dive rather than simply copied
    dive_vars = [
        "dive_number",
        "deepest_sample_time",
        "year",
        "month",
        "date",
        "hour",
        "dd",
        "mean_time",
        "mean_latitude",
        "mean_longitude",
        "start_time",
        "end_time",
        "start_latitude",
        "end_latitude",
        "start_longitude",
        "end_longitude",
    ]
    mission_nc_dive_d = (
        {}
    )  # Data of nc_dim_dive dimension - scalars assembled from different pieces of nc files

    # We use declarations on BaseNetCDF.nc_var_metadata to decide which vectors to include
    mission_nc_var_d = (
        {}
    )  # Data of different vector dimensions - vectors appended directly from contributing nc files

    for var in dive_vars:
        mission_nc_dive_d[var] = []

    unknown_vars = {}
    total_dive_vars = set()
    for dive_nc_profile_name in dive_nc_profile_names:
        log_debug("Processing %s" % dive_nc_profile_name)
        try:  # RuntimeError
            dive_num = 0  # impossible dive number
            (
                status,
                globals_d,
                _,
                eng_f,
                calib_consts,
                results_d,
                _,
                nc_info_d,
                instruments_d,
            ) = MakeDiveProfiles.load_dive_profile_data(
                base_opts, False, dive_nc_profile_name, None, None, None, None
            )
            if status == 0:
                raise RuntimeError("Unable to read %s" % dive_nc_profile_name)
            # Just take the file as-is
            # elif status == 2:
            # raise RuntimeError("%s requires updating" % dive_nc_profile_name)

            try:
                dive_num = globals_d["dive_number"]
            except KeyError as e:
                raise RuntimeError(
                    "No dive_number attribute in %s" % dive_nc_profile_name
                ) from e

            if not mission_timeseries_name:
                # calib_consts is set; figure out filename, etc.
                try:
                    instrument_id = int(calib_consts["id_str"])
                except:
                    instrument_id = int(base_opts.instrument_id)
                if instrument_id == 0:
                    log_warning("Unable to determine instrument id; assuming 0")

                platform_id = "SG%03d" % instrument_id
                platform_var = globals_d["platform"]

                mission_title = Utils.ensure_basename(calib_consts["mission_title"])
                mission_timeseries_name = os.path.join(
                    base_opts.mission_dir,
                    "sg%03d_%s_timeseries.nc" % (instrument_id, mission_title),
                )
                log_info(
                    "Making mission timeseries %s from files found in %s"
                    % (mission_timeseries_name, base_opts.mission_dir)
                )

            # process the file
            # See if this dive was skipped, had an error, or is missing variables we require
            try:
                results_d["processing_error"]
            except KeyError:
                pass
            else:
                log_warning(
                    "%s is marked as having a processing error - not including in timeseries"
                    % dive_nc_profile_name
                )
                continue

            try:
                results_d["skipped_profile"]
            except KeyError:
                pass
            else:
                log_warning(
                    "%s is marked as a skipped_profile - not including in timeseries"
                    % dive_nc_profile_name
                )
                continue

            try:
                reviewed = reviewed and results_d["reviewed"]
            except KeyError:
                reviewed = False

            BaseNetCDF.merge_nc_globals(master_globals_d, globals_d)
            BaseNetCDF.merge_instruments(master_instruments_d, instruments_d)

            # Collect the GPS positions
            try:
                mission_nc_dive_d["start_latitude"].append(
                    results_d["log_gps_lat"][GPS.GPS_I.GPS2]
                )
                mission_nc_dive_d["start_longitude"].append(
                    results_d["log_gps_lon"][GPS.GPS_I.GPS2]
                )
                mission_nc_dive_d["start_time"].append(
                    results_d["log_gps_time"][GPS.GPS_I.GPS2]
                )

                mission_nc_dive_d["end_latitude"].append(
                    results_d["log_gps_lat"][GPS.GPS_I.GPSE]
                )
                mission_nc_dive_d["end_longitude"].append(
                    results_d["log_gps_lon"][GPS.GPS_I.GPSE]
                )
                mission_nc_dive_d["end_time"].append(
                    results_d["log_gps_time"][GPS.GPS_I.GPSE]
                )
            except KeyError as exception:
                raise RuntimeError(
                    "Unable to extract GPS fix data from %s (%s)"
                    % (dive_nc_profile_name, exception.args)
                ) from exception

            # Compute average position
            profile_mean_lat, profile_mean_lon = Utils.average_position(
                results_d["log_gps_lat"][GPS.GPS_I.GPS2],
                results_d["log_gps_lon"][GPS.GPS_I.GPS2],
                results_d["log_gps_lat"][GPS.GPS_I.GPSE],
                results_d["log_gps_lon"][GPS.GPS_I.GPSE],
            )
            mission_nc_dive_d["mean_latitude"].append(profile_mean_lat)
            mission_nc_dive_d["mean_longitude"].append(profile_mean_lon)
            mean_profile_time = (
                (
                    results_d["log_gps_time"][GPS.GPS_I.GPSE]
                    - results_d["log_gps_time"][GPS.GPS_I.GPS2]
                )
                / 2.0
            ) + results_d["log_gps_time"][GPS.GPS_I.GPS2]
            mission_nc_dive_d["mean_time"].append(mean_profile_time)
            mission_nc_dive_d["dive_number"].append(dive_num)

            profile_t = time.gmtime(mean_profile_time)

            mission_nc_dive_d["year"].append(profile_t.tm_year)
            mission_nc_dive_d["month"].append(profile_t.tm_mon)
            mission_nc_dive_d["date"].append(profile_t.tm_mday)
            mission_nc_dive_d["hour"].append(
                profile_t.tm_hour + (profile_t.tm_sec / 60.0)
            )
            mission_nc_dive_d["dd"].append(
                (profile_t.tm_yday - 1)
                + (profile_t.tm_hour / 24.0)
                + (profile_t.tm_min / 1440.0)
                + (profile_t.tm_sec / 86400.0)
            )

            # Find the deepest sample
            max_depth_sample_index = 0
            max_depth = 0.0
            tmp_sgdepth_m_v = results_d["depth"]
            sg_np = len(tmp_sgdepth_m_v)
            for i in range(sg_np):
                if tmp_sgdepth_m_v[i] > max_depth:
                    max_depth = tmp_sgdepth_m_v[i]
                    max_depth_sample_index = i
            tmp_sgdepth_m_v = None
            # log_debug("Deepest sample = %d (%d)" % (max_depth_sample_index, max_depth))

            mission_nc_dive_d["deepest_sample_time"].append(
                results_d[BaseNetCDF.nc_sg_time_var][max_depth_sample_index]
            )

            log_debug("Processing %s" % dive_nc_profile_name)

            # See what is inside
            # add eng_f vector data to results_d so we add those if so marked
            for column in eng_f.columns:
                column_v = eng_f.get_col(column)
                results_d[BaseNetCDF.nc_sg_eng_prefix + column] = column_v

            dive_nc_varnames = list(results_d.keys())
            temp_dive_vars = {}
            extended_dim_names = []  # since infos can share dims, only extend once
            for dive_nc_varname in dive_nc_varnames:
                try:
                    md = BaseNetCDF.nc_var_metadata[dive_nc_varname]
                except KeyError:
                    try:
                        unknown_vars[dive_nc_varname]
                    except KeyError:
                        # issue the warning once...
                        log_warning(
                            "Unknown variable (%s) in %s - skipping"
                            % (dive_nc_varname, dive_nc_profile_name)
                        )
                        unknown_vars[dive_nc_varname] = dive_nc_profile_name
                    continue

                include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
                if include_in_mission_profile:
                    # Variable is tagged for adding to the mission profile
                    if mdp_dim_info:
                        temp_dive_vars[dive_nc_varname] = results_d[dive_nc_varname]
                        # We know from ensure_cf_compliance() that this var is a vector
                        mdp_dim_info = mdp_dim_info[0]  # get first (and only) info
                        dim_name = nc_info_d[mdp_dim_info]
                        # initialize or extend
                        if dim_name not in extended_dim_names:
                            # We are going to initialize or extend below
                            mmt_varname = BaseNetCDF.nc_mdp_mmt_vars[mdp_dim_info]
                            mmt_dive = np.empty(
                                len(temp_dive_vars[dive_nc_varname][:]), np.int32
                            )  # an array for this dive's data point
                            mmt_dive[:] = dive_num
                        try:
                            old_dim_name = master_nc_info_d[mdp_dim_info]
                            if old_dim_name != dim_name:
                                # An instrumment has changed dimensions - normally this represents a situation where there are
                                # netcdf files from two different missions (or something equally bad).  Howerver,
                                # for gliders where the CTD has been moved from scicon to the truck (or back) via the new tailboards,
                                # a new set of vectors must be constructed, with a new dimension that is different
                                # then the others

                                # Note: this logic does not deal with the case where the CTD is from scicon->truck->scicon or the inverse.

                                if dive_nc_varname not in ctd_vars:
                                    raise RuntimeError(
                                        "Differing dim_info %s vs %s for %s in ncfile:%s"
                                        % (
                                            old_dim_name,
                                            dim_name,
                                            dive_nc_varname,
                                            dive_nc_profile_name,
                                        )
                                    )
                                rename_ctd_dim = True
                                log_debug(
                                    "Differing dim_info %s vs %s, varname:%s ncfile:%s"
                                    % (
                                        old_dim_name,
                                        dim_name,
                                        dive_nc_varname,
                                        dive_nc_profile_name,
                                    )
                                )

                            if dim_name not in extended_dim_names:
                                extended_dim_names.append(
                                    dim_name
                                )  # first time for this file
                                master_nc_info_d[dim_name] = (
                                    master_nc_info_d[dim_name] + nc_info_d[dim_name]
                                )  # extend size
                                mission_nc_var_d[mmt_varname] = np.concatenate(
                                    (mission_nc_var_d[mmt_varname], mmt_dive)
                                )  # extend dive numbers
                        except KeyError:
                            # our first time seeing this mdp_dim_info
                            master_nc_info_d[mdp_dim_info] = dim_name
                            # our first time for this file as well
                            extended_dim_names.append(dim_name)
                            master_nc_info_d[dim_name] = nc_info_d[dim_name]  # size
                            mission_nc_var_d[mmt_varname] = mmt_dive
                    else:
                        # accumulate per-dive scalars we want to copy
                        try:
                            values = mission_nc_dive_d[dive_nc_varname]
                        except KeyError:
                            values = []
                            mission_nc_dive_d[dive_nc_varname] = values
                            dive_vars.append(dive_nc_varname)
                        try:
                            value = results_d[dive_nc_varname]
                        except KeyError:
                            log_error(
                                "Unable to extract %s from %s"
                                % (dive_nc_varname, dive_nc_profile_name)
                            )
                            value = (
                                QC.QC_MISSING
                                if nc_data_type == "Q"
                                else BaseNetCDF.nc_nan
                            )
                        values.append(value)

            # now initialize or extend the vector values for these variables
            # BUG: this assumes that if you declare True for include_in_mission_profile in BaseNetCDF.nc_var_metadata
            # that the variable will *always* have values written out, even if nans or whatever
            # See hack below for a fix for one corner case

            for temp_dive_varname in temp_dive_vars:
                try:
                    # append this dive data to the accumulating list
                    mission_nc_var_d[temp_dive_varname] = np.array(
                        np.append(
                            mission_nc_var_d[temp_dive_varname],
                            temp_dive_vars[temp_dive_varname],
                        )
                    )
                except KeyError:
                    # first time
                    mission_nc_var_d[temp_dive_varname] = temp_dive_vars[
                        temp_dive_varname
                    ][:].copy()
                total_dive_vars.add(temp_dive_varname)

            # log_info(
            #    f"{dive_nc_profile_name} : {total_dive_vars - set(temp_dive_vars)}"
            # )

            # This code is designed to catch the specific case that there are missing vectors
            # from a dimension in a dive, but other vectors have been updated (see BUG: above)
            #
            # This code assumes the vector was present in earlier dives and does not handle new vecotrs
            # being added mid-mission - as in moving the CTD from scicon to truck (and potentially back)
            for missing_varname in total_dive_vars - set(temp_dive_vars):
                _, nc_data_type, _, mdp_dim_info = BaseNetCDF.nc_var_metadata[
                    missing_varname
                ]
                # Nothing in this dim was updated from this file
                if mdp_dim_info not in extended_dim_names:
                    continue

                log_info(
                    f"{missing_varname} mission from {dive_nc_profile_name} - adding empty vector"
                )

                missing_var_size = nc_info_d[nc_info_d[mdp_dim_info]]
                missing_var = np.zeros(missing_var_size, dtype=nc_data_type)

                mission_nc_var_d[missing_varname] = np.array(
                    np.append(mission_nc_var_d[missing_varname], missing_var)
                )

        except KeyboardInterrupt:
            log_error("Keyboard interrupt - breaking out")
            return (1, mission_timeseries_name)
        except RuntimeError as exception:
            log_error("%s - skipping" % (exception.args[0]))
            continue

    if not mission_timeseries_name:
        log_error("Unable to determine timeseries file name - bailing out")
        return (1, mission_timeseries_name)

    if len(list(mission_nc_var_d.keys())) == 0:
        # If all the dives were skipped, e.g., faroes/jun09/sg105
        log_error("No data for timeseries - bailing out")
        return (1, None)

    start_t = time.strftime(
        "%Y%m%d", time.gmtime(mission_nc_var_d[BaseNetCDF.nc_sg_time_var][0])
    )
    end_t = time.strftime(
        "%Y%m%d", time.gmtime(mission_nc_var_d[BaseNetCDF.nc_sg_time_var][-1])
    )

    if rename_ctd_dim:
        # A good deal of this is a hack.  In the event that the SBECT migrated from one dimension to
        # another, we need to cons up a new dimension and migrate the relevent variables over there.
        # The dive number, time, depth and pressure variables are dropped in this case to simplify the above code

        # Note - this code assumes that the of the CTD is one-way (scicon to truck). A move back will result
        # in the contributions to this new dimension end up getting dropped from the timeseries file
        dropped_vars = []
        for var in list(mission_nc_var_d.keys()):
            if (
                var.endswith("_dive_number")
                or var == "time"
                or var == "pressure"
                or var == "depth"
            ):
                dropped_vars.append(var)
            if var in ctd_vars:
                if (var not in dropped_vars) and (
                    new_ctd_data_point not in master_nc_info_d
                ):
                    log_info(
                        f"adding nc_info_d {var}, len {len(mission_nc_var_d[var])}"
                    )
                    master_nc_info_d[new_ctd_data_point] = len(mission_nc_var_d[var])
                    master_nc_info_d[new_ctd_data_info] = new_ctd_data_point
                    BaseNetCDF.register_sensor_dim_info(
                        new_ctd_data_info,
                        new_ctd_data_point,
                        None,
                        data=False,
                        instrument_var=None,
                    )
                BaseNetCDF.nc_var_metadata[var][3] = (new_ctd_data_info,)
            # log_info("%s:%s" % (var, BaseNetCDF.nc_var_metadata[var]))
        for vv in dropped_vars:
            mission_nc_var_d.pop(vv)

    # for k,v in master_nc_info_d.iteritems():
    #    log_info("%s:%s" % (k,v))

    # update globals for this file

    # Timeseries_SG005_20041024_20041105
    master_globals_d["id"] = "Timeseries_SG%03d_%s_%s" % (instrument_id, start_t, end_t)
    master_globals_d["file_version"] = Globals.mission_timeseries_nc_fileversion
    master_globals_d["file_data_type"] = "timeseries"
    now_date = BaseNetCDF.nc_ISO8601_date(time.time())
    master_globals_d["history"] = "Written " + now_date
    if reviewed:
        # update the issued date
        master_globals_d["date_issued"] = now_date

    # Now write the results
    try:
        mission_timeseries_file = Utils.open_netcdf_file(mission_timeseries_name, "w")
    except:
        log_error("Unable to open %s for writing" % mission_timeseries_name)
        return (1, mission_timeseries_name)

    #
    # Set up the netCDF global attributes (header)
    #
    BaseNetCDF.write_nc_globals(mission_timeseries_file, master_globals_d, base_opts)
    instrument_vars = []

    # Was unlimited...
    # total number of concatentated data points over all dives
    created_dims = []
    for _, nc_dim_name in list(BaseNetCDF.nc_mdp_data_info.items()):
        if (
            nc_dim_name
        ):  # any registered?  normally only data infos are but see ctd_results_info
            if (
                nc_dim_name in master_nc_info_d and not nc_dim_name in created_dims
            ):  # do we have a size? which implies we have that data (and possibly results)
                log_debug(
                    "Creating dimension %s (%s)"
                    % (nc_dim_name, master_nc_info_d[nc_dim_name])
                )
                mission_timeseries_file.createDimension(
                    nc_dim_name, master_nc_info_d[nc_dim_name]
                )
                created_dims.append(nc_dim_name)  # Do this once

    nc_var_d = {}
    del_attrs = None
    # Allocate variables and assign all the associated variable's data points
    for var in list(mission_nc_var_d.keys()):
        try:
            md = BaseNetCDF.nc_var_metadata[var]
            include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
            dim_names = BaseNetCDF.nc_scalar  # assume scalar (should this ever be?)
            mmt_var_aux = None
            if mdp_dim_info:
                for mdi in mdp_dim_info:
                    dim_name = master_nc_info_d[mdi]
                    dim_names = dim_names + (dim_name,)
                    mmt_var_aux = {}
                    if add_dive_number_coordinates:  # DEAD
                        mmt_varname = BaseNetCDF.nc_mdp_mmt_vars[mdi]
                        if mmt_varname != var:  # avoid self reference
                            try:
                                mmt_var_aux = meta_data_d[BaseNetCDF.nc_coordinates]
                                mmt_var_aux = "%s %s" % (mmt_var_aux, mmt_varname)
                            except KeyError:
                                mmt_var_aux = mmt_varname
                            mmt_var_aux.update(
                                {BaseNetCDF.nc_coordinates: mmt_var_aux}
                            )  # This will override the default
                    if not rename_ctd_dim:
                        try:
                            instrument_var = master_instruments_d[var]
                            instrument_vars.append(instrument_var)
                            mmt_var_aux.update(
                                {"instrument": instrument_var, "platform": platform_var}
                            )
                        except:
                            pass
            else:  # scalar
                pass

            # Pass value, which is assigned by create_nc_var if present and after possible coercion
            value = mission_nc_var_d[var][:]
            nc_var_d[var] = BaseNetCDF.create_nc_var(
                mission_timeseries_file,
                var,
                dim_names,
                False,
                value,
                mmt_var_aux,
                del_attrs,
                f_timeseries=True,
            )

        except KeyError:
            log_error("Unknown result variable %s -- dropped" % var, "exc")

    # Create the per-dive data
    num_dives = len(mission_nc_dive_d[dive_vars[0]])
    mission_timeseries_file.createDimension(BaseNetCDF.nc_dim_dives, num_dives)
    mission_timeseries_file.createDimension(
        BaseNetCDF.nc_dim_trajectory_info, num_dives
    )  # trajectory
    BaseNetCDF.create_nc_var(
        mission_timeseries_file,
        "trajectory",
        (BaseNetCDF.nc_dim_trajectory_info,),
        True,
        mission_nc_dive_d["dive_number"],
        f_timeseries=True,
    )  # alias

    for var in dive_vars:
        BaseNetCDF.create_nc_var(
            mission_timeseries_file,
            var,
            (BaseNetCDF.nc_dim_dives,),
            False,
            mission_nc_dive_d[var],
            None,
            del_attrs,
            f_timeseries=True,
        )

    BaseNetCDF.create_nc_var(
        mission_timeseries_file,
        platform_var,
        BaseNetCDF.nc_scalar,
        False,
        "%s %s" % (platform_var, platform_id),
        {"call_sign": platform_id},
        f_timeseries=True,
    )
    for instrument_var in Utils.unique(instrument_vars):
        BaseNetCDF.create_nc_var(
            mission_timeseries_file,
            instrument_var,
            BaseNetCDF.nc_scalar,
            False,
            instrument_var,
            f_timeseries=True,
        )

    mission_timeseries_file.sync()
    mission_timeseries_file.close()

    mission_timeseries_name_gz = mission_timeseries_name + ".gz"
    if base_opts.gzip_netcdf:
        log_info(
            "Compressing %s to %s"
            % (mission_timeseries_name, mission_timeseries_name_gz)
        )
        if BaseGZip.compress(mission_timeseries_name, mission_timeseries_name_gz):
            log_warning("Failed to compress %s" % mission_timeseries_name)
    else:
        if os.path.exists(mission_timeseries_name_gz):
            try:
                os.remove(mission_timeseries_name_gz)
            except:
                log_error("Couldn't remove %s" % mission_timeseries_name_gz)

    return (ret_val, mission_timeseries_name)


def main():
    """Command line driver for creating mission timeseries from single dive netCDF files

    Returns:
        0 - success
        1 - failure

    Raises:
        None - all exceptions are caught and logged

    """
    base_opts = BaseOpts.BaseOptions(
        "Command line driver for creating mission timeseries from single dive netCDF files"
    )

    BaseLogger(base_opts)  # initializes BaseLog

    # Reset priority
    if base_opts.nice:
        try:
            os.nice(base_opts.nice)
        except:
            log_error("Setting nice to %d failed" % base_opts.nice)

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    # logger_init(init_dict)

    # Initialze the netCDF tables
    BaseNetCDF.init_tables(init_dict)

    # Collect up the possible files
    dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)

    (ret_val, _) = make_mission_timeseries(dive_nc_file_names, base_opts)
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
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
