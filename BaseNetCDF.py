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

"""Routines and variables for creating NetCDF files for Seagliders"""

# import configparser
import contextlib
import os
import sys
import time
import uuid
from functools import reduce

import netCDF4
import numpy as np
import yaml

import Globals
import NetCDFUtils
import QC
import Utils
from BaseLog import log_critical, log_debug, log_error, log_info, log_warning

nc_inf = np.array([np.inf], dtype=np.float64)[0]  # CF1.4 ensure double
nc_nan = np.array([np.nan], dtype=np.float64)[0]  # CF1.4 ensure double

nc_sg_cal_prefix = "sg_cal_"
nc_sg_log_prefix = "log_"
nc_sg_eng_prefix = "eng_"
nc_gc_prefix = "gc_"
nc_gc_state_prefix = "gc_state_"
nc_gc_msg_prefix = "gc_msg_"


# See http://www.unidata.ucar.edu/software/netcdf-java/formats/DataDiscoveryAttConvention.html
nc_metadata_convention_version = "Unidata Dataset Discovery v1.0"

# NetCDF Climate and Forecast (CF) Metadata Conventions
# see http://www.cgd.ucar.edu/cms/eaton/cf-metadata/CF-current.html#file
# http://cf-pcmdi.llnl.gov/documents/cf-standard-names/standard-name-table/16/cf-standard-name-table.html
# these are attribute conventions and names, not variable name conventions
# check compliantce using http://puma.nerc.ac.uk/cgi-bin/cf-checker.plb
nc_variables_convention_version = "CF-1.6"
# coordinates are for XYZT variables only, see ensure_CF_compliance below
nc_coordinates = "coordinates"
nc_coordinate_vars = {}  # nc_dim_info -> [T_var, X_var, Y_var, Z_var], then a string

# ancillary_variables are for variables that were used in the calculation of the value(s) of the variable
# typically these are calibration constants, etc.
nc_ancillary_variables = "ancillary_variables"


# Support functions for creating and merging global attributes
def nc_ISO8601_date(epoch_time):
    """return an epoch_time ala time.time() in required metadata standard format"""
    return time.strftime("%Y-%m-%dT%H:%m:%SZ", time.gmtime(epoch_time))


# These functions compare date strings for mergers
def nc_earliest_date(global_name, master_value, slave_value):  # pylint: disable=unused-argument
    """Returns ealiest date"""
    return master_value if master_value <= slave_value else slave_value


def nc_latest_date(global_name, master_value, slave_value):  # pylint: disable=unused-argument
    """Returns ealiest date"""
    return master_value if master_value > slave_value else slave_value


def nc_copy(global_name, master_value, slave_value):  # pylint: disable=unused-argument
    """Returns a copy"""
    return slave_value


def nc_stet(global_name, master_value, slave_value):  # pylint: disable=unused-argument
    """don't ask, don't tell"""
    return master_value


def nc_identical(global_name, master_value, slave_value):  # pylint: disable=unused-argument
    if master_value != slave_value:
        log_warning(
            "NC global values for %s don't match during merge ('%s' vs. '%s') -- using '%s'"
            % (global_name, str(master_value), str(slave_value), str(master_value))
        )
    return nc_stet(global_name, master_value, slave_value)


def nc_remove(global_name, master_value, slave_value):  # pylint: disable=unused-argument
    return None  # signal to delete the entry from globals


def nc_max(global_name, master_value, slave_value):  # pylint: disable=unused-argument
    return max(master_value, slave_value)


def nc_min(global_name, master_value, slave_value):  # pylint: disable=unused-argument
    return min(master_value, slave_value)


# Quel disaster!  use of the dir(nc_fh) function to get global attributes of an nc file
# means we get all sorts of other python junk (function names, etc.)
# Instead document which globals we write and enter in this dictionary instead
# The associated values describe how to merge values when combining globals lists
# during make_mission_profiles/timeseries:
# [cnf_override,init_fn,merge_fn]

nc_global_variables = {
    "project": [True, nc_copy, nc_stet],  # mission title
    "title": [
        True,
        nc_copy,
        nc_stet,
    ],  # pretty name w/ glider id and mission title (also available separately as sg_cal_mission_title and mission)
    "summary": [True, nc_copy, nc_stet],  # same as title
    "comment": [True, nc_copy, nc_stet],  # optional
    "acknowledgment": [True, nc_copy, nc_stet],  # optional support acknowledgment
    "institution": [True, nc_copy, nc_stet],  # institution running the glider
    # institution will be used if these are not provided
    "creator_name": [True, nc_copy, nc_stet],  # PI name
    "creator_email": [True, nc_copy, nc_stet],  # PI email
    "creator_url": [True, nc_copy, nc_stet],  # PI URL (NOT? project URL?)
    "contributor_name": [True, nc_copy, nc_stet],  # Someone helpful
    "contributor_role": [True, nc_copy, nc_stet],  # How they helped
    "disclaimer": [True, nc_copy, nc_stet],  # optional
    "source": [True, nc_copy, nc_identical],  # NODC required...the vessel id
    "references": [True, nc_copy, nc_stet],  # optional
    # This is used to document NODC accession URL to SG QC Manual at this processing level
    "processing_level": [False, nc_copy, nc_stet],
    "license": [True, nc_copy, nc_stet],  # NODC required
    # This variable duplicates much of the data below but is preserved
    "platform": [
        False,
        nc_copy,
        nc_identical,
    ],  # name of the variable describing the platform (NODC requirement)
    "wmo_id": [False, nc_copy, nc_identical],  # the WMO id assigned to this deployment
    "instrument": [
        False,
        nc_copy,
        nc_stet,
    ],  # name of variables describing the instrument(s) (NODC requirement)
    "glider": [False, nc_copy, nc_identical],  # integer glider number
    "platform_id": [False, nc_copy, nc_identical],  # string SGXXX glider id
    "mission": [False, nc_copy, nc_stet],  # integer mission number
    # per dive profile
    "dive_number": [
        False,
        nc_remove,
        nc_remove,
    ],  # used in mission_timeseries() but not written as a global there
    "start_time": [
        False,
        nc_remove,
        nc_remove,
    ],  # when did dive start (epoch time) or [nc_copy,math.min]
    "seaglider_software_version": [False, nc_copy, nc_identical],
    # make_mission_profiles/timeseries assign these directly
    "file_data_type": [False, nc_remove, nc_remove],
    "binwidth": [False, nc_remove, nc_remove],
    # what format and content for each NC file
    "file_version": [False, nc_remove, nc_remove],  # caller sets
    # write_nc_globals or callers assign these directly
    "history": [
        False,
        nc_remove,
        nc_remove,
    ],  # file processing history: when file was written, possible other stuff (processing history?)
    # Which version of the basestation and QC level processed the file?
    "base_station_version": [False, nc_remove, nc_remove],
    "base_station_micro_version": [False, nc_remove, nc_remove],
    "quality_control_version": [False, nc_remove, nc_remove],
    "Conventions": [
        False,
        nc_remove,
        nc_remove,
    ],  # Climate and Forecast (CF) metadata variable conventions
    # If the file uses the CF convention (and the Convention attribute indicates this),
    # THREDDS will assume the standard_name values are from the CF convention standard name table.
    # http://cf-pcmdi.llnl.gov/documents/cf-standard-names/standard-name-table/16/cf-standard-name-table.html
    "standard_name_vocabulary": [False, nc_copy, nc_identical],
    "magcalfile_contents": [
        False,
        nc_copy,
        nc_stet,
    ],  # If the heading data was corrected with a new TCM2MAT style file
    # this variable contains the contents of that file
    "auxmagcalfile_contents": [
        False,
        nc_copy,
        nc_stet,
    ],  # If the heading data for the auxcompass was corrected with a new TCM2MAT style file
    # this variable contains the contents of that file
    # global attribute conventions
    # These are used to index datasets for NODC etc
    "Metadata_Conventions": [False, nc_copy, nc_identical],
    "featureType": [False, nc_copy, nc_identical],
    "cdm_data_type": [False, nc_copy, nc_identical],
    "nodc_template_version": [False, nc_copy, nc_identical],
    # http://gcmd.nasa.gov/Resources/valids/archives/keyword_list.html
    # GCMD_Science_Keywords.pdf
    "keywords_vocabulary": [False, nc_copy, nc_identical],  # required
    "keywords": [True, nc_copy, nc_stet],  # TODO parse and merge
    # http://www.nodc.noaa.gov/General/NODC-Archive/seanamelist.txt
    # names only, no codes, e.g., "Labrador Sea"
    "sea_name": [
        True,
        nc_copy,
        nc_stet,
    ],  # In fact, merge unique but this often suffices
    "date_created": [False, nc_remove, nc_remove],  # when initially created
    "date_modified": [
        False,
        nc_remove,
        nc_remove,
    ],  # latest date any raw data src changed?
    "date_issued": [False, nc_remove, nc_remove],  # when last written
    "publisher_name": [
        True,
        nc_copy,
        nc_stet,
    ],  # optional: organization that will be distributing the data
    "publisher_email": [True, nc_copy, nc_stet],  # optional: publisher email
    "publisher_url": [True, nc_copy, nc_stet],  # optional
    "uuid": [False, nc_remove, nc_remove],
    "id": [False, nc_remove, nc_remove],
    "naming_authority": [False, nc_copy, nc_identical],
    # TODO much discussion amongst the complaince chaps about the use of *_resolution attributes or *_accuracy attributes
    # *_resolution implies a measure of the interval between actual measurements, hence the *density* of actual measurements
    # *_accuracy implies what the instrument can resolve, hence its maximum resolution as opposed to actual resolution
    "time_coverage_start": [False, nc_copy, nc_earliest_date],
    "time_coverage_end": [False, nc_copy, nc_latest_date],
    # DEAD 'time_coverage_units':[False,nc_copy,nc_identical], # How different from resolution?
    # DEAD 'time_coverage_duration':[False,nc_remove,nc_remove], # if we expose this we need to calculate from ISO start/stops
    "time_coverage_resolution": [False, nc_copy, nc_identical],
    # geospatial bounding box of dataset
    # geospatial_lat/lon are set only in profiles where they can be computed
    "geospatial_lat_min": [False, nc_copy, nc_min],
    "geospatial_lat_max": [False, nc_copy, nc_max],
    "geospatial_lat_units": [False, nc_copy, nc_identical],
    "geospatial_lat_resolution": [False, nc_copy, nc_identical],
    "geospatial_lon_min": [False, nc_copy, nc_min],
    "geospatial_lon_max": [False, nc_copy, nc_max],
    "geospatial_lon_units": [False, nc_copy, nc_identical],
    "geospatial_lon_resolution": [False, nc_copy, nc_identical],
    "geospatial_vertical_min": [False, nc_copy, nc_min],
    "geospatial_vertical_max": [False, nc_copy, nc_max],
    "geospatial_vertical_units": [False, nc_copy, nc_identical],
    "geospatial_vertical_resolution": [False, nc_copy, nc_identical],
    "geospatial_vertical_positive": [False, nc_copy, nc_identical],
}


# There are several possibilities at each step:
# key/value present in master and slave: merge and decide which value to use
# key/value present in slave but absent in master: decide if slave should be copied
# NOT HANDLED: key/value present in master but absent in slave: decide if master should be removed
# key/value absent in master and slave -- nothing to do; caller will fill if need be
def merge_nc_globals(master_globals_d, slave_globals_d):
    """Merge NC global attributes from slave into master dictionary
    Input:
    master_globals_d -- accumulating dict of global key/value pairs
    slave_globals_d  -- dict of global key/value pairs that might update master

    Output: None
    Side-effect: master_globals_d dictionary is updated, if appropriate
    """

    for key, slave_value in list(slave_globals_d.items()):
        try:
            merge_fns = nc_global_variables[key]
        except KeyError:
            # unknown global
            # remove it and note it here
            log_warning(f"Unknown NC global attribute during merge '{key}' -- skipping")
            merge_fns = [False, nc_remove, nc_remove]

        _, init_fn, merge_fn = merge_fns
        try:
            # values for both master and slave: merge
            master_value = master_globals_d[key]
            master_value = merge_fn(key, master_value, slave_value)
        except KeyError:
            # Nothing on the master: init
            master_value = init_fn(key, None, slave_value)

        if master_value:
            master_globals_d[key] = master_value
        else:
            with contextlib.suppress(KeyError):
                del master_globals_d[key]  # remove it if it exists


def merge_instruments(master_instruments_d, slave_instruments_d):
    """Combine master and slave dictionaries into the master"""
    for key, slave_value in list(slave_instruments_d.items()):
        try:
            # values for both master and slave: merge
            master_value = master_instruments_d[key]
            master_value = nc_identical(key, master_value, slave_value)
        except KeyError:
            # Nothing on the master: init
            master_value = nc_copy(key, None, slave_value)

        if master_value:
            master_instruments_d[key] = master_value
        else:
            with contextlib.suppress(KeyError):
                del master_instruments_d[key]  # remove it if it exists


def update_globals_from_nodc(base_opts, globals_d):
    """Parse global and local NODC.yml files, if any and update globals_d"""

    nodc_cnf_file = "NODC.yml"
    # Important NOTE:
    # all the names (but NOT the values) in the name,value pairs are coerced to lowercase!

    # build from globals_d and declarations
    nodc_dicts = [{}]
    for name, merge_fns in list(nc_global_variables.items()):
        cnf_override, _, _ = merge_fns
        if cnf_override and name in globals_d:
            nodc_dicts[0][name] = globals_d[name]

    for yaml_filename in (
        os.path.join(base_opts.basestation_etc, nodc_cnf_file),
        base_opts.mission_dir / nodc_cnf_file,
    ):
        if os.path.exists(yaml_filename):
            try:
                with open(yaml_filename, "r") as fi:
                    nodc_dicts.append(yaml.safe_load(fi.read()))
            except Exception:
                log_error(f"Could not process {yaml_filename} - skipping", "exc")

        else:
            log_info(f"{yaml_filename} does not exist - skipping")

    try:
        reduce(
            lambda x, y: NetCDFUtils.merge_dict(x, y, allow_override=True), nodc_dicts
        )
    except Exception:
        log_error("Error merging config templates", "exc")
    else:
        for k, v in nodc_dicts[0].items():
            log_debug(f"Updating {k} to {v}")
            globals_d[k] = v  # these should always strings

    # Prevoius .cnf based code

    # cp = configparser.RawConfigParser(nodc_defaults)
    # try:
    #     files = cp.read(
    #         [
    #             global_nodc_file,
    #             mission_nodc_file,
    #         ]
    #     )
    # except:
    #     # One way to get here is to have continuation lines on an entry like references: or acknowledgment:
    #     # that are not indented by a single space AND have a colon somewhere in the line
    #     # In this case you'll get a complaint about an unknown global variable with that phrase in lower case
    #     # NOTE: if there is a continuation but no space and no colon the parser skips it without complaint
    #     log_warning(f"Problems reading information from {nodc_cnf_file}")  # problems...

    # if cp.has_section("NODC"):
    #     for pair in cp.items("NODC"):
    #         name, value = pair
    #         globals_d[name] = value  # these are always strings
    # else:
    #     log_warning(
    #         f"No [NODC] section found in {global_nodc_file} or {mission_nodc_file}"
    #     )

    # if cp.has_section("NODC_controls"):
    #     for pair in cp.items("NODC_controls"):
    #         name, value = pair
    #         controls_d[name] = value  # these are always strings
    # else:
    #     log_error(
    #         f"No [NODC_controls] section found in {global_nodc_file} or {mission_nodc_file}"
    #     )

    return


def form_NODC_title(instruments, nodc_globals_d, nc_globals_d, mission_title):
    """Form an NODC-acceptable title for a per-dive nc file
    NODC requests this for better search support
    """
    # We always report 'physical' (e.g., CT, depth, etc.) info
    data_types = ["physical"]
    for instrument in instruments:
        try:
            data_type = nc_instrument_to_data_kind[instrument]
            if data_type not in data_types:
                data_types.append(data_type)
        except KeyError:
            pass
    try:
        sea_name = nodc_globals_d["sea_name"]
        sea_name = f" in the {sea_name}"
    except KeyError:
        sea_name = ""  # Not compliant yet...
    # NOTE: The word 'deployed' is critical to NODC automated processing
    # They use the text up to and including this word to name the accession
    phrase = "%s data collected from Seaglider %s during %s%s deployed on %s"
    title = phrase % (
        Utils.Oxford_comma(data_types).capitalize(),
        nc_globals_d["platform_id"],
        mission_title,
        sea_name,
        time.strftime("%Y-%m-%d", time.gmtime(nc_globals_d["start_time"])),
    )
    return title


