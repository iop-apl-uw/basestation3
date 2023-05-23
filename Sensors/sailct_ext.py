#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2010, 2011, 2012, 2020, 2022, 2023 by University of Washington.  All rights reserved.
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
SAILCT basestation sensor extension

Note: this file does not deal with ARS payload files as the previous basestation did.
"""

import shutil

from BaseLog import log_error


def init_logger(module_name, init_dict=None):
    """
    init_loggers

    returns:
    -1 - error in processing
     0 - success (data found and processed)
    """

    if init_dict is None:
        log_error("No datafile supplied for init_loggers - version mismatch?")
        return -1

    init_dict[module_name] = {"logger_prefix": "ct"}

    return 1


# pylint: disable=unused-argument
def asc2eng(base_opts, module_name, datafile=None):
    """
    asc2eng processor

    returns:
    -1 - error in processing
     0 - success (data found and processed)
     1 - no data found to process
    """

    if datafile is None:
        log_error("No datafile supplied for asc2eng conversion - version mismatch?")
        return -1

    sailct_condFreq = datafile.remove_col("sailct.CondFreq")
    sailct_tempFreq = datafile.remove_col("sailct.TempFreq")

    if sailct_condFreq is not None:
        sailct_condFreq = 4000000.0 / (sailct_condFreq / 255.0)
        sailct_tempFreq = 4000000.0 / (sailct_tempFreq / 255.0)

        datafile.eng_cols.append("sailct.condFreq")
        datafile.eng_cols.append("sailct.tempFreq")

        datafile.eng_dict["sailct.condFreq"] = sailct_condFreq
        datafile.eng_dict["sailct.tempFreq"] = sailct_tempFreq
        return 0

    return 1


def process_data_files(
    base_opts,
    module_name,
    calib_consts,
    fc,
    processed_logger_eng_files,
    processed_logger_other_files,
):
    """Processes other files

    Returns:
        0 - success
        1 - failure
    """
    if fc.is_up_data() or fc.is_down_data():
        sailct_dat_filename = fc.mk_base_datfile_name()
        shutil.copyfile(fc.full_filename(), sailct_dat_filename)
        if ConvertDatToEng(sailct_dat_filename, fc.mk_base_engfile_name()):
            log_error(
                f"Could not process {fc.full_filename()} to {fc.mk_base_engfile_name()}"
            )
            return 1
        else:
            processed_logger_eng_files.append(fc.mk_base_engfile_name())
            return 0
    else:
        log_error(f"Don't know how to handle {fc.full_filename()}")
        return 1


def ConvertDatToEng(inp_file_name, out_file_name):
    """
    Converts a SailCT data file to a SailCT eng file
    """
    try:
        inp_file = open(inp_file_name, "r")
    except:
        log_error(f"Unable to open {inp_file_name}")
        return 1
    try:
        out_file = open(out_file_name, "w")
    except:
        log_error(f"Unable to open {out_file_name}")
        return 1

    scale = None
    depth = "NaN"
    first_line = True
    for raw_line in inp_file:
        if raw_line[0] == "%":
            if raw_line.split(":")[0] == "% scale":
                scale = float(raw_line.split(":")[1])
                out_file.write("%columns: sailct.CondFreq,sailct.TempFreq,depth\n")
                out_file.write("%data:\n")
            else:
                out_file.write(raw_line.replace("% ", "%"))
        else:
            if scale is None:
                log_error("Scale not found - bailing out")
                return 1
            parts = raw_line.split()
            if first_line:
                cond_freq = int(parts[0])
                temp_freq = int(parts[1])
                first_line = False
            else:
                cond_freq = cond_freq + int(parts[0])
                temp_freq = temp_freq + int(parts[1])
            if len(parts) == 3:
                depth = parts[2]
            else:
                depth = "NaN"
            out_file.write(
                "%.3f %.3f %s\n"
                % (scale / float(cond_freq), scale / float(temp_freq), depth)
            )
    return 0
