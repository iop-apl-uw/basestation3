#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2011, 2012, 2013, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023 by University of Washington.  All rights reserved.
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

"""
WETlabs puck basestation sensor extension
"""

import copy

from BaseLog import log_error, log_debug
from BaseNetCDF import (
    assign_dim_info_dim_name,
    assign_dim_info_size,
    nc_mdp_data_info,
    nc_nan,
    nc_scalar,
    nc_sg_cal_prefix,
    nc_sg_data_info,
    nc_sg_eng_prefix,
    register_sensor_dim_info,
)
import Utils


# The basic idea:
# We define four different canonical wetlab puck type names
# In spite of scicon, this permits four puck instances to be flown per vehicle

# For convenience we name them according to the conventional type arrangement of channels:
#  wlbb2fl - 2 backscatter and 1 fluorescence
#  wlbbfl2 - 2 fluorescence and 1 backscatter
#  wlbb3   - 3 backscatter
#  wlfl3   - 3 fluorescence

# BUT in reality we don't care which channel is assigned to what puck so say you
# wanted to fly with two bb2fl's with different (and even duplicated) channels?
# Just call the other one a bbfl2 even if it is a lie.  We don't care below
# under the assumption the onboard cnf file assigns the right data output to the
# right channel name!.

# Even if we fix up the glider code to emit the new canonical channel names so no
# remapping is required. However, old files need to have their names mapped to
# the new canonical names.  We build the remapping tables from associated tables
# of old 'synonyms' for the canonical names If we see the old synonyms in asc or
# eng or nc files they are remapped.

# Finally, we add sg_calib_constants vars for recording dark count, scale, and
# resolution calibration data from the different channels and applying them to
# produce output if they are present.  The vars would look like:

#  <canonical_instrument>_<canonical_column>_dark_counts, etc.
# e.g.,
#   wlbbfl2_sig470nm_dark_counts = 27.0;


# If you are writing a cnf file for a particular conifguration of puck use the
# canonical instrument and column names below to reflect the channel order and
# prefix and all will be well.  We don't complain about the 'duplicate' metadata
# as long we you add the cnf files to the bottom of .sensors so this file is
# initialized first.

# The canonical instruments and their historical synonyms
instruments_d = {
    "wlbb2fl": [
        "wlbb2f",
        "bb2f",
        "bb2fl",
        "wlbb2flvmt",
        "wlbb2flvmg",
        "wlbb2fvmg",
        "WL_BB2FLVMT",
    ],
    # BUG BUG these were from cnf files?  what if both are declared?
    "wlbbfl2": ["bbfl2", "wlbbfl2vmt", "wlbbfl2vmg"],
    "wlbb3": [],  # new
    "wlfl3": [],  # new
}

# The canonical data channel names and their historical synonyms
# We include the ref columns because
# (1) in the deep past there was actually some sort of data there and
# (2) sometimes cnf files capture the reference/frequency label data

# All raw data is in some kind of 'counts'
# These are units only for the converted results
scattering_units = "meter^-1 steradian^-1"
chl_units = "micrograms/liter"
ppb_units = "1e-9"  # a part per billion