# See load_dive_profile_data() in MDP for the 'reader'
def write_nc_globals(nc_file, globals_d, base_opts):
    """Write global attributes to the NC file
    Input:
    nc_file -- file handle to writable NC file
    globals_d -- dict of global key/value pairs
    base_opts -- dict of basestation options
    Output: None
    """

    # Ensure these global attribute values on any new file we write
    now_date = nc_ISO8601_date(time.time())
    # local_date = time.asctime(time.localtime(time.time()))
    # Refinement of id, which the caller provides.  Reverse-DNS naming of naming authority recommended, hence:
    globals_d["naming_authority"] = "edu.washington.apl"

    # http://gcmd.nasa.gov/Resources/valids/archives/keyword_list.html
    # GCMD_Science_Keywords.pdf
    # Use only the most specific keywords
    # TODO add Oxygen if O2 sensor
    # TODO what about Ocean Currents, Upwelling/Downwelling?
    globals_d["keywords_vocabulary"] = (
        "NASA/GCMD Earth Science Keywords Version 6.0.0.0"
    )
    # The truck w/ a CTD provides these
    globals_d["keywords"] = (
        "Water Temperature, Conductivity, Salinity, Density, Potential Density, Potential Temperature"
    )
    globals_d["processing_level"] = Globals.quality_control_version
    # TODO Submit updated docs/SQCM.html to NODC.DataOfficer@noaa.gov for archival
    # List accession URL to Seaglider_Quality_Control_Manual.html versions here
    globals_d["references"] = (
        "http://data.nodc.noaa.gov/accession/0092291"  # v1.10, archived 7/18/2012
    )

    # caller sets history and date_issued as appropriate
    # we set date_created if apparently for the first time
    # even --force will maintain this date so only reset if you waste the nc file

    # It is all very unclear the difference between date_issued and date_modified
    # Does it mean when the raw data was modified? when the results were changed?
    # vs. when the data was made available to the public or simply put into this form?
    # We take
    # OR when they decide to submit to NODC etc. (which means 'updating' just the date on transmission)
    if "date_created" not in globals_d:  # set once
        globals_d["date_created"] = now_date
    # last time run (date_issued)
    # TODO: distinguish when the raw data was modified (updated files) or when the results were last modified (alg changes)?
    # or simply --forced??  or change of nc format or QC level...
    globals_d["date_modified"] = now_date
    # update uuid each time written
    globals_d["uuid"] = str(uuid.uuid1())
    # How we made this file
    globals_d["base_station_version"] = Globals.basestation_version
    # PYTHON3 TODO - Should we plumb in something that is the "near" equivalent
    # globals_d['base_station_micro_version'] = Utils.get_svn_version()
    globals_d["base_station_micro_version"] = 0
    globals_d["quality_control_version"] = Globals.quality_control_version
    globals_d["Metadata_Conventions"] = (
        nc_metadata_convention_version  # globals metadata conventions
    )
    globals_d["Conventions"] = (
        nc_variables_convention_version  # variable metadata conventions
    )
    globals_d["standard_name_vocabulary"] = (
        nc_variables_convention_version  # variable metadata conventions
    )
    # See http://www.nodc.noaa.gov/data/formats/netcdf and the trajectory template in particular:
    # http://www.nodc.noaa.gov/data/formats/netcdf/trajectoryIncomplete.cdl
    globals_d["featureType"] = "trajectory"
    globals_d["cdm_data_type"] = "Trajectory"  # required ACDD
    globals_d["nodc_template_version"] = "NODC_NetCDF_Trajectory_Template_v0.9"
    # NODC.cnf globals_d['license'] = 'These data may be redistributed and used without restriction.'

    update_globals_from_nodc(base_opts, globals_d)

    for key, value in list(globals_d.items()):
        try:
            nc_global_variables[key]
        except KeyError:
            log_warning(f"Unknown NC global attribute '{key}'")
            # fall through and write it anyway
            # load_dive_profile_data() will not return it, however
        setattr(nc_file, key, value)  # write as global attribute


# Main data table dimension names

# Each sensor has one or more data vectors collected on possibly
# differing time grids. Each sensor may or may not have a set of
# corrected (and dervied) quantities from those vecors and, depending
# on the requirements for the corrections, not all raw data and times
# will be used (see gpctd). Thus for each vector we write to an nc file
# we need to keep a record of which dimension we should use and, for
# doc and conversion purpose, which time var corresponds to that
# dimension.

# However, some instruments, notably all the sensors on a truck-only
# mission, all share the same dimension (sg_data_point) and time var
# (sg_epoch_time_s_v).  Further so do all the derived quantities.
# Rather than needlessly duplicating time data and adding more
# dimensions to the file, we'd like to reuse this one dimension.

# To that end, we define a dimension 'info' for each sensor and
# another for any results they might have.  So, for example, we have
# sg_data_info, gpctd_data_info, and sbect_data_info for CTD raw data
# info and ctd_results_info for the corrected and derviced quantiies.
# These 'info' are used to index into a dict to the actual dimensions
# used to describe the data for a particular file.  In one
# ctd_results_info might point to sg_data_point, in another
# gpctd_data_info if no points were dropped.  If points were dropped,
# it might point to ctd_data_point.

# Each info is registered with its default dimension name and that
# dimension's nc time var.  This registration forms only a default
# association which might get reassigned during processing.  The
# registration also declares whether the corresonding vectors are raw
# data or derived and corrected quantities.

# Further, each nc vector var is annotated with its info.  This is
# used during make_dive_profile() and make_mission_timeseries() to
# write the vector with the appropriate dimension.
# (make_mission_profiles() uses the info data to decimate all data to
# sg_data_point dimesnions before binning and writes each included
# vector with a set of new dimensions.)

# So, here are the rules for adding a new sensor:
# 1. Decide on unique names for their nc_var vectors of raw data
# 2. Define a <sensor>_data_info and a <sensor>_data_point dimension.
# 3. Determine what the associated nc time var is associated with the data (could be mew or shared)
# 4. If there are dervied quantities, create a <sensor>_result_info and <sensor>_result_point dimension
# 5. Mark each nc_var declaration with the proper data or result info.
# 6. If you have derived quantities, mark those to be incldued in MMP and MMT, but not the raw data.
#    Otherwise, mark the raw data to be included.
# 7. Add a registration statement to the sensor init_sensor() call for the data info and for any result info.

# mdp_dim_info tags:
# nc_scalar is used for scalars of all kinds
# DEAD nc_scalar = None
nc_scalar = ()

nc_trajectory_info = "trajectory_info"
nc_dim_trajectory_info = "trajectory"  # for CF compliance

nc_gps_info_info = "gps_info_info"
nc_dim_gps_info = "gps_info"  # rather than 'gps_time'

nc_gc_event_info = "gc_event_info"
nc_dim_gc_event = "gc_event"  # rather than 'gc_time'

nc_gc_state_info = "gc_state_info"
nc_dim_gc_state = "gc_state"  # rather than 'gc_time'

nc_tc_prefix = "tc_"
nc_tc_event_info = "tc_event_info"
nc_dim_tc_event = "tc_event"

nc_sg_data_info = "sg_data_info"  # eng
nc_dim_sg_data_point = "sg_data_point"  # rather than 'time'
nc_sg_time_var = (
    "time"  #  Legacy name of the variable.  Should have been sg_time but so it goes
)

nc_gpctd_data_info = "gpctd_data_info"  # gpctd
nc_sbect_data_info = "sbect_data_info"  # from scicon
nc_legato_data_info = "legato_data_info"  # from scicon_ext

nc_ctd_results_info = "ctd_results_info"  # derived CT and flight data from some CTD
nc_dim_ctd_data_point = (
    "ctd_data_point"  # because of possible truncation, can't always inherit data info
)
nc_ctd_time_var = "ctd_time"

#

# NOTE: Attempting to use unlimited variables via, e.g., createDimension(nc_dim_sg_data_point, None)
# does not work with netcdf on Mac OS X (at least) BUG
# You get strange values such as:
#  1.17522270165415e+214, 3.94101298290848e+180, 2.00461966079972e-313, ...
# for conductivity, etc. and other doubles.
# Issue avoided if you give explicit dimension size...

# There was a move to make the dimension name and the time variable be derivable from one another
# Thus we would have sg_time to sg_data_point, aa4330_data_point from aa4330_time, etc.
# But for legacy reasons we stick w/ the original name allowing us to read older nc files and not change doc
# If we change this to 'sg_time' you must bump the mission_*_nc_fileversion and required_nc_fileversion by 0.01

# Each instrument eventually will have its own dimensions for the points it creates
# In the case of unpumped CTs, these are 1:1 (since the glider controls it) but we declare it all anyway

# make similar dimensions for sbe43, optode, wetlabs, etc.

# called from init_sensors, which registers the truck info as well


