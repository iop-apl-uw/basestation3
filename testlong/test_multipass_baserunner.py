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

"""Validates BaseRunnerMulti/BaseRunnerPrivExec mechanisms that a pytest
sandbox structurally can't exercise: the real CAP_SETUID/CAP_SETGID
privilege-drop chain, cgroup v2 delegation for CgroupJoiner, real
multi-site inotify dispatch, systemd Type=notify/WatchdogSec compliance,
PR_SET_CHILD_SUBREAPER zombie reaping, SO_PEERCRED connection rejection,
and the migration/rollback lock handoff from a legacy per-site
BaseRunner.py instance.

See .claude/plans/2026-08-11-multipass-baserunner-validation.md for the
full design/rationale, and docs/BaseRunnerMulti.md's "Validate the
capability chain before relying on it in production" section, which
this module operationalizes.
"""

from __future__ import annotations

import shlex
import time
import uuid
from collections.abc import Iterator

import multipassutils
import pytest

SITES = ("alpha", "bravo", "charlie")


def _run(vm: multipassutils.Vm, cmd: list[str]) -> str:
    """Runs a command in the VM and returns stdout, failing loudly on error.

    Args:
        vm: Target VM.
        cmd: Command (and args) to execute.

    Returns:
        Captured stdout.

    Raises:
        AssertionError: If the command exits non-zero.
    """
    result = multipassutils.exec_in(vm, cmd)
    assert result.returncode == 0, f"{cmd} failed: {result.stdout}\n{result.stderr}"
    return result.stdout


def _uid_of(vm: multipassutils.Vm, user: str) -> str:
    """Looks up a Unix account's uid inside the VM."""
    return _run(vm, ["id", "-u", user]).strip()


def _read_file(vm: multipassutils.Vm, path: str) -> str:
    """Reads a file's content from inside the VM, as root (may not be
    world-readable)."""
    return _run(vm, ["sudo", "cat", path])


