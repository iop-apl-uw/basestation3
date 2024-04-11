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

# Dumps the currently active missions from missions.yml

import argparse
import os
import sys

import yaml

# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("missions_yml",
	help="path to mission.yml")
args = vars(ap.parse_args())

missions_yml = os.path.abspath(os.path.expanduser(args["missions_yml"]))

results_list = []
try:
    with open(missions_yml, "r") as fi:
        mission_config = yaml.safe_load(fi.read())
        missions = mission_config["missions"]
except Exception:
    sys.stderr.write(f'Failed to process{missions_yml}')
    sys.exit(1)

seaglider_mission_root = os.path.split(missions_yml)[0]
    
for m in missions:
    status = "active"
    if "status" in m:
        status = m["status"]
    if status == "active" and "path" in m:
        results_list.append(
            (os.path.join(seaglider_mission_root, m["path"]), m["glider"])
        )

for mission_dir, instrument_id in results_list:
    print(f"glider:{instrument_id} mission_dir:{mission_dir}")
