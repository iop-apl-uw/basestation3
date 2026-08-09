#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2023, 2024, 2026 by University of Washington.  All rights reserved.
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

import argparse
import glob
import os
import pathlib
import pdb
import sys
import time
import traceback

import orjson
import yaml

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))
import MakeKMLSSH

import BaseOpts
import BaseOptsType
import Utils
from BaseLog import BaseLogger, log_critical, log_error, log_info, log_warning

DEBUG_PDB = False


def get_active_missions(base_opts):
    results_list = []
    try:
        with open(base_opts.mission_yml, "r") as fi:
            mission_config = yaml.safe_load(fi.read())
            missions = mission_config["missions"]
    except Exception:
        log_error(f"Failed to process{base_opts.mission_yml}")
        return results_list

    seaglider_mission_root = os.path.split(base_opts.mission_yml)[0]

    for m in missions:
        status = "active"
        if "status" in m:
            status = m["status"]
        if status == "active" and "path" in m:
            results_list.append(
                (
                    pathlib.Path(os.path.join(seaglider_mission_root, m["path"])),
                    m["glider"],
                )
            )
    return results_list


def find_last_update(data_dir):
    list_of_files = glob.glob("%s/*" % data_dir)
    latest_file = max(list_of_files, key=os.path.getctime)
    return os.path.getctime(latest_file)