columns_d = {
    # Back scatter channels:
    # color: IR  R   O Y G   B   I V
    # nm:    880 700     532 470
    # Historically red was assigned to 470 and blue to 700 but that was incorrect.
    # If we see the old names we'll 'fix' this automatically below
    # iRobot added wlsig/ref1 sig1/ref1, etc.
    # per gbs: Typically these were used with wlNNN where NNN was the serial number.
    # We assume a script has already run over the eng files and renamed the instrument prefix to one of the canonical instrument names above
    # e.g., wl795 -> wlbbfl2
    # The script could also do the synonym mapping or it could be done usign this table; dealer's choice.
    "sig470nm": {
        "name": "blue scattering",
        "units": scattering_units,
        "synonyms": ["wl470sig", "470sig", "wlsig1", "redCount", "sig1"],
        "descr": "total volume blue scattering coefficient using manufacturer-supplied dark counts and scaling factor",
    },
    "ref470nm": {
        "name": "blue reference",
        "units": None,
        "synonyms": ["wl470ref", "470ref", "wlref1", "redRef", "ref1"],
    },
    "sig532nm": {
        "name": "green scattering",
        "units": scattering_units,
        "synonyms": ["sig532"],
        "descr": "total volume green scattering coefficient using manufacturer-supplied dark counts and scaling factor",
    },
    "ref532nm": {"name": "green reference", "units": None, "synonyms": []},
    # iRobot added wlsig/ref2
    # Actually also 600nm, 650nm, 660nm and 700nm as the diode changed over time (frs)
    "sig700nm": {
        "name": "red scattering",
        "units": scattering_units,
        "synonyms": [
            "wl600sig",
            "600sig",
            "wl700sig",
            "700sig",
            "wlsig2",
            "blueCount",
            "sig2",
            "sig650",
        ],
        "descr": "total volume red scattering coefficient using manufacturer-supplied dark counts and scaling factor",
    },
    "ref700nm": {
        "name": "red reference",
        "units": None,
        "synonyms": [
            "wl600ref",
            "600ref",
            "wl700ref",
            "700ref",
            "wlref2",
            "blueRef",
            "ref2",
        ],
    },
    # Add ref?
    "sig880nm": {
        "name": "infrared scattering",
        "units": scattering_units,
        "synonyms": ["sig880"],
    },
    # Fluorescence channels:
    # Color Dissolved Organic Material
    # iRobot Cdomsig1 Cdomref1
    "sig460nm": {
        "name": "CDOM fluorescence",
        "units": ppb_units,
        "synonyms": ["Cdomsig", "Cdomsig1", "sig460"],
    },
    "ref460nm": {
        "name": "CDOM reference",
        "units": None,
        "synonyms": ["Cdomref", "Cdomref1"],
    },
    # Do we need to add refs for these guys?
    "sig530nm": {"name": "uranine fluorescence", "units": ppb_units, "synonyms": []},
    "sig570nm": {
        "name": "phycoerythrin/rhodamine fluorescence",
        "units": ppb_units,
        "synonyms": [],
    },
    "sig680nm": {
        "name": "phycocyanin fluorescence",
        "units": ppb_units,
        "synonyms": ["sig680"],
    },
    # iRobot Chlsig1
    "sig695nm": {
        "name": "chlorophyll fluorescence",
        "units": chl_units,
        "synonyms": ["Chlsig", "fluorCount", "Chlsig1", "sig695", "sg695nm"],
        "descr": "chlorophyll-a concentration using manufacturer-supplied dark counts and scaling factor based on phytoplankton monoculture",
    },
    "ref695nm": {
        "name": "chlorophyll reference",
        "units": None,
        "synonyms": ["Chlref", "fluorRef", "Chlref1"],
    },
    # These alternative names were used in the case you installed two pucks w/
    # different light channels but you always get a 'temperature'. As long as
    # the instrument type differs we will keep channels separate and associated
    # properly.
    # What is this temperature?  The internal temperature of the device?
    # What is its scale? Operating range is 0 - 30 C
    # Some values are in the range of 500 so that would be ~15C if scale was 1K and offset was 0
    # iRobot temp1
    "temp": {
        "name": "temperature",
        "units": None,
        "synonyms": ["temp", "VFtemp", "L2VMTtemp", "therm", "temp1"],
    },
}

asc_remap_d = {}  # old instrument/column synonyms to canonical, including empty
eng_remap_d = {}  # old instrument/column synonyms to canonical, excluding empty
canonical_data_to_results_d = {}
display_sg_calib_vars = (
    False  # Do once to prepare a helpful cheatsheet of sg_calib_constants variables
)


