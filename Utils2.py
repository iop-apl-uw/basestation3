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

"""Misc utility routines that require other basestation modules"""

# This is the place for routines that depend on other basestation modules that in turn
# depend on other modules (with possible circular references).  

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import re
import os

from BaseLog import log_debug, log_error, log_warning
import BaseNetCDF
import CalibConst
import Utils

col_ncmeta_map_type = collections.namedtuple(
    "col_ncmeta_map_type", ["nc_var_name", "nc_meta_str"]
)

def read_cnf_file(
    conf_file_name,
    encode_list=True,
    ensure_list=None,
    lower=True,
    mission_dir=None,
    results_d=None,
):
    """Open and read a glider cnf file, returning parameter=value results as a dict.
    (NOTE: These files have a different format from cnf files parsed by ConfigParser)
    Returns None if no file.
    Multiple entries for a property are encoded as lists of values if encode_list is True,
    otherwise the last value is returned.
    If property is member of ensure_list, even a singleton will be returned as a list.
    Values are parsed as integers or floats, else they are recorded as strings.
    If lower is True property names are coerced to lower-case.
    If results_d is a dict, save and restore the file contents (as a string) to it; assert metadata if needed
    Return any parameter metadata (in the case this is a sensor cnf file from scicon)
    """
    if ensure_list is None:
        ensure_list = ["column"]
    nc_conf_file_name = conf_file_name.replace(".", "_")
    cnf_file_contents = None
    filename = conf_file_name
    if mission_dir is not None:
        filename = os.path.join(mission_dir, conf_file_name)
    if os.path.exists(filename):
        try:
            cnf_file = open(filename, "r")
        except IOError as exception:
            log_debug("Could not open %s (%s)" % (filename, exception.args))
            # fallthrough
        else:
            cnf_file_contents = []
            for conf_line in cnf_file:
                conf_line = (
                    conf_line.rstrip()
                )  # what about .rstrip(chr(0x1a)) for files uploaded from glider?
                if conf_line == "":
                    continue
                # keep comment lines, etc.
                cnf_file_contents.append(conf_line)
            cnf_file.close()
            cnf_file_contents = "\n".join(cnf_file_contents)

    if cnf_file_contents is not None:
        if results_d is not None:
            try:
                BaseNetCDF.nc_var_metadata[nc_conf_file_name]
            except KeyError:
                BaseNetCDF.form_nc_metadata(nc_conf_file_name, False, "c")
            results_d[
                nc_conf_file_name
            ] = cnf_file_contents  # save/update cnf file contents
    else:
        if results_d is not None:
            try:
                cnf_file_contents = results_d[nc_conf_file_name]  # any saved version?
            except KeyError:
                return (None, None)  # nope
        else:
            return (None, None)  # neither saved nor file

    cnf_dict = {}
    nc_meta_dict = collections.OrderedDict()
    for conf_line in cnf_file_contents.split("\n"):
        log_debug("Processing %s line (%s)" % (conf_file_name, conf_line))
        if conf_line[0] == "#":
            cl = conf_line[1:].rstrip().lstrip()
            if cl.startswith("(") and cl.endswith(")"):
                # nc meta data adds are potentially included as comments
                # Looks like dimension register - just stash the line
                cnf_eval_dict = {
                    "nc_nan": BaseNetCDF.nc_nan,
                    "nc_scalar": BaseNetCDF.nc_scalar,
                    "nc_sg_data_info": BaseNetCDF.nc_sg_data_info,
                }
                try:
                    # pylint: disable=eval-used
                    tmp = col_ncmeta_map_type(*eval(cl, cnf_eval_dict))
                except Exception:
                    log_error(
                        "Error processing nc meta data in %s (%s)"
                        % (conf_file_name, conf_line),
                        "exc",
                    )
                else:
                    # Confirm format
                    if tmp.nc_var_name.startswith("register_sensor_dim_info") or (
                        len(tmp.nc_meta_str) == 4
                        and isinstance(tmp.nc_meta_str[0], bool)
                        and isinstance(tmp.nc_meta_str[1], str)
                        and isinstance(tmp.nc_meta_str[2], dict)
                        and isinstance(tmp.nc_meta_str[3], tuple)
                    ):
                        nc_meta_dict[tmp.nc_var_name] = tmp.nc_meta_str
                    else:
                        log_error(
                            "netcdf meta data in %s (%s) is not formed correctly"
                            % (conf_file_name, conf_line)
                        )
            continue  # next line
        # parameter=value line
        conf_elts = conf_line.split("=")
        prop = conf_elts[0]
        if lower:
            prop = prop.lower()  # Convert to lower case
        value = conf_elts[1]
        try:
            value = int(value)
        except Exception:
            try:
                value = float(value)
            except Exception:
                # TODO? If string is enclosed in "", remove them?
                pass  # encode as-is, a string
        try:
            values = cnf_dict[prop]
        except KeyError:
            if prop in ensure_list:
                values = [value]
            else:
                values = value
        else:
            if encode_list:
                if not isinstance(values, list):
                    values = [values]
                values.append(value)
            else:
                values = value  # use most recent value
        cnf_dict[prop] = values  # update

    return (cnf_dict, nc_meta_dict)


def extract_calib_consts(dive_nc_file):
    """Extracts the calibration constants from the netCDF file

    Input:
    dive_nc_file - Open dive netcdf file

    Returns:
    calib_consts - calibration constants dictionary
    """

    calib_consts = {}

    sgc_var = re.compile(f"^{BaseNetCDF.nc_sg_cal_prefix}")

    for dive_nc_varname, nc_var in list(dive_nc_file.variables.items()):
        nc_is_scalar = len(nc_var.shape) == 0  # treat strings as scalars
        if sgc_var.search(dive_nc_varname):
            _, variable = sgc_var.split(dive_nc_varname)
            if nc_is_scalar:
                calib_consts[variable] = nc_var.getValue().item()
            else:  # nc_string
                calib_consts[variable] = (
                    nc_var[:].tobytes().decode("utf-8")
                )  # string comments

    return calib_consts


def get_mission_timeseries_name(base_opts, direc=None):
    ignore_fm = True
    if base_opts:
        mydir = base_opts.mission_dir
        ignore_fm = base_opts.ignore_flight_model
    elif direc:
        mydir = direc
    else:
        mydir = "./"

    sg_calib_file_name = os.path.join(mydir, "sg_calib_constants.m")

    # Read sg_calib_constants file
    calib_consts = CalibConst.getSGCalibrationConstants(
        sg_calib_file_name, not ignore_fm
    )

    # calib_consts is set; figure out filename, etc.
    try:
        instrument_id = int(calib_consts["id_str"])
    except Exception:
        instrument_id = int(base_opts.instrument_id)

    if instrument_id == 0:
        log_warning("Unable to determine instrument id; assuming 0")

    platform_id = "SG%03d" % instrument_id

    mission_title = Utils.ensure_basename(calib_consts["mission_title"])
    return os.path.join(
        mydir,
        "sg%03d_%s_timeseries.nc" % (instrument_id, mission_title),
    )


