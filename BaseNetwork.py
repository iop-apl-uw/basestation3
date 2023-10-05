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

"""
Processes network files
"""

import collections
import io
import os
import pdb
import sys
import time
import traceback

import numpy as np
import xarray as xr

from BaseLog import (
    BaseLogger,
    log_error,
    log_info,
    log_critical,
    log_warning,
    log_debug,
)
import BaseOpts
import LogFile
import NetCDFUtils
import Utils

# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False

var_template = {
    "variables": {
        "time": {
            "type": "f8",
            "num_digits": 0,
            "dimensions": [
                "profile_data_point",
                "depth_data_point",
            ],
            "attributes": {
                "_FillValue": -999,
                "long_name": "Time",
                "standard_name": "time",
                "units": "seconds since 1970-01-01T00:00:00Z",
            },
        },
        "temperature": {
            "type": "f4",
            "num_digits": 3,
            "dimensions": [
                "profile_data_point",
                "depth_data_point",
            ],
            "attributes": {
                "_FillValue": -999,
                "long_name": "Temperature",
                "standard_name": "sea_water_temperature",
                "units": "Celsius",
            },
        },
        "salinity": {
            "type": "f4",
            "num_digits": 2,
            "dimensions": [
                "profile_data_point",
                "depth_data_point",
            ],
            "attributes": {
                "_FillValue": -999,
                "long_name": "Salinity",
                "standard_name": "sea_water_practical_salinity",
                "units": "1",
            },
        },
        "depth": {
            "type": "f4",
            "num_digits": 2,
            "dimensions": ["depth_data_point"],
            "attributes": {
                "_FillValue": -999,
                "long_name": "Depth",
                "standard_name": "depth",
                "units": "m",
            },
        },
        # TODO - post AMOS2022/Hood Canal, this should be retired in favor of the log_ID
        # for now, topside may be depending on this variable
        "dive_number": {
            "type": "i2",
            "num_digits": 0,
            "attributes": {
                "_FillValue": -999,
                "comment": "Number of dive in mission",
            },
        },
        "log_ID": {
            "type": "i2",
            "num_digits": 0,
            "attributes": {
                "_FillValue": -999,
                "comment": "Seaglider serial number",
            },
        },
        "log_DIVE": {
            "type": "i2",
            "num_digits": 0,
            "attributes": {
                "_FillValue": -999,
                "comment": "Profile number from start of mission",
            },
        },
        "log__SM_DEPTHo": {
            "type": "f4",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Mesasured depth (m) at end of surface maneuver",
            },
        },
        "log__SM_ANGLEo": {
            "type": "f4",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Mesasured angle (deg) at end of surface maneuver",
            },
        },
        "log_TGT_NAME": {
            "type": "c",
            "comment": "Name of the active target",
        },
        "log_MHEAD_RNG_PITCHd_Wd": {
            "type": "f4",
            "num_digits": 2,
            "attributes": {
                "comment": "Seaglider computed flight parameters",
                "_FillValue": -999,
            },
            "coord_cols": [
                "desiredHead",
                "targetRange",
                "pitchAngDesired",
                "wDesired",
                "theta0",
                "dbdw",
                "pressureNoise",
            ],
        },
        "log_D_GRID": {
            "type": "f4",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Assumed mimimum depth during dive",
            },
        },
        "log_HUMID": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "Relative humidity inside the pressure hull (percent)",
            },
        },
        "log_TEMP": {
            "type": "f4",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Temperature (Celsius) inside the pressure hull",
            },
        },
        "log_INTERNAL_PRESSURE": {
            "type": "f4",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Pressure inside the pressure hull (psia)",
            },
        },
        "log_24V_AH": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "24 Volt battery report",
            },
            "coord_cols": [
                "MinVbatt24v",
                "sum24",
            ],
        },
        "log_10V_AH": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "10 Volt battery report",
            },
            "coord_cols": [
                "MinVbatt10v",
                "sum10",
            ],
        },
        "log_FG_AHR_24Vo": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "Fuel gauge accumulated 24V amp-hours",
            },
        },
        "log_FG_AHR_10Vo": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "Fuel gauge accumulated 10V amp-hours",
            },
        },
        "log_SDFILEDIR": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "SD card statistics",
            },
            "coord_cols": ["n_files", "n_dirs"],
        },
        "log_MAGCAL": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "On-board auto compass cal results",
            },
            "coord_cols": [
                "a",
                "b",
                "c",
                "d",
                "e",
                "f",
                "g",
                "h",
                "k",
                "p",
                "q",
                "r",
                "coverage",
                "circularity",
                "converged",
            ],
        },
        "log_IMPLIED_C_PITCH": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "On-board pitch regression results",
            },
            "coord_cols": [
                "-b/a",
                "a/p_pitch_cnv",
                "n_pit",
                "log_c_pitch",
                "log_pitch_gain",
            ],
        },
        "log_IMPLIED_C_VBD": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "On-board vbd regressions results",
            },
            "coord_cols": [
                "p_c_vbd-bias/p_vbd_cnv",
                "bias2",
                "npoints",
                "p_c_vbd-delta",
            ],
        },
        "log_FINISH": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "End of dive stats",
            },
            "coord_cols": [
                "depth",
                "density",
            ],
        },
        "log_FINISH1": {
            "type": "f4",
            "num_digits": 3,
            "attributes": {
                "_FillValue": -999,
                "comment": "End of dive stats",
            },
            "coord_cols": [
                "depth",
                "density",
                "vbd_ctl",
            ],
        },
        "log_GPS": {
            "type": "f8",
            "num_digits": 4,
            "attributes": {
                "_FillValue": -999,
                "comment": "Position fix for end of dive",
            },
            "coord_cols": [
                "time",
                "latitude",
                "longitude",
                "hdop",
            ],
        },
        "log_GPS2": {
            "type": "f8",
            "num_digits": 4,
            "attributes": {
                "_FillValue": -999,
                "comment": "Position fix for start of dive",
            },
            "coord_cols": [
                "time",
                "latitude",
                "longitude",
                "hdop",
            ],
        },
        "log_GC": {
            "type": "f8",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Guidance and control table",
            },
            "coord_cols": [
                "time",
                "depth",
                "w",
                "vbd_i",
                "pitch_i",
                "roll_i",
                "vbd_ad",
                "picth_ad",
                "roll_ad",
                "vbd_v",
                "state",
                "eop_code",
            ],
            "coord_row": "log_GC_time",
        },
        "log_MODEM": {
            "type": "f8",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Modem fix table",
            },
            "coord_cols": [
                "source",
                "time",
                "travel",
            ],
            "coord_row": "log_MODEM_data_points",
        },
        "log_FREEZE": {
            "type": "f8",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Freezing point measurement table",
            },
            "coord_cols": [
                "depth",
                "temperature",
                "freezing_point",
                "ice_condition",
                "dives_since_last_call",
                "surface_urgency",
            ],
            "coord_row": "log_FREEZE_data_points",
        },
        "start_time": {
            "type": "f8",
            "num_digits": 2,
            "attributes": {
                "_FillValue": -999,
                "comment": "Start of dive",
                "units": "seconds since 1970-01-01T00:00:00Z",
            },
        },
    },
}