def init_sensor(module_name, init_dict=None):
    """
    init_sensor

    Returns:
        -1 - error in processing
         0 - success (data found and processed)
    """

    if init_dict is None:
        log_error("No datafile supplied for init_sensors - version mismatch?")
        return -1

    meta_data_adds = {
        "sg_cal_remap_wetlabs_eng_cols": [
            False,
            "c",
            {"description": "Dictionary for remapping eng files"},
            nc_scalar,
        ],
    }
    for canonical_instrument, instrument_synonyms in instruments_d.items():
        # create data info
        data_time_var = "%s_time" % canonical_instrument  # from scicon
        data_info = "%s_data_info" % canonical_instrument
        register_sensor_dim_info(
            data_info,
            "%s_data_point" % canonical_instrument,
            data_time_var,
            "biological",
            canonical_instrument,
        )
        for synonym in instrument_synonyms:
            asc_remap_d["%s.time" % synonym] = data_time_var
            eng_remap_d["%s_time" % synonym] = data_time_var

        # create results info
        results_time_var = "%s_results_time" % canonical_instrument
        results_info = "%s_results_info" % canonical_instrument
        register_sensor_dim_info(
            results_info,
            "%s_result_point" % canonical_instrument,
            results_time_var,
            False,
            canonical_instrument,
        )
        # create the instrument variable
        # NOTE can't add empty strings netcdf.py dies so
        # DEAD 'ancillary_variables':'', # no calib constants
        md = [
            False,
            "c",
            {
                "long_name": "underway backscatter fluorescence puck",
                "make_model": "Wetlabs backscatter fluorescence puck",
            },
            nc_scalar,
        ]
        meta_data_adds[canonical_instrument] = md
        # for scicon data time var
        md = [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "%s time in GMT epoch format" % canonical_instrument,
            },
            (data_info,),
        ]
        meta_data_adds[data_time_var] = md

        # for any results
        md = [
            True,
            "d",
            {
                "standard_name": "time",
                "units": "seconds since 1970-1-1 00:00:00",
                "description": "%s result time in GMT epoch format"
                % canonical_instrument,
            },
            (results_info,),
        ]
        meta_data_adds[results_time_var] = md

        for cast, tag in (("a", "dive"), ("b", "climb")):
            meta_data_adds["%s_ontime_%s" % (canonical_instrument, cast)] = [
                False,
                "d",
                {
                    "description": "%s total time turned on %s"
                    % (canonical_instrument, tag),
                    "units": "secs",
                },
                nc_scalar,
            ]
            meta_data_adds["%s_samples_%s" % (canonical_instrument, cast)] = [
                False,
                "i",
                {
                    "description": "%s total number of samples taken %s"
                    % (canonical_instrument, tag)
                },
                nc_scalar,
            ]
            meta_data_adds["%s_timeouts_%s" % (canonical_instrument, cast)] = [
                False,
                "i",
                {
                    "description": "%s total number of samples timed out on %s"
                    % (canonical_instrument, tag)
                },
                nc_scalar,
            ]

        for canonical_column, defn_d in columns_d.items():
            # create the canonical meta data that everything gets mapped to
            # the raw data are always some count thing so they never have units
            name = defn_d["name"]
            # The canonical data variable and instrument_column name mapped to...
            # CRITICAL this must match what the remapper produces
            data_var = "%s_%s" % (canonical_instrument, canonical_column)
            eng_data_var = "%s%s" % (nc_sg_eng_prefix, data_var)
            md = [
                "f",
                "d",
                {
                    "_FillValue": nc_nan,
                    "description": "%s as reported by instrument" % name,
                    "instrument": canonical_instrument,
                },
                (nc_sg_data_info,),
            ]
            meta_data_adds[eng_data_var] = md

            scicon_data_var = "%s" % data_var
            md = [
                "f",
                "d",
                {
                    "_FillValue": nc_nan,
                    "description": "%s as reported by instrument" % name,
                    "instrument": canonical_instrument,
                },
                (data_info,),
            ]
            meta_data_adds[scicon_data_var] = md  # scicon
            units = defn_d["units"]
            if units is not None:
                # CONSIDER: Could add a qc vector for failing instruments, QC_UNSAMPLED etc?
                # There are no 'standard_name' for these results
                results_var = "%s_%s_adjusted" % (
                    canonical_instrument,
                    canonical_column,
                )  # better name?
                try:
                    descr = defn_d["descr"]
                except KeyError:
                    descr = (
                        "%s using manufacturer-supplied dark counts and scaling factor"
                        % name
                    )
                md = [
                    "f",
                    "d",
                    {
                        "_FillValue": nc_nan,
                        "units": units,
                        "description": descr,
                    },
                    (results_info,),
                ]
                meta_data_adds[results_var] = md
                # to support the adjusted variable above and record for posterity what the cal sheet said
                # Not all of these are used for processing
                md = [False, "d", {}, nc_scalar]
                dark_counts_var = "%s_%s_dark_counts" % (
                    canonical_instrument,
                    canonical_column,
                )
                meta_data_adds["%s%s" % (nc_sg_cal_prefix, dark_counts_var)] = md
                scale_factor_var = "%s_%s_scale_factor" % (
                    canonical_instrument,
                    canonical_column,
                )
                meta_data_adds["%s%s" % (nc_sg_cal_prefix, scale_factor_var)] = md
                # These let people know about full range but aren't used to convert
                res_counts_var = "%s_%s_resolution_counts" % (
                    canonical_instrument,
                    canonical_column,
                )
                meta_data_adds["%s%s" % (nc_sg_cal_prefix, res_counts_var)] = md
                max_counts_var = "%s_%s_max_counts" % (
                    canonical_instrument,
                    canonical_column,
                )
                meta_data_adds["%s%s" % (nc_sg_cal_prefix, max_counts_var)] = md
                if display_sg_calib_vars:
                    print("%s = 0.0; %% For %s channel" % (dark_counts_var, name))
                    print("%s = 0.0; %% For %s channel" % (scale_factor_var, name))
                    print("%s = 0.0; %% For %s channel" % (res_counts_var, name))
                    print(
                        "%s = 0.0; %% For %s channel" % (max_counts_var, name)
                    )  # only chl_units?

                # intern to drive sensor_data_processing() below
                canonical_data_to_results_d[data_var] = [
                    data_time_var,
                    data_info,
                    results_var,
                    results_time_var,
                    results_info,
                    dark_counts_var,
                    scale_factor_var,
                ]

    calib_var = "calibcomm_wetlabs"
    meta_data_adds["%s%s" % (nc_sg_cal_prefix, calib_var)] = [
        False,
        "c",
        {},
        nc_scalar,
    ]  # for all installed wetlabs
    if display_sg_calib_vars:
        print("%% Declare sensor calibration information as shown")
        print(
            "%s = 'wlbbfl2 SN234 calibrated 6/6/12; wlbb2fl SN567 calibrated 5/13/13';"
            % calib_var
        )

    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}

    # For all the historical instrument and column names generate remapping rules to sent raw and results to canonicals
    # We need eng remap in case we get old eng OR nc files without asc files
    # We generate asc files for legacy glider code remapping
    # As long as cnf files use the std names we'll pick them up too
    for canonical_instrument, instrument_synonyms in instruments_d.items():
        # permit canonical instruments but synonym columns for iRobot remapping
        instrument_synonyms = copy.copy(instrument_synonyms)
        instrument_synonyms.append(canonical_instrument)
        for instrument_synonym in instrument_synonyms:
            for canonical_column, defn_d in columns_d.items():
                canonical_instrument_column_asc = "%s.%s" % (
                    canonical_instrument,
                    canonical_column,
                )
                canonical_instrument_column_eng = "%s_%s" % (
                    canonical_instrument,
                    canonical_column,
                )
                for column_synonym in defn_d["synonyms"]:
                    asc_remap_d[
                        "%s.%s" % (instrument_synonym, column_synonym)
                    ] = canonical_instrument_column_asc
                    eng_remap_d[
                        "%s_%s" % (instrument_synonym, column_synonym)
                    ] = canonical_instrument_column_eng

    # very old files go to wlbb2fl by fiat
    for canonical_column, defn_d in columns_d.items():
        canonical_instrument_column_asc = "wlbb2fl.%s" % canonical_column
        canonical_instrument_column_eng = "wlbb2fl_%s" % canonical_column
        for column_synonym in defn_d["synonyms"]:
            asc_remap_d[column_synonym] = canonical_instrument_column_asc
            eng_remap_d[column_synonym] = canonical_instrument_column_eng

    return 0


