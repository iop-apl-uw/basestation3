#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2026  University of Washington.
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

"""Run processing on behalf of glider accounts - consolidated multi-site runner.

Replaces the one-process-per-site BaseRunner.py model with a single process
that watches every site's rundir (one inotify instance, one add_watch per
site) and dispatches jobs through BaseRunnerPrivExec.py, the only process
that holds CAP_SETUID/CAP_SETGID. This process itself - which parses
`.run`-file content originating from jailed, semi-trusted glider accounts -
never holds that capability and never runs as root; it only ever sends the
privileged helper a site *name* to look up in its own table.

Site identity for every filesystem operation is anchored to the inotify
watch descriptor a `.run` file arrived on (SiteRegistry.site_for_wd), never
to anything parsed out of the file's content - once one process legitimately
watches every site, the OS no longer backstops a code bug that confuses
which site a path belongs to, so this is the only thing that does.

Sites migrate from BaseRunner.py one at a time by repointing that site's
systemd unit - both processes use the same lock-file name
(base_runner_lockfile_name) on purpose, so starting BaseRunnerMulti for a
site automatically detects and signals a still-running old BaseRunner.py
instance for that same site to stop, the same way BaseRunner.py already
self-heals against a stale previous instance of itself.
"""

from __future__ import annotations

import collections
import dataclasses
import os
import pathlib
import pdb
import shutil
import signal
import socket
import stat
import struct
import sys
import threading
import time
import traceback
import uuid
from typing import Protocol

import orjson
import sdnotify
from inotify_simple import INotify, flags

import BaseOpts
import BaseOptsType
import SiteConfig
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

basestation_dir = str(pathlib.Path(__file__).parent.resolve())

base_runner_lockfile_name = ".base_runner_lockfile"

known_scripts = ("BaseLogin.py", "GliderEarlyGPS.py", "Base.py")
queued_scripts = ("BaseLogin.py", "GliderEarlyGPS.py", "Base.py")
docker_scripts = ("Base.py",)

# Scripts whose queued dispatch should receive Base.py-specific CLI flags
# and vis-progress notifications. BaseLogin.py/GliderEarlyGPS.py are queued
# (above) purely to avoid blocking the shared dispatch loop - they don't
# declare --job_id/--queue_length support and don't need vis progress UI.
job_id_scripts = ("Base.py",)
queue_length_scripts = ("Base.py",)
vis_notify_scripts = ("Base.py",)

# Scripts whose successful completion gets a timing line appended directly
# to the glider's own log_file (baselog.log), independent of this daemon's
# own log level, so the launch-latency floor stays visible for routine
# review without needing this daemon's log turned up.
timing_log_scripts = ("BaseLogin.py", "GliderEarlyGPS.py")

dog_stroke_interval = 10
inotify_read_timeout = 1 * 1000  # In milliseconds
site_retry_interval = 60  # Seconds between retrying sites that failed to activate

DEBUG_PDB = False

exit_event = threading.Event()


def quit_func(signo: int, _frame: object) -> None:
    """Signal handler - requests a clean shutdown.

    Args:
        signo: The signal number received.
        _frame: Unused stack frame, per the signal.signal handler contract.

    Returns:
        None.
    """
    log_info(f"Interrupted by {signo}, shutting down")
    exit_event.set()


def _try_activate_site(site: SiteConfig.SiteConfig) -> bool:
    """Checks a site's watch_dir exists and acquires its lock file.

    Migrating a site is a manual, operator-driven cutover: stop the old
    per-site BaseRunner.py unit, then (re)start BaseRunnerMulti with that
    site in sites.yaml - see docs/BaseRunnerMulti.md's "Migrating a
    site". If a stale lock is still held by a live process, this refuses
    to activate the site rather than trying to evict it automatically:
    an earlier version of this function did that (signaling the old
    process, escalating to SIGKILL), but that mechanism required routing
    every eviction through BaseRunnerPrivExec (this process can't signal
    a different uid's process directly) and, per real multipass VM
    testing, still wasn't reliable against a still-enabled unit with
    Restart=always - systemd just restarts it. A loud "still running,
    fix it yourself" is simpler and more honest than a self-healing path
    that doesn't reliably self-heal.

    Args:
        site: The site to attempt to activate.

    Returns:
        True if the site's watch_dir exists and its lock was acquired,
        False if the site isn't ready yet (missing watch_dir, or a live
        process still holds its lock) and should stay pending.
    """
    if not site.watch_dir.exists():
        log_error(f"[{site.name}] {site.watch_dir} does not exist - skipping for now")
        return False

    # SiteConfig duck-types as the BaseOptions these Utils lock-file helpers
    # expect - they only ever read .mission_dir/.ignore_lock off whatever
    # they're given (confirmed in Utils.py), which SiteConfig provides.
    lock_file_pid = Utils.check_lock_file(site, base_runner_lockfile_name)  # ty: ignore[invalid-argument-type]
    if lock_file_pid < 0:
        log_error(f"[{site.name}] Error accessing the lockfile - proceeding anyway...")
    elif lock_file_pid > 0:
        log_error(
            f"[{site.name}] pid:{lock_file_pid} still holds this site's lock - "
            "stop the old BaseRunner.py unit for this site first, then it will "
            "be picked up on the next retry"
        )
        return False

    Utils.create_lock_file(site, base_runner_lockfile_name)  # ty: ignore[invalid-argument-type]
    return True


