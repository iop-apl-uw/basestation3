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
    log_info
)

# Options
DEBUG_PDB = False


def main():
    base_opts = BaseOpts.BaseOptions(
        "Get legato pressure correction constants from a Seaglider selftest capture file",
        additional_arguments={
            "capture": BaseOpts.options_t(
                None,
                ("GetLegatoPressCorr",),
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

    f_found_vals = False
    try:
        with open(base_opts.capture, "rb") as fi:
            for raw_line in fi:
                line_count += 1
                try:
                    s = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    log_info(
                        f"Could not decode line {line_count} in {base_opts.capture} - skipping"
                    )
                    continue
                s = s.rstrip().lstrip()
                if "calibration" in s:
                    press_label = "label = conductivity"
                    n = s.find(press_label)
                    if n >= 0:
                        s=s[n+len(press_label) :]
                        values = scanf("_%d, datetime = %d, c0 = %f, c1 = %f, c2 = %f, x0 = %f, x1 = %f, x2 = %f, x3 = %f, x4 = %f, x5 = %f", s)
                        if len(values) == 11:
                            f_found_vals = True
                            print(f"Found pressure cal values x2:{values[7]} x3:{values[8]} x4:{values[9]}")
                            if values[7] or values[8] or values[9]:
                                print("On-board pressure correction enabled")
                                print("set \"legato_cond_press_correction = 0;\" in sg_calib_constants.m")
                            else:
                                print("On-board pressure correction not enabled")
                                print("set \"legato_cond_press_correction = 1;\" in sg_calib_constants.m")
                            break

            if not f_found_vals:
                log_warning(f"Did not find legato meta data in {base_opts.capture}")
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
