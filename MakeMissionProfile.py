#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2012, 2016, 2019, 2020, 2021, 2022, 2023 by University of Washington.  All rights reserved.
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

"""Routines for creating mission profile from a Seaglider's dive profiles
"""

import cProfile
import functools
import os
import pdb
import pprint
import pstats
import sys
import time
import traceback

import numpy as np

import BaseGZip
import BaseNetCDF
import BaseOpts
import FileMgr
import Globals
import GPS
import MakeDiveProfiles
import Sensors
import QC
import Utils

from BaseLog import (
    BaseLogger,
    log_info,
    log_error,
    log_warning,
    log_critical,
    log_debug,
)

DEBUG_PDB = False


def bin_data(bin_width, which_half, include_empty_bins, depth_m_v, inp_data_columns):
    """Bins data accorrding to the specified bin_width

    Note: deepest bin is included in the down profile

    Input:
        bin_width - width of bin, in meters
        which_half - see WhichHalf for details
        include_empty_bins - Should the empty bins be included or eliminated?
        depth_m_v - vehicle depth (corrected for latitude), in meters
        inp_data_columns - list of data columns - each the same length as depth_m_v

    Output:
        obs_bin - number of observations for each bin
        depth_m_bin - depth in m, binned
        data_columns_bin - data colums binned

    """

    if not include_empty_bins and which_half == Globals.WhichHalf.combine:
        log_error("Combined profiles and stripping empty bins not currently supported")
        return None

    try:
        num_data_cols = len(inp_data_columns)
        # Filter out NaNs from depth colunn
        if len(np.nonzero(np.isnan(depth_m_v))[0]):
            depth_filter_i = np.logical_not(np.isnan(depth_m_v))
            depth_m_v = depth_m_v[depth_filter_i].copy()
            data_columns = []
            for d in range(num_data_cols):
                data_columns.append(inp_data_columns[d][depth_filter_i])
        else:
            data_columns = inp_data_columns
    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_error("Unexpected error in bin_data", "exc")
        return [None, None, None]

    # First, create an array of indices of the bins and find the largest such index
    # Find the sample index for the maximum depth
    max_depth_sample_index = 0
    max_depth = 0.0
    num_rows = len(depth_m_v)
    for i in range(num_rows):
        if depth_m_v[i] > max_depth:
            max_depth = depth_m_v[i]
            max_depth_sample_index = i

    bin_index = np.zeros(num_rows, np.int32)

    try:
        # Seed the bin_index mapping from index to depth bin
        for i in range(num_rows):
            # bin_index[i] = 1 + int((depth_m_v[i] + bin_width/2.0)/bin_width)
            # Zero base indexing
            bin_index[i] = int(round((depth_m_v[i] + bin_width / 2.0) / bin_width)) - 1
    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_error("Unexpected error in bin_data", "exc")
        return [None, None, None]

    # print len(bin_index)
    # print "bin_index"
    # print bin_index

    log_debug(
        "Init max_depth_sample_index = %d, bin_index[max_depth_sample_index] = %d, max_depth=%f"
        % (max_depth_sample_index, bin_index[max_depth_sample_index], max_depth)
    )  # Index of maximum depth

    # Now that we know the index to bin mapping, make sure that the max_depth_sample_index is the
    # highest index in the bin that contains the deepest observation - implicitly assigning those
    # observations to the down bin
    for i in range(max_depth_sample_index, num_rows):
        if bin_index[i] == bin_index[max_depth_sample_index]:
            max_depth_sample_index = i
        if bin_index[i] < bin_index[max_depth_sample_index]:
            break

    log_debug(
        "Final max_depth_sample_index = %d, bin_index[max_depth_sample_index] = %d"
        % (max_depth_sample_index, bin_index[max_depth_sample_index])
    )  # Index of maximum depth

    log_debug(
        "bin_index[max_depth_sample_index] = %d" % bin_index[max_depth_sample_index]
    )
    # float32 to float64
    if which_half == Globals.WhichHalf.combine:
        obs_bin = np.zeros(bin_index[max_depth_sample_index] + 1, np.float64)
        # log_info("Number combined bins %d" % len(obs_bin))
        # obs_bin = np.zeros(bin_index[max_depth_sample_index], np.float64)
        obs_bin[:] = BaseNetCDF.nc_nan
        data_cols_bin = []
        for _ in data_columns:
            data_cols_bin.append(
                np.zeros(bin_index[max_depth_sample_index] + 1, np.float64)
            )
            # data_cols_bin.append(np.zeros(bin_index[max_depth_sample_index], np.float64))
        depth_bin = np.zeros(bin_index[max_depth_sample_index] + 1, np.float64)
        # depth_bin = np.zeros(bin_index[max_depth_sample_index], np.float64)

        # Bin the profile
        for j in range(bin_index[max_depth_sample_index] + 1):
            # for j in xrange(bin_index[max_depth_sample_index]):
            obs_bin_tuple = np.where(bin_index == j)
            num_obs_bin = len(obs_bin_tuple[0])
            if num_obs_bin:
                depth_bin[j] = float((j + 1) * bin_width)
                for d in range(num_data_cols):
                    # data_cols_bin[d][j] = average(data_columns[d][obs_bin_tuple])
                    # Average the actual readings - anything that is a BaseNetCDF.nc_nan or nc_inf is excluded
                    temp_data_col = data_columns[d][obs_bin_tuple]
                    try:
                        data_cols_bin[d][j] = np.average(
                            temp_data_col[np.where(np.isfinite(temp_data_col))]
                        )
                    except (ZeroDivisionError, FloatingPointError):
                        data_cols_bin[d][j] = BaseNetCDF.nc_nan

        return (obs_bin, depth_bin, data_cols_bin)

    else:
        # Up, Down or both
        if which_half in (Globals.WhichHalf.down, Globals.WhichHalf.both):
            obs_down_bin = np.zeros(bin_index[max_depth_sample_index] + 1, np.float64)
            log_debug("Number down bins %d" % len(obs_down_bin))
            # obs_down_bin = np.zeros(bin_index[max_depth_sample_index], np.float64)
            data_cols_down_bin = []
            for _ in data_columns:
                data_cols_down_bin.append(
                    np.zeros(bin_index[max_depth_sample_index] + 1, np.float64)
                )
                # data_cols_down_bin.append(np.zeros(bin_index[max_depth_sample_index], np.float64))
            depth_down_bin = np.zeros(bin_index[max_depth_sample_index] + 1, np.float64)
            # depth_down_bin = np.zeros(bin_index[max_depth_sample_index], np.float64)

            bin_down_index = np.zeros(num_rows)
            bin_down_index[:] = -1
            bin_down_index[: max_depth_sample_index + 1] = bin_index[
                : max_depth_sample_index + 1
            ]
            # print 'Bin down index'
            # print bin_down_index

            # Bin the down profile
            for j in range(bin_index[max_depth_sample_index] + 1):
                # for j in xrange(bin_index[max_depth_sample_index]):
                obs_bin_tuple = np.where(bin_down_index == j)
                num_obs_bin = len(obs_bin_tuple[0])
                obs_down_bin[j] = num_obs_bin
                depth_down_bin[j] = float((j + 1) * bin_width)
                if num_obs_bin:
                    # print data_columns
                    for d in range(num_data_cols):
                        # data_cols_down_bin[d][j] = np.average(data_columns[d][obs_bin_tuple])
                        # Average the actual readings - anything that is a BaseNetCDF.nc_nan or nc_inf is excluded
                        temp_data_col = data_columns[d][obs_bin_tuple]
                        try:
                            data_cols_down_bin[d][j] = np.average(
                                temp_data_col[np.where(np.isfinite(temp_data_col))]
                            )
                        except (ZeroDivisionError, FloatingPointError):
                            data_cols_down_bin[d][j] = BaseNetCDF.nc_nan

                # msg = "index=%d obs = %d depth=%.2f" % (j, num_obs_bin, depth_up_bin[j])
                # for d in xrange(num_data_cols):
                #    msg = msg + " dc[%d]=%f" % (d, data_cols_up_bin[d][j])
                # log_info(msg)
            # print "obs_down_bin"
            # print obs_down_bin

        if which_half in (Globals.WhichHalf.up, Globals.WhichHalf.both):
            # obs_up_bin = np.zeros(bin_index[max_depth_sample_index] + 1, np.float64)
            obs_up_bin = np.zeros(bin_index[max_depth_sample_index], np.float64)
            log_debug("Number up bins %d" % len(obs_up_bin))
            data_cols_up_bin = []
            for _ in data_columns:
                # data_cols_up_bin.append(np.zeros(bin_index[max_depth_sample_index] + 1, np.float64))
                data_cols_up_bin.append(
                    np.zeros(bin_index[max_depth_sample_index], np.float64)
                )
            # depth_up_bin = np.zeros(bin_index[max_depth_sample_index] + 1, np.float64)
            depth_up_bin = np.zeros(bin_index[max_depth_sample_index], np.float64)

            bin_up_index = np.zeros(num_rows)
            bin_up_index[:] = -1
            bin_up_index[max_depth_sample_index + 1 : num_rows] = bin_index[
                max_depth_sample_index + 1 : num_rows
            ]
            # print 'Bin up index'
            # print bin_up_index

            # Bin the up profile
            # for j in xrange(bin_index[max_depth_sample_index] + 1):
            for j in range(bin_index[max_depth_sample_index]):
                obs_bin_tuple = np.where(bin_up_index == j)
                num_obs_bin = len(obs_bin_tuple[0])
                obs_up_bin[j] = num_obs_bin
                depth_up_bin[j] = float((j + 1) * bin_width)
                if num_obs_bin:
                    for d in range(num_data_cols):
                        # data_cols_up_bin[d][j] = np.average(data_columns[d][obs_bin_tuple])
                        # Average the actual readings - anything that is a BaseNetCDF.nc_nan or nc_inf is excluded
                        temp_data_col = data_columns[d][obs_bin_tuple]
                        try:
                            data_cols_up_bin[d][j] = np.average(
                                temp_data_col[np.where(np.isfinite(temp_data_col))]
                            )
                        except (ZeroDivisionError, FloatingPointError):
                            data_cols_up_bin[d][j] = BaseNetCDF.nc_nan

                # msg = "index=%d obs = %d depth=%.2f" % (j, num_obs_bin, depth_up_bin[j])
                # for d in xrange(num_data_cols):
                #    msg = msg + " dc[%d]=%f" % (d, data_cols_up_bin[d][j])
                # log_info(msg)

        # Tranverse the vectors and remove the zero filled bins along the half profile desired
        # NOTE: this needs to be re-done to deal with shift to a zero based index scheme
        # and tested with .bpo file generation
        total_bins = 0
        if which_half in (Globals.WhichHalf.down, Globals.WhichHalf.both):
            if include_empty_bins:
                total_bins += len(depth_down_bin)
            else:
                for i in range(len(depth_down_bin)):
                    if obs_down_bin[i] > 0:
                        total_bins += 1

        if which_half in (Globals.WhichHalf.up, Globals.WhichHalf.both):
            if include_empty_bins:
                total_bins += len(depth_up_bin)
            else:
                for i in range(len(depth_up_bin)):
                    if obs_up_bin[i] > 0:
                        total_bins += 1

        log_debug("Total bins = %d" % total_bins)

        obs_bin = np.zeros(total_bins, np.float64)
        obs_bin[:] = BaseNetCDF.nc_nan
        depth_bin = np.zeros(total_bins, np.float64)
        depth_bin[:] = BaseNetCDF.nc_nan
        data_cols_bin = []
        for d in range(num_data_cols):
            temp = np.zeros(total_bins, np.float64)
            temp[:] = BaseNetCDF.nc_nan
            data_cols_bin.append(temp)

        current_bin = 0
        if which_half in (Globals.WhichHalf.down, Globals.WhichHalf.both):
            for i in range(len(depth_down_bin)):
                if obs_down_bin[i] > 0:
                    obs_bin[current_bin] = obs_down_bin[i]
                    for d in range(num_data_cols):
                        data_cols_bin[d][current_bin] = data_cols_down_bin[d][i]
                if obs_down_bin[i] > 0 or include_empty_bins:
                    depth_bin[current_bin] = depth_down_bin[i]
                    current_bin += 1

        if which_half in (Globals.WhichHalf.up, Globals.WhichHalf.both):
            for i in range(-1, -len(depth_up_bin) - 1, -1):
                if obs_up_bin[i] > 0:
                    obs_bin[current_bin] = obs_up_bin[i]
                    for d in range(num_data_cols):
                        data_cols_bin[d][current_bin] = data_cols_up_bin[d][i]
                if obs_up_bin[i] > 0 or include_empty_bins:
                    depth_bin[current_bin] = depth_up_bin[i]
                    current_bin += 1

        return [obs_bin, depth_bin, data_cols_bin]