def main(instrument_id=None, base_opts=None):
    """Command line app for creating kml/kmz files of ssh contours

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    if base_opts is None:
        base_opts = BaseOpts.BaseOptions(
            "Command line app for creating kml/kmz files of ssh contours",
            additional_arguments={
                "fetch_ssh": BaseOptsType.options_t(
                    False,
                    ("MakeKMLSSHMissions",),
                    ("--fetch_ssh",),
                    bool,
                    {
                        "help": "Fetch the most recent ssh data",
                        "action": argparse.BooleanOptionalAction,
                    },
                ),
                "data_dir": BaseOptsType.options_t(
                    None,
                    ("MakeKMLSSHMissions",),
                    ("data_dir",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Location of Aviso data",
                        "action": BaseOpts.FullPathlibAction,
                    },
                ),
                # "kml_output_dir": BaseOptsType.options_t(
                #     None,
                #     ("MakeKMLSSHMissions",),
                #     ("kml_output_dir",),
                #     BaseOpts.FullPath,
                #     {
                #         "help": "Location to put generated kml files",
                #         "action": BaseOpts.FullPathAction,
                #     },
                # ),
                # "href_base": BaseOptsType.options_t(
                #     None,
                #     ("MakeKMLSSHMissions",),
                #     ("href_base",),
                #     str,
                #     {
                #         "help": "URL for base of KML location",
                #     },
                # ),
                "mission_yml": BaseOptsType.options_t(
                    None,
                    ("MakeKMLSSHMissions",),
                    ("mission_yml",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Path to vis mission config file",
                        "action": BaseOpts.FullPathlibAction,
                    },
                ),
                # Duplicates entries in BaseOpts
                "force": BaseOptsType.options_t(
                    False,
                    ("MakeKMLSSHMissions",),
                    ("--force",),
                    bool,
                    {
                        "help": "Forces creation of all kml files",
                        "action": "store_true",
                    },
                ),
                # End duplicate
                "mergessh": BaseOptsType.options_t(
                    True,
                    ("MakeKMLSSHMissions",),
                    ("--mergessh",),
                    bool,
                    {
                        "help": "Launches MakeKML.py to merge in generated ssh",
                        "action": argparse.BooleanOptionalAction,
                    },
                ),
            },
        )

    BaseLogger(base_opts, include_time=True)

    base_opts.basestation_directory = os.path.join(
        os.path.dirname(os.path.realpath(__file__)), os.pardir
    )

    processing_start_time = time.time()

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    kmz_files = []
    results = get_active_missions(base_opts)

    for mission_dir, instrument_id in results:
        # r was directory and instrument_id - is the later available from missions.yml?
        if (
            find_last_update(base_opts.data_dir) > time.time() - (3600 * 24 * 5)
            or base_opts.force
        ):
            sg_plot_consts = os.path.join(mission_dir, "sg_plot_constants.m")
            if not os.path.exists(sg_plot_consts):
                log_warning(f"Didn't find {sg_plot_consts} Skipping")
            else:
                try:
                    ret_val = MakeKMLSSH.make_kml(
                        base_opts.data_dir,
                        # base_opts.kml_output_dir,
                        mission_dir,
                        sg_plot_consts,
                        instrument_id=instrument_id,
                        fetch_ssh=base_opts.fetch_ssh,
                    )
                except Exception:
                    log_error(f"Could not generate ssh kml for {mission_dir}", "exc")
                else:
                    if not ret_val:
                        continue
                    kmz_files.append((ret_val, instrument_id))
                    if base_opts.mergessh:
                        # Check for existing process
                        base_opts.ignore_lock = False
                        base_opts.mission_dir = mission_dir
                        lock_file_pid = Utils.check_lock_file(
                            base_opts, ".conversion_lock"
                        )
                        if lock_file_pid < 0:
                            log_error(
                                "Error accessing the lockfile - proceeding anyway..."
                            )
                        elif lock_file_pid > 0:
                            # The PID still exists
                            log_warning(
                                "Previous conversion process (pid:%d) still exists - skipping launch of MakeKML"
                                % lock_file_pid
                            )
                            continue
                        # Create a standard date/time string here
                        makekml_log = os.path.join(
                            mission_dir,
                            f"makekml_{time.strftime('%y%m%d%H%M%S', time.gmtime(time.time()))}",
                        )

                        cmd_line = (
                            "%s %s -v --mission_dir %s --config %s  > %s 2>&1"
                            % (
                                sys.executable,
                                os.path.join(
                                    base_opts.basestation_directory, "MakeKML.py"
                                ),
                                mission_dir,
                                os.path.join(
                                    mission_dir, f"sg{instrument_id:03d}.conf"
                                ),
                                makekml_log,
                            )
                        )

                        log_info(f"Running {cmd_line}")
                        Utils.run_cmd_shell(cmd_line)

                        log_info(
                            f"Back from MakeKML.py - see {makekml_log} for details"
                        )

                        try:
                            msg = {
                                "glider": instrument_id,
                                # This may cause issues with vis, but we'll try it like this to start
                                "dive": 0,
                                "content": "files=kmz",
                                "time": time.time(),
                            }
                            Utils.notifyVis(
                                instrument_id,
                                "urls-files",
                                orjson.dumps(msg).decode("utf-8"),
                            )
                        except Exception:
                            log_error("Failed notification of vis", "exc")

    if False:
        # if kmz_files:
        try:
            fo = open(os.path.join(base_opts.kml_output_dir, "seaglider_ssh.kml"), "w")
        except Exception:
            log_error("Problems opening", "exc")
        else:
            fo.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            fo.write(
                '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2" xmlns:kml="http://www.opengis.net/kml/2.2" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            )
            fo.write("<Document>\n")
            fo.write("<name>Seaglider SSH contours</name>\n")

            for k in kmz_files:
                _, f = os.path.split(k[0])
                href = os.path.join(base_opts.href_base, f)
                fo.write(
                    "    <NetworkLink><name>SG%03d SSH</name><Link><href>%s</href></Link></NetworkLink>\n"
                    % (k[1], href)
                )
            fo.write("</Document></kml>\n")
            fo.close()

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    log_info("Run time %f seconds" % (time.time() - processing_start_time))
    return 0


if __name__ == "__main__":
    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        retval = main()
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_critical("Unhandled exception in main -- exiting")
        sys.exit(1)
    else:
        sys.exit(retval)