# TODO: Keep this until its clear the template will not be housed in a json file
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


def create_ds_var(dso, template, var_name, data, row_coord=None):
    """Creates a DataSet variable with metadata
    Input:
        dso - output dataset
        template - dictionary of metadata
        var_name - name of variable as appears in teamplate
        data - input data
        row_coord - array for row coordinates

    Returns:
        dataarray for variable

    """
    if isinstance(data, str):
        inp_data = np.array(data, dtype=np.dtype(("S", len(data))))
    elif np.ndim(data) == 0:
        # Scalar data
        inp_data = np.dtype(template["variables"][var_name]["type"]).type(data)
    else:
        inp_data = data.astype(template["variables"][var_name]["type"])

    if "num_digits" in template["variables"][var_name]:
        inp_data = inp_data.round(template["variables"][var_name]["num_digits"])

    # Set missing values to fill value
    if np.ndim(inp_data) == 0:
        if inp_data == np.nan:
            inp_data = template["variables"][var_name]["attributes"]["_FillValue"]
    else:
        inp_data[inp_data == np.nan] = template["variables"][var_name]["attributes"][
            "_FillValue"
        ]

    # Set the dimensions and coodinates
    coords = None
    dims = None
    if isinstance(data, str):
        dims = None
    elif "dimensions" in template["variables"][var_name]:
        dims = template["variables"][var_name]["dimensions"]
    elif np.ndim(inp_data) == 0:
        dims = []
    elif "coord_cols" in template["variables"][var_name]:
        if "coord_row" in template["variables"][var_name]:
            dims = [template["variables"][var_name]["coord_row"], var_name + "_columns"]
            coords = {
                dims[0]: row_coord,
                dims[1]: template["variables"][var_name]["coord_cols"],
            }
        else:
            dims = [var_name + "_columns"]
            coords = {dims[0]: template["variables"][var_name]["coord_cols"]}
    else:
        dims = [var_name + "_data_point"]

    # Attributes
    attrs = None
    if "attributes" in template["variables"][var_name]:
        attrs = fix_ints(np.int32, template["variables"][var_name]["attributes"])

    da = xr.DataArray(
        inp_data,
        dims=dims,
        attrs=attrs,
        coords=coords,
    )
    dso[var_name] = da

    return da


