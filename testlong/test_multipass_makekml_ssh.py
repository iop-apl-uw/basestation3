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


"""Validates ssh/MakeKMLSSHMissions.py's per-site runner identity switch for
real, on the testlong multipass VM - which a pytest sandbox can't do: the
real makekml-ssh-worker.service (baserunner + ambient CAP_SETUID/CAP_SETGID
+ PrivateTmp), real per-site runner accounts and groups, and real
ownership/credentials of the files each site's child and its MakeKML.py
grandchild write.

Reuses conftest.py's session-wide baserunner_vm (sites alpha/bravo/charlie,
runner-<site> accounts, baserunner in every site group - which is exactly
what makes the "no supplementary group leakage" check below meaningful).
ssh/MakeKMLSSH.py and MakeKML.py are swapped for stubs
(testlong/fixtures/stubs/) that record the calling process's identity,
since the real ones need Copernicus data; everything else is real.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterator
from pathlib import Path

import multipassutils
import pytest

SITES = ("alpha", "bravo", "charlie")
GLIDERS = {"alpha": 701, "bravo": 702, "charlie": 703}
COMPLETE_GLIDER = 711  # an alpha mission with status: complete
STRAY_GLIDER = 799  # active, but under no site's tree

BASESTATION_DIR = "/usr/local/basestation3"
PYTHON = f"{BASESTATION_DIR}/.venv/bin/python"
SCRIPT = f"{BASESTATION_DIR}/ssh/MakeKMLSSHMissions.py"
SITES_YAML = f"{BASESTATION_DIR}/etc/sites.yaml"
TEST_ROOT = "/srv/makekml-test"
MASTER_YML = f"{TEST_ROOT}/missions.yml"
STRAY_DIR = f"{TEST_ROOT}/stray/sg{STRAY_GLIDER:03d}"
DATA_DIR = "/home/ssh/data"
UNIT = "makekml-ssh-worker.service"
STUBBED = (f"{BASESTATION_DIR}/ssh/MakeKMLSSH.py", f"{BASESTATION_DIR}/MakeKML.py")


def _run(vm: multipassutils.Vm, cmd: list[str]) -> str:
    """Runs a command in the VM and returns stdout, failing loudly on error."""
    result = multipassutils.exec_in(vm, cmd)
    assert result.returncode == 0, f"{cmd} failed: {result.stdout}\n{result.stderr}"
    return result.stdout


def _sudo_bash(vm: multipassutils.Vm, script: str) -> str:
    """Runs a bash script as root in the VM, failing loudly on error."""
    return _run(vm, ["sudo", "bash", "-euo", "pipefail", "-c", script])


def _jail_home(site: str) -> str:
    return f"/home/jails/{site}/gliderjail/home"


def _mission_dir(site: str, glider: int) -> str:
    return f"{_jail_home(site)}/sg{glider:03d}"


def _worker_unit(repo_root: Path) -> str:
    """The repo's real makekml-ssh-worker.service, with only ExecStart's paths
    swapped for this VM's (its own venv python, sites.yaml, test master file)."""
    unit = (repo_root / "ssh" / UNIT).read_text()
    exec_start = (
        f"ExecStart={PYTHON} {SCRIPT} --verbose --sites_config {SITES_YAML} "
        f"{DATA_DIR} {MASTER_YML}\n"
    )
    new_unit, count = re.subn(r"^ExecStart=(?:.*\\\n)*.*\n", exec_start, unit, flags=re.M)
    assert count == 1, "expected exactly one ExecStart in the worker unit"
    return new_unit


def _setup_script(worker_unit: str) -> str:
    """Root bash script: stubs, SSH data, mission trees, master file, unit."""
    lines = [
        # Swap in the identity-recording stubs, keeping the originals
        *(
            f"cp -p {path} {path}.orig && install -m 644 /home/ubuntu/fixtures/stubs/"
            f"{Path(path).name} {path}"
            for path in STUBBED
        ),
        # Shared SSH data, fresh enough to process, owned by baserunner
        f"install -d -o baserunner -g baserunner -m 755 {DATA_DIR}",
        f"install -o baserunner -g baserunner -m 644 /dev/null {DATA_DIR}/ssh.nc",
        # Stray mission: active, but under no site's tree
        f"install -d -m 755 {STRAY_DIR}",
        f"touch {STRAY_DIR}/sg_plot_constants.m",
    ]
    for site, glider in GLIDERS.items():
        home = _jail_home(site)
        gliders = [glider] + ([COMPLETE_GLIDER] if site == "alpha" else [])
        for gid in gliders:
            lines.append(
                f"install -d -o runner-{site} -g {site} -m 2770 {_mission_dir(site, gid)}"
            )
            lines.append(
                f"install -o runner-{site} -g {site} -m 660 /dev/null "
                f"{_mission_dir(site, gid)}/sg_plot_constants.m"
            )
        site_yml = f"missions:\n  - {{glider: {glider}}}\n"
        if site == "alpha":
            site_yml += f"  - {{glider: {COMPLETE_GLIDER}, status: complete}}\n"
        lines.append(f"printf %s {shlex.quote(site_yml)} > {home}/missions.yml")
        lines.append(f"chown runner-{site}:{site} {home}/missions.yml")

    master = f"missions:\n  - {{glider: {STRAY_GLIDER}, path: {STRAY_DIR}}}\ndomains:\n"
    for site in SITES:
        master += (
            f"  {site}: {{missions: {_jail_home(site)}/missions.yml, "
            f"root: {_jail_home(site)}}}\n"
        )
    lines += [
        f"printf %s {shlex.quote(master)} > {MASTER_YML}",
        f"chmod 644 {MASTER_YML}",
        f"printf %s {shlex.quote(worker_unit)} > /etc/systemd/system/{UNIT}",
        "systemctl daemon-reload",
    ]
    return "\n".join(lines)