def set_globals() -> None:
    """Allows global varaibles to be reset externally"""
    global \
        nc_mdp_data_info, \
        nc_mdp_time_vars, \
        nc_mdp_instrument_vars, \
        nc_mdp_mmt_vars, \
        nc_data_infos, \
        nc_instrument_to_data_kind, \
        nc_dim_profile, \
        nc_dim_depth, \
        nc_dim_dives, \
        nc_char_dims, \
        nc_string_dim_format, \
        nc_var_metadata, \
        ensure_long_names, \
        after_static_check
    ##########
    nc_mdp_data_info = {}  # info -> dim_name or None
    nc_mdp_time_vars = {}  # registered dim_name -> time_var
    nc_mdp_instrument_vars = {}  # dim_info to instrument variable
    nc_mdp_mmt_vars = {}  # registered dim_name -> constructed var to hold dive numbers in MMT
    nc_data_infos = []  # registered infos with time_vars
    # TODO add keywords for data types as well so we can compose keywords globals
    nc_instrument_to_data_kind = {}  # e.g., sbe41 => 'physical', etc.

    # make_mission_profiles() writes all matricies with dimensions (profile,depth) based on included binned vectors
    nc_dim_profile = "profile"  # for make_mission_profiles()  matricies
    nc_dim_depth = "depth"  # for make_mission_profiles()  matricies

    # dimension for the accumulated scalars, one per included dive
    nc_dim_dives = "dive"  # for make_mission_timeseries() matricies

    # a dictionaary mapping from string length to a string dimension for reuse by the current file being written
    # callers reset this global for each new NC file you write
    nc_char_dims = {}
    nc_string_dim_format = "string_%d"  # was "STRING%d" per ARGO

    # Metadata for netCDF data
    # Fields are:
    #  0 - include in mission file
    #  1 - nc data type
    #  2 - dictionary of attribute names and values
    # The dictionary of attributes is arbitrary, but the commonly expected ones are:

    #   description - one line description of the variables

    #   units - units the variable is expressed in
    #      CF1.4 -- there are rules for composing units that must be followed
    #      CF1.4: units need to be SI and must follow the conventions found in:
    #      Prefixes:       http://www.unidata.ucar.edu/software/udunits/udunits-2/udunits2-prefixes.xml
    #      Base units:     http://www.unidata.ucar.edu/software/udunits/udunits-2/udunits2-base.xml
    #      Derived units:  http://www.unidata.ucar.edu/software/udunits/udunits-2/udunits2-derived.xml
    #      Acceptable:     http://www.unidata.ucar.edu/software/udunits/udunits-2/udunits2-accepted.xml
    #      Non-SI:         http://www.unidata.ucar.edu/software/udunits/udunits-2/udunits2-common.xml

    #   standard_name - the generally accepted oceangraphic name for this variable (that is, the netCDF name
    #                   may include instrument of origin details or other qualifiers)
    #   standard_name values are constrained by CF1.4; see the table. otherwise use 'long_name' if you must
    #   ONLY use standard_value for the main variables you want oceanographers to use
    #   e.g., see salinity_raw (long_name) and salinity (standard_name: sea_water_salinity)
    #   http://cf-pcmdi.llnl.gov/documents/cf-standard-names/standard-name-table/14/cf-standard-name-table.html

    # NOTE: if you change the format of the table, don't forget to update the metadata in ./Sensors modules

    # Constraints:
    # - Always add a default type, even though we try to infer from values if given
    # - All qc variables should declare their type as nc_qc_type (see comment in QC.py) and should declare units,
    #        if necessary, as 'qc_flag' for compliance conversion
    # - Do NOT use 'missing_value', which is deprecated in CF1.4 (but NOT CF1.5, sigh); use '_FillValue' for missing or undefined values
    #   add _FillValue only if some data points are truely missing, e.g., unsampled or based on unsampled data
    #   NOTE: _FillValue are handled differently for different vectors and then for only a few of them
    #   all variables used in timeseries (include in mission file == True or with [D] and [P] in description string) should have an appropriate _FillValue
    # - timeseries code assumes all variables declared for inclusion will *always* be present in processed dives, even if just filled with _FillValue

    nc_var_metadata = {
        # The platform variable; NODC requires the name 'glider'
        "glider": [False, "c", {"nodc_name": "glider"}, nc_scalar],
        "compass_timeouts_times_truck": [
            False,
            "c",
            {
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "compass epoch times for of timeouts truck",
            },
            nc_scalar,
        ],
        "compass_timeouts_truck": [
            False,
            "i",
            {"description": "compass total number of samples timed out on truck"},
            nc_scalar,
        ],
        "sg_cal_id_str": [
            False,
            "c",
            {"description": "Three digit vehicle identification string"},
            nc_scalar,
        ],
        "sg_cal_mission_title": [
            False,
            "c",
            {"description": "Description of mission"},
            nc_scalar,
        ],
        # Normally a number but we require it as a string
        # Typically has the form: a8xxnnnn where a is some region indicator (where launched)
        # Can be preceded with Q (hence the string requirement) if the data might go to TESAC
        "sg_cal_wmo_id": [
            False,
            "c",
            {"description": "The WMO id assigned to this deployment"},
            nc_scalar,
        ],
        # motor limits and rates (UNUSED--look at $PITCH_MAX, etc...)
        # These are never used but we have them here to record them without complaint from legacy sg_calib_constants.m files
        "sg_cal_pitch_max_cnts": [False, "i", {}, nc_scalar],
        "sg_cal_pitch_min_cnts": [False, "i", {}, nc_scalar],
        "sg_cal_roll_max_cnts": [False, "i", {}, nc_scalar],
        "sg_cal_roll_min_cnts": [False, "i", {}, nc_scalar],
        "sg_cal_vbd_cnts_per_cc": [False, "d", {}, nc_scalar],
        "sg_cal_vbd_max_cnts": [False, "i", {}, nc_scalar],
        "sg_cal_vbd_min_cnts": [False, "i", {}, nc_scalar],
        "sg_cal_pump_rate_intercept": [False, "d", {}, nc_scalar],
        "sg_cal_pump_rate_slope": [False, "d", {}, nc_scalar],
        "sg_cal_pump_power_intercept": [False, "d", {}, nc_scalar],
        "sg_cal_pump_power_slope": [False, "d", {}, nc_scalar],
        # buoyancy parameters
        "sg_cal_volmax": [
            False,
            "d",
            {"description": "Maximum displaced volume of the glider", "units": "m^3"},
            nc_scalar,
        ],
        # DEAD 'sg_cal_vbd_change_rate' : [False, 'd', {'description':'Buoyancy loss rate of vehicle during deployment', 'units':'cc/day'}, nc_scalar],
        "sg_cal_mass": [
            False,
            "d",
            {"description": "Mass of the glider", "units": "kg"},
            nc_scalar,
        ],
        "sg_cal_mass_comp": [
            False,
            "d",
            {"description": "Mass of the compressee", "units": "kg"},
            nc_scalar,
        ],
        "sg_cal_abs_compress": [
            False,
            "d",
            {"description": "SG vehicle compressibility", "units": "cc/dbar"},
            nc_scalar,
        ],
        "sg_cal_therm_expan": [
            False,
            "d",
            {
                "description": "SG thermal expansion coeff",
                "units": "cc/degrees_Celsius",
            },
            nc_scalar,
        ],
        "sg_cal_temp_ref": [
            False,
            "d",
            {
                "description": "Reference temperature for SG thermal expansion calculation",
                "units": "degrees_Celsius",
            },
            nc_scalar,
        ],
        # hydrodynamic parameters
        "sg_cal_rho0": [
            False,
            "d",
            {
                "description": "Typical expected density of seawater for this deployment",
                "units": "kg/m^3",
            },
            nc_scalar,
        ],
        "sg_cal_hd_a": [
            False,
            "d",
            {
                "description": "Hydrodynamic lift factor for given hull shape (1/degrees of attack angle)"
            },
            nc_scalar,
        ],
        "sg_cal_hd_b": [
            False,
            "d",
            {
                "description": "Hydrodynamic drag factor for given hull shape (Pa^(-1/4))"
            },
            nc_scalar,
        ],
        "sg_cal_hd_c": [
            False,
            "d",
            {
                "description": "Hydrodynamic induced drag factor for given hull shape (1/radians^2 of attack angle)"
            },
            nc_scalar,
        ],
        "sg_cal_hd_s": [
            False,
            "d",
            {
                "units": "fraction",
                "description": "How the drag scales by shape (-1/4 for SG per Eriksen, et al.)",
            },
            nc_scalar,
        ],
        "sg_cal_solve_flare_apogee_speed": [
            False,
            "i",
            {
                "description": "Whether to solve for accelerated speeds during flare and apogee"
            },
            nc_scalar,
        ],
        # Sparton compass pitch and roll coeffients, used to invert correction if desired
        "sg_cal_sparton_pitch0": [False, "d", {}, nc_scalar],
        "sg_cal_sparton_pitch1": [False, "d", {}, nc_scalar],
        "sg_cal_sparton_pitch2": [False, "d", {}, nc_scalar],
        "sg_cal_sparton_pitch3": [False, "d", {}, nc_scalar],
        # Currently we do not adjust roll but record the parameters if they want...
        "sg_cal_sparton_roll0": [False, "d", {}, nc_scalar],
        "sg_cal_sparton_roll1": [False, "d", {}, nc_scalar],
        "sg_cal_sparton_roll2": [False, "d", {}, nc_scalar],
        "sg_cal_sparton_roll3": [False, "d", {}, nc_scalar],
        # SBECT 41 coefficients
        "sg_cal_calibcomm": [False, "c", {}, nc_scalar],
        "sg_cal_c_g": [False, "d", {}, nc_scalar],
        "sg_cal_c_h": [False, "d", {}, nc_scalar],
        "sg_cal_c_i": [False, "d", {}, nc_scalar],
        "sg_cal_c_j": [False, "d", {}, nc_scalar],
        "sg_cal_cpcor": [
            False,
            "d",
            {
                "description": "Nominal compression factor of conductivity tube with pressure"
            },
            nc_scalar,
        ],
        "sg_cal_ctcor": [
            False,
            "d",
            {
                "description": "Nominal thermal expansion factor of a cube of boro-silicate glass"
            },
            nc_scalar,
        ],
        "sg_cal_sbe_cond_freq_max": [
            False,
            "d",
            {
                "description": "SBE41 maximum permitted conductivity frequency",
                "units": "Hz",
            },
            nc_scalar,
        ],
        "sg_cal_sbe_cond_freq_min": [
            False,
            "d",
            {
                "description": "SBE41 minimum permitted conductivity frequency",
                "units": "Hz",
            },
            nc_scalar,
        ],
        "sg_cal_t_g": [False, "d", {}, nc_scalar],
        "sg_cal_t_h": [False, "d", {}, nc_scalar],
        "sg_cal_t_i": [False, "d", {}, nc_scalar],
        "sg_cal_t_j": [False, "d", {}, nc_scalar],
        "sg_cal_sbe_temp_freq_max": [
            False,
            "d",
            {
                "description": "SBE41 maximum permitted temperature frequency",
                "units": "Hz",
            },
            nc_scalar,
        ],
        "sg_cal_sbe_temp_freq_min": [
            False,
            "d",
            {
                "description": "SBE41 minimum permitted temperature frequency",
                "units": "Hz",
            },
            nc_scalar,
        ],
        # User-specified adjustments to raw data, if any
        "sg_cal_cond_bias": [
            False,
            "d",
            {"units": "mS/cm", "description": " Conductivity bias"},
            nc_scalar,
        ],
        "sg_cal_depth_bias": [
            False,
            "d",
            {"units": "meters", "description": "Depth bias of pressure sensor"},
            nc_scalar,
        ],
        "sg_cal_depth_slope_correction": [
            False,
            "d",
            {
                "description": "Correction factor to apply to truck depth to compensate for data with incorrect pressure slope"
            },
            nc_scalar,
        ],
        "sg_cal_pitchbias": [
            False,
            "d",
            {"units": "degrees", "description": "Pitch sensor bias"},
            nc_scalar,
        ],
        "sg_cal_rollbias": [
            False,
            "d",
            {"units": "degrees", "description": "Roll sensor bias"},
            nc_scalar,
        ],
        "sg_cal_temp_bias": [
            False,
            "d",
            {"units": "degrees_Celsius", "description": "Temperature bias"},
            nc_scalar,
        ],
        "sg_cal_vbdbias": [
            False,
            "d",
            {"units": "cc", "description": "VBD bias"},
            nc_scalar,
        ],
        "sg_cal_min_stall_speed": [
            False,
            "d",
            {
                "units": "cm/s",
                "description": "Minimum likely speed for vehicle, else stalled",
            },
            nc_scalar,
        ],
        "sg_cal_max_stall_speed": [
            False,
            "d",
            {
                "units": "cm/s",
                "description": "Maximum likely speed for vehicle, else stalled",
            },
            nc_scalar,
        ],
        "sg_cal_min_stall_angle": [
            False,
            "d",
            {"units": "degrees", "description": "Minimum flight angle, else stalled"},
            nc_scalar,
        ],
        "sg_cal_sg_configuration": [
            False,
            "i",
            {"description": "The general configuration of the glider"},
            nc_scalar,
        ],
        # Cell interior geometry
        "sg_cal_sg_ct_geometry": [
            False,
            "i",
            {"description": "The geometry of the CT sensor itself"},
            nc_scalar,
        ],
        "sg_cal_sbect_x_T": [
            False,
            "d",
            {"description": "Cell mouth to thermistor x offset", "units": "meters"},
            nc_scalar,
        ],  # relative to center of cell mount
        "sg_cal_sbect_z_T": [
            False,
            "d",
            {"description": "Cell mouth to thermistor z offset", "units": "meters"},
            nc_scalar,
        ],  # relative to center of cell mount
        "sg_cal_sbect_x_m": [
            False,
            "d",
            {"description": "Length of mouth portion of cell", "units": "meters"},
            nc_scalar,
        ],
        "sg_cal_sbect_r_m": [
            False,
            "d",
            {"description": "Radius of mouth portion of cell", "units": "meters"},
            nc_scalar,
        ],
        "sg_cal_sbect_cell_length": [
            False,
            "d",
            {
                "units": "meters",
                "description": "Combined length of the 2 narrow (sample) portions of cell",
            },
            nc_scalar,
        ],
        "sg_cal_sbect_r_n": [
            False,
            "d",
            {"units": "meters", "description": "Radius of narrow portion of cell"},
            nc_scalar,
        ],
        "sg_cal_sbect_r_w": [
            False,
            "d",
            {"units": "meters", "description": "Radius of wide portion of cell"},
            nc_scalar,
        ],
        "sg_cal_sbect_x_w": [
            False,
            "d",
            {"units": "meters", "description": "Length of wide portion of cell"},
            nc_scalar,
        ],
        "sg_cal_sbect_C_d0": [
            False,
            "d",
            {"description": "Measured cell drag coefficient"},
            nc_scalar,
        ],  # (1.2 for the original SG cell mount before SG105, 2.4 for new style)
        # Cell type and response factors
        "sg_cal_sg_ct_type": [
            False,
            "i",
            {
                "units": "flag",
                "description": "The type of CT sensor (original, gun, pumped)",
            },
            nc_scalar,
        ],
        "sg_cal_sbect_unpumped": [
            False,
            "i",
            {"units": "flag", "description": "Whether the CTD is pumped or not"},
            nc_scalar,
        ],
        "sg_cal_sbect_tau_T": [
            False,
            "d",
            {"units": "seconds", "description": "Thermistor response (from Seabird)"},
            nc_scalar,
        ],
        "sg_cal_sbect_gpctd_tau_1": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Time delay between thermistor and mouth of conductivity tube in pumped CTD",
            },
            nc_scalar,
        ],
        "sg_cal_sbect_gpctd_u_f": [
            False,
            "d",
            {
                "units": "cm/s",
                "description": "Tube flow speed for continuous pumped CTD",
            },
            nc_scalar,
        ],
        "sg_cal_sbe_cond_freq_offset": [
            False,
            "d",
            {"units": "Hz", "description": "Conductivity frequency offset"},
            nc_scalar,
        ],
        "sg_cal_sbe_temp_freq_offset": [
            False,
            "d",
            {"units": "Hz", "description": "Temperature frequency offset"},
            nc_scalar,
        ],
        # Non-modal correction (DEAD)
        # TODO: maintain this definition but declare it dead so we can read it from old files but drop it in new files
        # Add 'DEAD' tag to metadata with first version no longer supporting it. If dead, return none from create_nc_var() immediately.
        # TODO: add PCor to sbe43_ext.py and declare DEAD, remove code in MDP::load_dive_profile_data()
        "sg_cal_sbect_tau_w_min": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Minimum thermal response time of the glass/epoxy tube",
            },
            nc_scalar,
        ],  # DEAD UNUSED
        "sg_cal_sbect_u_r": [
            False,
            "d",
            {"units": "m/s", "description": "Thermal inertia response rolloff speed "},
            nc_scalar,
        ],  # DEAD UNUSED
        # Modal correction
        "sg_cal_sbect_modes": [
            False,
            "i",
            {"description": "Number of modes to use for thermal-inertia correction"},
            nc_scalar,
        ],
        "sg_cal_sbect_inlet_bl_factor": [
            False,
            "d",
            {"description": "Scale factor for inlet boundary layer formation"},
            nc_scalar,
        ],
        "sg_cal_sbect_Nu_0i": [
            False,
            "d",
            {
                "description": "Scale factor for unmodeled flow disruption to interior flow Biot number"
            },
            nc_scalar,
        ],
        "sg_cal_sbect_Nu_0e": [
            False,
            "d",
            {
                "description": "Scale factor for unmodeled flow disruption to exterior flow Biot number"
            },
            nc_scalar,
        ],
        # Cell installation geometry wrt pressure sensor
        "sg_cal_sg_sensor_geometry": [
            False,
            "i",
            {
                "description": "How the CT is mounted with respect to the SG pressure sensor"
            },
            nc_scalar,
        ],
        "sg_cal_glider_xT": [
            False,
            "d",
            {"description": "Glider x coord of thermistor tip", "units": "meters"},
            nc_scalar,
        ],
        "sg_cal_glider_zT": [
            False,
            "d",
            {"description": "Glider z coord of thermistor tip", "units": "meters"},
            nc_scalar,
        ],
        "sg_cal_glider_xP": [
            False,
            "d",
            {"description": "Glider x coord of pressure gauge", "units": "meters"},
            nc_scalar,
        ],  # to center of pressure gauge
        "sg_cal_glider_zP": [
            False,
            "d",
            {"description": "Glider z coord of pressure gauge", "units": "meters"},
            nc_scalar,
        ],  # to center of pressure gauge
        "sg_cal_sg_vehicle_geometry": [
            False,
            "i",
            {"description": "Various size measurements of the vehicle itself"},
            nc_scalar,
        ],
        "sg_cal_glider_length": [
            False,
            "d",
            {
                "description": "Length of standard glider body (not including antenna mast)",
                "units": "meters",
            },
            nc_scalar,
        ],
        "sg_cal_glider_interstitial_volume": [
            False,
            "d",
            {
                "description": "SG interstitial volume between fairing and hull",
                "units": "m^3",
            },
            nc_scalar,
        ],
        "sg_cal_glider_interstitial_length": [
            False,
            "d",
            {
                "description": "SG equivalent interstitial pipe length",
                "units": "meters",
            },
            nc_scalar,
        ],  #
        "sg_cal_glider_r_en": [
            False,
            "d",
            {"description": "Nose entry hole radius", "units": "meters"},
            nc_scalar,
        ],  # hole size
        "sg_cal_glider_wake_entry_thickness": [
            False,
            "d",
            {"description": "Wake entry region thickness", "units": "meters"},
            nc_scalar,
        ],
        "sg_cal_glider_vol_wake": [
            False,
            "d",
            {"description": "Attached wake volume", "units": "m^3"},
            nc_scalar,
        ],
        "sg_cal_glider_r_fair": [
            False,
            "d",
            {"description": "Maximum radius of fairing", "units": "meters"},
            nc_scalar,
        ],
        # Parameters that control standard QC tests
        "sg_cal_QC_temp_max": [
            False,
            "d",
            {
                "units": "degrees_Celsius",
                "description": "Maximum allowable temperature",
            },
            nc_scalar,
        ],
        "sg_cal_QC_temp_min": [
            False,
            "d",
            {
                "units": "degrees_Celsius",
                "description": "Minimum allowable temperature",
            },
            nc_scalar,
        ],
        "sg_cal_QC_temp_spike_depth": [
            False,
            "d",
            {"units": "meters", "description": "Depth for deep temperature spike test"},
            nc_scalar,
        ],
        "sg_cal_QC_temp_spike_deep": [
            False,
            "d",
            {
                "units": "degrees_Celsius/meter",
                "description": "Allowable temperature spike in deep water",
            },
            nc_scalar,
        ],
        "sg_cal_QC_temp_spike_shallow": [
            False,
            "d",
            {
                "units": "degrees_Celsius/meter",
                "description": "Allowable temperature spike in shallow deep water",
            },
            nc_scalar,
        ],
        "sg_cal_QC_temp_gradient_depth": [
            False,
            "d",
            {
                "units": "meters",
                "description": "Depth for deep temperature gradient test",
            },
            nc_scalar,
        ],
        "sg_cal_QC_temp_gradient_deep": [
            False,
            "d",
            {
                "units": "degrees_Celsius/meter",
                "description": "Allowable temperature gradient in deep water",
            },
            nc_scalar,
        ],
        "sg_cal_QC_temp_gradient_shallow": [
            False,
            "d",
            {
                "units": "degrees_Celsius/meter",
                "description": "Allowable temperature gradient in shallow water",
            },
            nc_scalar,
        ],
        "sg_cal_QC_cond_max": [
            False,
            "d",
            {"units": "mS/cm", "description": "Maximum conductivity value"},
            nc_scalar,
        ],
        "sg_cal_QC_cond_min": [
            False,
            "d",
            {"units": "mS/cm", "description": "Minimum conductivity value"},
            nc_scalar,
        ],
        "sg_cal_QC_cond_spike_depth": [
            False,
            "d",
            {
                "units": "meters",
                "description": "Depth for deep conductivity spike test",
            },
            nc_scalar,
        ],
        "sg_cal_QC_cond_spike_deep": [
            False,
            "d",
            {
                "units": "mS/cm/m",
                "description": "Allowable conductivity spike in deep water",
            },
            nc_scalar,
        ],
        "sg_cal_QC_cond_spike_shallow": [
            False,
            "d",
            {
                "units": "mS/cm/m",
                "description": "Allowable conductivity spike in shallow deep water",
            },
            nc_scalar,
        ],
        "sg_cal_QC_salin_max": [
            False,
            "d",
            {"units": "PSU", "description": "Maximum salinity value (PSU)"},
            nc_scalar,
        ],
        "sg_cal_QC_salin_min": [
            False,
            "d",
            {"units": "PSU", "description": "Minimum salinity value (PSU)"},
            nc_scalar,
        ],
        "sg_cal_QC_salin_spike_depth": [
            False,
            "d",
            {"units": "meters", "description": "Depth for deep salinity spike test"},
            nc_scalar,
        ],
        "sg_cal_QC_salin_spike_deep": [
            False,
            "d",
            {
                "units": "PSU/meter",
                "description": "Allowable salinity spike in deep water",
            },
            nc_scalar,
        ],
        "sg_cal_QC_salin_spike_shallow": [
            False,
            "d",
            {
                "units": "PSU/meter",
                "description": "Allowable salinity spike in shallow deep water (PSU/meter)",
            },
            nc_scalar,
        ],
        "sg_cal_QC_salin_gradient_depth": [
            False,
            "d",
            {"units": "meters", "description": "Depth for deep salinity gradient test"},
            nc_scalar,
        ],
        "sg_cal_QC_salin_gradient_deep": [
            False,
            "d",
            {
                "units": "PSU/meter",
                "description": "Allowable salinity gradient in deep water (PSU/meter)",
            },
            nc_scalar,
        ],
        "sg_cal_QC_salin_gradient_shallow": [
            False,
            "d",
            {
                "units": "PSU/meter",
                "description": "Allowable salinity gradient in shallow water (PSU/meter)",
            },
            nc_scalar,
        ],
        "sg_cal_QC_overall_ctd_percentage": [
            False,
            "d",
            {"description": "Maximum fraction of CTD data that can be QC_BAD"},
            nc_scalar,
        ],
        "sg_cal_QC_overall_speed_percentage": [
            False,
            "d",
            {"description": "Maximum fraction of CTD data that can be QC_BAD"},
            nc_scalar,
        ],
        "sg_cal_QC_bound_action": [
            False,
            "i",
            {"description": "What QC to assert when a bound is exceeded"},
            nc_scalar,
        ],
        "sg_cal_QC_spike_action": [
            False,
            "i",
            {"description": "What QC to assert when a spike is detected"},
            nc_scalar,
        ],
        "sg_cal_GPS_position_error": [
            False,
            "d",
            {"units": "meters", "description": "Assumed error of GPS fixes"},
            nc_scalar,
        ],
        "sg_cal_use_auxpressure": [
            False,
            "i",
            {"description": "Whether to use aux pressure sensor data"},
            nc_scalar,
        ],
        "sg_cal_use_auxcompass": [
            False,
            "i",
            {"description": "Whether to use aux compass sensor data"},
            nc_scalar,
        ],
        "sg_cal_use_adcppressure": [
            False,
            "i",
            {
                "description": "Whether to use the adcp pressure sensor over the truck pressure"
            },
            nc_scalar,
        ],
        "sg_cal_sbe_cond_freq_C0": [
            False,
            "d",
            {"description": "Conductivity zero frequency"},
            nc_scalar,
        ],
        # Legato corrections
        "sg_cal_legato_time_lag": [
            False,
            "d",
            {"description": ""},
            nc_scalar,
        ],
        "sg_cal_legato_alpha": [
            False,
            "d",
            {"description": ""},
            nc_scalar,
        ],
        "sg_cal_legato_tau": [
            False,
            "d",
            {"description": "Thermister response"},
            nc_scalar,
        ],
        "sg_cal_legato_ctcoeff": [
            False,
            "d",
            {"description": ""},
            nc_scalar,
        ],
        "sg_cal_legato_use_truck_pressure": [
            False,
            "d",
            {
                "description": "Use the seaglider's pressure trace for ctd corrections (non-zero). Use the legato's pressure trace for ctd corrections (zero)."
            },
            nc_scalar,
        ],
        "sg_cal_legato_cond_press_correction": [
            False,
            "d",
            {
                "description": "Early legato units required a conductivity correction based on pressure (non-zero).  Later units do this onboard (zero)."
            },
            nc_scalar,
        ],
        # log file header values
        "log_version": [
            False,
            "d",
            {"description": "Version of glider software"},
            nc_scalar,
        ],
        "log_glider": [False, "i", {"description": "Glider three digit id"}, nc_scalar],
        "log_mission": [False, "i", {"description": "Mission number"}, nc_scalar],
        "log_dive": [False, "i", {"description": "Dive number"}, nc_scalar],
        "log_start": [False, "d", {"description": "Dive start time"}, nc_scalar],
        # log file parameters (alphabetically)
        # as a rule control and AD parameters are 'i' type, strings are 'c' and the rest should be 'd'
        # even times and depths
        "log_10V_AH": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_24V_AH": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_MAXI_10V": [False, "d", {}, nc_scalar],
        "log_MAXI_24V": [False, "d", {}, nc_scalar],
        "log_AD7714Ch0Gain": [False, "i", {}, nc_scalar],
        "log_AH0_10V": [False, "d", {}, nc_scalar],
        "log_AH0_24V": [False, "d", {}, nc_scalar],
        "log_ALTIM_BOTTOM_PING": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_ALTIM_BOTTOM_PING_RANGE": [False, "d", {}, nc_scalar],
        "log_ALTIM_BOTTOM_TURN_MARGIN": [False, "d", {}, nc_scalar],
        "log_ALTIM_FREQUENCY": [False, "d", {}, nc_scalar],
        "log_ALTIM_PING_DELTA": [False, "d", {}, nc_scalar],
        "log_ALTIM_PING_DEPTH": [False, "d", {}, nc_scalar],
        "log_ALTIM_PING_N": [False, "d", {}, nc_scalar],
        "log_ALTIM_PING_FIT": [False, "d", {}, nc_scalar],
        "log_ALTIM_PULSE": [False, "d", {}, nc_scalar],
        "log_ALTIM_SENSITIVITY": [False, "d", {}, nc_scalar],
        "log_ALTIM_TOP_MIN_OBSTACLE": [False, "d", {}, nc_scalar],
        "log_ALTIM_TOP_PING": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_ALTIM_TOP_PING_RANGE": [False, "d", {}, nc_scalar],
        "log_ALTIM_TOP_TURN_MARGIN": [False, "d", {}, nc_scalar],
        "log_APOGEE_PITCH": [False, "d", {}, nc_scalar],
        "log_CALL_NDIVES": [False, "i", {}, nc_scalar],
        "log_CALL_TRIES": [False, "i", {}, nc_scalar],
        "log_CALL_WAIT": [False, "i", {}, nc_scalar],
        "log_N_CYCLES": [False, "i", {}, nc_scalar],
        "log_CAPMAXSIZE": [False, "i", {}, nc_scalar],
        "log_CAPUPLOAD": [False, "i", {}, nc_scalar],
        "log_CAP_FILE_SIZE": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_CF8_MAXERRORS": [False, "i", {}, nc_scalar],
        "log_CFSIZE": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_COMM_SEQ": [False, "i", {}, nc_scalar],
        "log_COMPASS2_DEVICE": [False, "d", {}, nc_scalar],
        "log_COMPASS_DEVICE": [False, "d", {}, nc_scalar],
        "log_COMPASS_USE": [False, "i", {}, nc_scalar],
        "log_COURSE_BIAS": [False, "d", {}, nc_scalar],
        "log_CURRENT": [False, "c", {}, nc_scalar],
        "log_CT_PROFILE": [False, None, {}, nc_scalar],
        "log_CT_RECORDABOVE": [False, None, {}, nc_scalar],
        "log_CT_XMITABOVE": [False, None, {}, nc_scalar],
        "log_C_PITCH": [False, "i", {}, nc_scalar],
        "log_C_PITCH_AUTO_DELTA": [False, "d", {}, nc_scalar],
        "log_C_PITCH_AUTO_MAX": [False, "d", {}, nc_scalar],
        "log_C_ROLL_CLIMB": [False, "d", {}, nc_scalar],
        "log_C_ROLL_DIVE": [False, "d", {}, nc_scalar],
        "log_C_VBD": [False, "i", {}, nc_scalar],
        "log_C_VBD_AUTO_DELTA": [False, "i", {}, nc_scalar],
        "log_C_VBD_AUTO_MAX": [False, "i", {}, nc_scalar],
        "log_DATA_FILE_SIZE": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_DBDW": [False, "d", {}, nc_scalar],
        "log_DEEPGLIDER": [False, "i", {}, nc_scalar],
        "log_DEEPGLIDERMB": [False, "i", {}, nc_scalar],
        "log_DEVICE1": [False, "d", {}, nc_scalar],
        "log_DEVICE2": [False, "d", {}, nc_scalar],
        "log_DEVICE3": [False, "d", {}, nc_scalar],
        "log_DEVICE4": [False, "d", {}, nc_scalar],
        "log_DEVICE5": [False, "d", {}, nc_scalar],
        "log_DEVICE6": [False, "d", {}, nc_scalar],
        "log_DEVICES": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_DEVICE_MAMPS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_DEVICE_MAX_MAMPS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_DEVICE_SECS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_DIVE": [False, "i", {}, nc_scalar],
        "log_D_ABORT": [False, "d", {}, nc_scalar],
        "log_D_BOOST": [False, "d", {}, nc_scalar],
        "log_D_CALL": [False, "d", {}, nc_scalar],
        "log_D_FINISH": [False, "d", {}, nc_scalar],
        "log_D_FLARE": [False, "d", {}, nc_scalar],
        "log_D_GRID": [False, "d", {}, nc_scalar],
        "log_D_NO_BLEED": [False, "d", {}, nc_scalar],
        "log_D_OFFGRID": [False, "d", {}, nc_scalar],
        "log_D_PITCH": [False, "d", {}, nc_scalar],
        "log_D_SAFE": [False, "d", {}, nc_scalar],
        "log_D_SURF": [False, "d", {}, nc_scalar],
        "log_D_TGT": [False, "d", {}, nc_scalar],
        "log_EOP_CODE": [False, "c", {}, nc_scalar],
        "log_ERRORS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_ESCAPE_HEADING": [False, "d", {}, nc_scalar],
        "log_ESCAPE_HEADING_DELTA": [False, "d", {}, nc_scalar],
        "log_ESCAPE_REASON": [False, "c", {}, nc_scalar],
        "log_ESCAPE_STARTED_DIVE": [False, "d", {}, nc_scalar],
        "log_EXED__exec_file": [
            False,
            "c",
            {"description": "Name of file executed"},
            ("log_EXED_info",),
        ],
        "log_EXED__seq_num": [
            False,
            "i",
            {"description": "Sequence number"},
            ("log_EXED_info",),
        ],
        "log_EXED__why": [
            False,
            "c",
            {"description": "Reason for exed"},
            ("log_EXED_info",),
        ],
        "log_FERRY_MAX": [False, "d", {}, nc_scalar],
        "log_FG_AHR_10V": [False, "d", {}, nc_scalar],
        "log_FG_AHR_10Vo": [False, "d", {}, nc_scalar],
        "log_FG_AHR_24V": [False, "d", {}, nc_scalar],
        "log_FG_AHR_24Vo": [False, "d", {}, nc_scalar],
        "log_FILEMGR": [False, "i", {}, nc_scalar],
        "log_FINISH": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_FINISH1": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_FINISH2": [False, "d", {}, nc_scalar],
        "log_FIX_MISSING_TIMEOUT": [False, "d", {}, nc_scalar],
        "log_FREEZE__depth": [
            False,
            "f",
            {"description": "Depth of observation", "units": "m"},
            ("log_FREEZE_info",),
        ],
        "log_FREEZE__temp": [
            False,
            "f",
            {"description": "Measured temperature", "units": "C"},
            ("log_FREEZE_info",),
        ],
        "log_FREEZE__Tf": [
            False,
            "f",
            {},
            ("log_FREEZE_info",),
        ],
        "log_FREEZE__ice": [
            False,
            "f",
            {"description": ""},
            ("log_FREEZE_info",),
        ],
        "log_FREEZE__call": [
            False,
            "f",
            {"description": ""},
            ("log_FREEZE_info",),
        ],
        "log_FREEZE__urgent": [
            False,
            "f",
            {"description": ""},
            ("log_FREEZE_info",),
        ],
        "log_GCHEAD": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_GLIDE_SLOPE": [False, "d", {}, nc_scalar],
        "log_GPS": [
            False,
            "c",
            {
                "description": "String reported in logfile for GPS fix (first surface position after dive)"
            },
            nc_scalar,
        ],
        "log_GPS1": [
            False,
            "c",
            {
                "description": "String reported in logfile for GPS1 fix (first surface position before dive)"
            },
            nc_scalar,
        ],
        "log_GPS2": [
            False,
            "c",
            {
                "description": "String reported in logfile for GPS2 fix (last surface position before dive)"
            },
            nc_scalar,
        ],
        "log_GPS_DEVICE": [False, "d", {}, nc_scalar],
        "log_HD_A": [
            False,
            "d",
            {
                "description": "Hydrodynamic lift factor for given hull shape (1/degrees of attack angle)"
            },
            nc_scalar,
        ],
        "log_HD_B": [
            False,
            "d",
            {
                "description": "Hydrodynamic drag factor for given hull shape (Pa^(-1/4))"
            },
            nc_scalar,
        ],
        "log_HD_C": [
            False,
            "d",
            {
                "description": "Hydrodynamic induced drag factor for given hull shape (1/degrees^2 of attack angle)"
            },
            nc_scalar,
        ],
        "log_HEADING": [False, "d", {}, nc_scalar],
        "log_HEAD_ERRBAND": [False, "d", {}, nc_scalar],
        "log_HEAPDBG": [False, "i", {}, nc_scalar],
        "log_HUMID": [False, "d", {}, nc_scalar],
        "log_ICE_FREEZE_MARGIN": [False, "d", {}, nc_scalar],
        "log_ID": [False, "i", {}, nc_scalar],
        "log_IMPLIED_C_PITCH": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_IMPLIED_C_VBD": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_INTERNAL_PRESSURE": [
            False,
            "c",
            {},
            nc_scalar,
        ],  # multi-valued string starting r7263
        "log_INT_PRESSURE_SLOPE": [False, "d", {}, nc_scalar],
        "log_INT_PRESSURE_YINT": [False, "d", {}, nc_scalar],
        "log_IRIDIUM_FIX": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_IRON": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_KALMAN_ARGS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_KALMAN_CONTROL": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_KALMAN_USE": [False, "i", {}, nc_scalar],
        "log_KALMAN_X": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_KALMAN_Y": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_KERMIT": [False, "i", {}, nc_scalar],
        "log_LOGGERDEVICE1": [False, "d", {}, nc_scalar],
        "log_LOGGERDEVICE2": [False, "d", {}, nc_scalar],
        "log_LOGGERDEVICE3": [False, "d", {}, nc_scalar],
        "log_LOGGERDEVICE4": [False, "d", {}, nc_scalar],
        "log_LOGGERS": [False, "d", {}, nc_scalar],
        "log_LOITER_D_NO_PUMP": [False, "d", {}, nc_scalar],
        "log_LOITER_DBDW": [False, "d", {}, nc_scalar],
        "log_LOITER_W_DBAND": [False, "d", {}, nc_scalar],
        "log_LOITER_D_TOP": [False, "d", {}, nc_scalar],
        "log_LOITER_D_BOTTOM": [False, "d", {}, nc_scalar],
        "log_LOITER_N_DIVE": [False, "d", {}, nc_scalar],
        "log_MAGCAL": [False, "c", {}, nc_scalar],
        "log_MAGERROR": [False, "d", {}, nc_scalar],
        "log_MASS": [False, "d", {}, nc_scalar],
        "log_MASS_COMP": [False, "d", {}, nc_scalar],
        "log_MAX_BUOY": [False, "d", {}, nc_scalar],
        #'log_MEM' : [False, 'd', {}, nc_scalar],
        "log_MEM": [
            False,
            "c",
            {},
            nc_scalar,
        ],  # Multi-valued string for version 67.00 and later
        "log_MEM0": [
            False,
            "c",
            {},
            nc_scalar,
        ],  # Multi-valued string for version 67.00 and later
        "log_MEM1": [
            False,
            "c",
            {},
            nc_scalar,
        ],  # Multi-valued string for version 67.00 and later
        "log_MEM2": [
            False,
            "c",
            {},
            nc_scalar,
        ],  # Multi-valued string for version 67.00 and later
        "log_MHEAD_RNG_PITCHd_Wd": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_MINV_10V": [False, "d", {}, nc_scalar],
        "log_MINV_24V": [False, "d", {}, nc_scalar],
        "log_MISSION": [False, "i", {}, nc_scalar],
        "log_MOTHERBOARD": [False, "i", {}, nc_scalar],
        "log_NAV__start_t": [
            False,
            "d",
            {
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Time of NAV start",
            },
            ("log_NAV_info",),
        ],
        "log_NAV__stop_t": [
            False,
            "d",
            {
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Time of NAV end",
            },
            ("log_NAV_info",),
        ],
        "log_NAV__start_d": [
            False,
            "f",
            {
                "units": "m",
                "description": "Depth at NAV start",
            },
            ("log_NAV_info",),
        ],
        "log_NAV__stop_d": [
            False,
            "f",
            {
                "units": "m",
                "description": "Depth at NAV end",
            },
            ("log_NAV_info",),
        ],
        "log_NAV__n_msgs": [
            False,
            "i",
            {
                "description": "Number of messages",
            },
            ("log_NAV_info",),
        ],
        "log_NAV_DEVICE": [False, "i", {}, nc_scalar],
        "log_NAV2_DEVICE": [False, "i", {}, nc_scalar],
        "log_NAV3_DEVICE": [False, "i", {}, nc_scalar],
        "log_NAV4_DEVICE": [False, "i", {}, nc_scalar],
        "log_NAV_MODE": [False, "i", {}, nc_scalar],
        "log_N_FILEKB": [False, "i", {}, nc_scalar],
        "log_N_GPS": [False, "i", {}, nc_scalar],
        "log_N_NOCOMM": [False, "i", {}, nc_scalar],
        "log_N_NOCOMM_RESUME": [False, "i", {}, nc_scalar],
        "log_N_NOSURFACE": [False, "i", {}, nc_scalar],
        "log_N_DIVES": [False, "i", {}, nc_scalar],
        "log_NET": [False, "c", {}, nc_scalar],
        "log_NETWORK_DEVICE": [False, "c", {}, nc_scalar],
        "log_NOCOMM_ACTION": [False, "i", {}, nc_scalar],
        "log_PHONE_DEVICE": [False, "d", {}, nc_scalar],
        "log_PHONE_SUPPLY": [False, "i", {}, nc_scalar],
        "log_OPTIONS": [False, "i", {}, nc_scalar],
        "log_PITCH_ADJ_DBAND": [False, "d", {}, nc_scalar],
        "log_PITCH_ADJ_GAIN": [False, "d", {}, nc_scalar],
        "log_PITCH_AD_RATE": [False, "d", {}, nc_scalar],
        "log_PITCH_CNV": [False, "d", {}, nc_scalar],
        "log_PITCH_DBAND": [False, "d", {}, nc_scalar],
        "log_PITCH_GAIN": [False, "d", {}, nc_scalar],
        "log_PITCH_GAIN_AUTO_DELTA": [False, "d", {}, nc_scalar],
        "log_PITCH_GAIN_AUTO_MAX": [False, "d", {}, nc_scalar],
        "log_PITCH_MAX": [False, "d", {}, nc_scalar],
        "log_PITCH_MAXERRORS": [False, "i", {}, nc_scalar],
        "log_PITCH_MIN": [False, "i", {}, nc_scalar],
        "log_PITCH_TIMEOUT": [False, "d", {}, nc_scalar],
        "log_PITCH_VBD_SHIFT": [False, "d", {}, nc_scalar],
        "log_PITCH_W_DBAND": [False, "d", {}, nc_scalar],
        "log_PITCH_W_GAIN": [False, "d", {}, nc_scalar],
        "log_PRESSURE_DEVICE": [False, "c", {}, nc_scalar],
        "log_PRESSURE_SLOPE": [False, "d", {}, nc_scalar],
        "log_PRESSURE_YINT": [False, "d", {}, nc_scalar],
        "log_PROTOCOL": [False, "i", {}, nc_scalar],
        "log_P_OVSHOOT": [False, "d", {}, nc_scalar],
        "log_P_OVSHOOT_WITHG": [False, "d", {}, nc_scalar],
        "log_RAFOS_CLK": [False, "d", {}, nc_scalar],
        "log_RAFOS_CORR_THRESH": [False, "d", {}, nc_scalar],
        "log_RAFOS_DEVICE": [False, "d", {}, nc_scalar],
        "log_RAFOS_FIX": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_RAFOS_HIT_WINDOW": [False, "d", {}, nc_scalar],
        "log_RAFOS_PEAK_OFFSET": [False, "d", {}, nc_scalar],
        "log_RAFOS_MMODEM": [False, "d", {}, nc_scalar],
        "log_RAFOS__src": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__listen_s": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__listen_ms": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__source_s": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__c1": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__c2": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__c3": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__c4": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__c5": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__c6": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__i1": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__i2": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__i3": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__i4": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__i5": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_RAFOS__i6": [
            False,
            "i",
            {},
            ("log_RAFOS_info",),
        ],
        "log_NETBOX": [False, "i", {}, nc_scalar],
        "log_RELAUNCH": [False, "i", {}, nc_scalar],
        "log_RECOV_CODE": [False, "c", {}, nc_scalar],
        "log_RESTART_TIME": [False, "c", {}, nc_scalar],
        "log_RHO": [
            False,
            "d",
            {
                "description": "Expected density at deepest point over the deployment",
                "units": "gram/cc",
            },
            nc_scalar,
        ],  # not kg/m^3!
        "log_ROLL_ADJ_DBAND": [False, "d", {}, nc_scalar],
        "log_ROLL_ADJ_GAIN": [False, "d", {}, nc_scalar],
        "log_ROLL_AD_RATE": [False, "d", {}, nc_scalar],
        "log_ROLL_CNV": [False, "d", {}, nc_scalar],
        "log_ROLL_DEG": [False, "d", {}, nc_scalar],
        "log_ROLL_MAX": [False, "i", {}, nc_scalar],
        "log_ROLL_MAXERRORS": [False, "i", {}, nc_scalar],
        "log_ROLL_MIN": [False, "i", {}, nc_scalar],
        "log_ROLL_TIMEOUT": [False, "d", {}, nc_scalar],
        "log_R_PORT_OVSHOOT": [False, "d", {}, nc_scalar],
        "log_R_STBD_OVSHOOT": [False, "d", {}, nc_scalar],
        "log_SDSIZE": [
            False,
            "c",
            {},
            nc_scalar,
        ],  # Multi-valued string for version 67.00 and later
        "log_SDFILEDIR": [
            False,
            "c",
            {},
            nc_scalar,
        ],  #  RevE - Number of files and directories on the sd card
        "log_SEABIRD_C_Z": [
            False,
            "d",
            {"description": "Conductivity zero frequency"},
            nc_scalar,
        ],
        "log_SEABIRD_C_G": [False, "d", {}, nc_scalar],
        "log_SEABIRD_C_H": [False, "d", {}, nc_scalar],
        "log_SEABIRD_C_I": [False, "d", {}, nc_scalar],
        "log_SEABIRD_C_J": [False, "d", {}, nc_scalar],
        "log_SEABIRD_T_G": [False, "d", {}, nc_scalar],
        "log_SEABIRD_T_H": [False, "d", {}, nc_scalar],
        "log_SEABIRD_T_I": [False, "d", {}, nc_scalar],
        "log_SEABIRD_T_J": [False, "d", {}, nc_scalar],
        "log_SENSORS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_SENSOR_MAMPS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_SENSOR_SECS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_SHORTING_PLUG": [False, "d", {}, nc_scalar],  # From Kongsberg firmware
        "log_SIM_PITCH": [False, "d", {}, nc_scalar],
        "log_SIM_W": [False, "d", {}, nc_scalar],
        "log_SMARTDEVICE1": [False, "d", {}, nc_scalar],
        "log_SMARTDEVICE2": [False, "d", {}, nc_scalar],
        "log_SMARTS": [False, "d", {}, nc_scalar],
        "log_SM_CC": [False, "d", {}, nc_scalar],
        "log_SM_CCo": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_SM_GC": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_SM_PING": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_SOUNDSPEED": [False, "d", {}, nc_scalar],
        "log_SPEED_FACTOR": [False, "d", {}, nc_scalar],
        "log_SPEED_LIMITS": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_STARTED": [False, None, {}, nc_scalar],  # ??
        "log_STROBE": [False, "i", {}, nc_scalar],
        "log_SURF": [False, "c", {}, nc_scalar],
        "log_SURFACE_URGENCY": [False, "i", {}, nc_scalar],
        "log_SURFACE_URGENCY_FORCE": [False, "i", {}, nc_scalar],
        "log_SURFACE_URGENCY_TRY": [False, "i", {}, nc_scalar],
        "log_SUPER": [False, "c", {}, nc_scalar],
        "log_TCM_PITCH_OFFSET": [False, "d", {}, nc_scalar],
        "log_TCM_ROLL_OFFSET": [False, "d", {}, nc_scalar],
        "log_TCM_TEMP": [False, "d", {}, nc_scalar],
        "log_TEMP": [
            False,
            "d",
            {"description": "Temperature inside pressure hull", "units": "C"},
            nc_scalar,
        ],
        "log_TGT_AUTO_DEFAULT": [False, "i", {}, nc_scalar],
        "log_TGT_DEFAULT_LAT": [False, "d", {}, nc_scalar],
        "log_TGT_DEFAULT_LON": [False, "d", {}, nc_scalar],
        "log_TGT_LATLONG": [False, "c", {}, nc_scalar],  # Multi-valued string
        "log_TGT_NAME": [False, "c", {}, nc_scalar],
        "log_TGT_RADIUS": [False, "d", {}, nc_scalar],
        "log_TT8_MAMPS": [
            False,
            "c",
            {},
            nc_scalar,
        ],  # Multi-valued string (2 values in later versions)
        "log_T_ABORT": [False, "d", {}, nc_scalar],
        "log_T_BOOST": [False, "d", {}, nc_scalar],
        "log_T_DIVE": [False, "d", {}, nc_scalar],
        "log_T_EPIRB": [False, "d", {}, nc_scalar],
        "log_T_GPS": [False, "d", {}, nc_scalar],
        "log_T_GPS_ALMANAC": [False, "d", {}, nc_scalar],
        "log_T_GPS_CHARGE": [False, "d", {}, nc_scalar],
        "log_T_LOITER": [False, "d", {}, nc_scalar],
        "log_T_SLOITER": [False, "d", {}, nc_scalar],
        "log_T_MISSION": [False, "d", {}, nc_scalar],
        "log_T_NO_W": [False, "d", {}, nc_scalar],
        "log_T_RSLEEP": [False, "d", {}, nc_scalar],
        "log_T_TURN": [False, "d", {}, nc_scalar],
        "log_T_TURN_SAMPINT": [False, "d", {}, nc_scalar],
        "log_T_WATCHDOG": [False, "d", {}, nc_scalar],
        "log_UNCOM_BLEED": [False, "i", {}, nc_scalar],
        "log_UPLOAD_DIVES_MAX": [False, "i", {}, nc_scalar],
        "log_USE_BATHY": [False, "i", {}, nc_scalar],
        "log_D_BATHY_OFFSET": [False, "d", {}, nc_scalar],
        "log_USE_ICE": [False, "i", {}, nc_scalar],
        "log_VBD_BLEED_AD_RATE": [False, "d", {}, nc_scalar],
        "log_VBD_CNV": [False, "d", {}, nc_scalar],
        "log_VBD_DBAND": [False, "d", {}, nc_scalar],
        "log_VBD_MAX": [False, "i", {}, nc_scalar],
        "log_VBD_MAXERRORS": [False, "i", {}, nc_scalar],
        "log_VBD_MIN": [False, "i", {}, nc_scalar],
        "log_VBD_PUMP_AD_RATE_APOGEE": [False, "d", {}, nc_scalar],
        "log_VBD_PUMP_AD_RATE_SURFACE": [False, "d", {}, nc_scalar],
        "log_VBD_TIMEOUT": [False, "d", {}, nc_scalar],
        "log_VBD_LP_IGNORE": [False, "d", {}, nc_scalar],
        "log_STOP_T": [False, "d", {}, nc_scalar],
        "log_W_ADJ_DBAND": [False, "d", {}, nc_scalar],
        "log_XPDR_DEVICE": [False, "d", {}, nc_scalar],
        "log_XPDR_INHIBIT": [False, "d", {}, nc_scalar],
        "log_XPDR_INT": [False, "d", {}, nc_scalar],
        "log_XPDR_PINGS": [False, "c", {}, nc_scalar],
        "log_XPDR_REP": [False, "d", {}, nc_scalar],
        "log_XPDR_VALID": [False, "d", {}, nc_scalar],
        "log_OSC": [False, "i", {}, nc_scalar],
        "log__CALLS": [False, "d", {}, nc_scalar],
        "log__SM_ANGLEo": [False, "d", {}, nc_scalar],
        "log__SM_DEPTHo": [False, "d", {}, nc_scalar],
        "log__XMS_NAKs": [False, "d", {}, nc_scalar],
        "log__XMS_TOUTs": [False, "d", {}, nc_scalar],
        # These are found on iRobot versions of the software
        "log_T_BOOST_BLACKOUT": [False, "d", {}, nc_scalar],
        "log_LENGTH": [False, "d", {}, nc_scalar],
        "log_DIRECT_CONTROL": [False, "d", {}, nc_scalar],
        "log_ROLL_GAIN_P": [False, "d", {}, nc_scalar],
        "log_EBE_ENABLE": [False, "d", {}, nc_scalar],
        "log_GC_WINDOW": [False, "d", {}, nc_scalar],
        "log_GC_LAST_COLLECTION": [False, "d", {}, nc_scalar],
        "log_EXEC_P": [False, "d", {}, nc_scalar],
        "log_EXEC_DT": [False, "d", {}, nc_scalar],
        "log_EXEC_T": [False, "d", {}, nc_scalar],
        "log_EXEC_N": [False, "d", {}, nc_scalar],
        "log_PING": [False, "c", {}, nc_scalar],
        "log_SIMULATE": [False, "i", {}, nc_scalar],
        "log_NET_PING": [False, "c", {}, nc_scalar],  # multi-valued string in gc table
        "log_TS": [False, "c", {}, nc_scalar],  # multi-valued string in gc table
        "log_TE": [False, "c", {}, nc_scalar],  # multi-valued string in gc table
        "log_MODEM__src": [
            False,
            "f",
            {},
            ("log_MODEM_info",),
        ],
        "log_MODEM__arr_s": [
            False,
            "f",
            {},
            ("log_MODEM_info",),
        ],
        "log_MODEM__arr_ms": [
            False,
            "f",
            {},
            ("log_MODEM_info",),
        ],
        "log_MODEM__srcLa": [
            False,
            "f",
            {},
            ("log_MODEM_info",),
        ],
        "log_MODEM__srcLo": [
            False,
            "f",
            {},
            ("log_MODEM_info",),
        ],
        "log_MODEM__trav": [
            False,
            "f",
            {},
            ("log_MODEM_info",),
        ],
        "log_MODEM__rng": [
            False,
            "f",
            {},
            ("log_MODEM_info",),
        ],
        "log_MODEM__corr1": [
            False,
            "f",
            {},
            ("log_MODEM_info",),
        ],
        "log_MODEM_MSG__msg": [
            False,
            "c",
            {"description": "Messages direct from the micro modem"},
            ("log_MODEM_MSG_info",),
        ],
        "log_MODEM_NOISE__t": [
            False,
            "d",
            {
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Time of noise report",
            },
            ("log_MODEM_NOISE_info",),
        ],
        "log_MODEM_NOISE__noise": [
            False,
            "f",
            {"description": "Reported noise"},
            ("log_MODEM_NOISE_info",),
        ],
        "log_CKPRE": [False, "i", {}, nc_scalar],
        "log_CKPOST": [False, "c", {}, nc_scalar],  # multi-valued string
        "log_MAMPS": [False, "c", {}, nc_scalar],  # multi-valued string
        "log_MAMPS10": [False, "f", {}, nc_scalar],
        "log_MAMPS15": [False, "c", {}, nc_scalar],  # multi-valued string
        "log_MAMPS24": [False, "f", {}, nc_scalar],
        "log_VOC": [False, "d", {}, nc_scalar],
        # $STATE line entries (gc_state)
        "gc_state_secs": [
            True,
            "d",
            {
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Start of STATE time in GMT epoch format",
            },
            (nc_gc_state_info,),
        ],
        "gc_state_state": [
            True,
            "i",
            {"description": "Name of the GC state"},
            (nc_gc_state_info,),
        ],
        "gc_state_eop_code": [
            True,
            "i",
            {"description": "GC states end of phase (EOP) code"},
            (nc_gc_state_info,),
        ],
        # GC table messages
        "gc_msg_NEWHEAD_secs": [
            True,
            "d",
            {
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Start of NEWHEAD time in GMT epoch format",
            },
            (f"{nc_gc_msg_prefix}NEWHEAD_info",),
        ],
        "gc_msg_NEWHEAD_depth": [
            "f",
            "d",
            {
                "standard_name": "depth",
                "positive": "down",
                "units": "meters",
                "description": "Measured vertical distance below the surface",
            },
            (f"{nc_gc_msg_prefix}NEWHEAD_info",),
        ],
        "gc_msg_NEWHEAD_heading": [
            "f",
            "d",
            {
                "description": "New vehicle heading (true)",
                "units": "decimal degrees",
            },
            (f"{nc_gc_msg_prefix}NEWHEAD_info",),
        ],
        # $GC line entries (gc_event)
        "gc_st_secs": [
            True,
            "d",
            {
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Start of GC time in GMT epoch format",
            },
            (nc_gc_event_info,),
        ],
        "gc_pitch_ctl": [False, "d", {"units": "cm"}, (nc_gc_event_info,)],
        "gc_vbd_ctl": [False, "d", {"units": "cm"}, (nc_gc_event_info,)],
        "gc_roll_ctl": [False, "d", {"units": "cm"}, (nc_gc_event_info,)],
        "gc_depth": [False, "d", {"units": "meters"}, (nc_gc_event_info,)],
        "gc_ob_vertv": [False, "d", {"units": "cm/s"}, (nc_gc_event_info,)],
        "gc_data_pts": [False, "i", {"units": "1"}, (nc_gc_event_info,)],
        "gc_end_secs": [
            False,
            "d",
            {
                "units": "seconds  since 1970-1-1 00:00:00",
                "description": "End of GC time in GMT epoch format",
            },
            (nc_gc_event_info,),
        ],
        "gc_pitch_secs": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Elapsed seconds since start of this pitch change",
            },
            (nc_gc_event_info,),
        ],
        "gc_roll_secs": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Elapsed seconds since start of this roll change",
            },
            (nc_gc_event_info,),
        ],
        "gc_vbd_secs": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Elapsed seconds since start of this VBD change",
            },
            (nc_gc_event_info,),
        ],
        "gc_vbd_st": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Time since st_secs for start of VBD move",
            },
            (nc_gc_event_info,),
        ],
        "gc_pitch_st": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Time since st_secs for start of pitch move",
            },
            (nc_gc_event_info,),
        ],
        "gc_roll_st": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Time since st_secs for start of roll move",
            },
            (nc_gc_event_info,),
        ],
        "gc_vbd_start_time": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Start of VBD motor move time in GMT epoch format",
                "_FillValue": nc_nan,
            },
            (nc_gc_event_info,),
        ],
        "gc_pitch_start_time": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Start of pitch motor move time in GMT epoch format",
                "_FillValue": nc_nan,
            },
            (nc_gc_event_info,),
        ],
        "gc_roll_start_time": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Start of roll motor move time in GMT epoch format",
                "_FillValue": nc_nan,
            },
            (nc_gc_event_info,),
        ],
        "gc_vbd_end_time": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "End of VBD motor move time in GMT epoch format",
                "_FillValue": nc_nan,
            },
            (nc_gc_event_info,),
        ],
        "gc_pitch_end_time": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "End of pitch motor move time in GMT epoch format",
                "_FillValue": nc_nan,
            },
            (nc_gc_event_info,),
        ],
        "gc_roll_end_time": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "End of roll motor move time in GMT epoch format",
                "_FillValue": nc_nan,
            },
            (nc_gc_event_info,),
        ],
        "gc_vbd_i": [False, "d", {"units": "A"}, (nc_gc_event_info,)],
        "gc_gcphase": [
            False,
            "i",
            {
                "flag_values": [1, 2, 3, 4, 5, 6],
                "flag_meanings": "pitch vbd active_roll passive_roll roll_back passive",
            },
            (nc_gc_event_info,),
        ],
        "gc_flags": [
            False,
            "i",
            {
                "flag_values": [1, 2, 3, 4, 5, 6],
                "flag_meanings": "pitch vbd active_roll passive_roll roll_back passive",
            },
            (nc_gc_event_info,),
        ],
        "gc_pitch_i": [False, "d", {"units": "A"}, (nc_gc_event_info,)],
        "gc_roll_i": [False, "d", {"units": "A"}, (nc_gc_event_info,)],
        "gc_pitch_ad": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_roll_ad": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_pitch_ad_start": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_roll_ad_start": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_vbd_ad": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_vbd_ad_start": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_vbd_pot1_ad": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_vbd_pot2_ad": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_vbd_pot1_ad_start": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_vbd_pot2_ad_start": [False, "d", {"units": "1"}, (nc_gc_event_info,)],
        "gc_pitch_retries": [False, "i", {"units": "1"}, (nc_gc_event_info,)],
        "gc_pitch_errors": [False, "i", {"units": "1"}, (nc_gc_event_info,)],
        "gc_roll_retries": [False, "i", {"units": "1"}, (nc_gc_event_info,)],
        "gc_roll_errors": [False, "i", {"units": "1"}, (nc_gc_event_info,)],
        "gc_vbd_retries": [False, "i", {"units": "1"}, (nc_gc_event_info,)],
        "gc_vbd_errors": [False, "i", {"units": "1"}, (nc_gc_event_info,)],
        "gc_pitch_volts": [False, "d", {"units": "V"}, (nc_gc_event_info,)],
        "gc_roll_volts": [False, "d", {"units": "V"}, (nc_gc_event_info,)],
        "gc_vbd_volts": [False, "d", {"units": "V"}, (nc_gc_event_info,)],
        "gc_int_press": [
            False,
            "d",
            {"description": "Internal pressure", "units": "psia"},
            (nc_gc_event_info,),
        ],
        "gc_humidity": [
            False,
            "d",
            {"description": "Internal relative humidity", "units": "percent"},
            (nc_gc_event_info,),
        ],
        "gc_intP": [
            False,
            "d",
            {"description": "Internal pressure", "units": "psia"},
            (nc_gc_event_info,),
        ],
        "gc_humid": [
            False,
            "d",
            {"description": "Internal relative humidity", "units": "percent"},
            (nc_gc_event_info,),
        ],
        # Turn controller
        "log_TS_HEAD": [False, "c", {}, nc_scalar],  # multi-valued string
        "log_TE_HEAD": [False, "c", {}, nc_scalar],  # multi-valued string
        f"{nc_tc_prefix}start_time": [
            False,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Start of TC event in GMT epoch format",
            },
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}end_time": [
            False,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "End of TC event in GMT epoch format",
            },
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}start_time_est": [
            False,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Estimated start of TC event in GMT epoch format",
            },
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}p": [
            False,
            "d",
            {"description": "Difference in heading from desired", "units": "degrees"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}d": [
            False,
            "d",
            {"description": "Rate of heading error change", "units": "degrees/second"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}i": [
            False,
            "d",
            {"description": "Integral of heading error", "units": "degree seconds"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}rollDeg": [
            False,
            "d",
            {"description": "Heading correction", "units": "degrees"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}rollAD": [
            False,
            "d",
            {"description": "Starting AD position", "units": "AD counts"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}targetAD": [
            False,
            "d",
            {"description": "Target AD for turn", "units": "AD counts"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}sec": [
            False,
            "d",
            {"description": "Duration of the turn event", "units": "seconds"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}destAD": [
            False,
            "d",
            {"description": "Desitination AD for turn event", "units": "AD counts"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}endAD": [
            False,
            "d",
            {"description": "Final AD for the turn event", "units": "AD counts"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}amps": [
            False,
            "d",
            {"description": "Average current for the turn event", "units": "amps"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}maxAmps": [
            False,
            "d",
            {"description": "Max current for the turn event", "units": "amps"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}volts": [
            False,
            "d",
            {"description": "Measured voltage for the turn event", "units": "amps"},
            (nc_tc_event_info,),
        ],
        f"{nc_tc_prefix}errors": [
            False,
            "d",
            {"description": "Errors for the turn event"},
            (nc_tc_event_info,),
        ],
        # Columns in the engineering file
        "eng_elaps_t_0000": [
            False,
            "d",
            {
                "standard_name": "time",
                "units": "seconds",
                "description": "Elapsed seconds since start of mission",
            },
            (nc_sg_data_info,),
        ],
        "eng_elaps_t": [
            False,
            "d",
            {
                "standard_name": "time",
                "units": "seconds",
                "description": "Elapsed seconds since start of dive",
            },
            (nc_sg_data_info,),
        ],
        "eng_rec": [False, "d", {}, (nc_sg_data_info,)],
        "eng_GC_phase": [
            False,
            "d",
            {
                "flag_values": [1, 2, 3, 4, 5, 6],
                "flag_meanings": "pitch vbd active_roll passive_roll roll_back passive",
            },
            (nc_sg_data_info,),
        ],
        "eng_GC_state": [
            False,
            "i",
            {
                # "flag_values": [1, 2, 3, 4, 5, 6],
                # "flag_meanings": "pitch vbd active_roll passive_roll roll_back passive",
                "description": "Motor status byte",
            },
            (nc_sg_data_info,),
        ],
        "eng_GC_flags": [
            False,
            "d",
            {
                "flag_values": [1, 2, 3, 4, 5, 6],
                "flag_meanings": "pitch vbd active_roll passive_roll roll_back passive",
            },
            (nc_sg_data_info,),
        ],
        "eng_pressure": [
            False,
            "d",
            {"description": "Reported pressure", "units": "psia"},
            (nc_sg_data_info,),
        ],
        "eng_press_counts": [
            False,
            "d",
            {"description": "Pressure sensor AD counts"},
            (nc_sg_data_info,),
        ],
        "eng_depth": [
            False,
            "d",
            {
                "standard_name": "depth",
                "positive": "down",
                "units": "cm",
                "description": "Measured vertical distance below the surface",
            },
            (nc_sg_data_info,),
        ],
        "eng_head": [
            "f",
            "d",
            {"description": "Vehicle heading (magnetic)", "units": "degrees"},
            (nc_sg_data_info,),
        ],
        "eng_pitchAng": [
            "f",
            "d",
            {"description": "Vehicle pitch", "units": "degrees"},
            (nc_sg_data_info,),
        ],
        "eng_rollAng": [
            False,
            "d",
            {"description": "Vehicle roll", "units": "degrees"},
            (nc_sg_data_info,),
        ],
        "eng_pitchCtl": [False, "d", {}, (nc_sg_data_info,)],
        "eng_rollCtl": [False, "d", {}, (nc_sg_data_info,)],
        "eng_vbdCC": [False, "d", {}, (nc_sg_data_info,)],
        "eng_volt1": [False, "d", {}, (nc_sg_data_info,)],
        "eng_volt2": [False, "d", {}, (nc_sg_data_info,)],
        "eng_curr1": [False, "d", {}, (nc_sg_data_info,)],
        "eng_curr2": [False, "d", {}, (nc_sg_data_info,)],
        # Declaration of eng-based CT freq (normal unpumped sbect and SailCT)
        # are in Sensors/sbect_ext.py, as are scicon unpumped CT freq vars.
        # gpctd (pumped sbect) variables are declared in Sensors/payload_ext.py
        # Other eng_ variables are declared in various sensor and logger extensions
        # and created for any cnf sensor definition
        # Per-profile derived results
        # QC status variables and vectors
        "reviewed": [
            False,
            "i",
            {
                "description": "Whether a scientist has reviewed and approved this profile"
            },
            nc_scalar,
        ],
        "directives": [
            False,
            "c",
            {
                "description": "The control directives supplied by the scientist for this profile"
            },
            nc_scalar,
        ],
        # These are written only if they are true
        "skipped_profile": [
            False,
            "i",
            {
                "description": "Whether a scientist decided to skip processing this profile"
            },
            nc_scalar,
        ],
        "processing_error": [
            False,
            "i",
            {
                "description": "Whether an error was encountered while processing this profile"
            },
            nc_scalar,
        ],
        "test_tank_dive": [
            False,
            "i",
            {"description": "Whether this is a test tank dive"},
            nc_scalar,
        ],
        "deck_dive": [
            False,
            "i",
            {"description": "Whether this is a deck dive"},
            nc_scalar,
        ],
        # In spite of their prefix, access as results_d['log_gps_lat']
        "log_gps_lat": [
            False,
            "d",
            {
                "standard_name": "latitude",
                "units": "degrees_north",
                "description": "GPS latitudes",
            },
            (nc_gps_info_info,),
        ],
        "log_gps_lon": [
            False,
            "d",
            {
                "standard_name": "longitude",
                "units": "degrees_east",
                "description": "GPS longitudes",
            },
            (nc_gps_info_info,),
        ],
        "log_gps_time": [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "GPS times in GMT epoch format",
            },
            (nc_gps_info_info,),
        ],
        "log_gps_first_fix_time": [
            False,
            "d",
            {"units": "seconds", "description": "Time to first fix"},
            (nc_gps_info_info,),
        ],
        "log_gps_final_fix_time": [
            False,
            "d",
            {"units": "seconds", "description": "Time to fix"},
            (nc_gps_info_info,),
        ],
        "log_gps_hdop": [
            False,
            "d",
            {"description": "Horizontal Dilution Of Precision"},
            (nc_gps_info_info,),
        ],
        "log_gps_magvar": [
            False,
            "d",
            {
                "units": "degrees",
                "description": "Magnetic variance (degrees, positive E)",
            },
            (nc_gps_info_info,),
        ],
        "log_gps_driftspeed": [
            False,
            "d",
            {"units": "knots", "description": "Estimated surface drift speed"},
            (nc_gps_info_info,),
        ],
        "log_gps_driftheading": [
            False,
            "d",
            {"units": "degrees true", "description": "Estimated drift direction"},
            (nc_gps_info_info,),
        ],
        "log_gps_n_satellites": [
            False,
            "d",
            {"description": "Number of satellites contributing to the final fix"},
            (nc_gps_info_info,),
        ],
        "log_gps_hpe": [
            False,
            "d",
            {"units": "meters", "description": "Horizontal position error"},
            (nc_gps_info_info,),
        ],
        "log_gps_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the GPS1 information",
            },
            (nc_gps_info_info,),
        ],
        "magnetic_variation": [
            False,
            "d",
            {"description": "The magnetic variance from true north (degrees)"},
            nc_scalar,
        ],
        "avg_latitude": [
            False,
            "d",
            {
                "units": "degrees_north",
                "description": "The average latitude of the dive",
            },
            nc_scalar,
        ],
        "avg_longitude": [
            False,
            "d",
            {
                "units": "degrees_east",
                "description": "The average longitude of the dive",
            },
            nc_scalar,
        ],
        nc_sg_time_var: [
            True,
            "d",
            {
                "standard_name": "time",
                "axis": "T",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Time of the [P] in GMT epoch format",
            },
            (nc_sg_data_info,),
        ],
        "pressure": [
            "f",
            "d",
            {
                "units": "dbar",
                "description": "Uncorrected sea-water pressure at pressure sensor",
            },
            (nc_sg_data_info,),
        ],
        "depth": [
            "f",
            "d",
            {
                "standard_name": "depth",
                "axis": "Z",
                "units": "meters",
                "positive": "down",
                "description": "Depth below the surface, corrected for average latitude",
            },
            (nc_sg_data_info,),
        ],
        "GPS1_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the GPS1 information",
            },
            nc_scalar,
        ],
        "GPS2_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the GPS2 information",
            },
            nc_scalar,
        ],
        "GPSE_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the final GPS information",
            },
            nc_scalar,
        ],
        "start_of_climb_time": [
            False,
            "d",
            {
                "units": "seconds",
                "description": "Elapsed seconds after dive start when second (positive) apogee pump starts",
            },
            nc_scalar,
        ],
        # CT values (missing values are marked in parallel _qc variable as QC_MISSING)
        nc_ctd_time_var: [
            True,
            "d",
            {
                "standard_name": "time",
                "axis": "T",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Time of CTD [P] in GMT epoch format",
            },
            (nc_ctd_results_info,),
        ],
        "ctd_depth": [
            "f",
            "d",
            {
                "standard_name": "depth",
                "axis": "Z",
                "units": "meters",
                "positive": "down",
                "description": "CTD thermistor depth corrected for average latitude",
            },
            (nc_ctd_results_info,),
        ],
        "ctd_pressure": [
            "f",
            "d",
            {
                "standard_name": "sea_water_pressure",
                "units": "dbar",
                "description": "Pressure at CTD thermistor",
            },
            (nc_ctd_results_info,),
        ],
        "ctd_pressure_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust pressure - legato only",
            },
            (nc_ctd_results_info,),
        ],
        # TODO: parse the field and test in MMP and MMT if all are included...
        "temperature_raw": [
            "f",
            "d",
            {
                "units": "degrees_Celsius",
                "description": "Uncorrected temperature (in situ)",
            },
            (nc_ctd_results_info,),
        ],
        "conductivity_raw": [
            "f",
            "d",
            {"units": "S/m", "description": "Uncorrected conductivity"},
            (nc_ctd_results_info,),
        ],
        "salinity_raw": [
            "f",
            "d",
            {
                "units": "PSU",
                "description": "Uncorrected salinity derived from temperature_raw and conductivity_raw (PSU)",
            },
            (nc_ctd_results_info,),
        ],
        "temperature_raw_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each raw temperature value",
            },
            (nc_ctd_results_info,),
        ],
        "conductivity_raw_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each raw conductivity value",
            },
            (nc_ctd_results_info,),
        ],
        "salinity_raw_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each raw salinity value",
            },
            (nc_ctd_results_info,),
        ],
        # CT adjusted values (missing values are marked in parallel _qc variable as QC_MISSING)
        "temperature": [
            "f",
            "d",
            {
                "standard_name": "sea_water_temperature",
                "units": "degrees_Celsius",
                "description": "Termperature (in situ) corrected for thermistor first-order lag",
            },
            (nc_ctd_results_info,),
        ],
        "conductivity": [
            "f",
            "d",
            {
                "standard_name": "sea_water_electrical_conductivity",
                "units": "S/m",
                "description": "Conductivity corrected for anomalies",
            },
            (nc_ctd_results_info,),
        ],
        "salinity": [
            "f",
            "d",
            {
                "standard_name": "sea_water_salinity",
                "units": "PSU",
                "description": "Salinity corrected for thermal-inertia effects (PSU)",
            },
            (nc_ctd_results_info,),
        ],
        "conservative_temperature": [
            "f",
            "d",
            {
                "units": "degrees_Celsius",
                "description": "Conservative termperature per TEOS-10",
            },
            (nc_ctd_results_info,),
        ],
        "absolute_salinity": [
            "f",
            "d",
            {"units": "g/kg", "description": "Absolute salinity per TEOS-10"},
            (nc_ctd_results_info,),
        ],
        "gsw_sigma0": [
            "f",
            "d",
            {
                "standard_name": "sea_water_sigma_theta",
                "ref_pressure": "0",
                "units": "kg/m^3",
            },
            (nc_ctd_results_info,),
        ],
        "gsw_sigma3": [
            "f",
            "d",
            {
                "standard_name": "sea_water_sigma_theta",
                "ref_pressure": "3000",
                "units": "kg/m^3",
            },
            (nc_ctd_results_info,),
        ],
        "gsw_sigma4": [
            "f",
            "d",
            {
                "standard_name": "sea_water_sigma_theta",
                "ref_pressure": "4000",
                "units": "kg/m^3",
            },
            (nc_ctd_results_info,),
        ],
        "temperature_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each corrected temperature value",
            },
            (nc_ctd_results_info,),
        ],
        "conductivity_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each corrected conductivity value",
            },
            (nc_ctd_results_info,),
        ],
        "salinity_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each corrected salinity value",
            },
            (nc_ctd_results_info,),
        ],
        "CTD_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the corrected CTD values",
            },
            nc_scalar,
        ],
        # Derived seawater properties from salinity
        "density": [
            False,
            "d",
            {
                "standard_name": "sea_water_density",
                "ref_pressure": "0",
                "units": "g/m^3",
                "description": "Sea water potential density",
            },
            (nc_ctd_results_info,),
        ],
        "density_insitu": [
            False,
            "d",
            {
                "units": "g/m^3",
                "description": "Sea water in-situ density based on pressure",
            },
            (nc_ctd_results_info,),
        ],
        "sigma_t": [
            "f",
            "d",
            {
                "standard_name": "sea_water_sigma_t",
                "ref_pressure": "0",
                "description": "Sigma based on density",
                "units": "g/m^3",
            },
            (nc_ctd_results_info,),
        ],
        "theta": [
            False,
            "d",
            {
                "standard_name": "sea_water_potential_temperature",
                "units": "degrees_Celsius",
                "description": "Potential temperature based on corrected salinity",
            },
            (nc_ctd_results_info,),
        ],
        "sigma_theta": [
            False,
            "d",
            {
                "standard_name": "sea_water_sigma_theta",
                "ref_pressure": "0",
                "units": "kg/m^3",
            },
            (nc_ctd_results_info,),
        ],
        "sigma3": [
            False,
            "d",
            {
                "standard_name": "sea_water_sigma_theta",
                "ref_pressure": "3000",
                "units": "kg/m^3",
            },
            (nc_ctd_results_info,),
        ],
        "sigma4": [
            False,
            "d",
            {
                "standard_name": "sea_water_sigma_theta",
                "ref_pressure": "4000",
                "units": "kg/m^3",
            },
            (nc_ctd_results_info,),
        ],
        "sound_velocity": [
            "f",
            "d",
            {
                "standard_name": "speed_of_sound_in_sea_water",
                "description": "Sound velocity",
                "units": "m/s",
            },
            (nc_ctd_results_info,),
        ],
        # Vehicle speed and glide angle data
        "hdm_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether corrected temperatures, salinities, and velocities from the hydrodynamic model converged on a consistent solution",
            },
            nc_scalar,
        ],
        "buoyancy": [
            False,
            "d",
            {
                "units": "g",
                "description": "Buoyancy of vehicle, corrected for compression effects",
            },
            (nc_ctd_results_info,),
        ],
        # Based on eng data (pitch, depth) only
        "speed_gsm": [
            "f",
            "d",
            {"description": "Vehicle speed based on gsm", "units": "cm/s"},
            (nc_ctd_results_info,),
        ],
        "glide_angle_gsm": [
            False,
            "d",
            {"description": "Glide angle based on gsm", "units": "degrees"},
            (nc_ctd_results_info,),
        ],
        "horz_speed_gsm": [
            "f",
            "d",
            {"description": "Vehicle horizontal speed based on gsm", "units": "cm/s"},
            (nc_ctd_results_info,),
        ],
        "vert_speed_gsm": [
            "f",
            "d",
            {"description": "Vehicle vertical speed based on gsm", "units": "cm/s"},
            (nc_ctd_results_info,),
        ],
        "flight_avg_speed_east_gsm": [
            False,
            "d",
            {
                "units": "m/s",
                "description": "Eastward component of flight average speed based on gsm",
            },
            nc_scalar,
        ],
        "flight_avg_speed_north_gsm": [
            False,
            "d",
            {
                "units": "m/s",
                "description": "Northward component of flight average speed based on gsm",
            },
            nc_scalar,
        ],
        "north_displacement_gsm": [
            False,
            "d",
            {"description": "Northward displacement from gsm", "units": "meters"},
            (nc_ctd_results_info,),
        ],
        "east_displacement_gsm": [
            False,
            "d",
            {"description": "Eastward displacement from gsm", "units": "meters"},
            (nc_ctd_results_info,),
        ],
        "speed": [
            "f",
            "d",
            {"description": "Vehicle speed based on hdm", "units": "cm/s"},
            (nc_ctd_results_info,),
        ],
        "glide_angle": [
            False,
            "d",
            {"description": "Glide angle based on hdm", "units": "degrees"},
            (nc_ctd_results_info,),
        ],
        "horz_speed": [
            "f",
            "d",
            {"description": "Vehicle horizontal speed based on hdm", "units": "cm/s"},
            (nc_ctd_results_info,),
        ],
        "vert_speed": [
            "f",
            "d",
            {"description": "Vehicle vertical speed based on hdm", "units": "cm/s"},
            (nc_ctd_results_info,),
        ],
        "speed_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust each hdm speed value",
            },
            (nc_ctd_results_info,),
        ],
        "flight_avg_speed_east": [
            False,
            "d",
            {
                "units": "m/s",
                "description": "Eastward component of flight average speed based on hdm",
            },
            nc_scalar,
        ],
        "flight_avg_speed_north": [
            False,
            "d",
            {
                "units": "m/s",
                "description": "Northward component of flight average speed based on hdm",
            },
            nc_scalar,
        ],
        "north_displacement": [
            False,
            "d",
            {"description": "Northward displacement from hdm", "units": "meters"},
            (nc_ctd_results_info,),
        ],
        "east_displacement": [
            False,
            "d",
            {"description": "Eastward displacement from hdm", "units": "meters"},
            (nc_ctd_results_info,),
        ],
        # depth-average current
        # NOTE: these are scalar in a profile but a vector in mission_timeseries, etc.
        "depth_avg_curr_east_gsm": [
            False,
            "d",
            {
                "units": "m/s",
                "description": "Eastward component of depth-average current based on gsm",
            },
            nc_scalar,
        ],
        "depth_avg_curr_north_gsm": [
            False,
            "d",
            {
                "units": "m/s",
                "description": "Northward component of depth-average current based on gsm",
            },
            nc_scalar,
        ],
        "depth_avg_curr_east": [
            "f",
            "d",
            {
                "standard_name": "eastward_sea_water_velocity",
                "units": "m/s",
                "description": "Eastward component of the [D] depth-average current based on hdm",
            },
            nc_scalar,
        ],
        "depth_avg_curr_north": [
            "f",
            "d",
            {
                "standard_name": "northward_sea_water_velocity",
                "units": "m/s",
                "description": "Northward component of the [D] depth-average current based on hdm",
            },
            nc_scalar,
        ],
        "depth_avg_curr_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the [D] depth-average current values and displacements",
            },
            nc_scalar,
        ],
        "depth_avg_curr_error": [
            False,
            "d",
            {
                "units": "m/s",
                "description": "Expected error of depth-average current from GPS",
            },
            nc_scalar,
        ],
        "delta_time_s": [
            False,
            "d",
            {"units": "s", "description": "Difference between sample times"},
            (nc_ctd_results_info,),
        ],
        "polar_heading": [
            False,
            "d",
            {"units": "radians", "description": "Vehicle heading from the east"},
            (nc_ctd_results_info,),
        ],
        "GPS_east_displacement_m": [
            False,
            "d",
            {
                "units": "m",
                "description": "Total vehicle eastward displacement based on GPS2 and GPSE locations",
            },
            nc_scalar,
        ],
        "GPS_north_displacement_m": [
            False,
            "d",
            {
                "units": "m",
                "description": "Total vehicle northward displacement based on GPS2 and GPSE locations",
            },
            nc_scalar,
        ],
        "total_flight_time_s": [
            False,
            "d",
            {
                "units": "s",
                "description": "Total flight time seconds including surface maneuver drift time",
            },
            nc_scalar,
        ],
        "latitude_gsm": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "units": "degrees_north",
                "description": "Latitude of the [P] based on gsm DAC",
            },
            (nc_ctd_results_info,),
        ],
        "longitude_gsm": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "units": "degrees_east",
                "description": "Longitude of the [P] based on gsm DAC",
            },
            (nc_ctd_results_info,),
        ],
        "latitude": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "latitude",
                "axis": "Y",
                "units": "degrees_north",
                "description": "Latitude of the [P] based on hdm DAC",
            },
            (nc_ctd_results_info,),
        ],
        "longitude": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "longitude",
                "axis": "X",
                "units": "degrees_east",
                "description": "Longitude of the [P] based on hdm DAC",
            },
            (nc_ctd_results_info,),
        ],
        "latlong_qc": [
            True,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the [D] estimated latitude and longitude estimates",
            },
            nc_scalar,
        ],
        # surface drift current
        "surface_curr_east": [
            False,
            "d",
            {
                "standard_name": "surface_eastward_sea_water_velocity",
                "units": "cm/s",
                "description": "Eastward component of surface current",
            },
            nc_scalar,
        ],
        "surface_curr_north": [
            False,
            "d",
            {
                "standard_name": "surface_northward_sea_water_velocity",
                "units": "cm/s",
                "description": "Northward component of surface current",
            },
            nc_scalar,
        ],
        "surface_curr_qc": [
            False,
            QC.nc_qc_type,
            {
                "units": "qc_flag",
                "description": "Whether to trust the surface current values",
            },
            nc_scalar,
        ],
        "surface_curr_error": [
            False,
            "d",
            {
                "units": "m/s",
                "description": "Expected error of surface drift current from GPS",
            },
            nc_scalar,
        ],
        "dissolved_oxygen_sat": [
            "f",
            "d",
            {
                "units": "micromoles/kg",
                "description": "Calculated saturation value for oxygen given measured presure and corrected temperature, and salinity",
            },
            (nc_ctd_results_info,),
        ],
        # This variable is an alias to dive_number below; required for CF compliance.
        "trajectory": [
            False,
            "i",
            {
                "description": "Dive number for observations",
                "long_name": "Unique identifier for each feature instance",
                "cf_role": "trajectory_id",
            },
            (nc_trajectory_info,),
        ],
        # Variables used in make_mission_timeseries() make_mission_profiles()
        # These deliberately have nc_scalar for mdp_dim_info.  This is calculated and set by MMT and MMP
        "dive_number": [
            True,
            "i",
            {"description": "Dive number for given observation"},
            nc_scalar,
        ],
        # make_mission_profile()
        # over all the dives collected (nc_dim_dives)
        "GPS2_lat": ["f", "d", {}, nc_scalar],
        "GPS2_lon": ["f", "d", {}, nc_scalar],
        "GPS2_time": ["f", "d", {}, nc_scalar],
        "GPSEND_lat": ["f", "d", {}, nc_scalar],
        "GPSEND_lon": ["f", "d", {}, nc_scalar],
        "GPSEND_time": ["f", "d", {}, nc_scalar],
        "mean_latitude": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "longitude",
                "units": "degrees_north",
                "description": "Mean latitude of the [D]",
            },
            nc_scalar,
        ],
        "mean_longitude": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "latitude",
                "units": "degrees_east",
                "description": "Mean longitude of the [D]",
            },
            nc_scalar,
        ],
        "mean_time": [
            True,
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Mean time of the [D] in GMT epoch format",
            },
            nc_scalar,
        ],
        "deepest_sample_time": [
            True,
            "d",
            {"description": "Time for the deepest sample in the given dive"},
            nc_scalar,
        ],
        "obs_bin": [
            "f",
            "d",
            {"description": "Number of CT observations for this bin"},
            nc_scalar,
        ],
        # Mission profile variables
        "year": [
            True,
            "i",
            {"_FillValue": -1, "description": "Year of the [D]"},
            nc_scalar,
        ],
        "month": [
            True,
            "i",
            {
                "_FillValue": -1,
                "description": "Month of the year of the [D] - one based",
            },
            nc_scalar,
        ],
        "date": [
            True,
            "i",
            {
                "_FillValue": -1,
                "description": "Month date of the month of the [D] - one based",
            },
            nc_scalar,
        ],
        "hour": [
            True,
            "i",
            {
                "_FillValue": -1,
                "description": "Decimal hour of the day of the [D] - zero based",
            },
            nc_scalar,
        ],  # BUG? why not mv:-1?
        "dd": [
            True,
            "i",
            {
                "_FillValue": -1,
                "description": "Decimal day of the year of the [D] - zero based",
            },
            nc_scalar,
        ],  # BUG? why not mv:-1?
        # must have same mdp_info as nc_sg_time_var, see MMP
        "bin_time": [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "mean time for the bin in GMT epoch format",
            },
            (nc_sg_data_info,),
        ],
        "start_time": [
            False,
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Starting time of the [D] in GMT epoch format",
            },
            nc_scalar,
        ],
        "end_time": [
            False,
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "Ending time of the [D] in GMT epoch format",
            },
            nc_scalar,
        ],
        "start_latitude": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "latitude",
                "units": "degrees_north",
                "description": "Starting latitude of the [D]",
            },
            nc_scalar,
        ],
        "end_latitude": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "longitude",
                "units": "degrees_north",
                "description": "Ending latitude of the [D]",
            },
            nc_scalar,
        ],
        "start_longitude": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "latitude",
                "units": "degrees_east",
                "description": "Starting longitude of the [D]",
            },
            nc_scalar,
        ],
        "end_longitude": [
            "f",
            "d",
            {
                "_FillValue": nc_nan,
                "standard_name": "longitude",
                "units": "degrees_east",
                "description": "Ending longitude of the [D]",
            },
            nc_scalar,
        ],
    }

    # Neither long_name nor standard_name are required (consumers just use the variable name instead) but it silences the compliance checker
    ensure_long_names = (
        False  # CF1.4 just a WARNING ensure compliance at the expense of space
    )
    after_static_check = False