def convert_network_logfile(base_opts, in_file_name, out_file_name):
    """Converts a network log/eng file to text output

    Input:
        in_file_name - name of input file name
        out_file_name - name of output file name or None.
                        if None, the out_file_name will be created from the compressed
                        eng header info, in the same directory as the input file
    Returns:
        out_file_name
        None - failure

    """

    convertor = base_opts.network_log_decompressor or "/usr/local/bin/log"

    if not os.path.isfile(convertor):
        log_error(
            f"Convertor {convertor} does not exit - not processing {in_file_name}"
        )
        return None

    if not os.access(convertor, os.X_OK):
        log_error(
            f"Convertor {convertor} is not marked as executable - not processing {in_file_name}"
        )
        return None

    if not os.path.isfile(in_file_name):
        log_error(f"{in_file_name} does not exist")
        return None

    cmdline = f"{convertor} {in_file_name}"
    log_info(f"Running {cmdline}")
    try:
        (sts, run_output) = Utils.run_cmd_shell(cmdline, timeout=10)
    except:
        log_error(f"Error running {cmdline}", "exc")
        return None

    if sts is None:
        log_error(
            f"Error running {cmdline} - timeout", "exc", alert="CONVERSION_TIMEOUT"
        )
        return None

    if sts >> 8:
        error = ""
        for l in run_output:
            error += l.decode()
        log_error(f"Error running {cmdline} - {error}")

        return None

    if out_file_name is None:
        try:
            # So we can seek to the start
            run_output = io.BytesIO(run_output.read())
            sgid = divenum = None
            for ll in run_output.readlines():
                ll = ll.decode()
                if ll.startswith("$ID,"):
                    sgid = float(ll.rstrip()[4:])
                elif ll.startswith("$DIVE,"):
                    divenum = float(ll.rstrip()[6:])
            if sgid is None or sgid < 100.0 or divenum is None or divenum <= 0:
                log_debug(f"Could not formulate file name for {in_file_name}")
                return None
            run_output.seek(0)
            out_file_name = os.path.join(
                os.path.split(in_file_name)[0],
                f"p{int(sgid):03d}{int(divenum):04d}.nlog",
            )
        except:
            log_error("Failed to format out_file_name", "exc")
            return None

    try:
        fo = open(out_file_name, "wb")
    except:
        log_error(f"Failed to open {out_file_name}")
        return None

    for l in run_output:
        fo.write(l)
    fo.close()

    return out_file_name


def convert_network_profile(in_file_name, out_file_name):
    """Converts a network ct profile plain text output
    Input:
        in_file_name - name of input file name
        out_file_name - name of output file name or None.
                        if None, the out_file_name will be created from the compressed
                        profile header info, in the same directory as the input file
    Returns:
        out_file_name
        None - failure
    """

    convertor = "/usr/local/bin/x3decode_ts"

    if not os.path.isfile(convertor):
        log_error(
            f"Convertor {convertor} does not exit - not processing {in_file_name}"
        )
        return None

    if not os.access(convertor, os.X_OK):
        log_error(
            "Convertor (%s) is not marked as executable - not processing %s"
            % (convertor, in_file_name)
        )
        return None

    if not os.path.isfile(in_file_name):
        log_error(f"{in_file_name} does not exits")
        return None

    if out_file_name is None:
        # See if there is enough meta data to build the new file name
        try:
            with open(in_file_name, "rb") as fi:
                header = fi.readline()
                splits = header.decode().split(" ")
                if len(splits) >= 4:
                    out_file_name = os.path.join(
                        os.path.split(in_file_name)[0],
                        f"p{splits[2][2:]}{splits[3][2:6]}.npro",
                    )
        except:
            log_error("Failed to format out_file_name", "exc")
            return None

    if out_file_name is None:
        log_debug(f"Could not formulate output file name for {in_file_name}")
        return out_file_name

    cmdline = f"{convertor} -i {in_file_name} -o {out_file_name}"
    log_info(f"Running {cmdline}")
    try:
        (sts, fo) = Utils.run_cmd_shell(cmdline, timeout=10)
    except:
        log_error(f"Error running {cmdline}", "exc")
        return None

    if sts is None:
        log_error(
            f"Error running {cmdline} - timeout", "exc", alert="CONVERSION_TIMEOUT"
        )
        return None

    if sts >> 8:
        error = ""
        for l in fo:
            error += l.decode()
        log_error(f"Error running {cmdline} - {error}")

        return None

    return out_file_name


