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

"""Docker- and multipass-based fixtures for the testlong/ suite.

These tests build Docker images/spin up VMs, so they're slow - they're
deliberately not part of `make test`/CI. `pyproject.toml` sets
`testpaths = ["tests"]`, so a bare `pytest`/`make test` invocation does not
collect this directory; run these explicitly instead: `make testlong` or
`uv run pytest testlong/`.

Set TESTLONG_KEEP_IMAGES=1 to skip removing the built Docker images at the
end of the session, for faster iteration when re-running locally. Set
TESTLONG_KEEP_VM=1 to do the same for the multipass VM used by the
BaseRunnerMulti validation tests - relaunching and re-provisioning it
(`uv sync` inside the VM alone takes a while) is far more expensive than
rebuilding a Docker image.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import dockerutils
import multipassutils
import pytest

KEEP_IMAGES_ENV = "TESTLONG_KEEP_IMAGES"
KEEP_VM_ENV = "TESTLONG_KEEP_VM"
BASERUNNER_VM_NAME = "testlong-baserunner"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Returns the repository root (parent of this testlong/ directory).

    Returns:
        Absolute path to the repository root.
    """
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def docker_available() -> None:
    """Skips the test session if Docker isn't installed/running.

    Raises:
        pytest.skip.Exception: If the `docker` CLI is missing or `docker
            info` fails.
    """
    if shutil.which("docker") is None:
        pytest.skip("docker not found on PATH")
    result = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        pytest.skip(f"docker not available: {result.stderr.strip()}")


@pytest.fixture(scope="session")
def runtime_image(
    docker_available: None, repo_root: Path
) -> Iterator[dockerutils.RuntimeImage]:
    """Builds the Dockerfile's `runtime` stage once per test session.

    Args:
        docker_available: Ensures Docker is usable before building.
        repo_root: Build context.

    Yields:
        The built image's tag and the build args used.
    """
    tag = "basestation-testlong:runtime"
    user_id, group_id, baserunner = 1000, 1000, "baserunner"
    dockerutils.docker_build(
        str(repo_root),
        "runtime",
        tag,
        {"USER_ID": str(user_id), "GROUP_ID": str(group_id), "BASERUNNER": baserunner},
    )
    yield dockerutils.RuntimeImage(
        tag=tag, user_id=user_id, group_id=group_id, baserunner=baserunner
    )
    if not os.environ.get(KEEP_IMAGES_ENV):
        dockerutils.remove_image(tag)


@pytest.fixture(scope="session")
def ci_image(docker_available: None, repo_root: Path) -> Iterator[str]:
    """Builds the Dockerfile's `ci` stage once per test session.

    Args:
        docker_available: Ensures Docker is usable before building.
        repo_root: Build context.

    Yields:
        The built image's tag.
    """
    tag = "basestation-testlong:ci"
    dockerutils.docker_build(str(repo_root), "ci", tag)
    yield tag
    if not os.environ.get(KEEP_IMAGES_ENV):
        dockerutils.remove_image(tag)


@pytest.fixture(scope="session")
def multipass_available() -> None:
    """Skips the test session if multipass isn't installed/available.

    Raises:
        pytest.skip.Exception: If the `multipass` CLI is missing or
            `multipass version` fails.
    """
    if shutil.which("multipass") is None:
        pytest.skip("multipass not found on PATH")
    result = subprocess.run(
        ["multipass", "version"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip(f"multipass not available: {result.stderr.strip()}")


@pytest.fixture(scope="session")
def baserunner_vm(
    multipass_available: None, repo_root: Path
) -> Iterator[multipassutils.Vm]:
    """Launches and provisions the BaseRunnerMulti validation VM, once per session.

    Creates three fake sites (alpha/bravo/charlie), the baserunner service
    account, a real `uv sync`'d copy of this checkout with stub
    Base.py/BaseLogin.py/GliderEarlyGPS.py swapped in (see
    testlong/fixtures/setup_baserunner_env.sh), and installs (but does not
    start) the baserunnermulti/baserunnerprivexec/baserunner-legacy@
    systemd units - individual tests control starting/stopping those,
    since the migration/rollback test needs a specific ordering the other
    tests don't.

    Args:
        multipass_available: Ensures multipass is usable before launching.
        repo_root: This checkout's root, transferred into the VM so
            BaseRunnerMulti.py's own dependency chain (BaseOpts ->
            Plotting, Utils -> numpy/scipy/netCDF4/...) can be uv sync'd
            for real - there's no way around this, even with the science
            scripts themselves stubbed out.

    Yields:
        The provisioned Vm.

    Raises:
        pytest.fail.Exception: If VM provisioning fails.
    """
    vm = multipassutils.launch(BASERUNNER_VM_NAME, cpus=2, memory="4G", disk="20G")
    try:
        multipassutils.transfer(str(repo_root), vm, "/home/ubuntu/basestation3")
        fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        multipassutils.transfer(str(fixtures_dir), vm, "/home/ubuntu/fixtures")
        result = multipassutils.exec_in(
            vm, ["sudo", "bash", "/home/ubuntu/fixtures/setup_baserunner_env.sh"]
        )
        if result.returncode != 0:
            pytest.fail(f"VM provisioning failed:\n{result.stdout}\n{result.stderr}")
        yield vm
    finally:
        if not os.environ.get(KEEP_VM_ENV):
            multipassutils.delete(vm)