# Set globals on initial import
set_globals()


def register_sensor_dim_info(
    dim_info, dim_name, time_var, data=False, instrument_var=None
):
    """Register the default dimension name and associated time nc var for dim info
    Also registers the dim_info, of course.
    """
    if dim_info in nc_mdp_data_info:
        log_error(f"Duplicate registration of {dim_info} -- ignored", "parent")
        return
    # register
    nc_mdp_data_info[dim_info] = dim_name
    if dim_name:
        # For make_mission_timeseries() we need a variable that will record the
        # dive number for every point in an accumulated dimension of the related name
        mmt_varname = dim_name + "_dive_number"
        nc_mdp_mmt_vars[dim_info] = mmt_varname
        # explicitly include_in_mission_profile
        form_nc_metadata(
            mmt_varname,
            True,
            "i",
            {"description": f"Dive number for given {dim_name} observation"},
            (dim_info,),
        )
    if dim_name and time_var:
        # register the associated time var
        nc_mdp_time_vars[dim_name] = time_var
    if data:
        # declare that all vectors using this dim_info describe raw data
        # MDP uses this flag to determine what derived results to drop
        # when rebuilding a file
        nc_data_infos.append(dim_info)  # raw data variables
        if instrument_var:
            if isinstance(data, str):
                nc_instrument_to_data_kind[instrument_var] = data  # to help form titles
            elif data is True:
                nc_instrument_to_data_kind[instrument_var] = "physical"

    if instrument_var:
        nc_mdp_instrument_vars[dim_info] = instrument_var