# def parse_timestamp(rs):
#     """Convert a timestamp string into a list of ints"""
#     splits = rs.split()
#     return [int(x) for x in splits]


class log_parser:
    """Machinery for parsing a network log file"""

    # pylint: disable=missing-function-docstring disable=no-self-use

    def __init__(self):
        self.global_table = {}
        self.gc_table = []
        self.state_table = []
        self.modem_table = []
        self.freeze_table = []

    # Parsers
    def float32_cnv(self, x):
        return np.array(x, np.float32)

    def float64_cnv(self, x):
        return np.array(x, np.float64)

    def str_cnv(self, x):
        return str(x[0])

    def state_cnv(self, x):
        return [
            np.float32(x[0]),
            LogFile.map_state_code(x[1]),
            LogFile.map_eop_code(x[2]) if len(x) >= 3 else np.nan,
        ]

    def gps_cnv(self, x):
        ttime = time.mktime(time.strptime(x[1] + x[0], "%H%M%S%d%m%y"))
        lat = Utils.ddmm2dd(np.float64(x[2]))
        lon = Utils.ddmm2dd(np.float64(x[3]))
        hdop = np.float64(x[4])
        return np.array([ttime, lat, lon, hdop])

    # Adders
    def add_to_global_table(self, param_name, val):
        self.global_table[param_name] = val

    def add_to_gc_table(self, param_name, val):
        # pylint: disable=unused-argument
        if len(val) != 10:
            raise TypeError("Incorrect number of values for GC line", val)
        self.gc_table.append(val)

    def add_to_modem_table(self, param_name, val):
        # pylint: disable=unused-argument
        if len(val) != 3:
            raise TypeError("Incorrect number of values for MODEM line", val)
        self.modem_table.append(val)

    def add_to_freeze_table(self, param_name, val):
        # pylint: disable=unused-argument
        if len(val) != 6:
            raise TypeError("Incorrect number of values for FREEZE line", val)
        self.freeze_table.append(val)

    def add_to_state_table(self, param_name, val):
        # pylint: disable=unused-argument
        if len(val) < 2 or len(val) > 3:
            raise TypeError("Incorrect number of values for STATE line", val)
        self.state_table.append(val)

    parser_type = collections.namedtuple("parser_type", ("parser", "add_action"))
    log_parse = {
        "$_SM_DEPTHo": parser_type(float32_cnv, add_to_global_table),
        "$_SM_ANGLEo": parser_type(float32_cnv, add_to_global_table),
        "$TGT_NAME": parser_type(str_cnv, add_to_global_table),
        "$MHEAD_RNG_PITCHd_Wd": parser_type(float32_cnv, add_to_global_table),
        "$D_GRID": parser_type(float32_cnv, add_to_global_table),
        "$ID": parser_type(float32_cnv, add_to_global_table),
        "$DIVE": parser_type(float32_cnv, add_to_global_table),
        "$HUMID": parser_type(float32_cnv, add_to_global_table),
        "$TEMP": parser_type(float32_cnv, add_to_global_table),
        "$INTERNAL_PRESSURE": parser_type(float32_cnv, add_to_global_table),
        "$24V_AH": parser_type(float32_cnv, add_to_global_table),
        "$10V_AH": parser_type(float32_cnv, add_to_global_table),
        "$FG_AHR_24Vo": parser_type(float32_cnv, add_to_global_table),
        "$FG_AHR_10Vo": parser_type(float32_cnv, add_to_global_table),
        "$SDFILEDIR": parser_type(float32_cnv, add_to_global_table),
        "$MAGCAL": parser_type(float32_cnv, add_to_global_table),
        "$IMPLIED_C_PITCH": parser_type(float32_cnv, add_to_global_table),
        "$IMPLIED_C_VBD": parser_type(float32_cnv, add_to_global_table),
        "$FINISH": parser_type(float32_cnv, add_to_global_table),
        "$FINISH1": parser_type(float32_cnv, add_to_global_table),
        "$GPS": parser_type(gps_cnv, add_to_global_table),
        "$GC": parser_type(float32_cnv, add_to_gc_table),
        "$MODEM": parser_type(float32_cnv, add_to_modem_table),
        "$STATE": parser_type(state_cnv, add_to_state_table),
        "$FREEZE": parser_type(float32_cnv, add_to_freeze_table),
    }

    def parse_log_line(self, rs):
        """Parses a log file line and adds the results to the correct table"""
        splits = rs.split(",")
        tag = splits[0]
        if tag not in self.log_parse:
            raise LookupError("Unknown logfile param", tag)
        vals = self.log_parse[tag].parser(self, splits[1:])
        self.log_parse[tag].add_action(self, tag, vals)