class InotifyLike(Protocol):
    """The one INotify method SiteRegistry needs - kept narrow so tests can
    supply a fake instead of a real INotify (which requires a real Linux
    inotify syscall, unavailable e.g. under local development on macOS).
    """

    def add_watch(self, path: str, mask: int) -> int:
        """See inotify_simple.INotify.add_watch."""
        ...


class SiteRegistry:
    """Tracks which sites are actively watched vs. still pending activation."""

    def __init__(
        self, sites: dict[str, SiteConfig.SiteConfig], inotify: InotifyLike
    ) -> None:
        """Builds the registry and makes an initial activation pass.

        Args:
            sites: Every site loaded from sites.yaml.
            inotify: The single shared INotify instance to register watches on.
        """
        self._sites = sites
        self._inotify = inotify
        self._wd_to_site: dict[int, SiteConfig.SiteConfig] = {}
        self._pending: set[str] = set(sites)
        self.activate_pending()

    @property
    def active_sites(self) -> list[SiteConfig.SiteConfig]:
        """Returns the sites currently being watched.

        Returns:
            A list of active SiteConfig instances.
        """
        return list(self._wd_to_site.values())

    def activate_pending(self) -> None:
        """Attempts to activate every currently-pending site.

        A site that isn't ready yet (missing watch_dir, or an inotify
        add_watch failure) stays pending and is retried on the next call -
        one bad site must not prevent the other sites from being watched.

        Returns:
            None.
        """
        for name in list(self._pending):
            site = self._sites[name]
            if not _try_activate_site(site):
                continue
            try:
                wd = self._inotify.add_watch(str(site.watch_dir), flags.CLOSE_WRITE)
            except OSError:
                log_error(
                    f"[{site.name}] Failed to add inotify watch on {site.watch_dir}",
                    "exc",
                )
                continue
            self._wd_to_site[wd] = site
            self._pending.discard(name)
            log_info(f"[{site.name}] now watching {site.watch_dir}")

    def site_for_wd(self, wd: int) -> SiteConfig.SiteConfig | None:
        """Looks up which site an inotify watch descriptor belongs to.

        This is the sole mechanism for recovering site identity from an
        inotify event - never parsed from event.name or `.run`-file content.

        Args:
            wd: The watch descriptor from an inotify Event.

        Returns:
            The owning SiteConfig, or None if wd is unrecognized.
        """
        return self._wd_to_site.get(wd)


class PrivExecError(Exception):
    """Raised when the privileged exec helper is unreachable or misbehaves.

    Covers connection-level failures (socket refused, no response, garbled
    reply) - the helper may simply be mid-restart, so callers are expected
    to retry.
    """


class PrivExecRejected(PrivExecError):
    """Raised when the helper is up but rejects the request as invalid.

    This means the request itself is malformed (unknown site, argv, or a
    log_file outside the site's tree) - a condition retrying will never fix,
    since nothing about the request changes between attempts.
    """