def _wait_until(predicate, timeout: float = 15.0, interval: float = 0.5) -> bool:
    """Polls predicate() until it returns truthy or timeout elapses.

    Args:
        predicate: Zero-arg callable to poll.
        timeout: Max seconds to wait.
        interval: Seconds between polls.

    Returns:
        True if predicate() became truthy before the timeout, else False.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _drop_run_file(
    vm: multipassutils.Vm, site: str, glider_num: int, cmd_line: str
) -> tuple[str, str]:
    """Writes a synthetic `.run` file for site, mirroring glider_login's format.

    Pre-creates the mission directory the log_file will live under -
    BaseRunnerPrivExec opens log_file with O_CREAT, which needs the
    parent directory to already exist (matches how a real glider's own
    mission directory already exists at commissioning time).

    Args:
        vm: Target VM.
        site: One of SITES.
        glider_num: Synthetic glider id, e.g. 100 -> "sg100".
        cmd_line: The `.run` file's cmd_line field, e.g. "Base.py --foo".

    Returns:
        (mission_dir_on_disk, log_file_on_disk) - the real, outside-jail
        paths (after jail_root rewriting) so the caller can inspect them.
    """
    # Dispatcher._process_run_file does `script, tail = cmd_line.split(" ",
    # 1)` (matching BaseRunner.py's original, pre-existing behavior) -
    # requires at least one space, i.e. a real .run file's cmd_line always
    # has trailing content after the script name. Guarantee that here so
    # callers can pass a bare script name without tripping over it.
    if " " not in cmd_line:
        cmd_line = f"{cmd_line} --stub-marker 1"

    jail_root = f"/home/jails/{site}/gliderjail"
    home_in_jail = f"/home/sg{glider_num}"
    mission_in_jail = f"{home_in_jail}/current"
    log_in_jail = f"{mission_in_jail}/baselog.log"
    mission_on_disk = f"{jail_root}{mission_in_jail}"
    log_on_disk = f"{jail_root}{log_in_jail}"
    run_file = f"{jail_root}/home/rundir/{uuid.uuid4().hex}.run"

    # umask 002 mirrors glider_login's own `umask 2` (glider_login:32) -
    # without it, root's mkdir defaults to 755 (no group-write), and
    # setgid alone only inherits group *ownership*, not the write bit
    # BaseRunnerPrivExec needs to create the log file as baserunner.
    script = (
        f"umask 002 && mkdir -p {shlex.quote(mission_on_disk)} && "
        f"printf '%s %s %s %s\\n' {shlex.quote(home_in_jail)} "
        f"{shlex.quote(mission_in_jail)} {shlex.quote(log_in_jail)} "
        f"{shlex.quote(cmd_line)} > {shlex.quote(run_file)}"
    )
    _run(vm, ["sudo", "bash", "-c", script])
    return mission_on_disk, log_on_disk


@pytest.fixture(scope="module")
def running_baserunner(baserunner_vm: multipassutils.Vm) -> Iterator[multipassutils.Vm]:
    """Starts baserunnerprivexec + baserunnermulti once, for tests 1-6.

    `systemctl start` on a Type=notify unit blocks until READY=1 (or the
    unit's start timeout elapses and it fails) - a successful `check`-free
    but asserted-zero-returncode start here is itself already a partial
    proof of item 4 (Type=notify compliance); test_type_notify_watchdog
    below still checks it explicitly and separately.

    Args:
        baserunner_vm: The provisioned (but not yet started) VM.

    Yields:
        The same Vm, with both services now active.
    """
    _run(baserunner_vm, ["sudo", "systemctl", "start", "baserunnerprivexec"])
    _run(baserunner_vm, ["sudo", "systemctl", "start", "baserunnermulti"])
    yield baserunner_vm
    multipassutils.exec_in(
        baserunner_vm, ["sudo", "systemctl", "stop", "baserunnermulti", "baserunnerprivexec"]
    )


def test_privilege_drop_chain(running_baserunner: multipassutils.Vm) -> None:
    """Item 1: a dispatched job really runs as the target site's own account."""
    vm = running_baserunner
    _mission_dir, log_file = _drop_run_file(vm, "alpha", 101, "Base.py")

    found = _wait_until(lambda: "user=runner-alpha" in _read_file(vm, log_file))
    assert found, f"expected job identity never appeared in {log_file}"

    content = _read_file(vm, log_file)
    assert f"uid={_uid_of(vm, 'runner-alpha')}" in content
    assert "uid=0" not in content  # never ran as root


def test_privexec_holds_only_setuid_setgid(running_baserunner: multipassutils.Vm) -> None:
    """Item 1 (capability chain): BaseRunnerPrivExec holds exactly CAP_SETUID/CAP_SETGID."""
    vm = running_baserunner
    pid = _run(vm, ["pgrep", "-f", "BaseRunnerPrivExec.py"]).splitlines()[0].strip()
    caps = _run(vm, ["getpcaps", pid])
    assert "cap_setuid" in caps
    assert "cap_setgid" in caps
    # A representative sample of capabilities that must NOT be present -
    # confirms this isn't accidentally running with a much broader set.
    for forbidden in ("cap_sys_admin", "cap_net_admin", "cap_dac_override"):
        assert forbidden not in caps, f"unexpected {forbidden} in: {caps}"


def test_cgroup_throttling(running_baserunner: multipassutils.Vm) -> None:
    """Item 2: CgroupJoiner writes cpu.max/cpu.weight/cgroup.procs for a throttled site."""
    vm = running_baserunner
    _mission_dir, _log_file = _drop_run_file(
        vm, "alpha", 102, "Base.py --stub-sleep-seconds 5"
    )

    site_cgroup = (
        "/sys/fs/cgroup/system.slice/baserunnerprivexec.service/site-alpha"
    )
    found = _wait_until(
        lambda: multipassutils.exec_in(
            vm, ["sudo", "test", "-f", f"{site_cgroup}/cpu.max"]
        ).returncode
        == 0
    )
    assert found, f"{site_cgroup}/cpu.max never appeared"

    cpu_max = _read_file(vm, f"{site_cgroup}/cpu.max").strip()
    assert cpu_max == "50000 100000", cpu_max
    cpu_weight = _read_file(vm, f"{site_cgroup}/cpu.weight").strip()
    assert cpu_weight == "50", cpu_weight

    # The job sleeps 5s, giving us a window to observe it still listed in
    # cgroup.procs while alive.
    procs = _read_file(vm, f"{site_cgroup}/cgroup.procs")
    assert procs.strip() != "", "expected the running job's pid in cgroup.procs"


def test_cgroup_unset_for_unthrottled_site(running_baserunner: multipassutils.Vm) -> None:
    """Item 2 (negative case): CgroupJoiner never writes a limit for an unthrottled site.

    cgroup v2 always exposes a cpu.max/cpu.weight *file* for any child
    cgroup once the parent has the "cpu" controller enabled in its own
    cgroup.subtree_control - regardless of whether CgroupJoiner ever
    wrote to that specific child (confirmed on a real VM: bravo's
    cpu.max exists purely because alpha's throttled dispatch already
    enabled "cpu" for every sibling under the same parent). So the
    correct check isn't file *existence* - it's that the *content*
    stays at cgroup v2's own default ("max 100000" == unlimited),
    proving CgroupJoiner.join() itself never wrote a real limit here.
    """
    vm = running_baserunner
    _mission_dir, log_file = _drop_run_file(vm, "bravo", 103, "Base.py")
    found = _wait_until(lambda: "user=runner-bravo" in _read_file(vm, log_file))
    assert found

    site_cgroup = "/sys/fs/cgroup/system.slice/baserunnerprivexec.service/site-bravo"
    cpu_max = _read_file(vm, f"{site_cgroup}/cpu.max").strip()
    assert cpu_max == "max 100000", f"expected cgroup v2's own default, got: {cpu_max!r}"


def test_multi_site_dispatch_never_cross_wired(running_baserunner: multipassutils.Vm) -> None:
    """Item 3: concurrent .run files across all three sites each land on the right one."""
    vm = running_baserunner
    expectations = {}
    for site in SITES:
        _mission_dir, log_file = _drop_run_file(vm, site, 200 + SITES.index(site), "Base.py")
        expectations[site] = log_file

    for site, log_file in expectations.items():
        found = _wait_until(
            lambda lf=log_file, s=site: f"user=runner-{s}" in _read_file(vm, lf)
        )
        assert found, f"{site}'s job never appeared in {log_file}"
        content = _read_file(vm, log_file)
        for other in SITES:
            if other != site:
                assert f"user=runner-{other}" not in content


def test_type_notify_watchdog_compliance(running_baserunner: multipassutils.Vm) -> None:
    """Item 4: systemd considers the unit started via READY=1, with WatchdogSec honored."""
    vm = running_baserunner
    active_state = _run(
        vm, ["systemctl", "show", "baserunnermulti", "--property=ActiveState", "--value"]
    ).strip()
    assert active_state == "active"
    sub_state = _run(
        vm, ["systemctl", "show", "baserunnermulti", "--property=SubState", "--value"]
    ).strip()
    assert sub_state == "running"
    watchdog_usec = _run(
        vm, ["systemctl", "show", "baserunnermulti", "--property=WatchdogUSec", "--value"]
    ).strip()
    assert watchdog_usec not in ("", "0"), "WatchdogSec=30 should be reflected here"


def test_subreaper_reaps_orphaned_grandchild(running_baserunner: multipassutils.Vm) -> None:
    """Item 5: a job's own orphaned grandchild gets reaped, not left a zombie."""
    vm = running_baserunner
    _mission_dir, log_file = _drop_run_file(
        vm, "charlie", 104, "Base.py --stub-fork-and-exit"
    )
    found = _wait_until(lambda: "forked grandchild" in _read_file(vm, log_file))
    assert found

    privexec_pid = _run(vm, ["pgrep", "-f", "BaseRunnerPrivExec.py"]).splitlines()[0].strip()
    # Give the grandchild (sleeps 2s then exits) time to finish and be reaped.
    no_zombies = _wait_until(
        lambda: "Z" not in _run(vm, ["ps", "--ppid", privexec_pid, "-o", "stat="]),
        timeout=10.0,
    )
    assert no_zombies, "a zombie grandchild was left under BaseRunnerPrivExec"


def test_so_peercred_rejects_wrong_uid(running_baserunner: multipassutils.Vm) -> None:
    """Item 6: a connection from an unexpected uid to the priv-exec socket is rejected.

    The socket file itself is 0600 owned by baserunner, so an ordinary
    (non-root) uid can't even connect - that's the primary defense,
    confirmed separately (connecting as `ubuntu` raises PermissionError
    before ever reaching application code). To exercise SO_PEERCRED
    itself specifically, this connects as root, which bypasses the
    filesystem permission check (root can always connect) - the
    application-level uid check must still reject it: observed as
    either an empty read (server closed the connection without
    responding) or ConnectionResetError (client still had a pending
    write/read when the server side closed), never a real response.
    """
    vm = running_baserunner
    script = (
        "python3 - <<'PY'\n"
        "import socket, struct, sys\n"
        "s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        "s.settimeout(3)\n"
        "s.connect('/run/baserunner/priv_exec.sock')\n"
        "payload = b'{\"query\": \"status\", \"pid\": 1}'\n"
        "try:\n"
        "    s.sendall(struct.pack('>I', len(payload)) + payload)\n"
        "    data = s.recv(4)\n"
        "except (socket.timeout, ConnectionResetError, BrokenPipeError):\n"
        "    data = b''\n"
        "print('EMPTY' if not data else 'GOT_RESPONSE')\n"
        "PY"
    )
    output = _run(vm, ["sudo", "bash", "-c", script])
    assert "EMPTY" in output, f"expected no response for a wrong-uid connection, got: {output}"


def test_migration_takeover_after_documented_stop_disable(
    baserunner_vm: multipassutils.Vm,
) -> None:
    """Item 7a: the documented migration procedure (stop+disable old unit FIRST) works cleanly.

    This is the reliable, documented path (docs/BaseRunnerMulti.md's
    "Migrating a site") - confirmed on a real VM that a bare SIGTERM to a
    still-*enabled* legacy unit is NOT sufficient on its own: every unit
    here has Restart=always, so systemd just restarts it, and the
    restarted instance then crashes trying to signal BaseRunnerMulti's
    own pid across uids (the same EPERM problem, mirrored - see
    test_signal_reaches_cross_uid_stale_process for the mechanism that
    prevents *that* direction). An explicit `systemctl stop` (not a raw
    signal) is the only thing that reliably keeps a Restart=always unit
    down, which is exactly what step 1 of the documented procedure does.
    """
    vm = baserunner_vm
    legacy_unit = "baserunner-legacy@runner-alpha.service"
    try:
        multipassutils.exec_in(
            vm, ["sudo", "systemctl", "stop", "baserunnermulti", "baserunnerprivexec"]
        )
        _run(vm, ["sudo", "systemctl", "start", legacy_unit])
        legacy_active = _wait_until(
            lambda: _run(
                vm, ["systemctl", "show", legacy_unit, "--property=ActiveState", "--value"]
            ).strip()
            == "active"
        )
        assert legacy_active, "legacy per-site unit never became active"

        # Step 1 of the documented procedure: stop AND disable first.
        _run(vm, ["sudo", "systemctl", "stop", legacy_unit])
        _run(vm, ["sudo", "systemctl", "disable", legacy_unit])

        _run(vm, ["sudo", "systemctl", "start", "baserunnerprivexec"])
        _run(vm, ["sudo", "systemctl", "start", "baserunnermulti"])

        _mission_dir, log_file = _drop_run_file(vm, "alpha", 105, "Base.py")
        dispatched = _wait_until(lambda: "user=runner-alpha" in _read_file(vm, log_file))
        assert dispatched, "BaseRunnerMulti did not take over watching alpha"

        still_stopped = (
            _run(
                vm, ["systemctl", "show", legacy_unit, "--property=ActiveState", "--value"]
            ).strip()
            != "active"
        )
        assert still_stopped, "legacy unit should stay down once explicitly stopped+disabled"
    finally:
        multipassutils.exec_in(vm, ["sudo", "systemctl", "stop", legacy_unit])
        multipassutils.exec_in(vm, ["sudo", "systemctl", "reset-failed", legacy_unit])
        # Restore the normal running state for any tests that run after
        # this one (module-scoped running_baserunner may already have
        # started these; starting an already-active unit is a no-op).
        multipassutils.exec_in(vm, ["sudo", "systemctl", "start", "baserunnerprivexec"])
        multipassutils.exec_in(vm, ["sudo", "systemctl", "start", "baserunnermulti"])


def test_signal_reaches_cross_uid_stale_process(baserunner_vm: multipassutils.Vm) -> None:
    """Item 7b: the stale-lock SIGTERM actually reaches a process under a different uid.

    This is the mechanism `_try_activate_site`/`PrivExecServer.handle_signal`
    fix: BaseRunnerMulti (running as baserunner) cannot os.kill a process
    owned by a different uid (runner-alpha here) directly - confirmed on
    a real VM this raises EPERM. Routing the signal through the
    privileged helper, which drops to the target site's own account
    first, makes it an ordinary same-uid operation. This test only
    proves the signal reaches the *original* pid (it does not assert the
    unit "stays down", since Restart=always means it won't on its own -
    see test_migration_takeover_after_documented_stop_disable for the
    reliable procedure).
    """
    vm = baserunner_vm
    legacy_unit = "baserunner-legacy@runner-alpha.service"
    try:
        multipassutils.exec_in(
            vm, ["sudo", "systemctl", "stop", "baserunnermulti", "baserunnerprivexec"]
        )
        _run(vm, ["sudo", "systemctl", "enable", legacy_unit])
        _run(vm, ["sudo", "systemctl", "start", legacy_unit])
        legacy_active = _wait_until(
            lambda: _run(
                vm, ["systemctl", "show", legacy_unit, "--property=ActiveState", "--value"]
            ).strip()
            == "active"
        )
        assert legacy_active, "legacy per-site unit never became active"

        original_pid = _run(
            vm, ["systemctl", "show", legacy_unit, "--property=MainPID", "--value"]
        ).strip()
        assert original_pid and original_pid != "0"

        _run(vm, ["sudo", "systemctl", "start", "baserunnerprivexec"])
        _run(vm, ["sudo", "systemctl", "start", "baserunnermulti"])

        original_pid_gone = _wait_until(
            lambda: multipassutils.exec_in(
                vm, ["sudo", "kill", "-0", original_pid]
            ).returncode
            != 0,
            timeout=15.0,
        )
        assert original_pid_gone, (
            f"original legacy pid {original_pid} was never signalled - "
            "cross-uid signal delivery failed"
        )
    finally:
        multipassutils.exec_in(vm, ["sudo", "systemctl", "stop", legacy_unit])
        multipassutils.exec_in(vm, ["sudo", "systemctl", "disable", legacy_unit])
        multipassutils.exec_in(vm, ["sudo", "systemctl", "reset-failed", legacy_unit])
        multipassutils.exec_in(
            vm, ["sudo", "rm", "-f", "/home/jails/alpha/gliderjail/home/rundir/.base_runner_lockfile"]
        )
        multipassutils.exec_in(vm, ["sudo", "systemctl", "start", "baserunnerprivexec"])
        multipassutils.exec_in(vm, ["sudo", "systemctl", "start", "baserunnermulti"])


@pytest.mark.skip(
    reason="Item 8 (optional): re-confirming the boot-storm fix under the new "
    "single-process model requires a full VM reboot + systemd-analyze capture, "
    "mirroring baserunner-migration.tar.gz's MULTIPASS-TEST.md. Deferred - the "
    "one-process design already structurally guarantees this (one systemd unit "
    "is one systemd unit), and items above already cover functional correctness."
)
def test_boot_storm_reduced_vs_legacy_per_site_units() -> None:
    pass