def _teardown_script() -> str:
    """Root bash script undoing _setup_script (best effort)."""
    mission_dirs = " ".join(
        [_mission_dir(site, glider) for site, glider in GLIDERS.items()]
        + [_mission_dir("alpha", COMPLETE_GLIDER)]
    )
    missions_ymls = " ".join(f"{_jail_home(site)}/missions.yml" for site in SITES)
    return "\n".join(
        [
            *(f"[ -e {path}.orig ] && mv -f {path}.orig {path}" for path in STUBBED),
            f"rm -rf {mission_dirs} {missions_ymls} {TEST_ROOT} {DATA_DIR}",
            f"rm -rf /etc/systemd/system/{UNIT} /etc/systemd/system/{UNIT}.d",
            "systemctl daemon-reload",
        ]
    )


@pytest.fixture(scope="module")
def makekml_vm(baserunner_vm: multipassutils.Vm, repo_root: Path) -> Iterator[multipassutils.Vm]:
    """Installs the stubs, mission trees, master missions.yml and real worker unit.

    Args:
        baserunner_vm: The provisioned VM (baserunnermulti is not needed and
            is not started here).
        repo_root: This checkout, for the real worker unit file.

    Yields:
        The same Vm, set up for the tests below; restored afterwards.
    """
    _sudo_bash(baserunner_vm, _setup_script(_worker_unit(repo_root)))
    try:
        yield baserunner_vm
    finally:
        multipassutils.exec_in(
            baserunner_vm, ["sudo", "bash", "-c", _teardown_script()]
        )


def _clear_outputs(vm: multipassutils.Vm) -> None:
    """Removes everything a previous run wrote into the mission directories."""
    dirs = [_mission_dir(site, glider) for site, glider in GLIDERS.items()]
    dirs += [_mission_dir("alpha", COMPLETE_GLIDER), STRAY_DIR]
    _sudo_bash(
        vm,
        "\n".join(
            f"rm -f {d}/*_ssh.kmz {d}/makekml_stub.json {d}/makekml_[0-9]* {d}/.conversion_lock"
            for d in dirs
        ),
    )


def _start_worker(vm: multipassutils.Vm) -> str:
    """Runs the worker unit to completion; returns its journal for this run.

    `systemctl start` on a Type=oneshot unit blocks until the process exits,
    and fails if it exited non-zero.
    """
    since = _run(vm, ["date", "+%s"]).strip()
    result = multipassutils.exec_in(vm, ["sudo", "systemctl", "start", UNIT])
    journal = _run(
        vm, ["sudo", "journalctl", "-u", UNIT, "--since", f"@{since}", "--no-pager", "-o", "cat"]
    )
    assert result.returncode == 0, f"{UNIT} failed:\n{result.stderr}\n{journal}"
    return journal


def _identity_file(vm: multipassutils.Vm, path: str) -> dict:
    """Reads one of the stubs' identity JSON files (as root)."""
    return json.loads(_run(vm, ["sudo", "cat", path]))


def _ids(vm: multipassutils.Vm, site: str) -> tuple[int, int]:
    """runner-<site>'s uid, and site's gid."""
    uid = int(_run(vm, ["id", "-u", f"runner-{site}"]))
    gid = int(_run(vm, ["getent", "group", site]).split(":")[2])
    return uid, gid