class PrivExecClient(Protocol):
    """Interface Dispatcher uses to reach BaseRunnerPrivExec.py.

    Kept as a small structural interface so Dispatcher's dispatch/
    completion logic can be tested against a fake in-memory implementation,
    with no real socket or helper process needed.
    """

    def dispatch(self, site: str, argv: list[str], log_file: pathlib.Path) -> int:
        """Requests a job be launched as site's runner account.

        Args:
            site: Site name to run as.
            argv: Full argv, including argv[0] as the executable path.
            log_file: Path the job's stdout/stderr should be appended to.

        Returns:
            The pid of the launched job.

        Raises:
            PrivExecError: If the helper is unreachable or fails.
            PrivExecRejected: If the helper rejects the request as invalid.
        """
        ...

    def status(self, pid: int) -> tuple[bool, int | None]:
        """Checks on a previously-dispatched job.

        Args:
            pid: pid returned from a prior dispatch() call.

        Returns:
            (done, returncode) - returncode is None while still running.

        Raises:
            PrivExecError: If the helper rejects or fails the request.
        """
        ...


_LEN_STRUCT = struct.Struct(">I")


def _send_frame(sock: socket.socket, payload: bytes) -> None:
    """Sends one length-prefixed frame over sock.

    Args:
        sock: Connected socket to write to.
        payload: Frame body to send.

    Returns:
        None.

    Raises:
        OSError: If the underlying socket write fails.
    """
    sock.sendall(_LEN_STRUCT.pack(len(payload)) + payload)


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    """Reads exactly n bytes from sock, or None if the peer closed early.

    Args:
        sock: Connected socket to read from.
        n: Number of bytes to read.

    Returns:
        The bytes read, or None if the connection closed early.

    Raises:
        OSError: If the underlying socket read fails.
    """
    chunks = bytearray()
    while len(chunks) < n:
        chunk = sock.recv(n - len(chunks))
        if not chunk:
            return None
        chunks.extend(chunk)
    return bytes(chunks)


def _recv_frame(sock: socket.socket) -> bytes | None:
    """Reads one length-prefixed frame from sock.

    Args:
        sock: Connected socket to read from.

    Returns:
        The frame body, or None if the connection closed early.

    Raises:
        OSError: If the underlying socket read fails.
    """
    header = _recv_exact(sock, _LEN_STRUCT.size)
    if header is None:
        return None
    (length,) = _LEN_STRUCT.unpack(header)
    return _recv_exact(sock, length)


class UnixSocketPrivExecClient:
    """PrivExecClient implementation that talks to BaseRunnerPrivExec.py."""

    def __init__(self, socket_path: str) -> None:
        """Initializes the client.

        Args:
            socket_path: Path to the privileged helper's UNIX socket.
        """
        self._socket_path = socket_path

    def _request(self, payload: dict) -> dict:
        """Sends one request and returns the parsed, successful response.

        Args:
            payload: Request dict to send.

        Returns:
            The parsed response dict (guaranteed "ok": True).

        Raises:
            PrivExecError: If the connection fails or the response is
                malformed.
            PrivExecRejected: If the helper reports the request itself is
                invalid.
        """
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(self._socket_path)
        except OSError as exc:
            sock.close()
            raise PrivExecError(f"could not reach privileged exec helper: {exc}") from exc

        try:
            _send_frame(sock, orjson.dumps(payload))
            data = _recv_frame(sock)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            # The peer closed without responding - same situation as a clean
            # EOF (_recv_frame returning None), just surfaced as a reset
            # instead of an empty read on some platforms/kernels.
            data = None
        except OSError as exc:
            raise PrivExecError(f"could not reach privileged exec helper: {exc}") from exc
        finally:
            sock.close()

        if data is None:
            raise PrivExecError("no response from privileged exec helper")
        response = orjson.loads(data)
        if not response.get("ok", False):
            raise PrivExecRejected(response.get("error", "unknown error"))
        return response

    def dispatch(self, site: str, argv: list[str], log_file: pathlib.Path) -> int:
        """See PrivExecClient.dispatch."""
        response = self._request(
            {"site": site, "argv": argv, "log_file": str(log_file)}
        )
        return response["pid"]

    def status(self, pid: int) -> tuple[bool, int | None]:
        """See PrivExecClient.status."""
        response = self._request({"query": "status", "pid": pid})
        return response["done"], response.get("returncode")


@dataclasses.dataclass
class QueuedJob:
    """One job waiting in a site/mission/script queue."""

    job_id: str
    argv: list[str]
    log_file: pathlib.Path


@dataclasses.dataclass
class RunningJob:
    """One job dispatched to the privileged exec helper and not yet reaped."""

    job_id: str
    pid: int
    argv: list[str]
    log_file: pathlib.Path
    start_time: float


