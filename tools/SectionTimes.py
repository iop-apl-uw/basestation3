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

import datetime
import os
import pdb
import sys
import traceback

import yaml

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))

import BaseOpts
import CommLog
import MakeDiveProfiles
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_error,
    #log_warning,
    log_info,
)

# Options
DEBUG_PDB = True


def main():
    base_opts = BaseOpts.BaseOptions(
        "Calculate times for each section",
        add_to_arguments= ["mission_dir", "instrument_id"],        
    )

    BaseLogger(base_opts)

    (comm_log, _, _, _, _) = CommLog.process_comm_log(
        os.path.join(base_opts.mission_dir, "comm.log"),
        base_opts,
        #known_commlog_files=known_files,
    )
    if comm_log is None:
        log_critical("Could not process comm.log -- bailing out")
        return 1
    
    base_opts.instrument_id = comm_log.get_instrument_id()

    section_file_name = os.path.join(base_opts.mission_dir, "sections.yml")
    if not os.path.exists(section_file_name):
        return 1

    with open(section_file_name, "r") as f:
        x = yaml.safe_load(f.read())

    if "variables" not in x or len(x["variables"]) == 0:
        log_error(f"No 'variables' key found in {section_file_name} - not plotting")
        return 1

    if "sections" not in x or len(x["sections"]) == 0:
        log_error(f"No 'sections' key found in {section_file_name} - not plotting")
        return 1

    try:
        dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
        for sk, sk_dict in list(x['sections'].items()):
            #log_info(f"{sk}:{sk_dict}")
            if "start" in sk_dict and "stop" in sk_dict:
                start_id = int(sk_dict["start"])
                stop_id = int(sk_dict["stop"])
                if stop_id < 0:
                    stop_id = int(os.path.split(dive_nc_file_names[-1])[1][4:8])
                    
                start_ncf_filename = os.path.join(base_opts.mission_dir, f"p{base_opts.instrument_id:03d}{start_id:04d}.nc")
                stop_ncf_filename = os.path.join(base_opts.mission_dir, f"p{base_opts.instrument_id:03d}{stop_id:04d}.nc")
                dsi_start = Utils.open_netcdf_file(start_ncf_filename)
                dsi_stop = Utils.open_netcdf_file(stop_ncf_filename)
                start_t = datetime.datetime.fromtimestamp(dsi_start.variables["log_gps_time"][1])
                stop_t = datetime.datetime.fromtimestamp(dsi_stop.variables["log_gps_time"][2])

                log_info(f"{sk}:{start_id} - {stop_id} => {(stop_t - start_t).days} days")

                dsi_start.close()
                dsi_stop.close()
                
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
    try:
        main()
    except Exception:
        if DEBUG_PDB:
            _, __, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        else:
            log_error("Untrapped error", "exc")