# If you are converting from eng for the first time, we go directly to canonical
# Every current output column name needs to have an entry that goes to the new canonical name
# so that old nc files can be converted as well.  The cost of legacy


# pylint: disable=unused-argument
def asc2eng(base_opts, module_name, datafile=None):
    """
    asc2eng processor

    returns:
    -1 - error in processing
     0 - success (data found and processed)
     1 - no data found to process
    """

    if datafile is None:
        log_error("No datafile supplied for asc2eng conversion - version mismatch?")
        return -1

    retval = 1  # assume no change
    for old_name, canonical_name in asc_remap_d.items():
        data = datafile.remove_col(old_name)
        if data is not None:
            datafile.eng_cols.append(canonical_name)
            datafile.eng_dict[canonical_name] = data
            retval = 0  # something changed

    return retval


def remap_engfile_columns_netcdf(
    base_opts, module, calib_consts=None, column_names=None
):
    """
    Called from MakeDiveProfiles.py to remap column headers from older .eng files to
    current naming standards for netCDF output

    The format in the sg_calib_constants.m file is
        remap_eng_cols='oldname:newname,oldname,newname';
    For example, remapping from iRobot/Hydroid gliders
        remap_eng_cols='oldname:newname,oldname,newname';
    Returns:
    0 - match found and processed
    1 - no match found
    """
    if column_names is None:
        log_error(
            "Missing arguments for WETlabs remap_engfile_columns_netcdf - version mismatch?"
        )
        return -1

    r1 = r2 = 0

    if calib_consts is None:
        # This happens when reading scicon collected WETlabs data
        # unable to specify sg_calib_constants remapping variable
        log_debug(
            "No calib_consts provided - WETlabs remap_engfile_columns_netcdf will skip reading the sg_calib_constants.m file"
        )
    else:
        # Check for any remapping specified in sg_calib_constants.m
        calib_remap_d = Utils.remap_dict_from_sg_calib(
            calib_consts, "remap_wetlabs_eng_cols"
        )
        if calib_remap_d:
            r1 = Utils.remap_column_names(calib_remap_d, column_names)

    # Old nc files will have been processed through old versions of asc2eng so have old names
    # We need to convert them here to canonical names
    r2 = Utils.remap_column_names(eng_remap_d, column_names)
    return 1 if r1 or r2 else 0