#
# nlog helpers end here
#


def make_netcdf_network_file(network_logfile, network_profile, ts_outputfile=False):
    """Creates a network netcdf file, from either or both of the arguments

    Returns:
        Name of network netcdf file or None
    """
    if not os.path.isfile(network_logfile) and not os.path.isfile(network_profile):
        log_error(f"Neither {network_logfile} nor {network_logfile} exits")
        return None

    log_info(f"Processing {network_logfile} {network_profile}")

    dso = xr.Dataset()

    dive_number = int(os.path.split(network_logfile)[1][4:8])
    glider_number_str = os.path.split(network_logfile)[1][1:4]
    create_ds_var(dso, var_template, "dive_number", dive_number)

    time_v = None

    if not os.path.isfile(network_profile):
        log_warning(f"{network_profile} not found - skipping")
    else:
        try:
            with open(network_profile, "r") as fi:
                for ll in fi.readlines():
                    if ll.startswith("%first_bin_depth"):
                        first_bin_depth = float(ll.split(":")[1])
                    elif ll.startswith("%bin_width"):
                        bin_width = float(ll.split(":")[1])
            data = np.genfromtxt(
                network_profile, comments="%", names=("temperature", "salinity")
            )
            depth = np.linspace(
                first_bin_depth,
                first_bin_depth + (bin_width * len(data["temperature"])),
                num=len(data["temperature"]),
                endpoint=False,
            )
            create_ds_var(dso, var_template, "depth", depth)
            for var_name in ("temperature", "salinity"):
                tmp_v = np.array((data[var_name], np.full(len(data[var_name]), np.nan)))
                create_ds_var(dso, var_template, var_name, tmp_v)
            time_v = np.array(
                (
                    np.full(len(data[var_name]), np.nan),
                    np.full(len(data[var_name]), np.nan),
                )
            )
        except:
            log_error(f"Failed processing {network_profile}", "exc")

    if not os.path.isfile(network_logfile):
        log_warning(f"{network_logfile} not found - skipping")
    else:
        try:
            raw_network_logfile = open(network_logfile, "rb")
        except:
            log_error(f"Failed opening {network_logfile}", "exc")
        else:
            lp = log_parser()
            line_count = 0
            start_time = 0
            while True:
                line_count += 1
                try:
                    raw_line = raw_network_logfile.readline().decode()
                except UnicodeDecodeError:
                    log_error(
                        f"Could not process line {line_count} of {network_logfile}"
                    )
                    continue
                raw_line = raw_line.rstrip()
                if raw_line == "":
                    break

                try:
                    if raw_line.startswith("$"):
                        lp.parse_log_line(raw_line)
                    elif raw_line.startswith("start:"):
                        try:
                            if "," in raw_line:
                                time_string = raw_line.split(",", maxsplit=1)[1]
                            else:
                                time_string = raw_line.split(":", maxsplit=1)[1]
                            start_time = Utils.parse_time(time_string)
                        except:
                            log_error(
                                f"Could not process start line {line_count} of {network_logfile} - skipping",
                                "exc",
                            )
                    else:
                        pass
                        # This is the first line in the .nlog
                        # ts = parse_timestamp(raw_line)
                except LookupError as e:
                    log_error(
                        f"{e.args[0]} {e.args[1]} line {line_count} of {network_logfile} - skipping",
                    )
                except:
                    log_error(
                        f"Could not process {line_count} of {network_logfile} - skipping",
                        "exc",
                    )
        raw_network_logfile.close()

        create_ds_var(dso, var_template, "start_time", start_time)

        if time_v is not None:
            # Use this since its closer to the downcast, as opposed to GPS which is the
            # end of the upcast.
            time_v[0, 0] = start_time

        # Regular logfile values
        for name, data in lp.global_table.items():
            create_ds_var(
                dso, var_template, "log_" + name[1:], data if len(data) > 1 else data[0]
            )

        # Merged GC/State table
        gc_time = []
        full_gc_table = None
        for ll in lp.gc_table:
            ll[0] += start_time
            gc_time.append(ll[0])
            new_row = np.append(ll, [np.nan, np.nan])
            if full_gc_table is None:
                full_gc_table = new_row
            else:
                full_gc_table = np.vstack([full_gc_table, new_row])
        for ll in lp.state_table:
            ll[0] += start_time
            gc_time.append(ll[0])
            full_gc_table = np.vstack(
                [full_gc_table, np.append(ll[0], np.append([np.nan] * 9, ll[1:]))]
            )
        rc = np.array(gc_time, np.float32)
        # Wrong solution - complete sorts rows and coloumns
        # data = np.sort(full_gc_table, axis=0)

        # Sort the table by the first column
        data = full_gc_table[full_gc_table[:, 0].argsort()]

        # Convert time to epoch time
        create_ds_var(dso, var_template, "log_GC", data, row_coord=rc)

        # Modem and FREEZE tables
        for tab, var_name in (
            ("modem_table", "log_MODEM"),
            ("freeze_table", "log_FREEZE"),
        ):
            t_table = None
            for ll in getattr(lp, tab):
                if t_table is None:
                    t_table = np.array(ll)
                else:
                    t_table = np.vstack([t_table, ll])

            if t_table is not None:
                if len(np.shape(t_table)) == 1:
                    # Convert to a 1xN table - makes the netcdf creation go.
                    t_table = np.reshape(t_table, (1, np.shape(t_table)[0]))
                rc = np.arange(np.shape(t_table)[0])
                create_ds_var(dso, var_template, var_name, t_table, row_coord=rc)

    if time_v is not None:
        create_ds_var(dso, var_template, "time", time_v)

    # Write out the netcdf file - netcdf 4, compressed variables
    comp = dict(zlib=True, complevel=9)
    encoding = {var: comp for var in dso.data_vars}
    #
    # From GliderDac - used for string variables.  Might be needed - this was need because
    # some issues with matlab reading the string variables
    #
    # encoding = {}
    # for var in dso.data_vars:
    #     encoding[var] = comp.copy()
    #     if var_template["variables"][var]["type"] == "c":
    #         encoding[var]["char_dim_name"] = var_template["variables"][var][
    #             "dimensions"
    #         ][0]

    if ts_outputfile and "start_time" in dso:
        start_ts = time.strftime("%Y%m%dT%H%M", time.gmtime(int(dso["start_time"])))

        file_name = f"sg{glider_number_str}_{start_ts}.ncdf"
        ncf_filename = os.path.join(os.path.split(network_logfile)[0], file_name)
    else:
        ncf_filename = network_logfile[: network_logfile.rfind(".nlog")] + ".ncdf"
    log_info(f"Creating {ncf_filename}")

    dso.to_netcdf(
        ncf_filename,
        "w",
        encoding=encoding,
        engine="netcdf4",
        format="NETCDF3_CLASSIC",
    )
    return ncf_filename


