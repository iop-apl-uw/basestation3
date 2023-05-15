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
CalibConst.py: seaglider calibration constants (matlab file) parser
"""

import re
import sys


from BaseLog import BaseLogger, log_error, log_debug, log_warning
from BaseNetCDF import nc_sg_cal_prefix, nc_var_metadata
from Globals import ignore_tags, ignore_tag


def getSGCalibrationConstants(
    calib_filename, suppress_required_error=False, ignore_fm_tags=True
):
    """Parses a matlab .m file for name = value pairs
    Returns a dictionary of the constant names and values
    """

    # helpers

    def rangeCheck(key, value):
        """Checks to see whether value lies in min/max range for given key.
        Ranges are hardcoded.
        Returns given key, value pair if within check; key value=None otherwise.

        Called by getSGCalibrationConstants, expects error(msg) to be defined.
        """
        if key == "example_key":
            if value < 0:  # min
                log_error(str(key) + ":" + str(value) + " is below minimum value")
                return None
            elif value > 10:  # max
                log_error(str(key) + ":" + str(value) + " is above maximum value")
                return None

        return value

    # constants
    required_keys = [
        "id_str",
        "mission_title",
        "mass",
    ]

    calib_consts = (
        {}
    )  # initialize calib_consts to include empty values for required keys
    for i in required_keys:
        calib_consts[i] = None

    eq = re.compile(r"^([^=]+)=(.*)")
    comment = re.compile(r"%.*")  # % and anything after it, to a newline
    bracket = re.compile(r"\[.*")
    # a bracket
    override = re.compile(r"override\..*")
    # e.g., override.RHO

    # open filename
    try:
        calib_file = open(calib_filename, "r")
    except:
        log_error("Unable to open file: " + calib_filename)
        return None

    # parse file : expect .m with  "name = value; %comment \n" lines
    eval_locals = {}  # local results from evaluating key = value lines
    for line in calib_file.readlines():
        # log_debug("parsing: " + line)

        # remove line comments
        m = comment.search(line)
        if m:
            comment_str = m.group(0)
            line, _ = comment.split(line)

        # Handle lines like hd_a = 4.3e-3; hd_b = 2.4e-5; hd_c = 5.7e-6;
        for expr in line.split(";"):
            # handle name=value pairs

            if eq.search(expr):
                # log_debug("found pair: " + expr)
                _, key, value, _ = eq.split(expr)
                key = key.strip()  # remove whitespace
                if override.search(key):
                    # this skips any override struct assignments used for IOP
                    continue

                if ignore_fm_tags and key in ignore_tags:
                    if ignore_tag not in comment_str:
                        log_warning(
                            f"{key} value ignored. v3 Flight Model does not use this value. Add '% FM_ignore' to sg_calib_constants.m to suppress this warning.",
                            alert=f"calib const {key}",
                            max_count=-1,
                        )
                    continue
                key = key.replace(
                    ".", "_"
                )  # CF1.4: Avoid invalid variable names from sg_calib_constants
                value = value.strip()
                value = value.strip("'\"")  # remove quotes from edges
                value.strip()
                if bracket.search(value):
                    # this skips even unbalanced []'s deliberately
                    # log_debug("skipping [] expression: " + expr)
                    continue

                nc_var_name = nc_sg_cal_prefix + key
                try:
                    md = nc_var_metadata[nc_var_name]
                    (
                        _,
                        nc_data_type,
                        _,
                        _,
                    ) = md
                except KeyError:
                    # Unknown variable but be silent here; complain when writing
                    nc_data_type = None
                if nc_data_type == "c":
                    pass  # Known string is just fine
                else:
                    try:
                        # We take all numerics, declared or not...
                        # pylint: disable=eval-used
                        value = float(eval(value, None, eval_locals))
                    except:
                        # Non-numeric value of an unknown variable
                        log_debug("Assuming %s is a string" % key)
                    # Sometimes simple variables are defined that are used in later expressions in the M file...handle them
                    eval_locals[key] = value

                value = rangeCheck(
                    key, value
                )  # value will be None if fails range check
                calib_consts[key] = value

    calib_file.close()

    # Log an error if any of the required keys is missing

    missingKeys = None

    for key in required_keys:
        if calib_consts[key] is None:
            if missingKeys is None:
                missingKeys = []
            missingKeys.append(key)

    if missingKeys is not None and suppress_required_error is False:
        log_error(
            "The following calibration constants are missing from %s: %s"
            % (calib_filename, str(missingKeys))
        )

    return calib_consts


def dump(in_filename, fo):
    """Dumps out the calib_consts dictionary constructed from a calibration constants matlab file"""
    print("Calibration constants extracted from: %s" % (in_filename), file=fo)

    calib_consts = getSGCalibrationConstants(in_filename)

    if calib_consts:
        for key, value in calib_consts.items():
            print("%s = %s (%s)" % (key, value, type(value)), file=fo)


if __name__ == "__main__":
    import BaseOpts

    base_opts = BaseOpts.BaseOptions(
        "Test entry for sg_calib_constants.m processing",
        additional_arguments={
            "calib_const_file": BaseOpts.options_t(
                None,
                ("CalibConst",),
                ("calib_const_file",),
                str,
                {
                    "help": "File to process",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )
    BaseLogger(base_opts)  # initializes BaseLog

    if base_opts.calib_const_file:
        dump(base_opts.calib_const_file, sys.stdout)

    sys.exit(0)
