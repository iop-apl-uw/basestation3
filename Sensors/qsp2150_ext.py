#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2026 by University of Washington.  All rights reserved.
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

"""Biospherical QSP2150 (Q-series) PAR sensor on the truck.

The sensor's calibration mode (its W setting) decides what the glider logs:

    A  volts - dark                          (net volts)
    B  (volts - dark) / C                    (calibrated, in air)
    C  (volts - dark) / (C * J)              (calibrated, in water)
    D  volts                                 (raw)

with C the calibration factor, J the immersion factor and dark the dark voltage, all
stored in the sensor. So the column's units depend on the mode, and are set per dive
from sg_calib_constants.m (tools/GetQSPConstants.py writes these from a selftest):

    qsp_mode        A, B, C or D
    qsp_cal_factor  C, volts per (qsp_units)
    qsp_immersion   J (the in-water immersion coefficient from the cal sheet)
    qsp_dark        dark, volts
    qsp_units       calibrated units, default uE/m^2/sec
    calibcomm_qsp   model, serial number and mode

eng_qsp_PARuV is the column as logged, labelled for the mode ("unknown" with no
qsp_mode). qsp_PAR is in-water PAR, made whenever the mode and the constants it needs
are there.

The glider samples the sensor from its own qsp2150.cnf:

    name=QSP2150  prefix=qsp  timeout=250  baud=9600  warmup=100
    voltage=10  current=0.00438  format="%00"  column=PARuV(1000000,0)

The basestation doesn't read that file: this extension converts the column, so its
scale (QSP_SCALE) must match the glider's.
"""

import math
from typing import Any

import numpy as np

import BaseNetCDF
from BaseLog import log_debug, log_error, log_info, log_warning

PREFIX = "qsp"
INSTRUMENT = "qsp2150"
RAW_COL = f"{PREFIX}.PARuV"  # .eng column name
# The same column once MakeDiveProfiles reads the .eng back (DataFile: "." -> "_")
MDP_COL = f"{PREFIX}_PARuV"
RAW_VAR = f"{BaseNetCDF.nc_sg_eng_prefix}{PREFIX}_PARuV"
PAR_VAR = f"{PREFIX}_PAR"
# Must match column=PARuV(1000000,0) in the glider's qsp2150.cnf
QSP_SCALE = 1000000.0
DEFAULT_UNITS = "uE/m^2/sec"
MODES = ("A", "B", "C", "D")
# What each mode needs, besides the mode, to make in-water PAR
MODE_NEEDS = {
    "A": ("qsp_cal_factor", "qsp_immersion"),
    "B": ("qsp_immersion",),
    "C": (),
    "D": ("qsp_cal_factor", "qsp_immersion", "qsp_dark"),
}
MODE_DESCRIPTIONS = {
    "A": "QSP2150 output as recorded, calibration mode A: volts - dark (net volts)",
    "B": "QSP2150 output as recorded, calibration mode B: (volts - dark) / cal factor, calibrated in air",
    "C": "QSP2150 output as recorded, calibration mode C: (volts - dark) / (cal factor * immersion), calibrated in water",
    "D": "QSP2150 output as recorded, calibration mode D: raw volts",
}
CALIB_VARS = {
    "qsp_mode": "c",
    "qsp_cal_factor": "d",
    "qsp_immersion": "d",
    "qsp_dark": "d",
    "qsp_units": "c",
    "calibcomm_qsp": "c",
}


def calib_mode(calib_consts: dict[str, Any]) -> str | None:
    """Reads the calibration mode from sg_calib_constants.

    Args:
        calib_consts: The calibration constants.

    Returns:
        "A".."D", or None if qsp_mode isn't set or isn't one of them (logged).
    """
    mode = calib_consts.get("qsp_mode")
    if mode is None:
        return None
    mode = str(mode).strip().upper()
    if mode not in MODES:
        log_warning(f"qsp_mode {calib_consts['qsp_mode']!r} is not one of {', '.join(MODES)} - treated as not set")
        return None
    return mode


def raw_metadata(mode: str | None, calib_consts: dict[str, Any]) -> tuple[str, str]:
    """Gives the units and description of the column as logged.

    Args:
        mode: The calibration mode, or None if not known.
        calib_consts: The calibration constants (for qsp_units).

    Returns:
        (units, description).
    """
    if mode is None:
        return (
            "unknown",
            "QSP2150 output as recorded - calibration mode not known (set qsp_mode in sg_calib_constants.m)",
        )
    if mode in ("A", "D"):
        return "V", MODE_DESCRIPTIONS[mode]
    return str(calib_consts.get("qsp_units", DEFAULT_UNITS)), MODE_DESCRIPTIONS[mode]


def calibrated_par(raw: np.ndarray, mode: str | None, calib_consts: dict[str, Any]) -> np.ndarray | None:
    """Converts the column as logged to in-water PAR.

    Args:
        raw: The column as logged (QSP_SCALE already divided out).
        mode: The calibration mode, or None if not known.
        calib_consts: The calibration constants.

    Returns:
        In-water PAR, in qsp_units; None if the mode isn't known or a constant it
        needs is missing (logged).
    """
    if mode is None:
        return None
    missing = [c for c in MODE_NEEDS[mode] if c not in calib_consts]
    if missing:
        log_warning(f"QSP2150 calibration mode {mode} needs {', '.join(missing)} in sg_calib_constants.m - no {PAR_VAR}")
        return None
    if mode == "C":
        return raw.copy()
    immersion = float(calib_consts["qsp_immersion"])
    if mode == "B":
        return raw / immersion
    cal_factor = float(calib_consts["qsp_cal_factor"])
    if mode == "A":
        return raw / (cal_factor * immersion)
    return (raw - float(calib_consts["qsp_dark"])) / (cal_factor * immersion)