def make_netcdf_network_files(network_files, processed_files_list):
    """Takes a list of network files and produces netcdf output files

    Input:
        base_opts - basestation options object
        network_files - list of processed network files
                        (need not have both log and profile for all dives)
        processed_files_list - list to append the names of the created files to

    Returns:
        0 - success
        non-zero - failure
    """

    ret_val = 0

    # Add missing files, remove non-network files
    net_files = collections.defaultdict(set)
    for nf in network_files:
        dive_num = int(os.path.split(nf)[1][4:8])

        if nf.endswith(".nlog"):
            net_files[dive_num].add(nf[: nf.rfind(".nlog")] + ".npro")
        elif nf.endswith(".npro"):
            net_files[dive_num].add(nf[: nf.rfind(".npro")] + ".nlog")
        else:
            log_warning(f"{nf} is not a network file - skipping")
            continue
        net_files[dive_num].add(nf)

    for _, files in net_files.items():
        dive_net_files = sorted(files)
        try:
            ncf_filename = make_netcdf_network_file(*dive_net_files)
        except:
            log_error(f"Failed to create cdf file from {dive_net_files}", "exc")
            ret_val = 1
        else:
            if ncf_filename:
                processed_files_list.append(ncf_filename)

    log_info(processed_files_list)
    return ret_val