# NOTE this is the closest to a ARGO profile data set, a set of dives (cycles)
# with the data presented as 2-D arrays of [dive_num,max_depth]
# ARGO would require 'both dive and climb' annotating 'D' (dive) and 'A' (ascent)
# ARGO would NOT bin but provide all the raw data.
# ARGO uses PRESSURE as the primary axis (not time, which is aux for us, or depth, which is derived from pressure)

# Note that we don't add any qc variables here (see declarations in BaseNetCDF).  This is mostly
# because we don't have a clear story in how to bin QC values in a bin.  One thought is to drop
# all bad points and mean the remaining good points, NaN if no points available.  (In which case
# we don't actually need to include any QC variable for the results since all are QC_GOOD).  But
# different vectors will have different QC flags and hence a different number of obs_bin, so a
# common obs_bin is probably right out.  In any case, we need to know which QC variable goes with
# which data vector, which we need to declare in BaseNetCDF (and perhaps even in the nc file
# as an 'auxillary_variable').


def make_mission_profile(dive_nc_profile_names, base_opts):
    """Creates a mission profile from a list of dive profiles

    Input:
        dive_nc_profile_names - A list of fully qualified dive profile filenames.
        base_opts - command-line options structure

    Returns:
        tuple(ret_val, mission_profile_name)
        ret_val
            0 - success
            1 - failure
        mission_profile_name - the name possibly changed from the input parameter

    Raises:
    """

    mission_profile_name = None  # not known yet
    BaseNetCDF.reset_nc_char_dims()

    bin_width = base_opts.bin_width
    if bin_width <= 0.0:
        log_error("bin_width must be greater the 0.0 (%f) - bailing out" % bin_width)
        return (1, mission_profile_name)

    which_half = base_opts.which_half

    if which_half == Globals.WhichHalf.down:
        wh_file = "down"
        wh_str = "Down profile only"
    elif which_half == Globals.WhichHalf.up:
        wh_file = "up"
        wh_str = "Up profile only"
    elif which_half == Globals.WhichHalf.both:
        wh_file = "up_and_down"
        wh_str = "Up and Down profile"
    elif which_half == Globals.WhichHalf.combine:
        wh_file = "combine"
        wh_str = "Up and Down profile combined"
    else:
        log_error(
            "Unknown WhichHalf %d - assuming %d" % which_half, Globals.WhichHalf.both
        )
        wh_file = "up_and_down"
        wh_str = "Up and Down profile"

    if dive_nc_profile_names is None or dive_nc_profile_names == []:
        log_error("No dive profile names provided to make_mission_profile")
        return (1, mission_profile_name)

    master_globals_d = {}
    master_instruments_d = {}
    platform_var = "Seaglider"
    reviewed = True  # assume the best

    # Sort the list of netcdf files per the dive number
    dive_nc_profile_names.sort(key=functools.cmp_to_key(FileMgr.sort_dive))

    # Walk through each netcdf file, open it up and extract the columns needed,
    # adding to lists as we go
    mission_nc_dive_d = (
        {}
    )  # Data of 'divenum' dimension - assembled from other pieces of nc files and calculated from bin
    included_binned_vars = (
        set()
    )  # all the binned vector variables we'll include the final nc file
    included_scalar_vars = set()
    unknown_vars = {}
    first_profile_name = None
    for dive_nc_profile_name in dive_nc_profile_names:
        log_debug("Processing %s" % dive_nc_profile_name)
        if first_profile_name is None:
            first_profile_name = dive_nc_profile_name
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

            if not mission_profile_name:
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
                mission_profile_name = os.path.join(
                    base_opts.mission_dir,
                    "sg%03d_%s_%1.1fm_%s_profile.nc"
                    % (instrument_id, mission_title, bin_width, wh_file),
                )
                log_info(
                    "Making mission profile %s from files found in %s"
                    % (mission_profile_name, base_opts.mission_dir)
                )

            # process the file
            # See if this dive was skipped, had an error, or is missing variables we require
            try:
                results_d["processing_error"]
            except KeyError:
                pass
            else:
                log_warning(
                    "%s is marked as having a processing error - not including in binned profile"
                    % dive_nc_profile_name
                )
                continue

            try:
                results_d["skipped_profile"]
            except KeyError:
                pass
            else:
                log_warning(
                    "%s is marked as a skipped_profile - not including in binned profile"
                    % dive_nc_profile_name
                )
                continue

            try:
                reviewed = reviewed and results_d["reviewed"]
            except KeyError:
                reviewed = False

            BaseNetCDF.merge_nc_globals(master_globals_d, globals_d)
            BaseNetCDF.merge_instruments(master_instruments_d, instruments_d)

            mission_nc_dive_d[dive_num] = {}
            # Collect the GPS positions
            # BUG no checking if GPS is ok here
            try:
                mission_nc_dive_d[dive_num]["GPS2_lat"] = results_d["log_gps_lat"][
                    GPS.GPS_I.GPS2
                ]
                mission_nc_dive_d[dive_num]["GPS2_lon"] = results_d["log_gps_lon"][
                    GPS.GPS_I.GPS2
                ]
                mission_nc_dive_d[dive_num]["GPS2_time"] = results_d["log_gps_time"][
                    GPS.GPS_I.GPS2
                ]

                mission_nc_dive_d[dive_num]["GPSEND_lat"] = results_d["log_gps_lat"][
                    GPS.GPS_I.GPSE
                ]
                mission_nc_dive_d[dive_num]["GPSEND_lon"] = results_d["log_gps_lon"][
                    GPS.GPS_I.GPSE
                ]
                mission_nc_dive_d[dive_num]["GPSEND_time"] = results_d["log_gps_time"][
                    GPS.GPS_I.GPSE
                ]
            except IndexError as e:
                raise RuntimeError(
                    "Unable to extract GPS fix data from %s" % dive_nc_profile_name
                ) from e

            # Compute average position
            profile_mean_lat, profile_mean_lon = Utils.average_position(
                results_d["log_gps_lat"][GPS.GPS_I.GPS2],
                results_d["log_gps_lon"][GPS.GPS_I.GPS2],
                results_d["log_gps_lat"][GPS.GPS_I.GPSE],
                results_d["log_gps_lon"][GPS.GPS_I.GPSE],
            )
            mission_nc_dive_d[dive_num]["profile_mean_lat"] = profile_mean_lat
            mission_nc_dive_d[dive_num]["profile_mean_lon"] = profile_mean_lon
            profile_mean_time = (
                (
                    results_d["log_gps_time"][GPS.GPS_I.GPSE]
                    - results_d["log_gps_time"][GPS.GPS_I.GPS2]
                )
                / 2.0
            ) + results_d["log_gps_time"][GPS.GPS_I.GPS2]
            mission_nc_dive_d[dive_num]["profile_mean_time"] = profile_mean_time

            # Compute dive average position
            dive_profile_mean_lat, dive_profile_mean_lon = Utils.average_position(
                results_d["log_gps_lat"][GPS.GPS_I.GPS2],
                results_d["log_gps_lon"][GPS.GPS_I.GPS2],
                profile_mean_lat,
                profile_mean_lon,
            )
            mission_nc_dive_d[dive_num]["dive_profile_mean_lat"] = dive_profile_mean_lat
            mission_nc_dive_d[dive_num]["dive_profile_mean_lon"] = dive_profile_mean_lon
            dive_profile_mean_time = (
                (profile_mean_time - results_d["log_gps_time"][GPS.GPS_I.GPS2]) / 2.0
            ) + results_d["log_gps_time"][GPS.GPS_I.GPS2]
            mission_nc_dive_d[dive_num][
                "dive_profile_mean_time"
            ] = dive_profile_mean_time

            # Compute climb average position
            climb_profile_mean_lat, climb_profile_mean_lon = Utils.average_position(
                profile_mean_lat,
                profile_mean_lon,
                results_d["log_gps_lat"][GPS.GPS_I.GPSE],
                results_d["log_gps_lon"][GPS.GPS_I.GPSE],
            )
            mission_nc_dive_d[dive_num][
                "climb_profile_mean_lat"
            ] = climb_profile_mean_lat
            mission_nc_dive_d[dive_num][
                "climb_profile_mean_lon"
            ] = climb_profile_mean_lon
            climb_profile_mean_time = (
                (results_d["log_gps_time"][GPS.GPS_I.GPSE] - profile_mean_time) / 2.0
            ) + profile_mean_time
            mission_nc_dive_d[dive_num][
                "climb_profile_mean_time"
            ] = climb_profile_mean_time

            log_debug(
                "dive = %d, dive_mean_time = %d, profile_mean_time = %d, climb_mean_time = %d"
                % (
                    dive_num,
                    dive_profile_mean_time,
                    profile_mean_time,
                    climb_profile_mean_time,
                )
            )

            log_debug(
                "dive = %d, log_gps_time1 = %d, log_gps_time2 = %d"
                % (
                    dive_num,
                    results_d["log_gps_time"][GPS.GPS_I.GPS2],
                    results_d["log_gps_time"][GPS.GPS_I.GPSE],
                )
            )

            # See what is inside
            # add eng_f vector data to results_d so we add those if so marked
            for column in eng_f.columns:
                column_v = eng_f.get_col(column)
                results_d[BaseNetCDF.nc_sg_eng_prefix + column] = column_v

            dive_nc_varnames = list(results_d.keys())
            temp_dive_vars = {}
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
                    #
                    if mdp_dim_info == BaseNetCDF.nc_scalar:
                        try:
                            value = results_d[dive_nc_varname]
                        except KeyError:
                            value = (
                                QC.QC_MISSING
                                if nc_data_type == "Q"
                                else BaseNetCDF.nc_nan
                            )
                        mission_nc_dive_d[dive_num][
                            dive_nc_varname
                        ] = value  # record scalar value
                        included_scalar_vars.add(dive_nc_varname)
                    else:
                        if nc_data_type == "Q":
                            # we don't bin qc vectors but we might want to use them to filter the others
                            # this is where we'd have to put them aside
                            pass
                        else:
                            # log_info("Including %s (%d)" % (dive_nc_varname, len(results_d[dive_nc_varname])))
                            temp_dive_vars[dive_nc_varname] = results_d[dive_nc_varname]

                            # Look up the matching _QC vector and if applicable, apply the only_good
                            dive_nc_varname_qc = dive_nc_varname + "_qc"

                            if dive_nc_varname_qc in results_d:
                                # find_qc(results_d[dive_nc_varname_qc], QC.only_good_qc_values, mask=True)
                                # temperature_qc = QC.decode_qc(dive_nc_file.variables['temperature_qc'])
                                temp_dive_vars[dive_nc_varname][
                                    np.logical_not(
                                        QC.find_qc(
                                            results_d[dive_nc_varname_qc],
                                            QC.only_good_qc_values,
                                            mask=True,
                                        )
                                    )
                                ] = BaseNetCDF.nc_nan

            # Bin the data
            temp_dive_vars["bin_time"] = temp_dive_vars[BaseNetCDF.nc_sg_time_var]
            temp_dive_var_names = list(temp_dive_vars.keys())

            # Why, you might ask, do we tag these as include_in_mission_profile when we remove them?
            # Because we do include them in make_mission_timeseries()....so perhaps we ought to extend the metadata table?
            temp_dive_var_names.remove("depth")
            temp_dive_var_names.remove(BaseNetCDF.nc_sg_time_var)
            temp_dive_var_names.remove("longitude")
            temp_dive_var_names.remove("latitude")
            temp_dive_var_names.sort()

            data_columns = []
            time_var_indicies_d = {}
            dupd_var_indicies_d = {}
            for t in temp_dive_var_names:
                # This variable will definitely be added (since it is after the removes)
                included_binned_vars.add(t)
                md = BaseNetCDF.nc_var_metadata[t]  # ensured available
                include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
                # convert all data to sg_data_point size if not
                # We know from ensure_cf_compliance() that this var is a vector
                mdp_dim_info = mdp_dim_info[0]  # get first (and only) info
                try:
                    time_var = BaseNetCDF.nc_mdp_time_vars[nc_info_d[mdp_dim_info]]
                except KeyError as e:
                    raise RuntimeError(
                        "Undeclared time var for %s (%s)" % (t, mdp_dim_info)
                    ) from e
                if time_var == BaseNetCDF.nc_sg_time_var:
                    sg_values = temp_dive_vars[t]
                    duplicates_i_v = []
                else:
                    try:
                        indices_i_v = time_var_indicies_d[time_var]
                        duplicates_i_v = dupd_var_indicies_d[time_var]
                    except KeyError:
                        # use nearest_indices() and cache the indices for time_var
                        # init_tables() ensures that all time_vars are included
                        indices_i_v, duplicates_i_v = Utils.nearest_indices(
                            temp_dive_vars[BaseNetCDF.nc_sg_time_var],
                            temp_dive_vars[time_var],
                        )
                        time_var_indicies_d[time_var] = indices_i_v
                        # if there are duplicates it is likely there was no data collected there
                        # (i.e., scicon partial data collection or different time bases)
                        # in any case we should only include a single data point at most
                        # record these locations and clear below
                        dupd_var_indicies_d[time_var] = duplicates_i_v
                    sg_values = temp_dive_vars[t][indices_i_v]
                    sg_values[
                        duplicates_i_v
                    ] = BaseNetCDF.nc_nan  # assume we are missing data here
                data_columns.append(sg_values)

            # 'profiles' contain either a 'down' (0) and an 'up' (1) profile dictionary or a single 'both' dictionary
            # each of these dictionaries contain a 'data_cols' dictionary containing each of the binned variables
            # for the down/up or both segments of the data from each nc file
            # there are no nc_vars created...
            if which_half == Globals.WhichHalf.both:
                mission_nc_dive_d[dive_num]["profiles"] = [{}, {}]
            else:
                mission_nc_dive_d[dive_num]["profiles"] = [{}]

            for i in range(len(mission_nc_dive_d[dive_num]["profiles"])):
                if which_half == Globals.WhichHalf.both:
                    if i == 0:
                        wh = Globals.WhichHalf.down
                    else:
                        wh = Globals.WhichHalf.up
                else:
                    wh = which_half
                temp_obs_bin, temp_depth_bin, data_cols_bin = bin_data(
                    bin_width, wh, True, temp_dive_vars["depth"], data_columns
                )
                log_debug(
                    "len(temp_obs_bin) = %d, len(temp_data_bin) = %d"
                    % (len(temp_obs_bin), len(temp_depth_bin))
                )

                # It is possible for there to be an empty profile - so
                # only report if there is data
                if len(temp_depth_bin) <= 0:
                    log_info(
                        "Empty profile found: %s wh:%d" % (dive_nc_profile_name, wh)
                    )

                if wh == Globals.WhichHalf.up:
                    # Reverse the vectors
                    temp_obs_bin = temp_obs_bin[::-1]
                    temp_depth_bin = temp_depth_bin[::-1]
                    for d in range(len(data_cols_bin)):
                        data_cols_bin[d] = data_cols_bin[d][::-1]

                mission_nc_dive_d[dive_num]["profiles"][i]["data_cols"] = {}
                mission_nc_dive_d[dive_num]["profiles"][i]["data_cols"][
                    "obs_bin"
                ] = np.array(temp_obs_bin, np.float64)
                mission_nc_dive_d[dive_num]["profiles"][i]["data_cols"][
                    "depth"
                ] = np.array(temp_depth_bin, np.float64)

                for j in range(len(temp_dive_var_names)):
                    if len(temp_depth_bin) > 0:
                        log_debug(
                            "Processing %s, type %s"
                            % (temp_dive_var_names[j], type(data_cols_bin[j][0]))
                        )

                    md = BaseNetCDF.nc_var_metadata[temp_dive_var_names[j]]
                    (
                        include_in_mission_profile,
                        nc_data_type,
                        meta_data_d,
                        mdp_dim_info,
                    ) = md
                    if nc_data_type == "d":
                        mission_nc_dive_d[dive_num]["profiles"][i]["data_cols"][
                            temp_dive_var_names[j]
                        ] = np.array(data_cols_bin[j], np.float64)
                    elif nc_data_type == "i":
                        mission_nc_dive_d[dive_num]["profiles"][i]["data_cols"][
                            temp_dive_var_names[j]
                        ] = np.array(data_cols_bin[j], np.int32)
                    else:
                        log_error(
                            "Unknown NC type %s for %s - trying float"
                            % (nc_data_type, temp_dive_var_names[j])
                        )
                        mission_nc_dive_d[dive_num]["profiles"][i]["data_cols"][
                            temp_dive_var_names[j]
                        ] = np.array(data_cols_bin[j], np.float64)

        except KeyboardInterrupt:
            log_error("Keyboard interrupt - breaking out")
            return (1, mission_profile_name)

        except RuntimeError as exception:
            log_error(exception.args[0])
            if dive_num and dive_num in mission_nc_dive_d:
                del mission_nc_dive_d[dive_num]

    if not mission_profile_name:
        log_error("Unable to determine profiles file name - bailing out")
        return (1, mission_profile_name)

    if not mission_nc_dive_d:
        log_error("No per dive netCDF files found - bailing out")
        return (1, mission_profile_name)

    # update globals for this file
    # Profile_SG005_20041024_20041105_up_and_down_5
    # We show size to the nearest meter (avoiding . in filename)
    master_globals_d["id"] = "Profile_SG%03d_%s_%s_%s_%dm" % (
        instrument_id,
        time.strftime("%Y%m%d", time.gmtime(temp_dive_vars["bin_time"][0])),
        time.strftime("%Y%m%d", time.gmtime(temp_dive_vars["bin_time"][-1])),
        wh_file,
        int(bin_width),
    )
    master_globals_d["file_version"] = Globals.mission_profile_nc_fileversion
    master_globals_d["binwidth"] = bin_width
    master_globals_d["file_data_type"] = wh_str
    now_date = BaseNetCDF.nc_ISO8601_date(time.time())
    master_globals_d["history"] = "Written " + now_date
    if reviewed:
        # update the issued date
        master_globals_d["date_issued"] = now_date

    try:
        mission_profile_file = Utils.open_netcdf_file(mission_profile_name, "w")
    except:
        log_error("Unable to open %s for writing" % mission_profile_name)
        return (1, mission_profile_name)

    #
    # Set up the netCDF global attributes (header)
    #
    BaseNetCDF.write_nc_globals(mission_profile_file, master_globals_d, base_opts)
    # Where to store all the variables
    mission_nc_var_d = {}

    # Was unlimited...
    # NOTE: the number of data points is the number of dives * number of profiles (1 or 2)
    num_profiles = len(list(mission_nc_dive_d.keys())) * (
        2 if Globals.WhichHalf.both else 1
    )
    mission_profile_file.createDimension(BaseNetCDF.nc_dim_profile, num_profiles)
    mission_profile_file.createDimension(
        BaseNetCDF.nc_dim_trajectory_info, num_profiles
    )  # trajectory

    # Find the maximum size of the depth dimensnion
    max_depth_len = 0
    max_depth_index = -1
    max_depth_dive_num = -1
    for dive_num in list(mission_nc_dive_d.keys()):
        for i in range(len(mission_nc_dive_d[dive_num]["profiles"])):
            depth_len = len(
                mission_nc_dive_d[dive_num]["profiles"][i]["data_cols"]["depth"]
            )
            if depth_len > max_depth_len:
                max_depth_index = i
                max_depth_len = depth_len
                max_depth_dive_num = dive_num
    log_info(
        "max_depth_len = %d, max_depth_dive_num = %d"
        % (max_depth_len, max_depth_dive_num)
    )

    # Now that the deepest profile is known
    mission_profile_file.createDimension(BaseNetCDF.nc_dim_depth, max_depth_len)

    aux_attrs = None
    # if False:  # DEAD
    #     # override the nc_coordinates declaration (NO!)
    #     aux_attrs = {nc_coordinates: "dive_number"}  # DEAD
    # YUCK! We reuse this variable name, which normally is part of ctd_results_info
    mission_nc_var_d["depth"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "depth",
        (BaseNetCDF.nc_dim_depth,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["depth"][:] = mission_nc_dive_d[max_depth_dive_num]["profiles"][
        max_depth_index
    ]["data_cols"]["depth"]

    # Create the netCDF variables and check that no new data column variables were introduced
    dive_nums = sorted(list(mission_nc_dive_d.keys()))

    # Create the profile vars
    # if False:
    #     mission_nc_var_d["dive_number"] = BaseNetCDF.create_nc_var(
    #         mission_profile_file,
    #         "dive_number",
    #         (BaseNetCDF.nc_dim_profile,),
    #         True,
    #         None,
    #         {nc_coordinates: "depth"},
    #     )  # DEAD
    # else:
    mission_nc_var_d["dive_number"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "dive_number",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        None,
        f_timeseries=True,
    )
    mission_nc_var_d["trajectory"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "trajectory",
        (BaseNetCDF.nc_dim_trajectory_info,),
        True,
        None,
        None,
        f_timeseries=True,
    )
    mission_nc_var_d["year"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "year",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["month"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "month",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["date"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "date",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d[BaseNetCDF.nc_sg_time_var] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        BaseNetCDF.nc_sg_time_var,
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["hour"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "hour",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["dd"] = BaseNetCDF.create_nc_var(
        mission_profile_file, "dd", (BaseNetCDF.nc_dim_profile,), True, None, aux_attrs
    )
    mission_nc_var_d["longitude"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "longitude",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["latitude"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "latitude",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["start_time"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "start_time",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["end_time"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "end_time",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["start_latitude"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "start_latitude",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["end_latitude"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "end_latitude",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["start_longitude"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "start_longitude",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )
    mission_nc_var_d["end_longitude"] = BaseNetCDF.create_nc_var(
        mission_profile_file,
        "end_longitude",
        (BaseNetCDF.nc_dim_profile,),
        True,
        None,
        aux_attrs,
        f_timeseries=True,
    )

    # Create all the nc vars, possibly adding instrument info and coordinates?
    instrument_vars = []
    for dive_varname in included_binned_vars:
        md = BaseNetCDF.nc_var_metadata[dive_varname]
        include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
        mission_nc_var_d[dive_varname] = BaseNetCDF.create_nc_var(
            mission_profile_file,
            dive_varname,
            (BaseNetCDF.nc_dim_profile, BaseNetCDF.nc_dim_depth),
            True,
            None,
            f_timeseries=True,
        )
    # Always add the platform variable
    BaseNetCDF.create_nc_var(
        mission_profile_file,
        platform_var,
        BaseNetCDF.nc_scalar,
        False,
        "%s %s" % (platform_var, platform_id),
        {"call_sign": platform_id},
        f_timeseries=True,
    )
    # If we don't add to instrument_vars above this is DEAD
    for instrument_var in Utils.unique(instrument_vars):
        BaseNetCDF.create_nc_var(
            mission_profile_file,
            instrument_var,
            BaseNetCDF.nc_scalar,
            False,
            instrument_var,
            f_timeseries=True,
        )

    # handle scalar variables in two steps: first create arrays to hold the concatenated values, then creatte the nc variable with possible coercion applied to values
    for scalar_var in included_scalar_vars:
        md = BaseNetCDF.nc_var_metadata[scalar_var]
        include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
        scalar_type = "i" if nc_data_type == "Q" else nc_data_type
        mission_nc_var_d[scalar_var] = np.zeros(
            num_profiles, dtype=(np.float64 if scalar_type == "d" else np.int32)
        )

    # Now map over accumulated, binned data and rearrange it from our dive_num, data_col
    # centric dicts into the profile-based nc file format according to the
    # different types of profiles desired
    nc_profile = 0
    for dive_num in dive_nums:
        for i in range(len(mission_nc_dive_d[dive_num]["profiles"])):
            mission_nc_var_d["dive_number"][nc_profile] = dive_num
            mission_nc_var_d["trajectory"][nc_profile] = dive_num  # an alias

            # Add to the data_point based vectors
            if which_half == Globals.WhichHalf.down or (
                which_half == Globals.WhichHalf.both and i == 0
            ):
                mission_nc_var_d["longitude"][nc_profile] = mission_nc_dive_d[dive_num][
                    "dive_profile_mean_lon"
                ]
                mission_nc_var_d["latitude"][nc_profile] = mission_nc_dive_d[dive_num][
                    "dive_profile_mean_lat"
                ]
                profile_time = mission_nc_dive_d[dive_num]["dive_profile_mean_time"]

                mission_nc_var_d["start_time"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPS2_time"]
                mission_nc_var_d["start_latitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPS2_lat"]
                mission_nc_var_d["start_longitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPS2_lon"]

                mission_nc_var_d["end_time"][nc_profile] = mission_nc_dive_d[dive_num][
                    "profile_mean_time"
                ]
                mission_nc_var_d["end_latitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["profile_mean_lat"]
                mission_nc_var_d["end_longitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["profile_mean_lon"]

            elif which_half == Globals.WhichHalf.up or (
                which_half == Globals.WhichHalf.both and i == 1
            ):
                mission_nc_var_d["longitude"][nc_profile] = mission_nc_dive_d[dive_num][
                    "climb_profile_mean_lon"
                ]
                mission_nc_var_d["latitude"][nc_profile] = mission_nc_dive_d[dive_num][
                    "climb_profile_mean_lat"
                ]
                profile_time = mission_nc_dive_d[dive_num]["climb_profile_mean_time"]

                mission_nc_var_d["start_time"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["profile_mean_time"]
                mission_nc_var_d["start_latitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["profile_mean_lat"]
                mission_nc_var_d["start_longitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["profile_mean_lon"]

                mission_nc_var_d["end_time"][nc_profile] = mission_nc_dive_d[dive_num][
                    "GPSEND_time"
                ]
                mission_nc_var_d["end_latitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPSEND_lat"]
                mission_nc_var_d["end_longitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPSEND_lon"]

            elif which_half == Globals.WhichHalf.combine:
                mission_nc_var_d["longitude"][nc_profile] = mission_nc_dive_d[dive_num][
                    "profile_mean_lon"
                ]
                mission_nc_var_d["latitude"][nc_profile] = mission_nc_dive_d[dive_num][
                    "profile_mean_lat"
                ]
                profile_time = mission_nc_dive_d[dive_num]["profile_mean_time"]

                mission_nc_var_d["start_time"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPS2_time"]
                mission_nc_var_d["start_latitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPS2_lat"]
                mission_nc_var_d["start_longitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPS2_lon"]

                mission_nc_var_d["end_time"][nc_profile] = mission_nc_dive_d[dive_num][
                    "GPSEND_time"
                ]
                mission_nc_var_d["end_latitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPSEND_lat"]
                mission_nc_var_d["end_longitude"][nc_profile] = mission_nc_dive_d[
                    dive_num
                ]["GPSEND_lon"]

            # Concatenate the scalars, which apply to all halves
            for scalar_var in included_scalar_vars:
                mission_nc_var_d[scalar_var][nc_profile] = mission_nc_dive_d[dive_num][
                    scalar_var
                ]

            mission_nc_var_d[BaseNetCDF.nc_sg_time_var][nc_profile] = profile_time
            profile_t = time.gmtime(profile_time)

            mission_nc_var_d["year"][nc_profile] = profile_t.tm_year
            mission_nc_var_d["month"][nc_profile] = profile_t.tm_mon
            mission_nc_var_d["date"][nc_profile] = profile_t.tm_mday
            mission_nc_var_d["hour"][nc_profile] = profile_t.tm_hour + (
                profile_t.tm_sec / 60.0
            )
            mission_nc_var_d["dd"][nc_profile] = (
                (profile_t.tm_yday - 1)
                + (profile_t.tm_hour / 24.0)
                + (profile_t.tm_min / 1440.0)
                + (profile_t.tm_sec / 86400.0)
            )

            log_debug(
                "nc_profile = %d, profile_time = %f, profile_t = %s"
                % (nc_profile, profile_time, pprint.pformat(profile_t))
            )

            for dive_varname in included_binned_vars:
                try:
                    data_len = len(
                        mission_nc_dive_d[dive_num]["profiles"][i]["data_cols"][
                            dive_varname
                        ]
                    )
                    log_debug(
                        "Processing dive:%s col:%s len:%d"
                        % (dive_num, dive_varname, data_len)
                    )
                except KeyError:
                    # var not present in this nc_profile
                    data_len = 0

                md = BaseNetCDF.nc_var_metadata[dive_varname]
                include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md

                # Now, assign the data column to the netCDF variable, by
                # ensuring the data columns are all of the same length
                # Fill the vectors with the missing values first
                if nc_data_type == "d":
                    temp_v = np.zeros(max_depth_len, np.float64)
                elif nc_data_type == "i":
                    temp_v = np.zeros(max_depth_len, np.int32)
                else:
                    log_error(
                        "Unknown NC type %s for %s - trying float"
                        % (nc_data_type, dive_varname)
                    )
                    temp_v = np.zeros(max_depth_len, np.float64)
                try:
                    fill_value = meta_data_d["_FillValue"]
                except KeyError:
                    fill_value = BaseNetCDF.nc_nan  # default
                temp_v[:] = fill_value  # fill entire array with fill value first
                # Now fill with just the data we have for this dive_num, if anyz
                if data_len:
                    temp_v[:data_len] = mission_nc_dive_d[dive_num]["profiles"][i][
                        "data_cols"
                    ][dive_varname]
                mission_nc_var_d[dive_varname][nc_profile, :] = temp_v

            nc_profile = nc_profile + 1

    # create scalar nc variables
    for scalar_var in included_scalar_vars:
        values = mission_nc_var_d[scalar_var]
        mission_nc_var_d[scalar_var] = BaseNetCDF.create_nc_var(
            mission_profile_file,
            scalar_var,
            (BaseNetCDF.nc_dim_profile,),
            True,
            values,
            aux_attrs,
        )

    mission_profile_file.sync()
    mission_profile_file.close()

    mission_profile_name_gz = mission_profile_name + ".gz"
    if base_opts.gzip_netcdf:
        log_info(
            "Compressing %s to %s" % (mission_profile_name, mission_profile_name_gz)
        )
        if BaseGZip.compress(mission_profile_name, mission_profile_name_gz):
            log_warning("Failed to compress %s" % mission_profile_name)
    else:
        if os.path.exists(mission_profile_name_gz):
            try:
                os.remove(mission_profile_name_gz)
            except:
                log_error("Couldn't remove %s" % mission_profile_name_gz)

    return (0, mission_profile_name)


def main():
    """Command line driver for creating mission profiles from single dive netCDF files

    All netCDF files of the form pXXXYYYY.nc (where XXX is the glider ID and
    YYYY is the dive number) from the mission directory are processed to create
    the mission profile.  The name of the profile may be optionally specified on
    the command line as a fully qualified path.  If no output file is specified,
    the output file is created in the mission directory with a standard name of
    the form:

        sgXXX_(mission_title)_BINWIDTHm_WHICHHALF_profile.nc

    where XXX is the glider id and (mission_title) is the is the contents of the
    mission_title field in the sg_calib_contants.m file, also located in the
    specified directory, BINWIDTH is the specified bin width in meters and
    WHICHHALF refers to which of the dive half profiles are included in each
    profile up, down, up_and_down (treated as seperate profiles) or combine
    (combine the down and up halfs)

    Returns:
        0 - success
        1 - failure

    Raises:
        None - all exceptions are caught and logged
    """
    base_opts = BaseOpts.BaseOptions(
        "Command line driver for creating mission profiles from single dive netCDF files"
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

    (ret_val, _) = make_mission_profile(dive_nc_file_names, base_opts)

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