def fetch_instrument_metadata(dim_info):
    """Find instrument metadata, given the dimension info"""
    if dim_info in nc_mdp_instrument_vars:
        instrument_var = nc_mdp_instrument_vars[dim_info]
        try:
            # md = nc_var_metadata[instrument_var]
            # include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
            _, _, meta_data_d, _ = nc_var_metadata[instrument_var]
            return meta_data_d
        except KeyError:
            return None
    else:
        return None


def assign_dim_info_dim_name(nc_info_d, dim_info, dim_name):
    """During processing of an nc file assign what actual dimension to use
    for a specific dim_info.  This is recorded in a transient nc_info dictionary
    associated with a specific file.
    """
    if dim_name:
        try:
            prev_dim_name = nc_info_d[dim_info]
            if prev_dim_name and prev_dim_name != dim_name:
                log_warning(
                    "Reassigning %s dim_name from %s to %s!"
                    % (dim_info, prev_dim_name, dim_name),
                    "parent",
                )
        except KeyError:
            try:
                prev_dim_name = nc_mdp_data_info[dim_info]
                # if (
                #     False and prev_dim_name and prev_dim_name != dim_name
                # ):  # DEAD permit this one time
                #     log_warning(
                #         "Reassigning %s expected dim_name from %s to %s!"
                #         % (dim_info, prev_dim_name, dim_name),
                #         "parent",
                #     )
            except KeyError:
                log_error(f"Unregistered dim_info {dim_info}!", "parent")
                return  # ignore this
        nc_info_d[dim_info] = dim_name  # update
    else:
        log_error(f"Missing dimension name to assign to {dim_info}", "parent")


