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

import os
import pdb
import sys
import traceback

from scanf import scanf

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))

import BaseOpts
from BaseLog import (
    BaseLogger,
    log_error,
    log_warning,
)

# Options
DEBUG_PDB = False


def main():
    base_opts = BaseOpts.BaseOptions(
        "Get optode constants from a Seaglider selftest capture file",
        additional_arguments={
            "capture": BaseOpts.options_t(
                None,
                ("GetOptodeConstants",),
                ("capture",),
                str,
                {
                    "help": "Seaglider self-test capture",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )

    BaseLogger(base_opts)

    line_count = 0
    foil_strs = {"A": "", "B": ""}
    phase = ""
    temp = ""
    ccoef_strs = {"0": "", "1": "", "2": "", "3": "", "4": ""}
    SVUcoef = ""
    optode_type = ""
    sn = None
    SVUon = False
    foilID = "???"

    try:
        with open(base_opts.capture, "rb") as fi:
            for raw_line in fi:
                line_count += 1
                try:
                    s = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    log_warning(
                        f"Could not decode line {line_count} in {base_opts.capture} - skipping"
                    )
                else:
                    # s = s.rstrip().lstrip()
                    pass
                # print(line_count, s)
                n = s.find("HOPTODE,N")
                if n >= 0:
                    s = s[n + 10 :]
                n = s.find("HAA4330,N")
                if n >= 0:
                    s = s[n + 10 :]

                values = scanf("SW ID %s %d %d", s)
                if values and len(values) == 3:
                    optode_type = values[0]
                    sn = values[1]
                    continue

                if s.startswith("PTC0Coef"):  # avoid this confound with C0Coef
                    continue

                if s.startswith("PTC1Coef"):  # avoid this confound with C1Coef
                    continue

                values = scanf("FoilID %s %d %s", s)
                if values:
                    foilID = f" Foil ID: {values[2]}"
                    continue

                for foil in ("A", "B"):
                    values = scanf(
                        f"FoilCoef{foil} %s %d %f %f %f %f %f %f %f %f %f %f %f %f %f %f",
                        s,
                    )
                    if values:
                        foil_strs[foil] = ""
                        for ii in range(2, 16):
                            foil_strs[foil] = (
                                f"{foil_strs[foil]}optode_FoilCoef{foil}{ii-2:d} = {values[ii]:g};\n"
                            )
                        continue

                values = scanf("PhaseCoef %s %d %f %f %f %f", s)
                if values:
                    for ii in range(2, 6):
                        phase = f"{phase}optode_PhaseCoef{ii-2} = {values[ii]:g};\n"
                    continue

                values = scanf("TempCoef %s %d %f %f %f %f %f %f", s)
                if values:
                    for ii in range(2, 6):
                        temp = f"tempoptode_TempCoef{ii-2} = {values[ii]:g};\n"
                    continue

                values = scanf("ConcCoef %s %d %f %f", s)
                if values:
                    for ii in range(2, 4):
                        # just add it to phase
                        phase = f"{phase}optode_ConcCoef{ii-2} = {values[ii]:g};\n"
                    continue

                for ccoef in ("0", "1", "2", "3", "4"):
                    values = scanf(f"C{ccoef}Coef %s %d %f %f %f %f", s)
                    if values:
                        for ii in range(2, 6):
                            ccoef_strs[ccoef] = (
                                f"{ccoef_strs[ccoef]}optode_C{ccoef}{ii-2}Coef = {values[ii]:g};\n"
                            )
                        continue

                values = scanf("Enable SVUformula %s %d %s", s)
                if values:
                    SVUon = 1 if values[2] == "Yes" else 0
                    continue

                values = scanf("SVUFoilCoef %s %d %f %f %f %f %f %f %f", s)
                if values:
                    for ii in range(2, 9):
                        SVUcoef = f"{SVUcoef}optode_SVUCoef{ii-2} = {values[ii]:g};\n"

        print("%% Add these lines to sg_calib_constants.m")
        print(
            f"calibcomm_optode = ''Optode {optode_type} SN: {sn} {foilID} calibrated ??/??/????'';"
        )
        print(phase)
        print(temp)
        # 4330
        for foil in ("A", "B"):
            if foil_strs[foil]:
                print(foil_strs[foil])
        if SVUon is not None:
            print(f"optode_SVU_enabled = {SVUon};\n")
            print(SVUcoef)
        # 3380
        for ccoef in ("0", "1", "2", "3", "4"):
            print(ccoef_strs[ccoef])

    except Exception:
        if DEBUG_PDB:
            _, _, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        else:
            log_error("Untrapped error", "exc")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        if DEBUG_PDB:
            _, __, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        else:
            log_error("Untrapped error", "exc")
