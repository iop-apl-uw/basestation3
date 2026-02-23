#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025, 2026  University of Washington.
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

"""Routines to read and apply mag calibrations to compass headings"""

import asyncio
import io
from typing import TextIO, Callable
import numpy as np
import numpy.typing as npt

import Utils
from BaseLog import log_error, log_info, log_warning


# TODO - multiple calibrations not handled
# TODO - new style calibaration files not handled
def readMagCalFile(mag_cal_filename):
    """Reads a old style mag cal file
    Input:
        mag_cal_filname - fully qualified path to the cal file
    Output:
        Single string containing the mag calibrations
    """
    try:
        fi = open(mag_cal_filename, "r")
        contents = "%s" % fi.readline().replace('"', "")  # tag line
        contents = "%s%s" % (contents, fi.readline())  # Roll coeffs
        contents = "%s%s" % (contents, fi.readline())  # Pitch coeffs
        contents = "%s%s" % (contents, fi.readline())  # abc/pqr coeffs
        # NOTE: for DG, add the next lines; if there are no lines readline() returns ''
        contents = "%s%s" % (
            contents,
            fi.readline(),
        )  #  pitch mass PQR adjustment (required for DG)
        contents = "%s%s" % (
            contents,
            fi.readline(),
        )  #  HV pack signature for testing HV Hi drift (DG)
        fi.close()
        return contents
    except Exception:
        # Trouble with open or close; readline never complains
        log_error("Could not process %s" % mag_cal_filename, "exc")
        return None


def readNewTCM2Matfile(stream: TextIO, keys: list[str]) -> dict[str, str]:
    ret_d = {}
    for line in stream:
        if line[0] == "/":
            continue

        split = [ii.strip() for ii in line.strip().split("=")]
        if len(split) != 2:
            continue

        if split[0] in keys:
            ret_d[split[0]] = split[1].strip('" ')

    return ret_d


def parseNewMagCalFile(
    magcal_filename: str,
) -> (
    tuple[npt.ArrayLike, Callable[[npt.ArrayLike], npt.ArrayLike], str]
    | tuple[None, None, None]
):
    try:
        with open(magcal_filename, "r") as fi:
            mag_d = readNewTCM2Matfile(
                fi,
                ["hard0", "soft0"],
            )
            fi.seek(0)
            contents = fi.read()

        if not any(ii in mag_d for ii in ["hard0", "soft0"]):
            return (None, None, None)

        abc = np.zeros(9)
        abc[0] = abc[4] = abc[8] = 1.0
        pqr = np.zeros(3)
        if "soft0" in mag_d:
            try:
                abc_vals = mag_d["soft0"].split()
                for ii in range(9):
                    abc[ii] = float(abc_vals[ii])
            except Exception as e:
                log_error(f"Could not process soft0:{mag_d['soft0']} ({e})")
                return (None, None, None)

        if "hard0" in mag_d:
            try:
                pqr_vals = mag_d["hard0"].split()
                for ii in range(3):
                    pqr[ii] = float(pqr_vals[ii])
            except Exception as e:
                log_error(f"Could not process hard0:{mag_d['hard0']} ({e})")
                return (None, None, None)
    except Exception as e:
        log_warning(f"Failed to process {magcal_filename} ({e})")
        return (None, None, None)
    else:
        # SG closure.
        pqrc = lambda p: pqr
        log_info
        return (abc, pqrc, contents)


def parseMagCal(contents):
    """Parses a old style mag cal file string
    Input:
        contents - single string, with embedded new lines containing the compass cal
    Output:
        abc and pqc values as lists
    """
    lines = contents.split("\n")
    if not lines or len(lines) < 4:
        log_error("Not enough lines for tcm2mat file")
        return (None, None)

    # line 0 is tag line
    # line 1 is the roll coeff line
    # line 2 is the pitch coeff line
    # line 3 is the abc_pqr line
    # for DG, optional line 4 contains pitchAD PQR scaling information
    # and line 5 contains HV pack info
    abc_pqr = lines[3].split()
    if len(abc_pqr) < 12:
        log_error("Failed to parse '%s' - not enough values on abc/pqr line" % abc_pqr)
        return (None, None)

    abc = np.zeros(9)
    pqr = np.zeros(3)
    try:
        for i in range(9):
            abc[i] = float(abc_pqr[i])
        for i in range(3):
            pqr[i] = float(abc_pqr[i + 9])
        return (abc, pqr)
        # Create the stock closure that ignores pitchAD values
        pqrc = lambda p: pqr  # noqa: E731

        # DG correction has five lines exactly.  SG with second compass
        # has a second compass definition right after the first
        if len(lines) == 5 and len(lines[4]) > 2 and lines[4] != "'":
            log_info("Assuming DG compass cal file")
            try:
                dg = lines[4].split()
                if len(dg) != 10:
                    log_error(
                        "Could not parse hard-iron scale coefficients in '%s'"
                        % lines[4]
                    )
                    # fall through and use default closure
                else:
                    pitch_ref = float(dg[0])
                    Pc = np.zeros(3)
                    for i in range(3):
                        Pc[i] = float(dg[i + 1])
                    Qc = np.zeros(3)
                    for i in range(3):
                        Qc[i] = float(dg[i + 1 + 3])
                    Rc = np.zeros(3)
                    for i in range(3):
                        Rc[i] = float(dg[i + 1 + 3 + 3])
                    cP = np.polyval(Pc, pitch_ref)
                    cQ = np.polyval(Qc, pitch_ref)
                    cR = np.polyval(Rc, pitch_ref)
                    pqrc = lambda p: (  # noqa: E731
                        np.polyval(Pc, p) - cP + pqr[0],
                        np.polyval(Qc, p) - cQ + pqr[1],
                        np.polyval(Rc, p) - cR + pqr[2],
                    )
            except Exception:
                log_error(
                    "Could not parse hard-iron scale coefficients in '%s'" % lines[4],
                    "exc",
                )
                # fall through - use the default closure
        return (abc, pqrc)
    except Exception:
        log_error("Could not parse %s as abc/pqr line" % abc_pqr)
        return (None, None)


def compassTransform(abc, pqrc, pitchAD, roll_deg, pitch_deg, mag):
    """
    Tranforms mag to heading
    """
    m_pqr = np.zeros(3)
    p = np.zeros(3)
    m = np.zeros(3)

    roll = np.radians(roll_deg)
    pitch = np.radians(pitch_deg)

    # now we negate for to get into cal space convention
    m[0] = mag[0]  # cal equations are based on -Y and -Z field values
    m[1] = -mag[1]
    m[2] = -mag[2]

    # pqrc passed in is a closure that generates a pqr given pitchAD

    # If this call is failing, likely that this is a DG style compass cal file
    # on a RevE glider with no pitch_ctl column - fix should go in MakeDiveProfiles
    # see calls to correct_heading
    pqr = pqrc(pitchAD)
    for j in range(3):
        m_pqr[j] = m[j] - pqr[j]

    for i in range(3):
        p[i] = 0.0
        for j in range(3):
            p[i] += m_pqr[j] * abc[i * 3 + j]

    cp = np.cos(pitch)
    cr = np.cos(roll)
    sp = np.sin(pitch)
    sr = np.sin(roll)
    magX = p[0] * cp - p[1] * sp * sr - p[2] * sp * cr
    magY = p[1] * cr - p[2] * sr

    heading = np.arctan2(magY, magX)
    if heading < 0:
        heading += 2 * np.pi

    return np.degrees(heading)
