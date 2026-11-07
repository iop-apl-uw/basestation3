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

"""Writes the sg_calib_constants.m entries for a Biospherical QSP2150 from a selftest capture.

During selftest the glider fetches the sensor's settings menu ("fetching metadata for
QSP2150"). This reads the model and serial number, calibration factor (C), immersion
factor (J), dark (K), calibration units (U) and calibration mode (W) from that menu and
prints the qsp_* entries Sensors/qsp2150_ext.py uses.

Usage:
    GetQSPConstants.py <selftest capture>
"""

import pdb
import re
import sys
import traceback
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import BaseOpts
from BaseLog import BaseLogger, log_error, log_info, log_warning

DEBUG_PDB = False

_NUM = r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"
# The sensor's menu lines, wherever they sit in a capture line
SETTINGS = {
    "model": re.compile(r"Model:\s*(\S+)\s+(\S+)"),
    "cal_factor": re.compile(rf"Calibration Factor for digital output:\s*{_NUM}"),
    "immersion": re.compile(rf"immersion factor[^:]*:\s*{_NUM}"),
    "dark": re.compile(rf"dark zero, currently dark\s*=\s*{_NUM}"),
    "units": re.compile(r"calibration units:\s*(\S+)"),
    "mode": re.compile(r"Calibration Mode\s*=\s*([A-Da-d])\b"),
}
MODE_TEXT = {"A": "net volts", "B": "in air", "C": "in water", "D": "raw volts"}
# "246.090,HQSP2150,N,..." - a capture line from a glider module
_CAPTURE_LINE = re.compile(r"^\d+\.\d+,([A-Z0-9_]+),[A-Z],")
_SECTION_START = re.compile(r"fetching metadata for QSP2150|^\*\*\* qsp", re.IGNORECASE)


def qsp_section(lines: list[str]) -> list[str]:
    """Picks the QSP2150 metadata lines out of a capture.

    The section starts at the glider's "fetching metadata for QSP2150" line (or a
    "*** qsp" header) and runs until a capture line from another module, another
    "***" header, or another "fetching metadata" line.

    Args:
        lines: The capture, one string per line.

    Returns:
        The section's lines; empty if the capture has none.
    """
    section: list[str] = []
    inside = False
    for line in lines:
        if _SECTION_START.search(line):
            inside = True
            continue
        if not inside:
            continue
        m = _CAPTURE_LINE.match(line)
        if (m and m.group(1) != "HQSP2150") or line.startswith("***") or "fetching metadata for" in line:
            break
        section.append(line)
    return section


def parse_settings(lines: list[str]) -> dict[str, str | tuple[str, str]]:
    """Reads the sensor's settings from its menu lines.

    Args:
        lines: The QSP2150 section of a capture.

    Returns:
        Setting -> value, for the settings found (model is (model, serial)).
    """
    found: dict[str, str | tuple[str, str]] = {}
    for line in lines:
        for key, pattern in SETTINGS.items():
            if key in found:
                continue
            m = pattern.search(line)
            if m:
                found[key] = (m.group(1), m.group(2)) if key == "model" else m.group(1)
    return found


def calib_lines(settings: dict[str, str | tuple[str, str]]) -> list[str]:
    """Formats the settings as sg_calib_constants.m lines.

    Args:
        settings: From parse_settings.

    Returns:
        The lines, in a fixed order, for the settings that were found.
    """
    out = []
    mode = str(settings.get("mode", "")).upper()
    comm = "Biospherical"
    if "model" in settings:
        model, serial = settings["model"]
        comm += f" {model} SN {serial}"
    if mode:
        comm += f", mode {mode} ({MODE_TEXT[mode]})"
    if "cal_factor" in settings:
        comm += f", cal {settings['cal_factor']} V/({settings.get('units', 'units')})"
    out.append(f"calibcomm_qsp = '{comm}';")
    if mode:
        out.append(f"qsp_mode = '{mode}';")
    if "cal_factor" in settings:
        out.append(f"qsp_cal_factor = {settings['cal_factor']};")
    if "immersion" in settings:
        out.append(f"qsp_immersion = {settings['immersion']};")
    if "dark" in settings:
        out.append(f"qsp_dark = {settings['dark']};")
    if "units" in settings:
        out.append(f"qsp_units = '{settings['units']}';")
    return out


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Prints the QSP2150 sg_calib_constants.m entries for a selftest capture.

    Args:
        cmdline_args: The command line.

    Returns:
        0 entries printed, 1 no QSP2150 metadata in the capture (or an error).
    """
    base_opts = BaseOpts.BaseOptions(
        "Get Biospherical QSP2150 calibration constants from a Seaglider selftest capture file",
        cmdline_args=cmdline_args,
        additional_arguments={
            "capture": BaseOpts.options_t(
                None,
                {"GetQSPConstants"},
                ("capture",),
                BaseOpts.FullPathlib,
                {"help": "Seaglider self-test capture", "action": BaseOpts.FullPathlibAction},
            ),
        },
    )

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb
    BaseLogger(base_opts)

    try:
        lines = base_opts.capture.read_bytes().decode("utf-8", errors="replace").splitlines()
        section = qsp_section(lines)
        if not section:
            log_info(f"No QSP2150 metadata in {base_opts.capture}")
            print("No QSP2150 metadata found")
            return 1
        settings = parse_settings(section)
        for key in SETTINGS:
            if key not in settings:
                log_warning(f"QSP2150 setting {key} not found in {base_opts.capture} - left out")
        mode = str(settings.get("mode", "")).upper()
        if "immersion" in settings and float(settings["immersion"]) == 1.0:
            if mode in ("A", "B", "D"):
                log_warning(
                    f"Mode {mode} with immersion factor 1.0: qsp_PAR will be in-air values - "
                    "set qsp_immersion to the cal sheet's immersion coefficient for in-water PAR"
                )
            elif mode == "C":
                log_warning(
                    "Mode C with immersion factor 1.0: the sensor's own output is in-air values - "
                    "set J on the sensor to the cal sheet's immersion coefficient"
                )
        print("Add to sg_calib_constants.m")
        for line in calib_lines(settings):
            print(line)
    except Exception:
        if DEBUG_PDB:
            _, _, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        else:
            log_error("Untrapped error", "exc")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