def assign_dim_info_size(nc_info_d, dim_info, size):
    """During processing of an nc file assign a size to a dimension
    for a specific dim_info.  This is recorded in a transient nc_info dictionary
    associated with a specific file.
    """
    if size is None or size == 0:
        # this can happen for very old missions where, e.g., there is no gc_state_info ($STATE)
        # individial dives or MMP calls will have nothing assigned to the dimension
        # This causes malformed nc files
        log_error(f"Missing dimension size to assign to {dim_info}", "parent")
        return

    try:
        dim_name = nc_info_d[dim_info]
    except KeyError:
        try:
            dim_name = nc_mdp_data_info[dim_info]
            nc_info_d[dim_info] = dim_name  # inherit
        except KeyError:
            log_error(
                "Attempting to assign a size %s to missing dimension name for %s!"
                % (size, dim_info),
                "parent",
            )
            return

    try:
        prev_size = nc_info_d[dim_name]
        if prev_size and prev_size != size:
            log_warning(
                f"Reassigning {dim_name} size from {prev_size} to {size}!",
                "parent",
            )
    except KeyError:
        pass
    nc_info_d[dim_name] = size  # update


def form_nc_metadata(
    nc_var=None,
    include_in_mission_profile=False,
    nc_data_type="d",
    meta_data_d=None,
    mdp_dim_info=nc_scalar,
):
    """Create a valid nc_var metadata entry for the table above
    Encodes default policies and ensures CF compliance in metadata, etc.

    If var is specified, updates the table with a warning on replacement

    Returns:
    md - the metadata entry
    None - if error
    """
    global after_static_check
    if after_static_check:
        pass  # BREAK here to track dynamic definitions of metadata

    if meta_data_d is None:
        meta_data_d = {}

    # by default include_in_mission_profile is False so dynamically generated variables are not propagated to MMT/MMP
    # you MUST explicitly (pre)declare any variables you want to propagated
    if include_in_mission_profile and len(mdp_dim_info) > 1:
        log_error(
            "MMP/MMT variable %s has improper number of dimensions %s; must be one-dimensional"
            % (nc_var if nc_var is not None else "Unknown", mdp_dim_info)
        )
        return None

    # NODC, CF and the like prefer 'comment' to 'description' as field name:
    # Do this or query-replace the fields and be done with it
    try:
        comment = meta_data_d["description"]
        del meta_data_d["description"]
        meta_data_d["comment"] = comment
    except KeyError:
        pass

    # GBS - 2021/08/10 - not sure what this is supposed to do
    assert not ensure_long_names
    # ensure standard names follow the conventions:
    # http://cf-pcmdi.llnl.gov/documents/cf-standard-names/standard-name-table/current/cf-standard-name-table.xml
    # if ensure_long_names:
    #     # if no long name ensure either standard_name or use variable name
    #     if "long_name" not in meta_data_d:
    #         # no long name
    #         if "standard_name" not in meta_data_d:
    #             # TODO should add this info explicitly and change this to a warning
    #             meta_data_d["long_name"] = var_name

    try:
        units = meta_data_d["units"]
        if units == "qc_flag":
            del meta_data_d["units"]
            meta_data_d["flag_values"] = QC.QC_flag_values
            meta_data_d["flag_meanings"] = QC.QC_flag_meanings
        if units.find("PSU") != -1:
            # A note on PSU as a unit from the standards:
            # Because it is dimensionless the units attribute should be given as 1e-3 or 0.001 i.e. parts per thousand if salinity is in PSU.
            meta_data_d["units"] = units.replace("PSU", "1e-3")  # per spec
    except KeyError:
        # No units...
        pass

    # Form up the bits
    md = [include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info]
    if nc_var:
        if nc_var in nc_var_metadata and (nc_var_metadata[nc_var] != md):
            log_warning(
                f"Replacing nc metadata for {nc_var} ({nc_var_metadata[nc_var]}) ({md})"
            )
        nc_var_metadata[nc_var] = md  # update the master dictionary
    return md