def make_netcdf_network_file_from_perdive(ncf_filename, ts_outputfile=False):
    """Processes a per-dive glider netcdf file into a network ncf file"""

    # These match the current on-board binning routine
    # TODO - make these configurable
    bin_width = 5.0
    first_bin_depth = 7.5

    dsi = xr.open_dataset(ncf_filename)

    if ts_outputfile:
        start_ts = time.strftime("%Y%m%dT%H%M", time.gmtime(dsi.attrs["start_time"]))
        file_name = f"{dsi.attrs['platform_id'].lower()}_{start_ts}.ncdf"
        ncf_output_filename = os.path.join(os.path.split(ncf_filename)[0], file_name)
    else:
        ncf_output_filename = ncf_filename[: ncf_filename.rfind(".nc")] + ".ncdf"
    log_info(f"Creating {ncf_output_filename}")

    # Temperature/Salinity
    if set(("temperature", "salinity", "ctd_depth", "ctd_time")).issubset(
        set(dsi.variables)
    ):
        dso = xr.Dataset()
        max_depth = np.floor(np.nanmax(dsi["ctd_depth"]))
        bin_centers = np.arange(first_bin_depth, max_depth + 0.01, bin_width)
        create_ds_var(dso, var_template, "depth", bin_centers)
        # Find mid-points between centers
        bin_edges = (bin_centers[1:] + bin_centers[:-1]) / 2.0
        # Add edges to grab everything into the first and last bin
        bin_edges = np.append(-20, np.append(bin_edges, max_depth + 50.0))

        max_depth_i = int(dsi["ctd_depth"].argmax())
        ctd_time = dsi["ctd_time"].data.astype(np.float64) / 1000000000.0
        t_down = NetCDFUtils.interp1_extend(
            dsi["ctd_depth"][:max_depth_i], ctd_time[:max_depth_i], bin_centers
        )
        t_up = NetCDFUtils.interp1_extend(
            dsi["ctd_depth"][max_depth_i:],
            ctd_time[max_depth_i:],
            bin_centers[::-1],
        )
        time_v = np.array((t_down, t_up))
        create_ds_var(dso, var_template, "time", time_v)

        for vvar in ("temperature", "salinity"):
            binned_data_down, *_ = NetCDFUtils.bindata(
                dsi["ctd_depth"][:max_depth_i], dsi[vvar][:max_depth_i], bin_edges
            )
            binned_data_up, *_ = NetCDFUtils.bindata(
                dsi["ctd_depth"][max_depth_i:], dsi[vvar][max_depth_i:], bin_edges
            )
            create_ds_var(
                dso, var_template, vvar, np.array((binned_data_down, binned_data_up))
            )

        # GPS positions
        log_gps_time = dsi["log_gps_time"].data.astype(np.float64) / 1000000000.0

        for ii, gps_name in ((1, "log_GPS2"), (2, "log_GPS")):
            create_ds_var(
                dso,
                var_template,
                gps_name,
                np.array(
                    (
                        log_gps_time[ii],
                        dsi["log_gps_lat"][ii],
                        dsi["log_gps_lon"][ii],
                        dsi["log_gps_hdop"][ii],
                    )
                ),
            )
        # Simple log file
        for log_var_name in (
            "log__SM_DEPTHo",
            "log__SM_ANGLEo",
            "log_MHEAD_RNG_PITCHd_Wd",
            "log_D_GRID",
            "log_HUMID",
            "log_TEMP",
            "log_INTERNAL_PRESSURE",
            "log_24V_AH",
            "log_10V_AH",
            "log_FG_AHR_24Vo",
            "log_FG_AHR_10Vo",
            "log_SDFILEDIR",
            "log_MAGCAL",
            "log_IMPLIED_C_PITCH",
            "log_IMPLIED_C_VBD",
            "log_FINISH",
        ):
            if log_var_name not in dsi.variables:
                continue
            if dsi[log_var_name].data.dtype.type is np.string_:
                data = np.array(
                    dsi[log_var_name].data.tobytes().decode().split(","),
                    np.float32,
                )
            else:
                data = dsi[log_var_name].data

            create_ds_var(
                dso,
                var_template,
                log_var_name,
                data,
            )

        create_ds_var(dso, var_template, "log_TGT_NAME", dsi["log_TGT_NAME"])

        create_ds_var(dso, var_template, "dive_number", dsi.dive_number)
        create_ds_var(dso, var_template, "start_time", dsi.start_time)

        # GC table

        gc_st_secs = dsi["gc_st_secs"].data.astype(np.float64) / 1000000000.0
        full_gc_table = np.vstack(
            (
                gc_st_secs,
                dsi["gc_depth"],
                dsi["gc_ob_vertv"],
                dsi["gc_vbd_i"],
                dsi["gc_pitch_i"],
                dsi["gc_roll_i"],
                dsi["gc_vbd_ad"],
                dsi["gc_pitch_ad"],
                dsi["gc_roll_ad"],
                dsi["gc_vbd_volts"],
                np.full(len(gc_st_secs), np.nan),
                np.full(len(gc_st_secs), np.nan),
            )
        ).transpose()

        gc_state_secs = dsi["gc_state_secs"].data.astype(np.float64) / 1000000000.0
        for ii in range(len(gc_state_secs)):
            full_gc_table = np.vstack(
                [
                    full_gc_table,
                    np.append(
                        np.append(gc_state_secs[ii], [np.nan] * 9),
                        [
                            dsi["gc_state_state"].data[ii].astype(np.float64),
                            dsi["gc_state_eop_code"].data[ii].astype(np.float64),
                        ],
                    ),
                ]
            )

        # Sort the table by the first column
        gc_table = full_gc_table[full_gc_table[:, 0].argsort()]

        create_ds_var(
            dso, var_template, "log_GC", gc_table, row_coord=full_gc_table[:, 0]
        )

        # TODO: Modem table - not yet in the per-dive netcdf files

        # Write out the netcdf file - netcdf 4, compressed variables
        comp = dict(zlib=True, complevel=9)
        encoding = {var: comp for var in dso.data_vars}
        dso.to_netcdf(
            ncf_output_filename,
            "w",
            encoding=encoding,
            # engine="netcdf4",
            format="netCDF4",
        )
        return ncf_output_filename
    return None


