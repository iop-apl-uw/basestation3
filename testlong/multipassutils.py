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
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any


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


def transfer(local_path: str, vm: Vm, remote_path: str) -> None:
    """Copies a local file or directory into the VM.

    Args:
        local_path: Source path on the host.
        vm: Target VM.
        remote_path: Destination path inside the VM.

    Raises:
        subprocess.CalledProcessError: If the transfer fails.
    """
    subprocess.run(
        ["multipass", "transfer", "-r", local_path, f"{vm.name}:{remote_path}"],
        check=True,
    )


def exec_in(vm: Vm, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Runs a command inside a running VM via `multipass exec`.

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
    return subprocess.run(["multipass", "exec", vm.name, "--", *cmd], **kwargs)