def init_sensor(module_name: str, init_dict: dict | None = None) -> int:
    """Declares the QSP2150 netCDF variables.

    Args:
        module_name: Name of this module.
        init_dict: Where the declarations go.

    Returns:
        -1 error in processing, 0 success.
    """
    if init_dict is None:
        log_error("No init_dict supplied for init_sensor - version mismatch?")
        return -1

    meta_data_adds: dict[str, list] = {
        INSTRUMENT: [
            False,
            "c",
            {"long_name": "Biospherical QSP2150 PAR sensor", "make_model": "Biospherical QSP2150"},
            BaseNetCDF.nc_scalar,
        ],
        # units and description are set per dive, from the mode (sensor_data_processing)
        RAW_VAR: [
            True,
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": "unknown",
                "description": "QSP2150 output as recorded",
                "instrument": INSTRUMENT,
            },
            (BaseNetCDF.nc_sg_data_info,),
        ],
        PAR_VAR: [
            True,
            "d",
            {
                "_FillValue": BaseNetCDF.nc_nan,
                "units": DEFAULT_UNITS,
                "description": "Photosynthetically active radiation, calibrated for use in water",
                "instrument": INSTRUMENT,
            },
            (BaseNetCDF.nc_sg_data_info,),
        ],
    }
    for var, nc_type in CALIB_VARS.items():
        meta_data_adds[f"{BaseNetCDF.nc_sg_cal_prefix}{var}"] = [False, nc_type, {}, BaseNetCDF.nc_scalar]

    init_dict[module_name] = {"netcdf_metadata_adds": meta_data_adds}
    return 0


def asc2eng(base_opts: Any, module_name: str, datafile: Any = None) -> int:
    """Converts the QSP2150 column, dividing out the glider's scale.

    Args:
        base_opts: Command line options.
        module_name: Name of this module.
        datafile: The asc DataFile being converted.

    Returns:
        -1 error in processing, 0 column converted, 1 no QSP2150 column.
    """
    if datafile is None:
        log_error("No datafile supplied for asc2eng conversion - version mismatch?")
        return -1
    column = datafile.remove_col(RAW_COL)
    if column is None:
        return 1
    datafile.eng_cols.append(RAW_COL)
    datafile.eng_dict[RAW_COL] = column / QSP_SCALE
    return 0


def eng_decimal_pts(
    base_opts: Any,
    module_name: str,
    eng_col_names: list[str] | None = None,
    eng_decimal_pts: dict[str, int] | None = None,
) -> int:
    """Gives the QSP2150 column the decimal places the glider keeps.

    Args:
        base_opts: Command line options.
        module_name: Name of this module.
        eng_col_names: The data file's column names.
        eng_decimal_pts: Column name -> decimal places, added to here.

    Returns:
        -1 error in processing, 0 decimal places given, 1 no QSP2150 column.
    """
    if eng_col_names is None or eng_decimal_pts is None:
        log_error("No eng_col_names list or eng_decimal_pts dict supplied - version mismatch?")
        return -1
    if RAW_COL not in eng_col_names:
        return 1
    eng_decimal_pts[RAW_COL] = math.ceil(math.log10(QSP_SCALE))
    return 0


def sensor_data_processing(
    base_opts: Any,
    module: str,
    l_dict: dict | None = None,
    eng_f: Any = None,
    calib_consts: dict | None = None,
) -> int:
    """Labels the QSP2150 column for the calibration mode and makes in-water PAR.

    Args:
        base_opts: Command line options.
        module: Name of this module.
        l_dict: MakeDiveProfiles locals() (results_d).
        eng_f: The dive's eng file.
        calib_consts: The calibration constants.

    Returns:
        -1 error in processing, 0 data processed, 1 no QSP2150 data.
    """
    if l_dict is None or eng_f is None or calib_consts is None or "results_d" not in l_dict:
        log_error("Missing arguments for QSP2150 sensor_data_processing - version mismatch?")
        return -1

    present, raw = eng_f.find_col([MDP_COL])
    if not present:
        return 1

    mode = calib_mode(calib_consts)
    if mode is None:
        log_info("QSP2150 data but no qsp_mode in sg_calib_constants.m - units unknown")

    # The eng variables are written after this, from this metadata
    units, description = raw_metadata(mode, calib_consts)
    meta_data_d = BaseNetCDF.nc_var_metadata[RAW_VAR][2]
    # form_nc_metadata stored the declared description as "comment" (the CF name)
    meta_data_d["units"] = units
    meta_data_d["comment"] = description

    par = calibrated_par(np.asarray(raw, np.float64), mode, calib_consts)
    if par is not None:
        BaseNetCDF.nc_var_metadata[PAR_VAR][2]["units"] = str(calib_consts.get("qsp_units", DEFAULT_UNITS))
        l_dict["results_d"][PAR_VAR] = par
        log_debug(f"QSP2150 mode {mode}: {PAR_VAR} made")
    return 0
