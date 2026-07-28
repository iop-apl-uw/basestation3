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

"""Shared Docker subprocess helpers for the testlong/ suite.

Not a test module itself - plays the same role for testlong/ that
tests/testutils.py plays for tests/ (a plain, bare-imported helper module,
not a pytest plugin).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeImage:
    """A built `runtime` stage image and the build args used to create it.

    Attributes:
        tag: Docker image tag.
        user_id: USER_ID build-arg baked into the image.
        group_id: GROUP_ID build-arg baked into the image.
        baserunner: BASERUNNER build-arg (account name) baked into the image.
    """

    tag: str
    user_id: int
    group_id: int
    baserunner: str


@dataclass(frozen=True)
class Container:
    """A running, detached container with a source tree bind-mounted in.

    Attributes:
        container_id: Docker container ID.
        repo_mount: Path inside the container where the source is mounted.
    """

    container_id: str
    repo_mount: str


def docker_build(
    context: str, target: str, tag: str, build_args: dict[str, str] | None = None
) -> None:
    """Runs `docker build` for the given target/tag.

    Args:
        context: Build context directory.
        target: Dockerfile build stage to target.
        tag: Tag to apply to the built image.
        build_args: Optional --build-arg values.

    Raises:
        subprocess.CalledProcessError: If the build fails.
    """
    cmd = ["docker", "build", "--target", target, "-t", tag]
    for key, value in (build_args or {}).items():
        cmd += ["--build-arg", f"{key}={value}"]
    cmd.append(context)
    subprocess.run(cmd, check=True)


def remove_image(tag: str) -> None:
    """Force-removes a Docker image, ignoring errors if it's already gone.

    Args:
        tag: Image tag to remove.
    """
    subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True, check=False)


def run_container(image: str, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Runs a one-shot `docker run --rm` and returns the completed process.

    Args:
        image: Image tag to run.
        cmd: Command (and args) to execute inside the container.
        **kwargs: Extra keyword arguments forwarded to subprocess.run.

    Returns:
        The completed process, with captured stdout/stderr as text.
    """
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    return subprocess.run(["docker", "run", "--rm", image, *cmd], **kwargs)


def start_detached(image: str, mounts: dict[str, str], read_only: bool = True) -> str:
    """Starts a detached, self-removing container running `sleep infinity`.

    Args:
        image: Image to run.
        mounts: Mapping of host path -> container path to bind-mount.
        read_only: Whether the bind mount(s) should be read-only.

    Returns:
        The started container's ID.

    Raises:
        subprocess.CalledProcessError: If `docker run` fails to start it.
    """
    mode = "ro" if read_only else "rw"
    cmd = ["docker", "run", "-d", "--rm"]
    for host_path, container_path in mounts.items():
        cmd += ["-v", f"{host_path}:{container_path}:{mode}"]
    cmd += [image, "sleep", "infinity"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def exec_in(container_id: str, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Runs a command inside a running container via `docker exec`.

    Args:
        container_id: Target container's ID.
        cmd: Command (and args) to execute.
        **kwargs: Extra keyword arguments forwarded to subprocess.run.

    Returns:
        The completed process, with captured stdout/stderr as text.
    """
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", False)
    return subprocess.run(["docker", "exec", container_id, *cmd], **kwargs)


def stop(container_id: str) -> None:
    """Force-stops/removes a detached container, ignoring errors.

    Args:
        container_id: Container ID to stop.
    """
    subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, check=False)


def prepare_pilot_container(
    image: str, mounts: dict[str, str], pilot_user: str, read_only: bool = True
) -> Container:
    """Starts a container with sudo installed and a pilot user account created.

    Common setup shared by the install/update script tests: a bare Ubuntu
    image doesn't have `sudo` (needed by install/update_basestation.sh's own
    internal privilege-dropping) or the pilot Unix account the scripts
    expect to already exist.

    Args:
        image: Base image to run (e.g. "ubuntu:22.04").
        mounts: Mapping of host path -> container path to bind-mount.
        pilot_user: Username to create inside the container.
        read_only: Whether the bind mount(s) should be read-only.

    Returns:
        The prepared, running container.

    Raises:
        subprocess.CalledProcessError: If any setup step fails.
    """
    repo_mount = next(iter(mounts.values()))
    container_id = start_detached(image, mounts, read_only=read_only)
    exec_in(container_id, ["apt-get", "update"], check=True)
    exec_in(container_id, ["apt-get", "install", "-y", "sudo"], check=True)
    exec_in(
        container_id,
        ["adduser", "--disabled-password", "--gecos", "", pilot_user],
        check=True,
    )
    return Container(container_id=container_id, repo_mount=repo_mount)
