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

"""
Processes network files
"""

import collections
import io
import os
import pathlib
import pdb
import sys
import time
import traceback
import typing

import numpy as np
import xarray as xr

import BaseDB
import BaseOpts
import BaseOptsType
import LogFile
import NetCDFUtils
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


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
        # WetLabs (.npro_wl.dat) network profile variables. Raw telemetry
        # counts, not yet calibrated (that only happens in the full per-dive
        # pipeline - see Plotting/DiveWetlabs.py/Sensors/WETlabs_ext.py) -
        # this is just a quick preview. wl_depth is a separate bin grid from
        # "depth" above since the wl and ct sensors can report different
        # first_bin_depth/bin_width values for the same dive.
        "wl_depth": {
            "type": "f4",
            "num_digits": 2,
            "dimensions": ["wl_depth_data_point"],
            "attributes": {
                "_FillValue": -999,
                "long_name": "WetLabs profile depth",
                "standard_name": "depth",
                "units": "m",
            },
        },
        "sig470nm": {
            "type": "f4",
            "num_digits": 1,
            "dimensions": ["wl_depth_data_point"],
            "attributes": {
                "_FillValue": -999,
                "long_name": "Blue scattering (raw counts)",
                "units": "counts",
            },
        },
        "sig700nm": {
            "type": "f4",
            "num_digits": 1,
            "dimensions": ["wl_depth_data_point"],
            "attributes": {
                "_FillValue": -999,
                "long_name": "Red scattering (raw counts)",
                "units": "counts",
            },
        },
        "sig695nm": {
            "type": "f4",
            "num_digits": 1,
            "dimensions": ["wl_depth_data_point"],
            "attributes": {
                "_FillValue": -999,
                "long_name": "Chlorophyll fluorescence (raw counts)",
                "units": "counts",
            },
        },
        "temp": {
            "type": "f4",
            "num_digits": 1,
            "dimensions": ["wl_depth_data_point"],
            "attributes": {
                "_FillValue": -999,
                "long_name": "WetLabs puck internal temperature (raw counts)",
                "comment": "Not sea water temperature - see the 'temperature' variable for that.",
                "units": "counts",
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
        "log_EXED": {
            "type": "c",
            "attributes": {
                "comment": "Exed commands",
            },
            "coord_cols": [
                "name",
                "seqnum",
                "why",
            ],
            "coord_row": "log_EXED_data_points",
        },
        "log_WARN": {
            "type": "c",
            "attributes": {
                "comment": "WARN messages",
            },
            "coord_cols": [
                "warning",
            ],
            "coord_row": "log_WARN_data_points",
        },
        "log_NET_PING": {
            "type": "f8",
            "attributes": {
                "_FillValue": -999,
                "comment": "Network messages",
            },
            "coord_cols": [
                "time",
                "connectedtop",
                "range",
                "SNR",
            ],
            "coord_row": "log_NET_PING_data_points",
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
def fix_ints(data_type: type, attrs: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Convert int values from LL (json format) to appropriate size per gliderdac specs

    Args:
        data_type: Numpy scalar type to cast int-valued attributes to.
        attrs: Attribute dictionary to convert.

    Returns:
        A new attribute dictionary with int values cast to data_type.
    """
    new_attrs = {}
    for k, v in attrs.items():
        if isinstance(type(v), int):
            new_attrs[k] = data_type(v)
        elif k == "flag_values":
            new_attrs[k] = [data_type(li) for li in v]
        else:
            new_attrs[k] = v
    return new_attrs


def create_ds_var(
    dso: xr.Dataset,
    template: dict[str, typing.Any],
    var_name: str,
    data: typing.Any,
    row_coord: np.ndarray | None = None,
) -> xr.DataArray:
    """Creates a DataSet variable with metadata

    Args:
        dso: Output dataset.
        template: Dictionary of variable metadata.
        var_name: Name of variable as it appears in template.
        data: Input data - scalar, string, or array-like.
        row_coord: Array for row coordinates.

    Returns:
        The created DataArray for the variable (also assigned into dso).
    """
    if isinstance(data, str):
        inp_data = np.array(data, dtype=np.dtype(("S", len(data))))
    elif template["variables"][var_name]["type"] == "c":
        # This includes singleton strings
        inp_data = data
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
        if "_FillValue" in template["variables"][var_name]["attributes"]:
            inp_data[inp_data == np.nan] = template["variables"][var_name][  # ty: ignore[invalid-assignment]
                "attributes"
            ]["_FillValue"]

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


def _sglog_pythonpath_env(base_opts: BaseOpts.BaseOptions) -> dict[str, str] | None:
    """Builds an env with PYTHONPATH set for an sglog checkout under
    base_opts.basestation_directory/log/src, if one is present."""
    sglog_src = base_opts.basestation_directory / "log" / "src"
    if not (sglog_src / "sglog" / "cli.py").is_file():
        return None
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{sglog_src}{os.pathsep}{existing}" if existing else str(sglog_src)
    )
    return env


def convert_network_logfile(
    base_opts: BaseOpts.BaseOptions,
    in_file_name: pathlib.Path,
    out_file_name: pathlib.Path | None,
) -> pathlib.Path | None:
    """Converts a network log/eng file to text output

    Args:
        base_opts: Basestation options object.
        in_file_name: Path to the compressed network logfile.
        out_file_name: Path to the output file, or None. If None, the
            output name is derived from the compressed eng header info,
            in the same directory as the input file.

    Returns:
        Path to the converted output file, or None on failure.
    """

    env: dict[str, str] | None = None

    if base_opts.network_log_decompressor:
        convertor = base_opts.network_log_decompressor
        cmdline = f"{convertor} {in_file_name}"
    else:
        sglog_env = _sglog_pythonpath_env(base_opts)
        if sglog_env is not None:
            convertor = pathlib.Path(sys.executable)
            env = sglog_env
            cmdline = f"{sys.executable} -m sglog {in_file_name}"
        else:
            convertor = pathlib.Path("/usr/local/bin/log")
            cmdline = f"{convertor} {in_file_name}"

    if not convertor.is_file():
        log_error(
            f"Convertor {convertor} does not exit - not processing {in_file_name}"
        )
        return None

    if not os.access(convertor, os.X_OK):
        log_error(
            f"Convertor {convertor} is not marked as executable - not processing {in_file_name}"
        )
        return None

    if not in_file_name.is_file():
        log_error(f"{in_file_name} does not exist")
        return None

    log_info(f"Running {cmdline}")
    try:
        (sts, run_output) = Utils.run_cmd_shell(cmdline, timeout=10, env=env)
    except Exception:
        log_error(f"Error running {cmdline}", "exc")
        return None

    if sts is None:
        log_error(
            f"Error running {cmdline} - timeout", "exc", alert="CONVERSION_TIMEOUT"
        )
        return None

    if sts:
        error = ""
        if run_output is not None:
            for ll in run_output:
                error += ll.decode()
        log_error(f"Error running {cmdline} - {error}")

        return None

    if out_file_name is None:
        try:
            # So we can seek to the start
            run_output = io.BytesIO(run_output.read())  # ty: ignore[unresolved-attribute]
            sgid = divenum = None
            for ll in run_output.readlines():
                ll = ll.decode()
                if ll.startswith("$ID,"):
                    sgid = float(ll.rstrip()[4:])
                elif ll.startswith("$DIVE,"):
                    divenum = float(ll.rstrip()[6:])
            if sgid is None or sgid < 100.0 or divenum is None or divenum < 0:
                log_debug(f"Could not formulate file name for {in_file_name}")
                return None
            run_output.seek(0)
            out_file_name = in_file_name.parent / (
                f"p{int(sgid):03d}{int(divenum):04d}.nlog"
            )
        except Exception:
            log_error("Failed to format out_file_name", "exc")
            return None

    try:
        with out_file_name.open("wb") as fo:
            if run_output is not None:
                for ll in run_output:
                    fo.write(ll)
    except Exception:
        log_error(f"Failed to process {out_file_name}")
        return None

    return out_file_name


def convert_network_profile(
    base_opts: BaseOpts.BaseOptions,
    in_file_name: pathlib.Path,
    out_file_name: pathlib.Path | None,
) -> pathlib.Path | None:
    """Converts a network ct profile plain text output

    Args:
        base_opts: Basestation options object.
        in_file_name: Path to the compressed network ct profile.
        out_file_name: Path to the output file, or None. If None, the
            output name is derived from the compressed profile header
            info, in the same directory as the input file.

    Returns:
        Path to the converted output file, or None on failure.
    """

    convertor = base_opts.network_profile_decompressor or pathlib.Path(
        "/usr/local/bin/x3decode_ts"
    )

    if not convertor.is_file():
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

    if not in_file_name.is_file():
        log_error(f"{in_file_name} does not exists")
        return None

    if out_file_name is None:
        # See if there is enough meta data to build the new file name
        try:
            with in_file_name.open("rb") as fi:
                header = fi.readline()
                splits = header.decode().split(" ")
                if len(splits) >= 4:
                    out_file_name = in_file_name.parent / (
                        f"p{splits[2][2:]}{splits[3][2:6]}.npro"
                    )
        except Exception:
            log_error("Failed to format out_file_name", "exc")
            return None

    if out_file_name is None:
        log_debug(f"Could not formulate output file name for {in_file_name}")
        return out_file_name

    cmdline = f"{convertor} -i {in_file_name} -o {out_file_name}"
    log_info(f"Running {cmdline}")
    try:
        (sts, fo) = Utils.run_cmd_shell(cmdline, timeout=10)
    except Exception:
        log_error(f"Error running {cmdline}", "exc")
        return None

    if sts is None:
        log_error(
            f"Error running {cmdline} - timeout", "exc", alert="CONVERSION_TIMEOUT"
        )
        return None

    if sts:
        error = ""
        if fo is not None:
            for ll in fo:
                error += ll.decode()
        log_error(f"Error running {cmdline} - {error}")

        return None

    return out_file_name


# def parse_timestamp(rs):
#     """Convert a timestamp string into a list of ints"""
#     splits = rs.split()
#     return [int(x) for x in splits]


class log_parser:
    """Machinery for parsing a network log file"""

    # pylint: disable=no-self-use

    def __init__(self) -> None:
        """Initializes empty parse tables."""
        self.global_table: dict[str, typing.Any] = {}
        self.gc_table: list[np.ndarray] = []
        self.state_table: list[list[typing.Any]] = []
        self.modem_table: list[np.ndarray] = []
        self.freeze_table: list[np.ndarray] = []
        self.exed_table: list[list[str]] = []
        self.warn_table: list[str] = []
        self.net_ping_table: list[np.ndarray] = []

    # Parsers
    def float32_cnv(self, x: list[str]) -> np.ndarray:
        """Converts comma-split values to a float32 array.

        Args:
            x: Comma-split string values.

        Returns:
            The values as a float32 numpy array.
        """
        return np.array(x, np.float32)

    def float64_cnv(self, x: list[str]) -> np.ndarray:
        """Converts comma-split values to a float64 array.

        Args:
            x: Comma-split string values.

        Returns:
            The values as a float64 numpy array.
        """
        return np.array(x, np.float64)

    def str_cnv(self, x: list[str]) -> str:
        """Returns the first value as a string.

        Args:
            x: Comma-split string values.

        Returns:
            The first value.
        """
        return str(x[0])

    def strs_cnv(self, x: list[str]) -> list[str]:
        """Passes comma-split string values through unchanged.

        Args:
            x: Comma-split string values.

        Returns:
            The input values, unmodified.
        """
        return x

    def state_cnv(self, x: list[str]) -> list[typing.Any]:
        """Converts a $STATE line's values.

        Args:
            x: Comma-split string values - time, state code, and an
                optional end-of-profile code.

        Returns:
            [time as float32, mapped state, mapped end-of-profile code or nan].
        """
        return [
            np.float32(x[0]),
            LogFile.map_state_code(x[1]),
            LogFile.map_eop_code(x[2]) if len(x) >= 3 else np.nan,
        ]

    def gps_cnv(self, x: list[str]) -> np.ndarray:
        """Converts a $GPS line's values to [time, lat, lon, hdop].

        Args:
            x: Comma-split string values - date, time, lat, lon, hdop.

        Returns:
            [epoch time, decimal latitude, decimal longitude, hdop].
        """
        ttime = time.mktime(time.strptime(x[1] + x[0], "%H%M%S%d%m%y"))
        lat = Utils.ddmm2dd(np.float64(x[2]))
        lon = Utils.ddmm2dd(np.float64(x[3]))
        hdop = np.float64(x[4])
        return np.array([ttime, lat, lon, hdop])

    def net_ping_cnv(self, x: list[str]) -> np.ndarray:
        """Converts a $NET_PING line's values to a float64 array.

        Args:
            x: Comma-split string values.

        Returns:
            The values as a float64 numpy array.
        """
        return np.array([np.float64(y) for y in x])

    # Adders
    def add_to_global_table(self, param_name: str, val: typing.Any) -> None:
        """Records a scalar parameter value under its tag name.

        Args:
            param_name: Log tag name (e.g. "$ID").
            val: Converted parameter value.
        """
        self.global_table[param_name] = val

    def add_to_gc_table(self, param_name: str, val: np.ndarray) -> None:
        """Appends a $GC line's values to the GC table.

        Args:
            param_name: Log tag name (unused, kept for a uniform adder signature).
            val: Converted GC line values, expected length 10.

        Raises:
            TypeError: If val does not have exactly 10 values.
        """
        # pylint: disable=unused-argument
        if len(val) != 10:
            raise TypeError("Incorrect number of values for GC line", val)
        self.gc_table.append(val)

    def add_to_modem_table(self, param_name: str, val: np.ndarray) -> None:
        """Appends a $MODEM line's values to the modem table.

        Args:
            param_name: Log tag name (unused, kept for a uniform adder signature).
            val: Converted MODEM line values, expected length 3.

        Raises:
            TypeError: If val does not have exactly 3 values.
        """
        # pylint: disable=unused-argument
        if len(val) != 3:
            raise TypeError("Incorrect number of values for MODEM line", val)
        self.modem_table.append(val)

    def add_to_freeze_table(self, param_name: str, val: np.ndarray) -> None:
        """Appends a $FREEZE line's values to the freeze table.

        Args:
            param_name: Log tag name (unused, kept for a uniform adder signature).
            val: Converted FREEZE line values, expected length 6.

        Raises:
            TypeError: If val does not have exactly 6 values.
        """
        # pylint: disable=unused-argument
        if len(val) != 6:
            raise TypeError("Incorrect number of values for FREEZE line", val)
        self.freeze_table.append(val)

    def add_to_state_table(self, param_name: str, val: list[typing.Any]) -> None:
        """Appends a $STATE line's values to the state table.

        Args:
            param_name: Log tag name (unused, kept for a uniform adder signature).
            val: Converted STATE line values, expected length 2 or 3.

        Raises:
            TypeError: If val does not have 2 or 3 values.
        """
        # pylint: disable=unused-argument
        if len(val) < 2 or len(val) > 3:
            raise TypeError("Incorrect number of values for STATE line", val)
        self.state_table.append(val)

    def add_to_exed_table(self, param_name: str, val: list[str]) -> None:
        """Appends a $EXED line's values to the exed table.

        Args:
            param_name: Log tag name (unused, kept for a uniform adder signature).
            val: Converted EXED line values, expected length 3.

        Raises:
            TypeError: If val does not have exactly 3 values.
        """
        # pylint: disable=unused-argument
        if len(val) != 3:
            raise TypeError("Incorrect number of values for EXED line", val)
        self.exed_table.append(val)

    def add_to_warn_table(self, param_name: str, val: str) -> None:
        """Appends a $WARN line's value to the warn table.

        Args:
            param_name: Log tag name (unused, kept for a uniform adder signature).
            val: Converted WARN line value - a single string.

        Raises:
            TypeError: If val is not a string and does not have exactly 1 value.
        """
        # pylint: disable=unused-argument
        if not isinstance(val, str) and len(val) != 1:
            raise TypeError("Incorrect number of values for WARN line", val)
        self.warn_table.append(val)

    def add_to_net_ping_table(self, param_name: str, val: np.ndarray) -> None:
        """Appends a $NET_PING line's values to the net ping table.

        Args:
            param_name: Log tag name (unused, kept for a uniform adder signature).
            val: Converted NET_PING line values, expected length 4.

        Raises:
            TypeError: If val does not have exactly 4 values.
        """
        # pylint: disable=unused-argument
        if len(val) != 4:
            raise TypeError("Incorrect number of values for NET_PING line", val)
        self.net_ping_table.append(val)

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
        "$EXED": parser_type(strs_cnv, add_to_exed_table),
        "$WARN": parser_type(str_cnv, add_to_warn_table),
        "$NET_PING": parser_type(net_ping_cnv, add_to_net_ping_table),
    }

    def parse_log_line(self, rs: str) -> None:
        """Parses a log file line and adds the results to the correct table

        Args:
            rs: A single comma-separated "$TAG,val1,val2,..." log line.

        Raises:
            LookupError: If the tag is not a recognized logfile parameter.
        """
        splits = rs.split(",")
        tag = splits[0]
        if tag not in self.log_parse:
            raise LookupError("Unknown logfile param", tag)
        vals = self.log_parse[tag].parser(self, splits[1:])
        self.log_parse[tag].add_action(self, tag, vals)


#
# nlog helpers end here
#


def _read_profile_header(
    profile_file: pathlib.Path, default_names: tuple[str, ...] | None = None
) -> tuple[float, float, tuple[str, ...]] | None:
    """Reads a network profile file's %key: value header.

    Args:
        profile_file: Path to the plain-text network profile file
            (.npro / .npro_ct.dat / .npro_wl.dat).
        default_names: Column names to use if the file has no
            "%columns:" header line (the legacy bare-.npro format never
            had one). None means the file is required to have one.

    Returns:
        (first_bin_depth, bin_width, column_names), or None if the
        header is incomplete.
    """
    first_bin_depth = None
    bin_width = None
    names = default_names
    with profile_file.open("r") as fi:
        for ll in fi.readlines():
            if ll.startswith("%first_bin_depth"):
                first_bin_depth = float(ll.split(":")[1])
            elif ll.startswith("%bin_width"):
                bin_width = float(ll.split(":")[1])
            elif ll.startswith("%columns:"):
                names = tuple(ll.split(":", 1)[1].split())

    if first_bin_depth is None or bin_width is None or names is None:
        log_error(
            f"Could not read first_bin_depth/bin_width/columns header from {profile_file}"
        )
        return None
    return first_bin_depth, bin_width, names


# Raw WetLabs .npro_wl.dat column names -> this project's canonical sensor
# variable names - mirrors Sensors/WETlabs_ext.py's columns_d synonym table
# (kept as a small standalone copy here rather than importing that module,
# since Sensors/ isn't a regular importable package - it's loaded as sensor
# extensions dynamically, not via static import).
WL_RAW_TO_CANONICAL = {
    "470sig": "sig470nm",
    "700sig": "sig700nm",
    "Chlsig": "sig695nm",
    "temp": "temp",
}


def make_netcdf_network_file(
    network_logfile: pathlib.Path,
    network_profile_ct: pathlib.Path,
    network_profile_wl: pathlib.Path | None = None,
    ts_outputfile: bool = False,
) -> pathlib.Path | None:
    """Creates a network netcdf file, from any of the arguments

    Args:
        network_logfile: Path to the plain-text network logfile.
        network_profile_ct: Path to the plain-text network ct (CTD)
            profile - either the legacy bare .npro format, or the newer
            .npro_ct.dat format.
        network_profile_wl: Path to the plain-text network wl (WetLabs
            optical) profile (.npro_wl.dat), if the dive has one.
        ts_outputfile: If True, name the output file from the embedded
            start time and platform id instead of the input filename.

    Returns:
        Path to the created network netcdf file, or None on failure.
    """
    if not network_logfile.is_file() and not network_profile_ct.is_file():
        log_error(f"Neither {network_logfile} nor {network_profile_ct} exists")
        return None

    log_info(f"Processing {network_logfile} {network_profile_ct} {network_profile_wl}")

    dso = xr.Dataset()

    dive_number = int(network_logfile.name[4:8])
    glider_number_str = network_logfile.name[1:4]
    create_ds_var(dso, var_template, "dive_number", dive_number)

    time_v = None

    if not network_profile_ct.is_file():
        log_warning(f"{network_profile_ct} not found - skipping")
    else:
        try:
            header = _read_profile_header(
                network_profile_ct, default_names=("temperature", "salinity")
            )
            if header is None:
                pass
            else:
                first_bin_depth, bin_width, names = header
                data = np.genfromtxt(network_profile_ct, comments="%", names=names)
                if not data.size:
                    log_error(f"Read from {network_profile_ct} returned no data")
                else:
                    if np.ndim(data[names[0]]) == 0:
                        create_ds_var(
                            dso,
                            var_template,
                            "depth",
                            np.atleast_1d(np.array(bin_width / 2.0)),
                        )
                    else:
                        depth = np.linspace(
                            first_bin_depth,
                            first_bin_depth + (bin_width * len(data[names[0]])),
                            num=len(data[names[0]]),
                            endpoint=False,
                        )
                        create_ds_var(dso, var_template, "depth", depth)
                    for var_name in names:
                        tmp_v = np.array(
                            (
                                np.atleast_1d(data[var_name]),
                                np.full(len(np.atleast_1d(data[var_name])), np.nan),
                            )
                        )
                        create_ds_var(dso, var_template, var_name, tmp_v)
                    time_v = np.array(
                        (
                            np.full(len(np.atleast_1d(data[names[-1]])), np.nan),
                            np.full(len(np.atleast_1d(data[names[-1]])), np.nan),
                        )
                    )
        except Exception:
            DEBUG_PDB_F()
            log_error(f"Failed processing {network_profile_ct}", "exc")

    if network_profile_wl is not None:
        if not network_profile_wl.is_file():
            log_warning(f"{network_profile_wl} not found - skipping")
        else:
            try:
                header = _read_profile_header(network_profile_wl)
                if header is None:
                    pass
                else:
                    first_bin_depth, bin_width, names = header
                    data = np.genfromtxt(network_profile_wl, comments="%", names=names)
                    if not data.size:
                        log_error(f"Read from {network_profile_wl} returned no data")
                    else:
                        if np.ndim(data[names[0]]) == 0:
                            wl_depth = np.atleast_1d(np.array(bin_width / 2.0))
                        else:
                            wl_depth = np.linspace(
                                first_bin_depth,
                                first_bin_depth + (bin_width * len(data[names[0]])),
                                num=len(data[names[0]]),
                                endpoint=False,
                            )
                        create_ds_var(dso, var_template, "wl_depth", wl_depth)
                        for raw_name in names:
                            canonical_name = WL_RAW_TO_CANONICAL.get(raw_name, raw_name)
                            if canonical_name not in var_template["variables"]:
                                log_warning(
                                    f"No netcdf variable for wl column {raw_name} - skipping"
                                )
                                continue
                            create_ds_var(
                                dso,
                                var_template,
                                canonical_name,
                                np.atleast_1d(data[raw_name]),
                            )
            except Exception:
                DEBUG_PDB_F()
                log_error(f"Failed processing {network_profile_wl}", "exc")

    if not network_logfile.is_file():
        log_warning(f"{network_logfile} not found - skipping")
    else:
        try:
            with network_logfile.open("rb") as raw_network_logfile:
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

                    if not raw_line:
                        break

                    raw_line = raw_line.rstrip()
                    if not (raw_line):
                        continue

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
                            except Exception:
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
                    except Exception:
                        log_error(
                            f"Could not process {line_count} of {network_logfile} - skipping",
                            "exc",
                        )
        except Exception:
            log_error(f"Failed processing {network_logfile}", "exc")

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
            new_row = np.append(ll[0], np.append([np.nan] * 9, ll[1:]))
            if full_gc_table is None:
                full_gc_table = new_row
            else:
                full_gc_table = np.vstack([full_gc_table, new_row])
        rc = np.array(gc_time, np.float32)
        # Wrong solution - complete sorts rows and coloumns
        # data = np.sort(full_gc_table, axis=0)

        if full_gc_table is None:
            log_warning("Empty GC table - skipping")
        else:
            if len(np.shape(full_gc_table)) == 1:
                # Single row - convert to a 1xN table so column indexing/sort works.
                full_gc_table = np.reshape(full_gc_table, (1, np.shape(full_gc_table)[0]))

            # Sort the table by the first column
            data = full_gc_table[full_gc_table[:, 0].argsort()]

            # Convert time to epoch time
            create_ds_var(dso, var_template, "log_GC", data, row_coord=rc)

        # Modem and FREEZE tables
        for tab, var_name in (
            ("modem_table", "log_MODEM"),
            ("freeze_table", "log_FREEZE"),
            ("exed_table", "log_EXED"),
            ("warn_table", "log_WARN"),
            ("net_ping_table", "log_NET_PING"),
        ):
            t_table = None
            for ll in getattr(lp, tab):
                if t_table is None:
                    t_table = np.array(ll)
                else:
                    t_table = np.vstack([t_table, ll])

            if t_table is not None:
                if np.ndim(t_table) == 0:
                    # This is a string
                    create_ds_var(dso, var_template, var_name, t_table)
                else:
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
        ncf_filename = network_logfile.parent / file_name
    else:
        ncf_filename = network_logfile.with_suffix(".ncdf")
    log_info(f"Creating {ncf_filename}")

    dso.to_netcdf(
        ncf_filename,
        "w",
        encoding=encoding,
        engine="netcdf4",
        format="NETCDF3_CLASSIC",
    )
    return ncf_filename


# Real .nlog files always carry a "start:" line with a plausible calendar
# date. Some builds emit a line or two of debug output before it, so this
# is a window scan, not an anchor to a fixed line number.
_NLOG_SANITY_SCAN_LINES = 20
# Rejects a "start:" line decades in the past/future - seen in the wild
# from a broken en.r -> nlog conversion (e.g. year fields that decode to
# 1960 or 1970) without hardcoding a mission-specific date.
_NLOG_MIN_PLAUSIBLE_EPOCH = time.mktime((1995, 1, 1, 0, 0, 0, 0, 0, 0))
_NLOG_MAX_FUTURE_SLOP_SECS = 3 * 365 * 86400


def check_nlog_sanity(
    network_logfile: pathlib.Path,
    expected_sgid: int | None = None,
    max_scan_lines: int = _NLOG_SANITY_SCAN_LINES,
) -> str | None:
    """Checks whether a network logfile looks like real glider telemetry
    rather than the product of a broken en.r -> nlog conversion.

    A garbled conversion (seen in the wild - e.g. a decompressor crash
    whose output got written out as if it were the log) typically has no
    "start:" line at all, or one with an implausible date, and/or lacks an
    "$ID,<glider>" line naming the glider that produced the dive.

    Args:
        network_logfile: Path to the network logfile to check.
        expected_sgid: Glider number the file is supposed to belong to
            (e.g. parsed from the filename), checked against any early
            "$ID,..." line found. Pass None to skip that check.
        max_scan_lines: How many leading lines to scan.

    Returns:
        None if the file looks sane, otherwise a short reason it doesn't.
    """
    try:
        with network_logfile.open("rb") as f:
            lines = [
                f.readline().decode(errors="replace").rstrip()
                for _ in range(max_scan_lines)
            ]
    except Exception as e:
        return f"could not read file ({e})"

    start_reason = f"no start: line in the first {max_scan_lines} lines"
    for raw_line in lines:
        if not raw_line.startswith("start:"):
            continue
        try:
            time_string = (
                raw_line.split(",", maxsplit=1)[1]
                if "," in raw_line
                else raw_line.split(":", maxsplit=1)[1]
            )
            start_epoch = Utils.parse_time(time_string)
        except Exception as e:
            start_reason = f"unparseable start: line {raw_line!r} ({e})"
            continue
        if (
            start_epoch < _NLOG_MIN_PLAUSIBLE_EPOCH
            or start_epoch > time.time() + _NLOG_MAX_FUTURE_SLOP_SECS
        ):
            start_reason = f"implausible start: line {raw_line!r} (epoch {start_epoch:.0f})"
            continue
        start_reason = None
        break
    if start_reason is not None:
        return start_reason

    if expected_sgid is None:
        return None

    for raw_line in lines:
        if not raw_line.startswith("$ID,"):
            continue
        try:
            sgid = float(raw_line[len("$ID,") :])
        except ValueError:
            continue
        if abs(sgid - expected_sgid) < 0.5:
            return None

    return f"no $ID,{expected_sgid} line in the first {max_scan_lines} lines"


def make_netcdf_network_files(
    network_files: list[pathlib.Path], processed_files_list: list[pathlib.Path]
) -> int:
    """Takes a list of network files and produces netcdf output files

    Args:
        network_files: List of network files to process (need not have
            both log and profile for all dives).
        processed_files_list: Output list; paths of created netcdf files
            are appended to this list in place.

    Returns:
        0 on success, non-zero on failure.
    """

    ret_val = 0

    # Classify each file by role and group by dive number. A dive can have
    # a log, a ct-shaped profile (the legacy bare .npro, or the newer
    # .npro_ct.dat), and/or a wl-shaped profile (.npro_wl.dat) - any subset,
    # not necessarily all three.
    net_files: dict[int, dict[str, pathlib.Path]] = collections.defaultdict(dict)
    for nf in network_files:
        dive_num = int(nf.name[4:8])

        if nf.suffix == ".nlog":
            reason = (
                check_nlog_sanity(nf, expected_sgid=int(nf.name[1:4]))
                if nf.is_file()
                else None
            )
            if reason is not None:
                log_error(f"{nf} does not look like a valid nlog ({reason}) - skipping")
            else:
                net_files[dive_num]["log"] = nf
        elif nf.name.endswith(".npro_ct.dat") or nf.suffix == ".npro":
            net_files[dive_num]["ct"] = nf
        elif nf.name.endswith(".npro_wl.dat"):
            net_files[dive_num]["wl"] = nf
        else:
            log_warning(f"{nf} is not a network file - skipping")

    for dive_num, files in net_files.items():
        log_file = files.get("log")
        ct_file = files.get("ct")
        wl_file = files.get("wl")
        if log_file is None and ct_file is None:
            # A lone wl file with nothing else to derive dive/glider info
            # from isn't processable.
            log_warning(f"No .nlog or ct-profile file for dive {dive_num} - skipping")
            continue
        # Synthesize the other's expected sibling name when only one of
        # log/ct was supplied, same as before - make_netcdf_network_file()
        # tolerates either being missing on disk and logs accordingly. wl
        # is never synthesized this way: most dives simply have no optical
        # puck installed, so a missing wl file is not worth a warning.
        if log_file is None and ct_file is not None:
            log_file = ct_file.with_suffix(".nlog")
        if ct_file is None and log_file is not None:
            ct_file = log_file.with_suffix(".npro")
            if not ct_file.exists():
                ct_file = log_file.with_suffix(".npro_ct.dat")
        assert log_file is not None
        assert ct_file is not None
        if wl_file is None:
            wl_file = log_file.with_suffix(".npro_wl.dat")
            if not wl_file.exists():
                wl_file = None
        try:
            ncf_filename = make_netcdf_network_file(log_file, ct_file, wl_file)
        except Exception:
            DEBUG_PDB_F()
            log_error(f"Failed to create cdf file for dive {dive_num}", "exc")
            ret_val = 1
        else:
            if ncf_filename:
                processed_files_list.append(ncf_filename)

    log_info(processed_files_list)
    return ret_val


def make_netcdf_network_file_from_perdive(
    ncf_filename: pathlib.Path, ts_outputfile: bool = False
) -> pathlib.Path | None:
    """Processes a per-dive glider netcdf file into a network ncf file

    Args:
        ncf_filename: Path to the per-dive glider netcdf file.
        ts_outputfile: If True, name the output file from the embedded
            start time and platform id instead of the input filename.

    Returns:
        Path to the created network ncf file, or None if the input file
        lacks the CTD variables needed to build one.
    """

    # These match the current on-board binning routine
    # TODO - make these configurable
    bin_width = 5.0
    first_bin_depth = 7.5

    dsi = xr.open_dataset(ncf_filename)

    if ts_outputfile:
        start_ts = time.strftime("%Y%m%dT%H%M", time.gmtime(dsi.attrs["start_time"]))
        file_name = f"{dsi.attrs['platform_id'].lower()}_{start_ts}.ncdf"
        ncf_output_filename = ncf_filename.parent / file_name
    else:
        ncf_output_filename = ncf_filename.with_suffix(".ncdf")
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

        max_depth_i = int(dsi["ctd_depth"].argmax())  # ty: ignore[invalid-argument-type]
        ctd_time = dsi["ctd_time"].data.astype(np.float64) / 1000000000.0
        if not dsi["ctd_depth"][:max_depth_i].size or not ctd_time[:max_depth_i].size:
            t_down = None
        else:
            t_down = NetCDFUtils.interp1_extend(
                dsi["ctd_depth"][:max_depth_i], ctd_time[:max_depth_i], bin_centers
            )
        if not dsi["ctd_depth"][max_depth_i:].size or not ctd_time[max_depth_i:].size:
            t_up = None
        else:
            t_up = NetCDFUtils.interp1_extend(
                dsi["ctd_depth"][max_depth_i:],
                ctd_time[max_depth_i:],
                bin_centers[::-1],
            )
        # time_v = np.array((t_down, t_up))
        time_v = np.array([x for x in (t_down, t_up) if x is not None])
        create_ds_var(dso, var_template, "time", time_v)

        for vvar in ("temperature", "salinity"):
            if t_down is None:
                binned_data_down = None
            else:
                binned_data_down, *_ = NetCDFUtils.bindata(
                    dsi["ctd_depth"][:max_depth_i], dsi[vvar][:max_depth_i], bin_edges
                )
            if t_up is None:
                binned_data_up = None
            else:
                binned_data_up, *_ = NetCDFUtils.bindata(
                    dsi["ctd_depth"][max_depth_i:], dsi[vvar][max_depth_i:], bin_edges
                )
            create_ds_var(
                dso,
                var_template,
                vvar,
                np.array(
                    [x for x in (binned_data_down, binned_data_up) if x is not None]
                ),
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
            if dsi[log_var_name].data.dtype.type is np.bytes_:
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
            format="NETCDF4",
        )
        return ncf_output_filename
    return None


def make_netcdf_network_file_from_perdive_files(
    ncf_filenames: list[pathlib.Path],
    processed_files_list: list[pathlib.Path] | None = None,
) -> int:
    """Processes a list of glider per-dive netcdf files to network ncf file format

    Args:
        ncf_filenames: List of per-dive glider netcdf files to process.
        processed_files_list: Optional output list; paths of created
            network ncf files are appended to this list in place.

    Returns:
        0 (individual per-file failures are logged, not raised).
    """
    ret_val = 0

    for ncf_filename in ncf_filenames:
        try:
            ncf_output_filename = make_netcdf_network_file_from_perdive(ncf_filename)
        except Exception:
            DEBUG_PDB_F()
            log_error(
                f"Unhandled exception in processing {ncf_filename}-- skipping", "exc"
            )
        else:
            if ncf_output_filename and processed_files_list is not None:
                processed_files_list.append(ncf_output_filename)
    return ret_val


def main(
    instrument_id: int | None = None,
    base_opts: BaseOpts.BaseOptions | None = None,
    sg_calib_file_name: pathlib.Path | None = None,
    dive_nc_file_names: list[pathlib.Path] | None = None,
    nc_files_created: list[pathlib.Path] | None = None,
    processed_other_files: list[pathlib.Path] | None = None,
    known_mailer_tags: list[str] | None = None,
    known_ftp_tags: list[str] | None = None,
    processed_file_names: list[pathlib.Path] | None = None,
) -> int:
    """cli test/utility for network file processing and limited basestation extension

    Args:
        instrument_id: Glider instrument id (basestation extension call path only).
        base_opts: Basestation options object; built from argv if None.
        sg_calib_file_name: Path to sg_calib_constants.m (extension call path only).
        dive_nc_file_names: Per-dive netcdf files (extension call path only).
        nc_files_created: Netcdf files created this run; used as the input
            list when called as a basestation extension with no subparser.
        processed_other_files: Output list; created network files are
            appended to this list in place.
        known_mailer_tags: Known mailer tags (extension call path only).
        known_ftp_tags: Known ftp tags (extension call path only).
        processed_file_names: All processed file names (extension call path only).

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
                "log_in_file": BaseOptsType.options_t(
                    None,
                    {"BaseNetwork"},
                    ("log_in_file",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Compressed network logfile",
                        "action": BaseOpts.FullPathlibAction,
                        "subparsers": ("log",),
                    },
                ),
                "log_out_file": BaseOptsType.options_t(
                    None,
                    {"BaseNetwork"},
                    ("log_out_file",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Plain-text network logfile",
                        "action": BaseOpts.FullPathlibAction,
                        "subparsers": ("log",),
                        "nargs": "?",
                    },
                ),
                "pro_in_file": BaseOptsType.options_t(
                    None,
                    {"BaseNetwork"},
                    ("pro_in_file",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Compressed network ct profile",
                        "action": BaseOpts.FullPathlibAction,
                        "subparsers": ("pro",),
                    },
                ),
                "pro_out_file": BaseOptsType.options_t(
                    None,
                    {"BaseNetwork"},
                    ("pro_out_file",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Plain-text network ct profile",
                        "action": BaseOpts.FullPathlibAction,
                        "subparsers": ("pro",),
                        "nargs": "?",
                    },
                ),
                "network_files": BaseOptsType.options_t(
                    [],
                    {"BaseNetwork"},
                    ("network_files",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "List of network files to process",
                        "nargs": "+",
                        "action": BaseOpts.FullPathlibAction,
                        "subparsers": ("cdf",),
                    },
                ),
                "netcdf_files": BaseOptsType.options_t(
                    [],
                    {"BaseNetwork"},
                    ("netcdf_files",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "List of per-dive netcdf files to process",
                        "nargs": "+",
                        "action": BaseOpts.FullPathlibAction,
                        "subparsers": ("ncf",),
                    },
                ),
            },
        )

    BaseLogger(base_opts, include_time=True)

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    ret_val = 0
    if not hasattr(base_opts, "subparser_name"):
        # Called as a basestation extension
        ret_val = make_netcdf_network_file_from_perdive_files(
            nc_files_created or [], processed_other_files
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
        ret_val = convert_network_profile(
            base_opts, base_opts.pro_in_file, base_opts.pro_out_file
        )
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
        for ncf in processed_files_list:
            if ncf.suffix == ".ncdf":
                if not hasattr(base_opts, "mission_dir") or not base_opts.mission_dir:
                    base_opts.mission_dir = ncf.parent
                if (
                    not hasattr(base_opts, "instrument_id")
                    or not base_opts.instrument_id
                ):
                    try:
                        base_opts.instrument_id = int(ncf.stem[1:4])
                    except Exception:
                        base_opts.instrument_id = -1
                BaseDB.loadDB(base_opts, ncf, run_dive_plots=False)

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
    except Exception:
        DEBUG_PDB_F()

        log_critical("Unhandled exception in main -- exiting", "exc")