def sensor_data_processing(base_opts, module, l=None, eng_f=None, calib_consts=None):
    """
    Called from MakeDiveProfiles.py to do sensor specific processing

    Arguments:
    l - MakeDiveProfiles locals() dictionary
    eng_f - engineering file
    calib_constants - sg_calib_constants object

    Returns:
    -1 - error in processing
     0 - data found and processed
     1 - no appropriate data found
    """

    if (
        l is None
        or eng_f is None
        or calib_consts is None
        or "results_d" not in l
        or "nc_info_d" not in l
    ):
        log_error(
            "Missing arguments for WETlabs sensor_data_processing - version mismatch?"
        )
        return -1

    results_d = l["results_d"]
    nc_info_d = l["nc_info_d"]

    for data_var, directives in canonical_data_to_results_d.items():
        (
            data_time_var,
            data_info,
            results_var,
            results_time_var,
            results_info,
            dark_counts_var,
            scale_factor_var,
        ) = directives

        (data_present, data) = eng_f.find_col([data_var])
        if data_present:
            time_s_v = l["sg_epoch_time_s_v"]
            results_dim = nc_mdp_data_info[nc_sg_data_info]
        else:
            try:
                data = results_d[data_var]
                time_s_v = results_d[data_time_var]
                results_dim = nc_mdp_data_info[data_info]
                data_present = True
            except KeyError:
                data_present = False
        if data_present:
            # CONSIDER map over all raw signal data and see if the non-nan values are all constant and equal to some known frequency label
            # if so warn that the columns are probably not assigned correctly
            # Need a list of expected freq labels and the associated sig columns for colloq names
            # WARN: Data in <data_var> is <value>, which is the frequency label associated with <canonical_column>; column name mismatch?

            # CONSIDER look at 'reference' signals and if not variable or not equal to the expected frequency label warn as well?
            # No ancient sensors has a true fluctuating 'reference' value

            # see if required sg_calib_constants are present
            try:
                dark_counts = calib_consts[dark_counts_var]
                scale_factor = calib_consts[scale_factor_var]
                # Need to time data and dimension
            except KeyError:
                # normally, no warning about missing calibration data
                log_debug(
                    "%s data found but calibration constant(s) missing - skipping corrections"
                    % data_var
                )
            else:
                # scale the data and record in results
                scaled_data = scale_factor * (data - dark_counts)

                np = len(time_s_v)
                # NOTE this could happen up to 3 times per instrument if all calib data is present
                # but size shouldn't change per instrument so no foul
                assign_dim_info_dim_name(nc_info_d, results_info, results_dim)
                assign_dim_info_size(nc_info_d, results_info, np)
                results_d.update({results_time_var: time_s_v, results_var: scaled_data})
    return 0


def remap_instrument_names(base_opts, module, current_names=None):
    """Given a list of instrument names, map into the canonical names

    Returns:
    -1 - error in processing
     0 - data found and processed
     1 - no appropriate data found

    """
    if current_names is None:
        log_error(
            "Missing arguments for WETlabs remap_instrument_names - version mismatch?"
        )
        return -1

    ret_val = 1
    for oldname in current_names:
        for k, v in instruments_d.items():
            if oldname in v:
                current_names[current_names.index(oldname)] = k
                ret_val = 0
    return ret_val
