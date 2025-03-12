#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025  University of Washington.
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
import collections
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
import uuid

import orjson
import sdnotify
from inotify_simple import INotify, flags

import BaseOpts
import BaseOptsType
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

basestation_dir = str(pathlib.Path(__file__).parent.absolute())

base_runner_lockfile_name = ".base_runner_lockfile"
previous_runner_time_out = 10

known_scripts = ("BaseLogin.py", "GliderEarlyGPS.py", "Base.py")
queued_scripts = ("Base.py",)
docker_scripts = ("Base.py",)

dog_stroke_interval = 10
inotify_read_timeout = 1 * 1000  # In milliseconds

DEBUG_PDB = False

exit_event = threading.Event()

job_queues = collections.defaultdict(collections.deque)
running_jobs = {}


def quit_func(signo, _frame):
    """Signal handler"""
    log_info("Interrupted by %d, shutting down" % signo)
    exit_event.set()


def main():
    """Run processing on behalf of glider accounts"""

    base_opts = BaseOpts.BaseOptions(
        "Glider Account Processing",
        additional_arguments={
            "python_version": BaseOptsType.options_t(
                "/opt/basestation/bin/python",
                ("BaseRunner",),
                ("--python_version",),
                str,
                {
                    "help": "path to python executable",
                },
            ),
            "watch_dir": BaseOptsType.options_t(
                None,
                ("BaseRunner",),
                ("watch_dir",),
                str,
                {
                    "help": "Directory where run file are written",
                    "action": BaseOpts.FullPathTrailingSlashAction,
                },
            ),
            "jail_root": BaseOptsType.options_t(
                "",
                ("BaseRunner",),
                ("--jail_root",),
                str,
                {
                    "help": "Root of the seaglider jail, if used",
                    "action": BaseOpts.FullPathTrailingSlashAction,
                },
            ),
            "archive": BaseOptsType.options_t(
                False,
                ("BaseRunner",),
                ("--archive",),
                bool,
                {
                    "help": "Archive off run files",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "docker_image": BaseOptsType.options_t(
                "",
                ("BaseRunner",),
                ("--docker_image",),
                str,
                {
                    "help": "Docker image to use",
                },
            ),
            "docker_uid": BaseOptsType.options_t(
                -1,
                ("BaseRunner",),
                ("--docker_uid",),
                int,
                {
                    "help": "User id to run docker image as",
                },
            ),
            "docker_gid": BaseOptsType.options_t(
                -1,
                ("BaseRunner",),
                ("--docker_gid",),
                int,
                {
                    "help": "Group id to run docker image as",
                },
            ),
            "use_docker_basestation": BaseOptsType.options_t(
                False,
                ("BaseRunner",),
                ("--use_docker_basestation",),
                bool,
                {
                    "help": "Use the basestation installed in the docker container",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "docker_mount": BaseOptsType.options_t(
                [],
                ("BaseRunner",),
                ("--docker_mount",),
                str,
                {
                    "help": "Additional mounts for the docker container",
                    "action": "append",
                    "nargs": "*",
                },
            ),
            "queue_scripts": BaseOptsType.options_t(
                True,
                ("BaseRunner",),
                ("--queue_scripts",),
                bool,
                {
                    "help": "Additional mounts for the docker container",
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
        else:
            log_info(f"{lock_file_pid} responded to sighup")

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
            # log_debug(f"Found {run_file}")
            try:
                runfile_line = open(run_file, "r").readline()
                log_debug(runfile_line)
                (
                    seaglider_home_dir,
                    seaglider_mission_dir,
                    log_file,
                    cmd_line,
                ) = runfile_line.split(" ", 3)
                seaglider_home_dir = seaglider_home_dir.rstrip()
                seaglider_mission_dir = seaglider_mission_dir.rstrip()
                log_file = log_file.rstrip()
                if base_opts.jail_root:
                    if log_file.startswith(seaglider_mission_dir):
                        log_file = os.path.join(base_opts.jail_root, log_file[1:])
                    seaglider_home_dir = os.path.join(
                        base_opts.jail_root, seaglider_home_dir[1:]
                    )
                    seaglider_mission_dir = os.path.join(
                        base_opts.jail_root, seaglider_mission_dir[1:]
                    )

                try:
                    glider_id = int(os.path.split(seaglider_home_dir)[1][2:])
                except Exception:
                    log_error(
                        f"Unable to get glider id from {seaglider_home_dir} - using 000",
                        "exc",
                    )
                    glider_id = 0

                log_info(
                    f"run_file:{run_file} seaglider_home_dir:{seaglider_home_dir} seaglider_mission_dir:{seaglider_mission_dir} log_file:{log_file}, cmd_line:{cmd_line}"
                )

                script_name = cmd_line.split(" ", 1)[0].rstrip()
                if script_name not in known_scripts:
                    log_error(f"Unknown script ({cmd_line}) - skipping")
                else:
                    # Prepend the basestation directory and add on the python version
                    script, tail = cmd_line.split(" ", 1)
                    if (
                        base_opts.docker_image
                        and base_opts.use_docker_basestation
                        and script in docker_scripts
                    ):
                        full_path_script = os.path.join(
                            "/usr/local/basestation3", script
                        )
                    else:
                        full_path_script = os.path.join(basestation_dir, script)
                    cmd_line = f"{base_opts.python_version} {full_path_script} {tail}"

                    # If this is a script to be queued, do that here.
                    if base_opts.queue_scripts and script_name in queued_scripts:
                        job_id = str(uuid.uuid4())
                        cmd_line_parts = cmd_line.split()
                        if "--daemon" in cmd_line_parts:
                            cmd_line_parts.pop(cmd_line_parts.index("--daemon"))
                        cmd_line_parts.append("--job_id")
                        cmd_line_parts.append(job_id)
                        cmd_line = " ".join(cmd_line_parts)
                        cmd_line += f" >> {log_file} 2>&1"
                        log_info(
                            f"Enqueuing job_id:{job_id} in [{seaglider_mission_dir}:{script_name}] cmd_line:{cmd_line}"
                        )
                        que = (seaglider_mission_dir, script_name, glider_id)
                        job_queues[que].appendleft((job_id, cmd_line))

                        uuids = []
                        for job in job_queues[que]:
                            uuids.append(job[0])
                        if que in running_jobs:
                            uuids.append(running_jobs[que][0])
                        msg = {
                            "glider": glider_id,
                            "queue_id": f"{seaglider_mission_dir}||{script_name}",
                            "time": time.time(),
                            "uuids": uuids,
                            "action": "queued",
                            "target": job_id,
                        }
                        payload = orjson.dumps(msg).decode("utf-8")
                        log_debug(payload)
                        Utils.notifyVis(
                            glider_id,
                            f"{glider_id:03d}-proc-queue",
                            payload,
                        )

                        continue

                    # Re-direct on the cmdline, so scripts run with --daemon launch async and return right away
                    cmd_line = cmd_line.rstrip() + f" >> {log_file} 2>&1"

                    if base_opts.docker_image and script in docker_scripts:
                        # docker run -d --user 1000:1000 --volume /home/sg090:/home/sg090 --volume ~/work/git/basestation3:/usr/local/basestation3  basestation:3.10.10
                        docker_detach = ""
                        cmd_line_parts = cmd_line.split()
                        if "--daemon" in cmd_line_parts:
                            docker_detach = "-d"
                            cmd_line_parts.pop(cmd_line_parts.index("--daemon"))
                        cmd_line = " ".join(cmd_line_parts)
                        basestation_mount = ""
                        if not base_opts.use_docker_basestation:
                            basestation_mount = (
                                f"--volume {basestation_dir}:{basestation_dir}"
                            )
                        for m in base_opts.docker_mount:
                            basestation_mount += f" --volume {m[0]}"
                        if base_opts.docker_uid >= 0 and base_opts.docker_gid >= 0:
                            user_str = f" --user {base_opts.docker_uid}:{base_opts.docker_gid} "
                        else:
                            user_str = ""
                        if seaglider_home_dir != seaglider_mission_dir:
                            home_dir_str = (
                                f"--volume {seaglider_home_dir}:{seaglider_home_dir}"
                            )
                        else:
                            home_dir_str = ""
                        cmd_line = f'docker run {docker_detach} {user_str} {home_dir_str} --ipc="host" --volume {seaglider_mission_dir}:{seaglider_mission_dir} --volume /tmp:/tmp {basestation_mount} {base_opts.docker_image} /usr/bin/sh -c "{cmd_line}"'
                    # May not be critical, but for now, this script when launched out of systemd is
                    # running with unbuffered stdin/stdout - no need to launch other scripts this way
                    my_env = os.environ.copy()
                    if "PYTHONUNBUFFERED" in my_env:
                        del my_env["PYTHONUNBUFFERED"]
                    log_info(f"Running {cmd_line}")
                    completed_process = subprocess.run(
                        cmd_line,
                        shell=True,
                        env=my_env,
                        start_new_session=True,
                    )
                    if completed_process.returncode:
                        log_warning(
                            f"{cmd_line} returned {completed_process.returncode}"
                        )
            except KeyboardInterrupt:
                exit_event.set()
            except Exception:
                log_error(f"Error processing {run_file}", "exc")
            finally:
                log_debug("Cleanup")
                if os.path.exists(run_file):
                    f_archive_failed = False
                    if base_opts.archive:
                        archive_dir = os.path.join(base_opts.mission_dir, "archive")
                        if not os.path.exists(archive_dir):
                            try:
                                os.mkdir(archive_dir)
                            except Exception:
                                log_error(f"Failed to create {archive_dir}", "exc")
                                f_archive_failed = True
                        if not f_archive_failed:
                            try:
                                shutil.move(run_file, archive_dir)
                            except Exception:
                                log_error(
                                    f"Failed to move {run_file} to {archive_dir}", "exc"
                                )
                                f_archive_failed = True
                            else:
                                log_info(f"Archived {run_file}")
                    if not base_opts.archive or f_archive_failed:
                        try:
                            os.unlink(run_file)
                        except Exception:
                            log_critical(f"Failed to remove {run_file}", "exc")

        ## Check for process completion here
        # log_debug("Checking running jobs")
        for que in list(running_jobs):
            try:
                sg_mission_dir, script_name, glider_id = que
                job_id, popen, cmd_line = running_jobs[que]
                returncode = popen.poll()
                if returncode is not None:
                    if returncode:
                        log_warning(f"{job_id}:{cmd_line} returned {returncode}")
                    else:
                        log_info(f"Completed {job_id}:{cmd_line}")
                    # TODO: Check for any pid files left behind
                    running_jobs.pop(que)

                    uuids = []
                    for job in job_queues[que]:
                        uuids.append(job[0])
                    uuids.append(job_id)

                    msg = {
                        "glider": glider_id,
                        "queue_id": f"{seaglider_mission_dir}||{script_name}",
                        "time": time.time(),
                        "uuids": uuids,
                        "action": "complete",
                        "returncode": returncode,
                        "target": job_id,
                    }
                    payload = orjson.dumps(msg).decode("utf-8")
                    log_debug(payload)
                    Utils.notifyVis(
                        glider_id,
                        f"{glider_id:03d}-proc-queue",
                        payload,
                    )
            except KeyboardInterrupt:
                exit_event.set()
            except Exception:
                log_error(f"Error processing {que}", "exc")

        ## Deque and launch here
        # log_debug("Checking for new jobs to launch")
        for que in list(job_queues):
            try:
                if que not in running_jobs:
                    try:
                        job_id, cmd_line = job_queues[que].pop()
                    except IndexError:
                        continue
                    seaglider_mission_dir, script_name, glider_id = que
                    my_env = os.environ.copy()
                    if "PYTHONUNBUFFERED" in my_env:
                        del my_env["PYTHONUNBUFFERED"]
                    log_info(f"Starting {job_id}:{cmd_line}")
                    popen = subprocess.Popen(
                        cmd_line,
                        shell=True,
                        env=my_env,
                        # TODO - check if this is needed
                        start_new_session=True,
                    )
                    running_jobs[que] = (job_id, popen, cmd_line)

                    uuids = []
                    for job in job_queues[que]:
                        uuids.append(job[0])
                    uuids.append(job_id)

                    msg = {
                        "glider": glider_id,
                        "queue_id": f"{seaglider_mission_dir}||{script_name}",
                        "time": time.time(),
                        "uuids": uuids,
                        "action": "start",
                        "target": job_id,
                    }
                    payload = orjson.dumps(msg).decode("utf-8")
                    log_debug(payload)
                    Utils.notifyVis(
                        glider_id,
                        f"{glider_id:03d}-proc-queue",
                        payload,
                    )

            except KeyboardInterrupt:
                exit_event.set()
            except Exception:
                log_error(f"Error processing {que}", "exc")

    log_info("Shutdown signal received")

    Utils.cleanup_lock_file(base_opts, base_runner_lockfile_name)
    return 0


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