def _update_queue_length(argv: list[str], length: int) -> list[str]:
    """Replaces a queued job's placeholder "--queue_length 0" with its real value.

    Args:
        argv: The job's argv, as originally enqueued.
        length: The queue's current length (excluding this job).

    Returns:
        A new argv list with --queue_length's value updated, or an
        unmodified copy if --queue_length isn't present.
    """
    argv = list(argv)
    try:
        idx = argv.index("--queue_length")
    except ValueError:
        return argv
    if idx + 1 < len(argv):
        argv[idx + 1] = str(length)
    return argv


class Dispatcher:
    """Owns the multi-site job_queues/running_jobs state and dispatch logic.

    Kept as an object (rather than BaseRunner.py's module-level globals) so
    it can be constructed fresh per test, with a fake PrivExecClient, with
    no shared mutable state leaking between tests.
    """

    def __init__(self, priv_client: PrivExecClient, notify_vis: bool = False) -> None:
        """Initializes empty queues.

        Args:
            priv_client: Client used to reach the privileged exec helper.
            notify_vis: Whether _notify_vis() should actually push to vis.
                Defaults to False (the test-safe value); main() passes
                the real base_opts.notify_vis value explicitly.
        """
        self._priv_client = priv_client
        self._notify_vis_enabled = notify_vis
        self.job_queues: collections.defaultdict[tuple, collections.deque] = (
            collections.defaultdict(collections.deque)
        )
        self.running_jobs: dict[tuple, RunningJob] = {}

    def handle_run_file_event(self, site: SiteConfig.SiteConfig, run_file: pathlib.Path) -> None:
        """Processes one detected `.run` file for site, if still valid.

        Args:
            site: The site this run_file belongs to (from the inotify wd
                it arrived on - never inferred from file content).
            run_file: Full path to the candidate `.run` file.

        Returns:
            None.
        """
        if not (
            run_file.exists()
            and stat.S_ISREG(run_file.stat().st_mode)
            and run_file.name.endswith(".run")
        ):
            return
        try:
            self._process_run_file(site, run_file)
        except KeyboardInterrupt:
            exit_event.set()
        except Exception:
            log_error(f"[{site.name}] Error processing {run_file}", "exc")
        finally:
            self._cleanup_run_file(site, run_file)

    def _process_run_file(self, site: SiteConfig.SiteConfig, run_file: pathlib.Path) -> None:
        """Parses and dispatches (or enqueues) one `.run` file's job.

        Args:
            site: The owning site.
            run_file: Path to the `.run` file.

        Returns:
            None.

        Raises:
            Exception: Any parsing/dispatch failure - caught by the caller.
        """
        with run_file.open("r") as fo:
            runfile_line = fo.readline()
        log_debug(runfile_line)
        seaglider_home_dir, seaglider_mission_dir, log_file, cmd_line = runfile_line.split(
            " ", 3
        )
        seaglider_home_dir = seaglider_home_dir.rstrip()
        seaglider_mission_dir = seaglider_mission_dir.rstrip()
        log_file = log_file.rstrip()
        if site.jailed and log_file.startswith(seaglider_mission_dir):
            log_file = str(site.jail_root / log_file[1:])

        try:
            glider_id = int(pathlib.Path(seaglider_home_dir).name[2:])
        except Exception:
            log_error(
                f"[{site.name}] Unable to get glider id from {seaglider_home_dir} "
                "- using 000",
                "exc",
            )
            glider_id = 0

        log_info(
            f"[{site.name}] run_file:{run_file} seaglider_home_dir:{seaglider_home_dir} "
            f"seaglider_mission_dir:{seaglider_mission_dir} log_file:{log_file}, "
            f"cmd_line:{cmd_line}"
        )

        script_name = cmd_line.split(" ", 1)[0].rstrip()
        if script_name not in known_scripts:
            log_error(f"[{site.name}] Unknown script ({cmd_line}) - skipping")
            return

        script, tail = cmd_line.split(" ", 1)
        if site.docker_image and site.use_docker_basestation and script in docker_scripts:
            full_path_script = str(pathlib.Path("/usr/local/basestation3") / script)
        else:
            full_path_script = str(pathlib.Path(basestation_dir) / script)

        argv = [site.python_version, full_path_script, *tail.split()]

        if site.jailed:
            for ii, part in enumerate(argv):
                if part.startswith(seaglider_mission_dir):
                    argv[ii] = str(site.jail_root / part[1:])
            seaglider_mission_dir = str(site.jail_root / seaglider_mission_dir[1:])

        if site.queue_scripts and script_name in queued_scripts:
            self._enqueue(site, script_name, glider_id, seaglider_mission_dir, argv, log_file)
            return

        self._dispatch_blocking(site, argv, log_file)

    def _enqueue(
        self,
        site: SiteConfig.SiteConfig,
        script_name: str,
        glider_id: int,
        seaglider_mission_dir: str,
        argv: list[str],
        log_file: str,
    ) -> None:
        """Queues a job for async dispatch instead of running it inline.

        Args:
            site: The owning site.
            script_name: Basename of the script to run.
            glider_id: Numeric glider id, for vis notifications.
            seaglider_mission_dir: Mission directory (already jail-rewritten).
            argv: The job's argv (mutated with a copy internally).
            log_file: Path the job's stdout/stderr should be appended to.

        Returns:
            None.
        """
        job_id = str(uuid.uuid4())
        argv = list(argv)
        if "--daemon" in argv:
            argv.remove("--daemon")
        if script_name in job_id_scripts:
            argv.extend(["--job_id", job_id])
        if script_name in queue_length_scripts:
            argv.extend(["--queue_length", "0"])

        log_info(
            f"[{site.name}] Enqueuing job_id:{job_id} in "
            f"[{seaglider_mission_dir}:{script_name}] argv:{argv}"
        )
        que = (site.name, seaglider_mission_dir, script_name, glider_id)
        self.job_queues[que].appendleft(QueuedJob(job_id, argv, pathlib.Path(log_file)))

        if script_name in vis_notify_scripts:
            uuids = [job.job_id for job in self.job_queues[que]]
            if que in self.running_jobs:
                uuids.append(self.running_jobs[que].job_id)
            self._notify_vis(que, glider_id, uuids, "queued", job_id, returncode=None)

    def _dispatch_blocking(
        self, site: SiteConfig.SiteConfig, argv: list[str], log_file: str
    ) -> None:
        """Runs a non-queued script synchronously, blocking this event loop.

        Not reachable under any current sites.yaml - every SiteConfig
        defaults queue_scripts=True and every known_scripts entry is also
        in queued_scripts. Kept only for structural parity with
        BaseRunner.py, which has the same always-taken queued branch.
        Unlike BaseRunner.py, this blocks the SHARED multi-site loop, not
        just one site's - do not set queue_scripts=False in production.

        Args:
            site: The owning site.
            argv: The job's argv.
            log_file: Path the job's stdout/stderr should be appended to.

        Returns:
            None.
        """
        log_info(f"[{site.name}] Running {argv}")
        pid = self._priv_client.dispatch(site.name, argv, pathlib.Path(log_file))
        while True:
            done, returncode = self._priv_client.status(pid)
            if done:
                break
            time.sleep(0.1)
        if returncode:
            log_warning(f"[{site.name}] {argv} returned {returncode}")

    def _cleanup_run_file(self, site: SiteConfig.SiteConfig, run_file: pathlib.Path) -> None:
        """Archives or removes a consumed `.run` file.

        Args:
            site: The owning site.
            run_file: Path to the `.run` file to clean up.

        Returns:
            None.
        """
        log_debug("Cleanup")
        if not run_file.exists():
            return
        if not SiteConfig.is_contained(run_file, site.watch_dir):
            log_critical(
                f"[{site.name}] refusing to archive/remove {run_file} - not "
                f"contained within {site.watch_dir}"
            )
            return

        f_archive_failed = False
        if site.archive:
            archive_dir = site.watch_dir / "archive"
            if not archive_dir.exists():
                try:
                    archive_dir.mkdir()
                except Exception:
                    log_error(f"[{site.name}] Failed to create {archive_dir}", "exc")
                    f_archive_failed = True
            if not f_archive_failed:
                try:
                    shutil.move(str(run_file), str(archive_dir))
                except Exception:
                    log_error(
                        f"[{site.name}] Failed to move {run_file} to {archive_dir}", "exc"
                    )
                    f_archive_failed = True
                else:
                    log_info(f"[{site.name}] Archived {run_file}")
        if not site.archive or f_archive_failed:
            try:
                run_file.unlink()
            except Exception:
                log_critical(f"[{site.name}] Failed to remove {run_file}", "exc")

    def poll_completions(self) -> None:
        """Checks every in-flight job for completion, one loop pass.

        Returns:
            None.
        """
        for que in list(self.running_jobs):
            try:
                self._poll_one_completion(que)
            except Exception:
                log_error(f"Error processing {que}", "exc")

    def _poll_one_completion(self, que: tuple) -> None:
        """Checks one in-flight job for completion.

        Args:
            que: The (site_name, seaglider_mission_dir, script_name,
                glider_id) key into running_jobs.

        Returns:
            None.
        """
        site_name, _seaglider_mission_dir, script_name, glider_id = que
        running = self.running_jobs[que]
        try:
            done, returncode = self._priv_client.status(running.pid)
        except PrivExecError:
            log_error(f"[{site_name}] Could not get status for pid {running.pid}", "exc")
            return
        if not done:
            return

        if returncode:
            log_warning(f"[{site_name}] {running.job_id}:{running.argv} returned {returncode}")
        else:
            log_info(f"[{site_name}] Completed {running.job_id}:{running.argv}")
        self.running_jobs.pop(que)

        if script_name in timing_log_scripts:
            self._write_timing_line(site_name, script_name, running, returncode)

        if script_name in vis_notify_scripts:
            uuids = [job.job_id for job in self.job_queues[que]]
            uuids.append(running.job_id)
            self._notify_vis(que, glider_id, uuids, "complete", running.job_id, returncode)

    def _write_timing_line(
        self,
        site_name: str,
        script_name: str,
        running: RunningJob,
        returncode: int | None,
    ) -> None:
        """Appends a completion-timing line directly to the job's own log_file.

        Args:
            site_name: Owning site's name, for error logging only.
            script_name: Basename of the script that ran.
            running: The completed job's bookkeeping record.
            returncode: The job's exit code.

        Returns:
            None.
        """
        try:
            duration = time.time() - running.start_time
            now_str = time.strftime("%H:%M:%S %d %b %Y", time.gmtime())
            start_str = time.strftime("%H:%M:%S %d %b %Y", time.gmtime(running.start_time))
            with running.log_file.open("a") as fo:
                fo.write(
                    f"{now_str} UTC: INFO: BaseRunner: "
                    f"{script_name} (job_id={running.job_id}) started "
                    f"{start_str} UTC, completed in {duration:.2f}s, "
                    f"returncode={returncode}\n"
                )
        except Exception:
            log_error(f"[{site_name}] Failed to write timing line to {running.log_file}", "exc")

    def dispatch_queued(self) -> None:
        """Launches the next queued job for every site/mission/script queue.

        Returns:
            None.
        """
        for que in list(self.job_queues):
            try:
                self._dispatch_one_queued(que)
            except Exception:
                log_error(f"Error processing {que}", "exc")

    def _dispatch_one_queued(self, que: tuple) -> None:
        """Launches the next queued job for one site/mission/script queue.

        Args:
            que: The (site_name, seaglider_mission_dir, script_name,
                glider_id) key into job_queues.

        Returns:
            None.
        """
        if que in self.running_jobs:
            return
        try:
            job = self.job_queues[que].pop()
        except IndexError:
            return

        argv = _update_queue_length(job.argv, len(self.job_queues[que]))
        site_name, _seaglider_mission_dir, script_name, glider_id = que

        log_info(f"[{site_name}] Starting {job.job_id}:{argv}")
        start_time = time.time()
        try:
            pid = self._priv_client.dispatch(site_name, argv, job.log_file)
        except PrivExecRejected as exc:
            # The helper is up and has told us this exact request is
            # invalid (unknown site, bad argv, log_file outside the site's
            # tree, ...) - nothing about the request changes on a retry, so
            # requeuing would spin forever re-issuing the same rejection.
            # Drop the job, but write the failure where a pilot reviewing
            # the mission will actually see it.
            log_error(f"[{site_name}] Dropping {job.job_id}:{argv} - rejected: {exc}")
            try:
                with job.log_file.open("a") as fo:
                    fo.write(f"ERROR: BaseRunner: dispatch rejected, job dropped: {exc}\n")
            except OSError:
                log_error(f"[{site_name}] Failed to record rejection to {job.log_file}", "exc")
            return
        except Exception:
            # Put it back rather than dropping it: the .run file that
            # produced this job is already gone (cleaned up at enqueue
            # time), so a lost job here has no other path back into the
            # queue and would otherwise vanish silently on any transient
            # privileged-helper outage (e.g. a restart to pick up a
            # config change).
            self.job_queues[que].append(job)
            raise
        self.running_jobs[que] = RunningJob(job.job_id, pid, argv, job.log_file, start_time)

        if script_name in vis_notify_scripts:
            uuids = [j.job_id for j in self.job_queues[que]]
            uuids.append(job.job_id)
            self._notify_vis(que, glider_id, uuids, "start", job.job_id, returncode=None)

    def _notify_vis(
        self,
        que: tuple,
        glider_id: int,
        uuids: list[str],
        action: str,
        target: str,
        returncode: int | None,
    ) -> None:
        """Sends one proc-queue vis notification.

        Args:
            que: The (site_name, seaglider_mission_dir, script_name,
                glider_id) key the notification is about.
            glider_id: Numeric glider id.
            uuids: Job ids currently queued/in-flight for this que.
            action: One of "queued", "start", "complete".
            target: job_id this notification is about.
            returncode: Only meaningful for action="complete".

        Returns:
            None.
        """
        if not self._notify_vis_enabled:
            return
        site_name, seaglider_mission_dir, script_name, _ = que
        msg: dict[str, int | str | float | list[str] | None] = {
            "glider": glider_id,
            "queue_id": f"{site_name}||{seaglider_mission_dir}||{script_name}",
            "time": time.time(),
            "uuids": uuids,
            "action": action,
            "target": target,
        }
        if action == "complete":
            msg["returncode"] = returncode
        payload = orjson.dumps(msg).decode("utf-8")
        log_debug(payload)
        Utils.notifyVis(glider_id, "proc-queue", payload)