def ensure_CF_compliance():
    """Map over (combined) metadata table and ensure attributes, units, names, etc
    are compliant with the nc_convention_version declared above.

    Input: None
    Output: None
    Side-effect: nc_var_metadata attribute hashes are updated, if needed
    """
    # Write this code so it converts table entries once and is a NOP if called several times
    global after_static_check

    well_formed = True  # assume all metadata are well-formed
    nc_coordinate_vars_local = {}  # reset
    for var_name, md in list(nc_var_metadata.items()):
        if len(md) < 4:
            log_error(f"No dim info for {var_name} {md}")
            well_formed = False
            continue
        include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
        # This forms the entry 'properly' and checks for CF compliance, etc.
        md = form_nc_metadata(
            None, include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info
        )
        if md is None:
            well_formed = False
            continue
        # Do this here in case form_nc_metadata made changes
        # and to silence the replacing warning
        nc_var_metadata[var_name] = md
        # re-unpack in case of changes
        include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
        try:
            axis = meta_data_d["axis"]
            # There should be only a single dimension; ensured above
            if not include_in_mission_profile:
                log_warning(
                    "%s declares an axis (%s) but is not declared to be included in MMP/MMT!"
                    % (var_name, axis)
                )
                continue
            mdp_dim_info = mdp_dim_info[0]  # get the dim info from the tuple
            if mdp_dim_info not in nc_coordinate_vars_local:
                nc_coordinate_vars_local[mdp_dim_info] = {}
            nc_coordinate_vars_local[mdp_dim_info][axis] = var_name
        except KeyError:
            pass

    if not well_formed:
        log_critical("Unable to continue - problems in the metadata table definition")
        sys.exit(0)

    # coordinates_d for each dim_info maps an axis to a var_name
    # form a documentation string that maps an axis to a variable name
    # all coordinates must be pre-declared
    for dim_info, coordinates_d in list(nc_coordinate_vars_local.items()):
        coordinates = ""
        prefix = ""
        for axis in ["T", "X", "Y", "Z"]:  # order matters to NODC
            try:
                var = coordinates_d[axis]
                coordinates = f"{coordinates}{prefix}{var}"
                prefix = " "
            except KeyError:
                pass  # no such axis is ok...
        nc_coordinate_vars_local[dim_info] = coordinates  # replace with string

    # fix up meta_data_d for coordinates
    # can only do this after nc_coordinate_vars_local is computed above
    # mmt_time_vars = list(nc_mdp_time_vars.values())
    for _, md in list(nc_var_metadata.items()):
        include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
        if len(mdp_dim_info) == 1:  # vector?
            mdi = mdp_dim_info[0]
            # DEAD: seemed like a good idea to have each associated time variable
            # automatically added to a data variable with [TIME] in its description
            # but to be CF compliant per NODC we can only have one set of coordinates in the file,
            # so we opt explicitly for the ctd_ derived quantities.
            # if False:  # DEAD
            #     try:
            #         meta_data_d[nc_coordinates]  # did they specify 'coordinates'?
            #     except KeyError:
            #         if var_name not in mmt_time_vars:
            #             meta_data_d[
            #                 nc_coordinates
            #             ] = "[TIME]"  # this would be replaced with the associated time variable

            if (
                mdi in nc_coordinate_vars_local
                and "axis" not in meta_data_d  # we have some coordinates
                and mdi == nc_ctd_results_info  # this is not a primary axis
            ):  # limit this to ctd_results only per NODC
                meta_data_d[nc_coordinates] = nc_coordinate_vars_local[
                    mdi
                ]  # update coordinates string for documentation
    after_static_check = True


