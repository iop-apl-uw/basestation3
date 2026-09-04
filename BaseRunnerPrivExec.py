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

"""Privileged exec helper for BaseRunnerMulti.

This is the ONLY process in the BaseRunnerMulti design that holds
CAP_SETUID/CAP_SETGID (granted narrowly via the systemd unit's
AmbientCapabilities=/CapabilityBoundingSet=, never via sudo and never as
root). BaseRunnerMulti.py itself - which parses `.run`-file content
originating from jailed, semi-trusted glider accounts - never holds this
capability; it only ever sends this helper a site *name* over a local
UNIX socket, and this helper looks that name up in its own table (loaded
independently from the same sites.yaml) to find the target uid/gid. There
is no code path by which a compromised caller could ask this helper to
become an arbitrary uid.

Non-negotiable invariant: the privilege-drop syscall order in
PrivilegeDropper.drop_and_exec is setgroups -> setgid -> setuid -> execve,
in that exact order. See that method's docstring for why.
"""

from __future__ import annotations

import ctypes
import dataclasses
import os
import pathlib
import signal
import socket
import struct
import sys
import threading

import orjson
import sdnotify

import BaseOpts
import BaseOptsType
import SiteConfig
from BaseLog import BaseLogger, log_error, log_info, log_warning

_LEN_STRUCT = struct.Struct(">I")
_PR_SET_CHILD_SUBREAPER = 36


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
        The bytes read, or None if the connection closed before n bytes
        were available.

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
        The frame body, or None if the connection closed before a full
        frame was received.

    Raises:
        OSError: If the underlying socket read fails.
    """
    header = _recv_exact(sock, _LEN_STRUCT.size)
    if header is None:
        return None
    (length,) = _LEN_STRUCT.unpack(header)
    return _recv_exact(sock, length)


def _peer_uid(conn: socket.socket) -> int | None:
    """Returns the connecting peer's uid via SO_PEERCRED, if available.

    SO_PEERCRED is Linux-only; on platforms without it (e.g. local
    development on macOS) this returns None and the caller should treat
    peer-uid enforcement as unavailable rather than failing closed, since
    the primary access control is the socket file's own permissions.

    Args:
        conn: Connected socket to query.

    Returns:
        The peer's uid, or None if SO_PEERCRED is unavailable on this
        platform.

    Raises:
        OSError: If the getsockopt call itself fails unexpectedly.
    """
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


def _set_child_subreaper() -> None:
    """Best-effort: marks this process a reaper for orphaned grandchildren.

    Ensures any descendant a launched job forks off itself still gets
    reaped by this process instead of leaking as a zombie under init/
    systemd. Linux-only; a no-op (with a warning) elsewhere.

    Returns:
        None.

    Raises:
        No exceptions are raised.
    """
    if not sys.platform.startswith("linux"):
        log_warning("PR_SET_CHILD_SUBREAPER unavailable on this platform - skipping")
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        log_warning(f"prctl(PR_SET_CHILD_SUBREAPER) failed: errno={errno}")


def _move_self_into_leaf_cgroup(cgroup_root: pathlib.Path) -> None:
    """Moves this process into its own leaf child cgroup under cgroup_root.

    cgroup v2's "no internal process" constraint means a cgroup can't both
    hold member processes directly AND have a controller enabled in its
    own cgroup.subtree_control for children - and systemd starts a
    unit's main process directly inside that unit's own cgroup
    (cgroup_root here). Without this, CgroupJoiner.join()'s later attempt
    to enable "cpu" in cgroup_root/cgroup.subtree_control fails with
    ENOTSUP, because this daemon's own pid is still sitting directly in
    cgroup_root. Confirmed empirically on a real cgroup v2 mount (see
    .claude/plans/2026-08-11-multipass-baserunner-validation.md) - not
    something the original design derivation anticipated.

    Called once at startup, before any CgroupJoiner.join() call.

    Args:
        cgroup_root: Root of this process's own delegated cgroup subtree.

    Returns:
        None.

    Raises:
        No exceptions are raised - failure here just means per-site CPU
        throttling won't work (CgroupJoiner.join() will itself fail-open
        the same way it does for any other cgroup error), not that the
        daemon can't run.
    """
    leaf = cgroup_root / "supervisor"
    try:
        leaf.mkdir(parents=True, exist_ok=True)
        (leaf / "cgroup.procs").write_text(f"{os.getpid()}\n")
    except OSError as exc:
        log_warning(
            f"Could not move into leaf cgroup {leaf}: {exc} - "
            "per-site CPU throttling will not be available"
        )


class PrivilegeDropper:
    """Thin, mockable boundary around the actual privilege-drop syscalls.

    Isolating exactly these calls behind one seam is what lets the
    surrounding dispatch logic - including asserting this exact call
    order - be unit tested via mocks, without ever invoking the real
    syscalls (which require real privilege and are not safe to exercise
    inside a pytest process).
    """

    def drop_and_exec(
        self, user: str, uid: int, gid: int, argv: list[str], env: dict[str, str]
    ) -> None:
        """Drops privileges to user/uid/gid and execs argv. Does not return on success.

        Call order is safety-critical and must not be reordered:
        1. initgroups(user, gid) FIRST - skipping this is the dangerous,
           silent failure mode: the process would keep this helper's own
           supplementary groups (membership in every site's group),
           defeating the entire point of the drop. initgroups looks up
           user's real supplementary groups (e.g. a shared "gliders" group
           several sites' runner accounts belong to) via the system's
           account database and sets exactly those, rather than a single
           setgroups([gid]) - that once looked equally safe here but
           silently dropped every one of the target account's own real
           supplementary groups, breaking access to any directory (like a
           glider's home tree) it needs group membership, not just its own
           uid/gid, to reach.
        2. setgid(gid) SECOND - must happen before setuid, since a
           non-root process cannot change its gid.
        3. setuid(uid) LAST - irreversible; only safe once group
           membership is already correct.

        Args:
            user: Target account name to become (a site's runner_user) -
                used only to resolve supplementary groups via initgroups.
            uid: Target uid to become (a site's runner_uid).
            gid: Target gid to become (a site's runner_gid).
            argv: Full argv, including argv[0] as the executable path.
            env: Environment to exec with.

        Returns:
            Never returns on success (the process image is replaced).

        Raises:
            OSError: If any of initgroups/setgid/setuid/execve fails.
        """
        os.initgroups(user, gid)
        os.setgid(gid)
        os.setuid(uid)
        os.execve(argv[0], argv, env)


class CgroupJoiner:
    """Thin, mockable boundary around joining a per-site delegated cgroup.

    Restores the per-site CPU isolation the one-process-per-site
    BaseRunner.py model got for free from each site being its own systemd
    unit/cgroup: once every site's jobs are forked from this single
    process, a unit-level CPUQuota would cap the combined total of every
    site together, not each site individually, letting one noisy site
    starve the rest. Joining each job into its own site-scoped cgroup
    before exec restores that isolation.

    Isolating exactly these filesystem operations behind one seam is what
    lets the surrounding dispatch logic be unit tested via a fake/mock,
    without requiring a real delegated cgroupfs (which needs root/
    Delegate=yes and isn't available inside a pytest sandbox).
    """

    def join(self, site: SiteConfig.SiteConfig, cgroup_root: pathlib.Path) -> None:
        """Creates (if needed) and joins this process into site's own cgroup.

        Must be called BEFORE PrivilegeDropper.drop_and_exec - cgroup
        membership is independent of uid, so this process can move itself
        into a delegated cgroup while still running as the unprivileged
        helper account, then drop to the site's runner_uid/runner_gid
        afterward and remain in the cgroup it already joined.

        Args:
            site: The site whose job this process will become, via a
                later drop_and_exec call.
            cgroup_root: Root of this helper's own delegated cgroup
                subtree (requires Delegate=yes on this process's own
                systemd unit).

        Returns:
            None.

        Raises:
            No exceptions are raised - all failures are logged and
            treated as non-fatal (fail-open: throttling must never be
            able to block a job from running at all), matching this
            codebase's existing philosophy for other non-critical
            per-site setup (see BaseRunnerMulti.py's _try_activate_site
            for the same pattern applied to a bad site's watch_dir).
        """
        site_cgroup = cgroup_root / f"site-{site.name}"
        try:
            site_cgroup.mkdir(parents=True, exist_ok=True)
            if site.cpu_quota_pct is not None or site.cpu_weight is not None:
                # cgroup v2 requires the "cpu" controller to be explicitly
                # enabled in the PARENT's cgroup.subtree_control before a
                # child cgroup's own cpu.max/cpu.weight become writable -
                # Delegate=yes only grants write access to make that
                # happen ourselves, it does not enable anything by
                # default. Idempotent: re-enabling an already-enabled
                # controller is a harmless no-op.
                (cgroup_root / "cgroup.subtree_control").write_text("+cpu\n")
            if site.cpu_quota_pct is not None:
                (site_cgroup / "cpu.max").write_text(
                    f"{site.cpu_quota_pct * 1000} 100000\n"
                )
            if site.cpu_weight is not None:
                (site_cgroup / "cpu.weight").write_text(f"{site.cpu_weight}\n")
            (site_cgroup / "cgroup.procs").write_text(f"{os.getpid()}\n")
        except OSError as exc:
            log_warning(
                f"[{site.name}] Could not join cgroup {site_cgroup}: {exc} "
                "- job will run unthrottled"
            )


class ChildTable:
    """Tracks pids this server has forked and reaps them as they exit."""

    def __init__(self, waitpid_fn=os.waitpid) -> None:
        """Initializes an empty table.

        Args:
            waitpid_fn: os.waitpid-compatible callable; overridable for
                testing.
        """
        self._running: set[int] = set()
        self._completed: dict[int, int] = {}
        self._waitpid = waitpid_fn

    def note_started(self, pid: int) -> None:
        """Records that pid was just forked and is expected to exit later.

        Args:
            pid: The child's pid.

        Returns:
            None.
        """
        self._running.add(pid)

    def reap_available(self) -> None:
        """Non-blocking reap of any tracked children that have already exited.

        Returns:
            None.

        Raises:
            No exceptions are raised.
        """
        while True:
            try:
                pid, status = self._waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
            self._running.discard(pid)
            self._completed[pid] = os.waitstatus_to_exitcode(status)

    def status(self, pid: int) -> tuple[bool, int | None]:
        """Returns (done, returncode) for a previously-started pid.

        Args:
            pid: The child's pid, as returned from a prior dispatch.

        Returns:
            (True, returncode) if the child has exited, (False, None) if
            it's still running.

        Raises:
            KeyError: If pid was never started via note_started.
        """
        self.reap_available()
        if pid in self._completed:
            return True, self._completed[pid]
        if pid in self._running:
            return False, None
        raise KeyError(pid)


@dataclasses.dataclass
class DispatchRequest:
    """A validated request to launch one job as a specific site's runner account."""

    site: SiteConfig.SiteConfig
    argv: list[str]
    log_file: pathlib.Path


def validate_dispatch_request(
    sites: dict[str, SiteConfig.SiteConfig], request: dict
) -> DispatchRequest:
    """Validates a raw dispatch request against the known site table.

    The request carries a site *name* only, never a uid/gid - this
    function is the boundary that turns an untrusted name into a trusted
    SiteConfig, by looking it up in `sites` (this helper's own table),
    never by trusting anything else in the request.

    Args:
        sites: This helper's own resolved site table.
        request: Raw request dict, expected keys "site", "argv", "log_file".

    Returns:
        The validated DispatchRequest.

    Raises:
        ValueError: If the request is malformed, names an unknown site, or
            log_file is not contained within that site's own directory
            tree.
    """
    site_name = request.get("site")
    if not isinstance(site_name, str) or site_name not in sites:
        raise ValueError(f"unknown site {site_name!r}")
    site = sites[site_name]

    argv = request.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("argv must be a non-empty list of strings")

    log_file_raw = request.get("log_file")
    if not isinstance(log_file_raw, str):
        raise ValueError("log_file must be a string")
    log_file = pathlib.Path(log_file_raw)

    roots = [root for root in (site.watch_dir, site.jail_root) if root is not None]
    if not roots or not any(SiteConfig.is_contained(log_file, root) for root in roots):
        raise ValueError(
            f"log_file {log_file} is not contained within site {site_name!r}'s tree"
        )

    return DispatchRequest(site=site, argv=argv, log_file=log_file)


class PrivExecServer:
    """Serves dispatch/status requests from BaseRunnerMulti over a UNIX socket."""

    def __init__(
        self,
        sites: dict[str, SiteConfig.SiteConfig],
        dropper: PrivilegeDropper,
        fork_fn=os.fork,
        joiner: CgroupJoiner | None = None,
        cgroup_root: pathlib.Path | None = None,
    ) -> None:
        """Initializes the server.

        Args:
            sites: This helper's own resolved site table (loaded once, at
                this process's own startup, from the same sites.yaml
                BaseRunnerMulti reads).
            dropper: The PrivilegeDropper used for the actual privilege
                drop in forked children.
            fork_fn: os.fork-compatible callable; overridable for testing
                so the parent-side dispatch logic can be exercised without
                a real fork.
            joiner: The CgroupJoiner used to throttle each dispatched job.
                Defaults to a real CgroupJoiner() if not given.
            cgroup_root: Root of this helper's own delegated cgroup
                subtree. Required for joiner.join() to do anything useful;
                a missing/unwritable root just means jobs run unthrottled
                (logged, not fatal - see CgroupJoiner.join).
        """
        self._sites = sites
        self._dropper = dropper
        self._fork = fork_fn
        self._joiner = joiner if joiner is not None else CgroupJoiner()
        self._cgroup_root = cgroup_root
        self._children = ChildTable()

    def handle_dispatch(self, request: dict) -> dict:
        """Validates, forks, and (in the child) execs a dispatch request.

        The log_file is opened here, in the parent, before forking - see
        the module-level note on this being a narrow, accepted deviation
        for newly-created log files (an already-existing log_file, the
        common case, keeps whatever ownership it already had regardless
        of which identity appends to it).

        Args:
            request: Raw request dict.

        Returns:
            {"ok": True, "pid": <pid>} on success, or
            {"ok": False, "error": <message>} on failure. Never raises -
            all failure modes are reported in the response.
        """
        try:
            req = validate_dispatch_request(self._sites, request)
        except ValueError as exc:
            log_error(f"Rejected dispatch request: {exc}")
            return {"ok": False, "error": str(exc)}

        try:
            log_fd = os.open(
                str(req.log_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640
            )
        except OSError as exc:
            log_error(f"Could not open {req.log_file} for site {req.site.name}: {exc}")
            return {"ok": False, "error": f"could not open log_file: {exc}"}

        try:
            pid = self._fork()
        except OSError as exc:
            os.close(log_fd)
            log_error(f"fork() failed for site {req.site.name}: {exc}")
            return {"ok": False, "error": f"fork failed: {exc}"}

        if pid == 0:
            self._run_child(req, log_fd)  # never returns

        os.close(log_fd)
        self._children.note_started(pid)
        log_info(f"Dispatched site={req.site.name} pid={pid} argv={req.argv}")
        return {"ok": True, "pid": pid}

    def _run_child(self, req: DispatchRequest, log_fd: int) -> None:
        """Runs only inside the forked child; always exits, never returns.

        Args:
            req: The validated dispatch request.
            log_fd: Open fd (inherited from the parent) to redirect
                stdout/stderr to.

        Returns:
            Never returns - always calls os._exit.
        """
        try:
            os.dup2(log_fd, 1)
            os.dup2(log_fd, 2)
            if log_fd not in (1, 2):
                os.close(log_fd)
            if self._cgroup_root is not None:
                # Must happen before drop_and_exec - cgroup membership is
                # independent of uid, so this still-unprivileged process
                # can join the cgroup now and remain in it after dropping.
                # Caught separately (belt-and-suspenders on top of
                # CgroupJoiner's own internal fail-open behavior): a
                # throttling failure must never prevent the job itself
                # from launching.
                try:
                    self._joiner.join(req.site, self._cgroup_root)
                except Exception:
                    log_warning(f"[{req.site.name}] cgroup join raised - continuing unthrottled")
            # Runner accounts are typically created with no real home
            # directory (same reason baserunnerprivexec.service itself
            # needs Environment=MPLCONFIGDIR - see that unit file), so
            # anything expecting $HOME to be writable (matplotlib's config
            # cache, in practice) falls back to a throwaway /tmp dir with a
            # startup warning. log_file's own parent - the job's mission
            # directory - is already guaranteed writable by this site's
            # runner account, since the job's own output has to land there
            # regardless; reusing it as $HOME needs no extra per-site setup
            # (no real home directory to create/maintain per runner account).
            env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(req.log_file.parent),
            }
            self._dropper.drop_and_exec(
                req.site.runner_user, req.site.runner_uid, req.site.runner_gid, req.argv, env
            )
        except Exception:
            os._exit(127)
        os._exit(126)  # pragma: no cover - unreachable if execve succeeds

    def handle_status(self, request: dict) -> dict:
        """Answers a {"query": "status", "pid": <pid>} request.

        Args:
            request: Raw request dict.

        Returns:
            {"ok": True, "done": bool, "returncode": int|None} on success,
            or {"ok": False, "error": <message>} if pid is malformed or
            unknown.
        """
        pid = request.get("pid")
        if not isinstance(pid, int):
            return {"ok": False, "error": "pid must be an int"}
        try:
            done, returncode = self._children.status(pid)
        except KeyError:
            return {"ok": False, "error": f"unknown pid {pid}"}
        return {"ok": True, "done": done, "returncode": returncode}

    def handle_request(self, request: dict) -> dict:
        """Routes a raw request to the dispatch or status handler.

        Args:
            request: Raw request dict.

        Returns:
            The handler's response dict.
        """
        if request.get("query") == "status":
            return self.handle_status(request)
        return self.handle_dispatch(request)

    def handle_connection(self, conn: socket.socket) -> None:
        """Serves exactly one request/response pair over an accepted connection.

        Args:
            conn: The accepted connection socket.

        Returns:
            None.
        """
        peer_uid = _peer_uid(conn)
        if peer_uid is not None and peer_uid != os.getuid():
            log_error(f"Rejecting connection from unexpected uid {peer_uid}")
            return

        data = _recv_frame(conn)
        if data is None:
            return
        try:
            request = orjson.loads(data)
        except orjson.JSONDecodeError:
            _send_frame(conn, orjson.dumps({"ok": False, "error": "invalid JSON"}))
            return
        if not isinstance(request, dict):
            _send_frame(
                conn, orjson.dumps({"ok": False, "error": "request must be an object"})
            )
            return
        _send_frame(conn, orjson.dumps(self.handle_request(request)))

    def serve_forever(self, sock: socket.socket, stop_event: threading.Event) -> None:
        """Accepts and serves connections until stop_event is set.

        Uses a 1s accept timeout (rather than SIGCHLD) so children are
        reaped promptly without needing signal-safe code; a status query
        also reaps synchronously first, so this timeout only bounds how
        quickly a completed-but-not-yet-queried job's zombie is cleared.

        Args:
            sock: A bound, listening socket.
            stop_event: Set by the caller's signal handler to request shutdown.

        Returns:
            None.
        """
        sock.settimeout(1.0)
        while not stop_event.is_set():
            try:
                conn, _addr = sock.accept()
            except TimeoutError:
                self._children.reap_available()
                continue
            with conn:
                self.handle_connection(conn)


def main() -> int:
    """Entry point: loads config, binds the socket, and serves forever.

    Returns:
        0 on clean shutdown, 1 if sites.yaml failed to load.

    Raises:
        No exceptions are expected to propagate out of this function.
    """
    base_opts = BaseOpts.BaseOptions(
        "Privileged exec helper for BaseRunnerMulti",
        additional_arguments={
            "sites_config": BaseOptsType.options_t(
                None,
                {"BaseRunnerPrivExec"},
                ("--sites_config",),
                pathlib.Path,
                {
                    "help": "Path to sites.yaml",
                    "action": BaseOpts.FullPathlibAction,
                    "required": {"BaseRunnerPrivExec"},
                },
            ),
            "priv_exec_socket": BaseOptsType.options_t(
                "/run/baserunner/priv_exec.sock",
                {"BaseRunnerPrivExec"},
                ("--priv_exec_socket",),
                str,
                {"help": "UNIX socket path to listen on"},
            ),
            "cgroup_root": BaseOptsType.options_t(
                "/sys/fs/cgroup/system.slice/baserunnerprivexec.service",
                {"BaseRunnerPrivExec"},
                ("--cgroup_root",),
                str,
                {
                    "help": "Root of this process's own delegated cgroup "
                    "subtree (requires Delegate=yes on its systemd unit) - "
                    "each dispatched job is joined into a site-scoped "
                    "child cgroup under this root for per-site CPU "
                    "throttling"
                },
            ),
        },
    )
    BaseLogger(base_opts, include_time=True)

    sites = SiteConfig.load_sites_config(base_opts.sites_config)
    if sites is None:
        log_error("Failed to load sites config - exiting")
        return 1

    # Matches glider_login's own "umask 2" and BaseRunnerMulti.py/
    # BaseRunner.py's identical call: every dispatched job is a fork of
    # this process, so its umask is what actually reaches the files a job
    # creates (drop_and_exec's execve does not reset it) - without this,
    # jobs inherit systemd's default 0022 and their output loses the
    # group-write bit the rest of basestation assumes is there.
    os.umask(0o002)

    _set_child_subreaper()
    _move_self_into_leaf_cgroup(pathlib.Path(base_opts.cgroup_root))

    socket_path = pathlib.Path(base_opts.priv_exec_socket)
    if socket_path.exists():
        socket_path.unlink()
    socket_path.parent.mkdir(parents=True, exist_ok=True)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(socket_path))
    socket_path.chmod(0o600)
    sock.listen(5)

    # Only now - socket bound and listening - are we actually able to
    # serve a dispatch request. With the unit's Type=notify, this is what
    # makes BaseRunnerMulti.service's Requires=/After= on this unit an
    # actual readiness guarantee instead of just "the process was
    # forked": systemd won't start the watcher's unit until this fires.
    sdnotify.SystemdNotifier().notify("READY=1")

    stop_event = threading.Event()

    def _handle_signal(signo: int, _frame: object) -> None:
        log_info(f"Received signal {signo}, shutting down")
        stop_event.set()

    for sig in ("TERM", "INT"):
        signal.signal(getattr(signal, "SIG" + sig), _handle_signal)

    server = PrivExecServer(
        sites,
        PrivilegeDropper(),
        joiner=CgroupJoiner(),
        cgroup_root=pathlib.Path(base_opts.cgroup_root),
    )
    try:
        server.serve_forever(sock, stop_event)
    finally:
        sock.close()
        if socket_path.exists():
            socket_path.unlink()

    return 0


if __name__ == "__main__":
    sys.exit(main())
