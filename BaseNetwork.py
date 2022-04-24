#! /usr/bin/env python
# -*- python-fmt -*-
##
## Copyright (c) 2022 by University of Washington.  All rights reserved.
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
Processes network files
"""

# TODO Add state and eop decoding into a comment for GC table


import collections
import os
import pdb
import sys
import time
import traceback

import numpy as np
import xarray as xr

from BaseLog import BaseLogger, log_error, log_info, log_critical, log_warning
import BaseOpts
import LogFile
import Utils

DEBUG_PDB = "darwin" in sys.platform

var_template = {
    "variables": {
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
        "log_GPS": {
            "type": "f8",
            "num_digits": 4,
            "attributes": {
                "_FillValue": -999,
                "comment": "Position fix for dive",
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


def convert_network_logfile(in_file_name, out_file_name):
    """Converts a network log/eng file to text output

    Returns:
        0 - success
        1 - failure
    """

    convertor = "/usr/local/bin/log"

    if not os.path.isfile(convertor):
        log_error(
            f"Convertor {convertor} does not exits - not processing {in_file_name}"
        )
        return 1

    if not os.access(convertor, os.X_OK):
        log_error(
            f"Convertor {convertor} is not marked as executable - not processing {in_file_name}"
        )
        return 1

    if not os.path.isfile(in_file_name):
        log_error(f"{in_file_name} does not exits")
        return 1

    cmdline = f"{convertor} {in_file_name}"
    log_info(f"Running {cmdline}")
    try:
        (sts, run_output) = Utils.run_cmd_shell(cmdline, timeout=10)
    except:
        log_error(f"Error running {cmdline}", "exc")
        return 1

    if sts is None:
        log_error(
            f"Error running {cmdline} - timeout", "exc", alert="CONVERSION_TIMEOUT"
        )
        return 1

    if sts >> 8:
        error = ""
        for l in run_output:
            error += l.decode()
        log_error(f"Error running {cmdline} - {error}")

        return 1

    try:
        fo = open(out_file_name, "wb")
    except:
        log_error(f"Failed to open {out_file_name}")
        return 1

    for l in run_output:
        fo.write(l)
    fo.close()

    return 0


def convert_network_profile(in_file_name, out_file_name):
    """Converts a network ct profile plain text output

    Returns:
        0 - success
        1 - failure
    """

    convertor = "/usr/local/bin/x3decode_ts"

    if not os.path.isfile(convertor):
        log_error(
            f"Convertor {convertor} does not exits - not processing {in_file_name}"
        )
        return 1

    if not os.access(convertor, os.X_OK):
        log_error(
            "Convertor (%s) is not marked as executable - not processing %s"
            % (convertor, in_file_name)
        )
        return 1

    if not os.path.isfile(in_file_name):
        log_error(f"{in_file_name} does not exits")
        return 1

    cmdline = f"{convertor} -i {in_file_name} -o {out_file_name}"
    log_info(f"Running {cmdline}")
    try:
        (sts, fo) = Utils.run_cmd_shell(cmdline, timeout=10)
    except:
        log_error(f"Error running {cmdline}", "exc")
        return 1

    if sts is None:
        log_error(
            f"Error running {cmdline} - timeout", "exc", alert="CONVERSION_TIMEOUT"
        )
        return 1

    if sts >> 8:
        error = ""
        for l in fo:
            error += l.decode()
        log_error(f"Error running {cmdline} - {error}")

        return 1

    return 0


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
        "$GPS": parser_type(gps_cnv, add_to_global_table),
        "$GC": parser_type(float32_cnv, add_to_gc_table),
        "$MODEM": parser_type(float32_cnv, add_to_modem_table),
        "$STATE": parser_type(state_cnv, add_to_state_table),
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


def make_netcdf_netork_file(network_logfile, network_profile):
    """Creates a network netcdf file, from either or both of the arguments

    Returns:
        Name of network netcdf file or None
    """
    if not os.path.isfile(network_logfile) and not os.path.isfile(network_profile):
        log_error(f"Neither {network_logfile} nor {network_logfile} exits")
        return None

    ncf_filename = network_logfile[: network_logfile.rfind(".nlog")] + ".ncdf"
    log_info(f"Creating {ncf_filename}")

    dso = xr.Dataset()

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

        # Modem table
        modem_table = None
        for ll in lp.modem_table:
            if modem_table is None:
                modem_table = ll
            else:
                modem_table = np.vstack([modem_table, ll])

        rc = np.arange(np.shape(modem_table)[0])
        create_ds_var(dso, var_template, "log_MODEM", modem_table, row_coord=rc)

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
    dso.to_netcdf(
        ncf_filename,
        "w",
        encoding=encoding,
        # engine="netcdf4",
        format="netCDF4",
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
        ncf_filename = make_netcdf_netork_file(*sorted(files))
        if ncf_filename:
            processed_files_list.append(ncf_filename)

    return ret_val


def main():
    """cli test/utility for network file processing

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    # pylint: disable=unused-argument
    base_opts = BaseOpts.BaseOptions(
        "cmdline entry for basestation network file processing",
        additional_arguments={
            "log_in_file": BaseOpts.options_t(
                None,
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
                None,
                ("BaseNetwork",),
                ("log_out_file",),
                str,
                {
                    "help": "Plain-text network logfile",
                    "action": BaseOpts.FullPathAction,
                    "subparsers": ("log",),
                },
            ),
            "pro_in_file": BaseOpts.options_t(
                None,
                ("BaseNetwork",),
                ("pro_in_file",),
                str,
                {
                    "help": "Compressed network logfile",
                    "action": BaseOpts.FullPathAction,
                    "subparsers": ("pro",),
                },
            ),
            "pro_out_file": BaseOpts.options_t(
                None,
                ("BaseNetwork",),
                ("pro_out_file",),
                str,
                {
                    "help": "Plain-text network logfile",
                    "action": BaseOpts.FullPathAction,
                    "subparsers": ("pro",),
                },
            ),
            "network_files": BaseOpts.options_t(
                None,
                ("BaseNetwork",),
                ("network_files",),
                str,
                {
                    "help": "List of files to process",
                    "nargs": "+",
                    "action": BaseOpts.FullPathAction,
                    "subparsers": ("cdf",),
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
    if base_opts.subparser_name == "log":
        ret_val = convert_network_logfile(base_opts.log_in_file, base_opts.log_out_file)
    elif base_opts.subparser_name == "pro":
        ret_val = convert_network_profile(base_opts.pro_in_file, base_opts.pro_out_file)
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
