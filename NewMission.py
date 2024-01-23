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

import argparse
import os
import shutil
import sys
import time

import BaseOpts
import BaseDB
import Sensors
from BaseLog import BaseLogger, log_critical, log_error, log_info
from Globals import known_files


def main():
    """Prepares a new deployment directory by setting up appropriate symlinks and stubbing out needed files

    Returns:
        0 for success
        1 for failure

    Raises:
        Any exceptions raised are considered critical errors and not expected

    """
    # Get options
    base_opts = BaseOpts.BaseOptions(
        "Prepares a home directory for a new deployment by setting up symlinks, copying files and stubbing out files.  Note: group ownership of the new mission directory and created files is same as the home directory",
        additional_arguments={
            "initdb": BaseOpts.options_t(
                True,
                ("NewMission",),
                ("--initdb",),
                bool,
                {
                    "help": "Initializes the mission data base",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "glider_home": BaseOpts.options_t(
                None,
                ("NewMission",),
                ("glider_home",),
                BaseOpts.FullPathTrailingSlash,
                {
                    "help": "Seagliders home directory - NOTE: no tilda expansion done",
                    "action": BaseOpts.FullPathTrailingSlashAction,
                },
            ),
            "new_mission_dir": BaseOpts.options_t(
                None,
                ("NewMission",),
                ("new_mission_dir",),
                str,
                {
                    "help": "Mission directory relative to home directory",
                },
            ),
        },
    )

    BaseLogger(base_opts)  # initializes BaseLog

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    if not base_opts.instrument_id:
        try:
            glider_id = int(
                os.path.split(os.path.split(base_opts.glider_home)[0])[1][2:]
            )
            base_opts.instrument_id = glider_id
        except:
            log_error("Failed to figure out instrument_id", "exc")
            return 1

    new_mission_dir = os.path.abspath(
        os.path.join(base_opts.glider_home, base_opts.new_mission_dir)
    )
    current_symlink = os.path.abspath(os.path.join(base_opts.glider_home, "current"))

    if os.path.isdir(new_mission_dir):
        log_error(f"{new_mission_dir} exists - bailing out")
        return 1

    current_mission_dir = None
    if os.path.exists(current_symlink):
        if not os.path.islink(current_symlink):
            log_error(f"{current_symlink} exists and is not a symlink")
            return 1
        current_mission_dir = os.path.realpath(current_symlink)
        if not os.path.isdir(current_mission_dir):
            log_error(
                f"{current_symlink} points to {current_mission_dir} which is not a directory"
            )
            return 1
        log_info(f"Current mission directory {current_mission_dir}")

    log_info(f"Setting up new mission_dir {new_mission_dir}")

    # Set the owner and group - same as most recent mission or home directory
    # The owner may fail if the script is not run by root

    if current_mission_dir:
        stat_st = os.stat(current_mission_dir)
    else:
        stat_st = os.stat(base_opts.glider_home)

    uid = stat_st.st_uid
    gid = stat_st.st_gid

    os.umask(0o000)

    try:
        os.mkdir(new_mission_dir, mode=0o775)
    except:
        log_error(f"Failed to crete {new_mission_dir}", "exc")
        return 1

    items = [new_mission_dir]

    copy_files = [
        "sg_calib_constants.m",
        "sg_plot_constants.m",
        f"sg{base_opts.instrument_id:03d}.conf",
    ]
    copy_files += known_files

    # Add known logger files
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if "known_files" in d:
            for b in d["known_files"]:
                copy_files.append(b)

    for copy_file_name in copy_files:
        copy_file_fullpath = None
        if current_mission_dir:
            copy_file_fullpath = os.path.join(current_mission_dir, copy_file_name)
            if not os.path.exists(copy_file_fullpath):
                copy_file_fullpath = None
        if not copy_file_fullpath:
            copy_file_fullpath = os.path.join(base_opts.glider_home, copy_file_name)
            if not os.path.exists(copy_file_fullpath):
                copy_file_fullpath = None

        if copy_file_fullpath:
            new_copy_file_fullpath = os.path.join(new_mission_dir, copy_file_name)
            try:
                shutil.copy(copy_file_fullpath, new_copy_file_fullpath)
            except:
                log_error(
                    "Failed to propagate {copy_file_fullpath} to {new_copy_file_fullpath}",
                    "exc",
                )
            else:
                items.append(new_copy_file_fullpath)

    # new_cmdfile = os.path.join(new_mission_dir, "cmdfile")
    # try:
    #    with open(new_cmdfile, "w") as fo:
    #        fo.write("$QUIT\n")
    # except:
    #    log_error("Failed to write {new_cmdfile}", "exc")
    ##else:
    #    items.append(new_cmdfile)

    for dotfile in (
        ".pagers",
        ".urls",
        ".mailer",
        ".ftp",
        ".extensions",
        ".pre_extensions",
        ".pre_login",
        ".post_dive",
        ".post_mission",
    ):
        master_dotfile = os.path.join(base_opts.glider_home, dotfile)
        # if os.path.exists(master_dotfile):
        link_dotfile = os.path.join(new_mission_dir, dotfile)
        try:
            os.symlink(master_dotfile, link_dotfile)
        except:
            log_error("Failed to create symlink {link_dotfile}", "exc")
        # Cannot set permissions on symlink files
        # else:
        #    items.append(link_dotfile)

    try:
        os.unlink(current_symlink)
    except FileNotFoundError:
        pass
    except:
        log_error("Failed to unlink symlink {current_symlink} - bailing out", "exc")
        return 1

    try:
        # Create the link relative to the glider_home to support the jail case
        rel_new_mission_dir = os.path.relpath(
            new_mission_dir, start=base_opts.glider_home
        )
        log_info(f"rel_new_mission_dir {rel_new_mission_dir}")
        os.symlink(rel_new_mission_dir, current_symlink, target_is_directory=True)
    except:
        log_error("Failed to create symlink {rel_new_mission_dir} - bailing out", "exc")
        return 1
    # items.append(rel_current_symlink)

    if base_opts.initdb:
        base_opts.mission_dir = new_mission_dir
        BaseDB.createDB(base_opts)
        items.append(
            os.path.join(new_mission_dir, f"sg{base_opts.instrument_id:03d}.db")
        )

    # Update permissions
    for item in items:
        try:
            os.chown(item, uid, -1)
        except PermissionError:
            # If run as regular user, setting the UID is not permitted
            pass
        except:
            log_error(
                f"Failed to set UID on {item} to {uid}",
                "exc",
            )
            return 1

        try:
            os.chown(item, -1, gid)
        except:
            log_error(f"Failed to set GID on {item} to {gid} - bailing out", "exc")
            return 1

        try:
            os.chmod(item, stat_st.st_mode)
        except:
            log_info(
                f"Failed to set permissions on {item}",
                "exc",
            )

    print(f"New Mission directory {new_mission_dir}")
    os.system(f"ls -lta {new_mission_dir}")

    return 0


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