def make_netcdf_network_file_from_perdive_files(
    ncf_filenames, processed_files_list=None
):
    """Processes a list of glider per-dive netcdf files to network ncf file format"""
    ret_val = 0

    for ncf_filename in ncf_filenames:
        try:
            ncf_output_filename = make_netcdf_network_file_from_perdive(ncf_filename)
        except:
            if DEBUG_PDB:
                _, _, tracebk = sys.exc_info()
                traceback.print_exc()
                pdb.post_mortem(tracebk)
            log_error(
                f"Unhandled exception in processing {ncf_filename}-- skipping", "exc"
            )
        else:
            if ncf_output_filename and processed_files_list is not None:
                processed_files_list.append(ncf_output_filename)
    return ret_val


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
    """cli test/utility for network file processing and limited basestation extension

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
            "cmdline entry for basestation network file processing",
            additional_arguments={
                "log_in_file": BaseOpts.options_t(
                    "",
                    ("BaseNetwork",),
                    ("log_in_file",),
                    str,
                    {
                        "help": "Compressed network logfile",
                        "action": BaseOpts.FullPathAction,
                        "subparsers": ("log",),
                    },
                ),
                "log_out_file": BaseOpts.options_t(
                    "",
                    ("BaseNetwork",),
                    ("log_out_file",),
                    str,
                    {
                        "help": "Plain-text network logfile",
                        "action": BaseOpts.FullPathAction,
                        "subparsers": ("log",),
                        "nargs": "?",
                    },
                ),
                "pro_in_file": BaseOpts.options_t(
                    "",
                    ("BaseNetwork",),
                    ("pro_in_file",),
                    str,
                    {
                        "help": "Compressed network ct profile",
                        "action": BaseOpts.FullPathAction,
                        "subparsers": ("pro",),
                    },
                ),
                "pro_out_file": BaseOpts.options_t(
                    "",
                    ("BaseNetwork",),
                    ("pro_out_file",),
                    str,
                    {
                        "help": "Plain-text network ct profile",
                        "action": BaseOpts.FullPathAction,
                        "subparsers": ("pro",),
                        "nargs": "?",
                    },
                ),
                "network_files": BaseOpts.options_t(
                    "",
                    ("BaseNetwork",),
                    ("network_files",),
                    str,
                    {
                        "help": "List of network files to process",
                        "nargs": "+",
                        "action": BaseOpts.FullPathAction,
                        "subparsers": ("cdf",),
                    },
                ),
                "netcdf_files": BaseOpts.options_t(
                    "",
                    ("BaseNetwork",),
                    ("netcdf_files",),
                    str,
                    {
                        "help": "List of per-dive netcdf files to process",
                        "nargs": "+",
                        "action": BaseOpts.FullPathAction,
                        "subparsers": ("ncf",),
                    },
                ),
            },
        )

    BaseLogger(base_opts, include_time=True)

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    ret_val = 0
    if not hasattr(base_opts, "subparser_name"):
        # Called as a basestation extension
        ret_val = make_netcdf_network_file_from_perdive_files(
            nc_files_created, processed_other_files
        )
    elif base_opts.subparser_name == "ncf":
        processed_files_list = []
        ret_val = make_netcdf_network_file_from_perdive_files(
            base_opts.netcdf_files, processed_files_list
        )
        log_info(f"Created {processed_files_list}")
    elif base_opts.subparser_name == "log":
        ret_val = convert_network_logfile(
            base_opts, base_opts.log_in_file, base_opts.log_out_file
        )
        if ret_val is None:
            ret_val = 1
        else:
            ret_val = 0
    elif base_opts.subparser_name == "pro":
        ret_val = convert_network_profile(base_opts.pro_in_file, base_opts.pro_out_file)
        if ret_val is None:
            ret_val = 1
        else:
            ret_val = 0
    elif base_opts.subparser_name == "cdf":
        processed_files_list = []
        ret_val = make_netcdf_network_files(
            base_opts.network_files, processed_files_list
        )
        log_info(f"Created {processed_files_list}")

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
        main()
    except SystemExit:
        pass
    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting", "exc")