def main() -> int:
    """Run processing on behalf of glider accounts across every configured site.

    Returns:
        0 on clean shutdown, 1 if sites.yaml failed to load or no site
        could be activated.
    """
    base_opts = BaseOpts.BaseOptions(
        "Glider Account Processing (multi-site)",
        additional_arguments={
            "sites_config": BaseOptsType.options_t(
                None,
                {"BaseRunnerMulti"},
                ("--sites_config",),
                pathlib.Path,
                {
                    "help": "Path to sites.yaml",
                    "action": BaseOpts.FullPathlibAction,
                    "required": {"BaseRunnerMulti"},
                },
            ),
            "priv_exec_socket": BaseOptsType.options_t(
                "/run/baserunner/priv_exec.sock",
                {"BaseRunnerMulti"},
                ("--priv_exec_socket",),
                str,
                {"help": "UNIX socket path of the privileged exec helper"},
            ),
        },
    )
    BaseLogger(base_opts, include_time=True)

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    for sig in ("TERM", "HUP", "INT"):
        signal.signal(getattr(signal, "SIG" + sig), quit_func)

    sites = SiteConfig.load_sites_config(base_opts.sites_config)
    if sites is None:
        log_error("Failed to load sites config - exiting")
        return 1

    os.umask(0o002)

    inotify = INotify()
    registry = SiteRegistry(sites, inotify)
    if not registry.active_sites:
        log_error("No sites could be activated - exiting")
        return 1

    priv_client = UnixSocketPrivExecClient(base_opts.priv_exec_socket)
    dispatcher = Dispatcher(priv_client, notify_vis=base_opts.notify_vis)

    notifier = sdnotify.SystemdNotifier()
    notifier.notify("READY=1")

    next_stroke_time = time.time() + dog_stroke_interval
    next_retry_time = time.time() + site_retry_interval

    while not exit_event.is_set():
        if time.time() > next_stroke_time:
            notifier.notify("WATCHDOG=1")
            next_stroke_time = time.time() + dog_stroke_interval

        if time.time() > next_retry_time:
            registry.activate_pending()
            next_retry_time = time.time() + site_retry_interval

        for event in inotify.read(timeout=inotify_read_timeout):
            site = registry.site_for_wd(event.wd)
            if site is None:
                log_error(f"inotify event for unknown wd {event.wd} - ignoring")
                continue
            run_file = site.watch_dir / event.name
            dispatcher.handle_run_file_event(site, run_file)

        dispatcher.poll_completions()
        dispatcher.dispatch_queued()

    log_info("Shutdown signal received")
    for site in registry.active_sites:
        Utils.cleanup_lock_file(site, base_runner_lockfile_name)  # ty: ignore[invalid-argument-type]

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
