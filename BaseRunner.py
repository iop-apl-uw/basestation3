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

"""Run processing on behalf of glider accounts"""

import argparse
import os
import pathlib
import pdb
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import traceback

from inotify_simple import INotify, flags
import sdnotify

import BaseOpts
from BaseLog import (
    BaseLogger,
    log_error,
    log_info,
    log_critical,
    log_warning,
    log_debug,
)
import Utils

basestation_dir = str(pathlib.Path(__file__).parent.absolute())

base_runner_lockfile_name = ".base_runner_lockfile"
previous_runner_time_out = 10

known_scripts = ("BaseLogin.py", "GliderEarlyGPS.py", "Base.py")

dog_stroke_interval = 10
inotify_read_timeout = 5 * 1000  # In milliseconds

DEBUG_PDB = False

exit_event = threading.Event()


def quit_func(signo, _frame):
    """Signal handler"""
    log_info("Interrupted by %d, shutting down" % signo)
    exit_event.set()


def main():
    """Run processing on behalf of glider accounts"""

    base_opts = BaseOpts.BaseOptions(
        "Glider Account Processing",
        additional_arguments={
            "python_version": BaseOpts.options_t(
                "/opt/basestation/bin/python",
                ("BaseRunner",),
                ("--python_version",),
                str,
                {
                    "help": "path to python executable",
                },
            ),
            "watch_dir": BaseOpts.options_t(
                None,
                ("BaseRunner",),
                ("watch_dir",),
                str,
                {
                    "help": "Directory where run file are written",
                    "action": BaseOpts.FullPathTrailingSlashAction,
                },
            ),
            "jail_root": BaseOpts.options_t(
                None,
                ("BaseRunner",),
                ("--jail_root",),
                str,
                {
                    "help": "Root of the seaglider jail, if used",
                    "action": BaseOpts.FullPathTrailingSlashAction,
                },
            ),
            "archive": BaseOpts.options_t(
                False,
                ("BaseRunner",),
                ("--archive",),
                str,
                {
                    "help": "Archive off run files",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
        },
    )
    BaseLogger(base_opts, include_time=True)

    for sig in ("TERM", "HUP", "INT"):
        signal.signal(getattr(signal, "SIG" + sig), quit_func)

    if not os.path.exists(base_opts.watch_dir):
        log_error(f"{base_opts.watch_dir} does not exist - bailing out")
        return 1

    os.umask(0o002)

    base_opts.mission_dir = base_opts.watch_dir
    lock_file_pid = Utils.check_lock_file(base_opts, base_runner_lockfile_name)
    if lock_file_pid < 0:
        log_error("Error accessing the lockfile - proceeding anyway...")
    elif lock_file_pid > 0:
        # The PID still exists
        log_warning(
            "Previous runner process (pid:%d) still exists - signalling process to complete"
            % lock_file_pid
        )
        os.kill(lock_file_pid, signal.SIGTERM)
        if Utils.wait_for_pid(lock_file_pid, previous_runner_time_out):
            log_error(
                "Process pid:%d did not respond to sighup after %d seconds - trying to kill"
                % (lock_file_pid, previous_runner_time_out)
            )
            os.kill(lock_file_pid, signal.SIGKILL)

    Utils.create_lock_file(base_opts, base_runner_lockfile_name)

    inotify = INotify()
    watch_flags = flags.CLOSE_WRITE
    inotify.add_watch(base_opts.watch_dir, watch_flags)

    notifier = sdnotify.SystemdNotifier()
    notifier.notify("READY=1")

    next_stroke_time = time.time() + dog_stroke_interval
    # log_info(f"Next stroke {next_stroke_time}")

    while not exit_event.is_set():
        if time.time() > next_stroke_time:
            notifier.notify("WATCHDOG=1")
            next_stroke_time = time.time() + dog_stroke_interval
        for event in inotify.read(timeout=inotify_read_timeout):
            run_file = os.path.join(base_opts.mission_dir, event.name)
            # log_info(f"Received {event.name} {run_file}")
            if not (
                os.path.exists(run_file)
                and stat.S_ISREG(os.stat(run_file).st_mode)
                and run_file.endswith(".run")
            ):
                continue
            # Removal of the run file signals the runner it is okay to proceed
            log_debug(f"Found {run_file}")
            try:
                runfile_line = open(run_file, "r").readline()
                log_info(runfile_line)
                seaglider_root_dir, log_file, cmd_line = runfile_line.split(" ", 2)
                seaglider_root_dir = seaglider_root_dir.rstrip()
                log_file = log_file.rstrip()
                if base_opts.jail_root and log_file.startswith(seaglider_root_dir):
                    log_file = os.path.join(base_opts.jail_root, log_file[1:])
                log_info(f"{seaglider_root_dir}, {log_file}, {cmd_line}")
                if cmd_line.split(" ", 1)[0].rstrip() not in known_scripts:
                    log_error(f"Unknown script ({cmd_line}) - skipping")
                else:
                    # Prepend the basestation directory and add on the python version
                    script, tail = cmd_line.split(" ", 1)
                    full_path_script = os.path.join(basestation_dir, script)
                    cmd_line = f"{base_opts.python_version} {full_path_script} {tail}"

                    if base_opts.jail_root:
                        # Convert to the path outside the jail
                        cmd_line_parts = cmd_line.split()
                        for ii in range(len(cmd_line_parts)):
                            if cmd_line_parts[ii].startswith(seaglider_root_dir):
                                cmd_line_parts[ii] = os.path.join(
                                    base_opts.jail_root, cmd_line_parts[ii][1:]
                                )
                        cmd_line = " ".join(cmd_line_parts)

                    # May not be critical, but for now, this script when launched out of systemd is
                    # running with unbuffered stdin/stdout - no need to launch other scripts this way
                    my_env = os.environ.copy()
                    if "PYTHONUNBUFFERED" in my_env:
                        del my_env["PYTHONUNBUFFERED"]
                    # Re-direct on the cmdline, so scripts run with --daemon launch async and return right away
                    cmd_line += f" >> {log_file} 2>&1"
                    log_info(f"Running {cmd_line}")
                    completed_process = subprocess.run(
                        cmd_line,
                        shell=True,
                        env=my_env,
                        start_new_session=True,
                    )
                    if completed_process.returncode:
                        log_warning(f"{cmd_line} returned {completed_process.returncode}", "exc")
            except KeyboardInterrupt:
                exit_event.set()
            except:
                log_error(f"Error processing {run_file}", "exc")
            finally:
                log_info("Cleanup")
                if os.path.exists(run_file):
                    f_archive_failed = False
                    if base_opts.archive:
                        archive_dir = os.path.join(base_opts.mission_dir, "archive")
                        if not os.path.exists(archive_dir):
                            try:
                                os.mkdir(archive_dir)
                            except:
                                log_error(f"Failed to create {archive_dir}", "exc")
                                f_archive_failed = True
                        if not f_archive_failed:
                            try:
                                shutil.move(run_file, archive_dir)
                            except:
                                log_error(f"Failed to move {run_file} to {archive_dir}", "exc")
                                f_archive_failed = True
                            else:
                                log_info(f"Archived {run_file}")
                    if not base_opts.archive or f_archive_failed:
                        try:
                            os.unlink(run_file)
                        except:
                            log_critical(f"Failed to remove {run_file}", "exc")

    log_info("Shutdown signal received")

    Utils.cleanup_lock_file(base_opts, base_runner_lockfile_name)


if __name__ == "__main__":
    retval = 1

    try:
        retval = main()
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
