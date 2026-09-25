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

"""Shared multipass subprocess helpers for the testlong/ suite.

Not a test module itself - plays the same role for testlong/ that
dockerutils.py plays for the Docker-based tests here (and that
tests/testutils.py plays for tests/): a plain, bare-imported helper
module, not a pytest plugin.

Mirrors dockerutils.py's shape - launch/exec_in/delete map to
docker_build|start_detached/exec_in/stop - swapping Docker's
container-id-keyed model for multipass's name-keyed one (multipass has
no separate "id" concept; every operation addresses the VM by the name
it was launched with).

Set TESTLONG_MULTIPASS_SSH_KEY to a copy of multipassd's private key (on
macOS: /var/root/Library/Application Support/multipassd/ssh-keys/id_rsa,
root-only - copy it once with sudo) to have exec_in/transfer use the
system ssh instead of `multipass exec`/`multipass transfer`. Recent macOS
releases silently deny the multipass client's own connection to the VM
under Local Network privacy ("ssh connection failed: No route to host"),
without ever listing it in System Settings to allow it, while Apple's own
ssh is exempt. Unset (the default), nothing changes.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Any

SSH_KEY_ENV = "TESTLONG_MULTIPASS_SSH_KEY"

# Never copied into the VM by the ssh transfer path: host-specific (a macOS
# .venv is useless in the VM, which uv syncs its own) and large.
TRANSFER_EXCLUDES = (".venv", ".git", "__pycache__", ".ruff_cache", ".pytest_cache")


@dataclass(frozen=True)
class Vm:
    """A launched multipass VM.

    Attributes:
        name: The instance name it was launched with - multipass keys
            every subsequent operation (exec/transfer/delete) off this.
    """

    name: str


def launch(
    name: str,
    image: str = "22.04",
    cpus: int = 2,
    memory: str = "2G",
    disk: str = "8G",
    ready_timeout: float = 30.0,
) -> Vm:
    """Launches a new multipass VM and waits for it to be ready.

    `multipass launch` returning doesn't guarantee the guest agent used by
    `multipass exec`/`transfer` is actually reachable yet - observed this
    firsthand: a `transfer` immediately after `launch` returned failed
    (exit 2), while the identical command retried a few seconds later
    succeeded immediately. So this polls a trivial `exec` after launch
    and only returns once it actually succeeds, rather than trusting
    `launch`'s own exit status as sufficient.

    Args:
        name: Instance name to launch as.
        image: Ubuntu release/alias to launch (e.g. "22.04").
        cpus: Number of vCPUs.
        memory: Memory size, as a multipass size string (e.g. "2G").
        disk: Disk size, as a multipass size string (e.g. "8G").
        ready_timeout: Max seconds to wait for the guest agent to answer
            after `launch` returns.

    Returns:
        The launched Vm.

    Raises:
        subprocess.CalledProcessError: If the launch fails.
        TimeoutError: If the guest agent never becomes reachable within
            ready_timeout.
    """
    subprocess.run(
        [
            "multipass",
            "launch",
            "--name",
            name,
            "--cpus",
            str(cpus),
            "--memory",
            memory,
            "--disk",
            disk,
            image,
        ],
        check=True,
    )
    vm = Vm(name=name)
    deadline = time.time() + ready_timeout
    while time.time() < deadline:
        if exec_in(vm, ["true"]).returncode == 0:
            return vm
        time.sleep(1)
    raise TimeoutError(f"multipass guest agent for {name!r} never became ready")


def delete(vm: Vm) -> None:
    """Force-deletes and purges a VM, ignoring errors if it's already gone.

    Args:
        vm: The VM to delete.
    """
    subprocess.run(
        ["multipass", "delete", "--purge", vm.name], capture_output=True, check=False
    )


def _ssh_key() -> str | None:
    """The TESTLONG_MULTIPASS_SSH_KEY path, if the ssh fallback is enabled."""
    return os.environ.get(SSH_KEY_ENV) or None


def _vm_ip(vm: Vm) -> str:
    """Looks up a VM's IPv4 address from the multipass daemon.

    `multipass info` talks to multipassd over its local socket, so it isn't
    affected by the Local Network restriction the ssh fallback works around.

    Raises:
        subprocess.CalledProcessError: If `multipass info` fails.
        KeyError: If the VM has no IPv4 address yet.
    """
    result = subprocess.run(
        ["multipass", "info", "--format", "json", vm.name],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)["info"][vm.name]["ipv4"][0]


def _ssh_argv(vm: Vm, key: str) -> list[str]:
    """ssh command prefix reaching vm as the default "ubuntu" account."""
    return [
        "ssh",
        "-i",
        key,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "BatchMode=yes",
        # Offer only this key: otherwise ssh tries every ssh-agent key first,
        # and a well-stocked agent exhausts sshd's MaxAuthTries before this
        # key is reached ("Too many authentication failures").
        "-o",
        "IdentitiesOnly=yes",
        f"ubuntu@{_vm_ip(vm)}",
    ]


def transfer(local_path: str, vm: Vm, remote_path: str) -> None:
    """Copies a local file or directory into the VM.

    Args:
        local_path: Source path on the host.
        vm: Target VM.
        remote_path: Destination path inside the VM.

    With TESTLONG_MULTIPASS_SSH_KEY set, a directory is streamed as a tar
    over ssh (symlinks kept as symlinks, as `multipass transfer` does;
    TRANSFER_EXCLUDES left out) and a file is copied with ssh + cat.

    Raises:
        subprocess.CalledProcessError: If the transfer fails.
    """
    key = _ssh_key()
    if key is None:
        subprocess.run(
            ["multipass", "transfer", "-r", local_path, f"{vm.name}:{remote_path}"],
            check=True,
        )
        return

    ssh = _ssh_argv(vm, key)
    remote = shlex.quote(remote_path)
    if not os.path.isdir(local_path):
        with open(local_path, "rb") as fi:
            subprocess.run([*ssh, f"cat > {remote}"], stdin=fi, check=True)
        return

    excludes = [arg for name in TRANSFER_EXCLUDES for arg in ("--exclude", name)]
    tar = subprocess.Popen(
        ["tar", "--no-mac-metadata", *excludes, "-C", local_path, "-cf", "-", "."],
        stdout=subprocess.PIPE,
        # bsdtar: don't add AppleDouble ._* files for extended attributes
        env={**os.environ, "COPYFILE_DISABLE": "1"},
    )
    try:
        subprocess.run(
            [*ssh, f"mkdir -p {remote} && tar --warning=no-unknown-keyword -C {remote} -xf -"],
            stdin=tar.stdout,
            check=True,
        )
    finally:
        assert tar.stdout is not None
        tar.stdout.close()
        if tar.wait() != 0:
            raise subprocess.CalledProcessError(tar.returncode, "tar")


def exec_in(vm: Vm, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Runs a command inside a running VM via `multipass exec` (or ssh, see
    TESTLONG_MULTIPASS_SSH_KEY), as the VM's default "ubuntu" account.

    Args:
        vm: Target VM.
        cmd: Command (and args) to execute.
        **kwargs: Extra keyword arguments forwarded to subprocess.run.

    Returns:
        The completed process, with captured stdout/stderr as text.
    """
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    key = _ssh_key()
    if key is None:
        return subprocess.run(["multipass", "exec", vm.name, "--", *cmd], **kwargs)
    try:
        ssh = _ssh_argv(vm, key)
    except (subprocess.CalledProcessError, KeyError, IndexError) as exc:
        # e.g. no IPv4 yet right after launch - report as a failed command,
        # as `multipass exec` would, so launch()'s readiness poll retries.
        return subprocess.CompletedProcess(cmd, 255, "", str(exc))
    return subprocess.run([*ssh, shlex.join(cmd)], **kwargs)