def init_tables(init_dict):
    """Updates global structures based on configured loggers/sensors in the basestation installation

    @param init_dict: A dictionary of initialization dictionaries

    """
    for d in init_dict.values():
        if "netcdf_metadata_adds" in d:
            for key in d["netcdf_metadata_adds"]:
                if key not in nc_var_metadata:
                    # add only if there isn't a definition already
                    # this permits explicit declaration of metadata for, say, cnf columns
                    nc_var_metadata[key] = d["netcdf_metadata_adds"][key]
                else:
                    pass

    ensure_CF_compliance()  # update variable metadata for CF compliance
    # Test global consistency and requirements on metadata here...
    for time_var in list(nc_mdp_time_vars.values()):
        # Each time var needs to be included in MMP to permit decimation of data to sg_np
        try:
            md = nc_var_metadata[time_var]
            include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
            if not include_in_mission_profile:
                log_warning(
                    "Time var %s not declared for inclusion in MMT/MMP, as required -- fixing"
                    % time_var
                )
                # NOTE this complains that it is reasserting ... that is an ok thing
                # you can silence it by passing None as the name and setting it directly
                form_nc_metadata(
                    time_var, True, nc_data_type, meta_data_d, mdp_dim_info
                )
        except KeyError:
            log_critical(f"Undeclared time var {time_var}")

    for instrument_var in list(nc_mdp_instrument_vars.values()):
        try:
            md = nc_var_metadata[instrument_var]
        except KeyError:
            log_critical(f"Undeclared instrument_var var {instrument_var}")


def reset_nc_char_dims():
    """Reset the dictionary of string dimensions for the a new NC file"""
    global nc_char_dims  # just for clarity
    nc_char_dims = {}


def find_string_dim(string_size, nc_file):
    global nc_char_dims
    try:
        var_dims = nc_char_dims[
            string_size
        ]  # reassign var_dims to treat as 'array' below
    except KeyError:
        var_dims = nc_char_dims[string_size] = (
            nc_string_dim_format % string_size
        )  # compute dimension name
        nc_file.createDimension(var_dims, string_size)
    return var_dims


def create_nc_var(
    nc_file,
    var_name,
    var_dims,
    profile,
    value=None,
    additional_meta_data_d=None,
    remove_meta_data=None,
    timeseries_val=False,
):
    """Given a netCDF variable name, construct a netCDF variable, with the
    specified dimension of the type and missing value specified in the var metadata
    table.  If no metadata derive defaults from type.  Handle character-based strings
    by adding an appropriate dimension, if needed.

    Input:
        nc_file - file to create variable in
        var_name - name of the netCDF variable
        var_dims  - tuple of names of any netCDF dimensions
        profile - True if the netCDF file is a profile file, False if it is a timeseries file
        value - the value to be assigned (optional, in case the caller wants to do it)
        additional_meta_data_d - an optional dictonary of attributes for this variable; will override existing
        remove_meta_data - an optional list of attribute tags to remove from the metadata

    Output:
        Returns an instance of a netCDF vaiable
        None if variable cannot be created

    Uses:
        nc_var_metadata - dictionary for netcdf variables metadata
        nc_char_dims - dictionary of character dimensions currently in use by nc_file
    """
    if var_name in nc_file.variables:
        log_debug(f"{var_name} already defined")
        return nc_file.variables[var_name]

    try:
        md = nc_var_metadata[var_name]
    except KeyError:
        # TODO what if value is not None and an array?  We should error
        # if var_dims is non-None then look up the mdp_dim_info
        if var_dims:
            log_error(
                "Unknown vector nc variable %s%s -- unable to create NC variable"
                % (var_name, var_dims)
            )
            return None  # nothing to do...
        md = form_nc_metadata(
            None, nc_data_type=None
        )  # default scalar metadata with nc_data_type explicitly None -- see below

    include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
    if timeseries_val:
        if isinstance(timeseries_val, str):
            nc_data_type = timeseries_val
        elif isinstance(include_in_mission_profile, str):
            nc_data_type = include_in_mission_profile
    if nc_data_type is None:
        if value is None:
            log_error(
                "Unable to determine type for %s -- unable to create NC variable"
                % var_name
            )
            return None  # nothing to do...

        if isinstance(value, int):
            nc_data_type = "i"
        elif isinstance(value, float):
            nc_data_type = "d"
        # TODO: GBS 2020/02/21 - the type here *might* be better as bytes....
        elif isinstance(value, str):
            nc_data_type = "c"
        # TODO: GBS 2020/02/21 - This might be a good ultimate backstop.
        # elif isinstance(value, bytes):
        #    nc_data_type = 'c'
        #    value = value.decode('utf-8')
        #    log_warning("NC type for %s was bytes - converted to str" % (var_name, ))
        else:
            if len(var_dims) == 1 and var_dims[0] == nc_dim_sg_data_point:
                nc_data_type = "d"
            else:
                log_error(
                    "Unknown NC type %s for %s - unable to create NC variable"
                    % (type(value), var_name)
                )
                return None  # c'est la vie...
        log_warning(f"Missing metadata for {var_name} type should be '{nc_data_type}'")
        # update data type and silence subsequent references
        md = form_nc_metadata(
            var_name,
            include_in_mission_profile,
            nc_data_type,
            meta_data_d,
            mdp_dim_info,
        )

    log_debug(f"Creating netCDF var {var_name} nc_type={nc_data_type}")

    if nc_data_type == "Q":  # Handle QC encoding
        nc_data_type = "c"  # coerce type and value
        value = QC.encode_qc(value)

    if var_dims == nc_scalar:  # scalar variable?
        # DEBUG print "create_dim: %s None" % var_name
        if nc_data_type == "c":
            # Handle string scalars -- arrays of characters
            # We determine or reuse specific string dimensions
            # NOTE ARGO forces all strings to the nearest power of 2 size

            # NetCDF libraries to not handle empty string values and cause processing of netCDF
            # files with such strings to crash/halt.
            size = len(value)
            if value is None or size == 0:
                log_error(
                    "Must supply a non-empty value for string-valued NC var (%s) -- variable not created "
                    % var_name
                )
                return None
            var_dims = find_string_dim(size, nc_file)
            nc_var = nc_file.createVariable(
                var_name,
                "c",
                (var_dims,),
                compression="zlib",
                complevel=9,
                fill_value=meta_data_d.get("_FillValue", False),
            )
        else:  # another type we know
            nc_var = nc_file.createVariable(
                var_name,
                nc_data_type,
                (),
                compression="zlib",
                complevel=9,
                fill_value=meta_data_d.get("_FillValue", False),
            )
        if value is None:
            # try replacing the initial value with the fill value, if any
            with contextlib.suppress(KeyError):
                value = meta_data_d["_FillValue"]
            # if not, ah well, use None as is and hope for the best
    else:  # an explicit tuple of dimensions
        # DEBUG print "create_dim: %s ('%s')" % (var_name, string.join(var_dims,','))
        log_debug(f"{var_name} {nc_data_type} {var_dims}")

        # Special case - if this is an array of strings, generate the string dimension, add
        # it to the dimensions, generate the variable and update the value per this:
        if (
            isinstance(value, np.ndarray)
            and value.ndim == 1
            and value.dtype.kind == "S"
        ):
            # N.B. - Assumes all strings in the array are already the same size
            size = np.char.str_len(value)[0]
            if value is None or size == 0:
                log_error(
                    "Must supply a non-empty value for string-valued NC var (%s) -- variable not created "
                    % var_name
                )
                return None
            str_dim = find_string_dim(size, nc_file)
            nc_var = nc_file.createVariable(
                var_name,
                nc_data_type,
                (var_dims[0], str_dim),
                compression="zlib",
                complevel=9,
                fill_value=meta_data_d.get("_FillValue", False),
            )
            value = netCDF4.stringtochar(value)
        else:
            nc_var = nc_file.createVariable(
                var_name,
                nc_data_type,
                var_dims,
                compression="zlib",
                complevel=9,
                fill_value=meta_data_d.get("_FillValue", False),
            )
    if value is not None:
        try:
            if var_dims == nc_scalar:
                nc_var.assignValue(value)  # scalar
            else:
                nc_var[:] = value  # array
        except ValueError as exception:
            log_error(
                f"Unable to assign value to nc var {var_name} {var_dims} ({exception.args})"
            )
            return None
        except Exception:
            log_error(f"Unable to assign value to nc var {var_name} {var_dims}")
            return None

    # update the metadata on variable
    if additional_meta_data_d or remove_meta_data:
        md = {}  # make a copy of the metadata
        md.update(meta_data_d)
        if additional_meta_data_d:
            md.update(additional_meta_data_d)  # will override default or add
        if remove_meta_data:
            for tag in remove_meta_data:
                if tag in md:
                    del md[tag]  # off with its head!
    else:
        md = meta_data_d

    for attr_name, vvalue in list(md.items()):
        try:
            vvalue.index("[P]")
        except Exception:
            pass
        else:
            vvalue = vvalue.replace("[P]", "profile" if profile else "sample")

        try:
            vvalue.index("[D]")
        except Exception:
            pass
        else:
            vvalue = vvalue.replace("[D]", "profile" if profile else "dive")

        # DEAD: see comment on coordinates in ensure_CF_compliance()
        # if False and var_dims:
        #     try:
        #         vvalue.index("[TIME]")
        #         time_var = nc_mdp_time_vars[var_dims[0]]  # Assume first entry in tuple
        #     except:
        #         pass
        #     else:
        #         vvalue = vvalue.replace(
        #             "[TIME]", time_var if time_var != var_name else ""
        #         )
        # BUG: netcdf.py dies if vvalue is an empty string ''
        if attr_name != "_FillValue":
            nc_var.__setattr__(attr_name, vvalue)  # assert the metdata attribute
        # to fetch, use getattr(nc_var,attr_name) or nc_var.__getattribute__(attr_name)

    return nc_var