def _assert_runner_identity(vm: multipassutils.Vm, site: str, identity: dict) -> None:
    """The process that wrote identity was exactly runner-<site>, nothing more."""
    uid, gid = _ids(vm, site)
    assert (identity["uid"], identity["euid"]) == (uid, uid), identity
    assert (identity["gid"], identity["egid"]) == (gid, gid), identity
    # Only the runner's own groups - none of baserunner's (it's in every
    # site's group on this VM), which a missed initgroups would leak.
    assert identity["groups"] == [gid], identity
    # No capability survives into the runner's processes: baserunner's
    # ambient CAP_SETUID/CAP_SETGID must not be inherited.
    for cap_set in ("CapPrm", "CapEff", "CapAmb", "CapInh"):
        assert identity[cap_set] == 0, f"{cap_set} not empty: {identity}"
    assert identity["home"] == f"/tmp/makekml-ssh-runner-{site}", identity


@pytest.fixture(scope="module")
def worker_run(makekml_vm: multipassutils.Vm) -> str:
    """One run of the real worker unit (--jobs 1), shared by the checks below."""
    _clear_outputs(makekml_vm)
    return _start_worker(makekml_vm)


@pytest.mark.parametrize("site", SITES)
def test_kmz_owned_by_site_runner(
    makekml_vm: multipassutils.Vm, worker_run: str, site: str
) -> None:
    kmz = f"{_mission_dir(site, GLIDERS[site])}/sg{GLIDERS[site]:03d}_ssh.kmz"

    owner = _run(makekml_vm, ["sudo", "stat", "-c", "%U:%G", kmz]).strip()

    assert owner == f"runner-{site}:{site}"
    _assert_runner_identity(makekml_vm, site, _identity_file(makekml_vm, kmz))


@pytest.mark.parametrize("site", SITES)
def test_makekml_subprocess_runs_as_site_runner(
    makekml_vm: multipassutils.Vm, worker_run: str, site: str
) -> None:
    stub_out = f"{_mission_dir(site, GLIDERS[site])}/makekml_stub.json"

    owner = _run(makekml_vm, ["sudo", "stat", "-c", "%U:%G", stub_out]).strip()

    assert owner == f"runner-{site}:{site}"
    _assert_runner_identity(makekml_vm, site, _identity_file(makekml_vm, stub_out))


def test_worker_processes_each_site_and_skips_the_rest(
    makekml_vm: multipassutils.Vm, worker_run: str
) -> None:
    for site in SITES:
        assert f"{site}: processing 1 mission(s) as runner-{site}" in worker_run
        assert f"{site}: done" in worker_run
    assert f"sg{STRAY_GLIDER:03d} {STRAY_DIR}: not under any site" in worker_run

    leftovers = _run(
        makekml_vm,
        [
            "sudo",
            "bash",
            "-c",
            f"ls {STRAY_DIR} {_mission_dir('alpha', COMPLETE_GLIDER)}",
        ],
    )
    assert "_ssh.kmz" not in leftovers
    assert "makekml_stub.json" not in leftovers


def test_parallel_jobs(makekml_vm: multipassutils.Vm) -> None:
    """--jobs 3 runs every site at once, with the same per-site identities."""
    dropin = f"/etc/systemd/system/{UNIT}.d"
    _sudo_bash(
        makekml_vm,
        f"mkdir -p {dropin}\n"
        f"printf '[Service]\\nExecStart=\\nExecStart={PYTHON} {SCRIPT} --verbose --jobs 3 "
        f"--sites_config {SITES_YAML} {DATA_DIR} {MASTER_YML}\\n' > {dropin}/jobs.conf\n"
        "systemctl daemon-reload",
    )
    try:
        _clear_outputs(makekml_vm)
        journal = _start_worker(makekml_vm)
    finally:
        _sudo_bash(makekml_vm, f"rm -rf {dropin}\nsystemctl daemon-reload")

    # All three children were started before any of them finished
    first_done = min(journal.index(f"{site}: done") for site in SITES)
    for site in SITES:
        assert journal.index(f"{site}: processing") < first_done
        kmz = f"{_mission_dir(site, GLIDERS[site])}/sg{GLIDERS[site]:03d}_ssh.kmz"
        _assert_runner_identity(makekml_vm, site, _identity_file(makekml_vm, kmz))


def test_without_capabilities_fails_loudly(makekml_vm: multipassutils.Vm) -> None:
    """baserunner without CAP_SETUID/CAP_SETGID: every site fails with a CRITICAL
    naming the missing capabilities, and nothing is written."""
    _clear_outputs(makekml_vm)

    result = multipassutils.exec_in(
        makekml_vm,
        [
            "sudo", "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
            "--uid=baserunner", "--gid=baserunner", "-p", "PrivateTmp=yes",
            PYTHON, SCRIPT, "--verbose", "--sites_config", SITES_YAML, DATA_DIR, MASTER_YML,
        ],
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    for site in SITES:
        assert re.search(rf"CRITICAL: .*{site}: unable to run as runner-{site}.*CAP_SETUID", output), output
    for site, glider in GLIDERS.items():
        listing = _run(makekml_vm, ["sudo", "ls", _mission_dir(site, glider)])
        assert "_ssh.kmz" not in listing
