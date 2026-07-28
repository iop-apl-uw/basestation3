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

"""Validates install/install_basestation.sh end-to-end in a fresh container.

Runs the script against a bind-mounted copy of this checkout (via
BASESTATION_SOURCE_DIR) inside a bare ubuntu:22.04 container, then asserts
each documented outcome. This mechanically re-validates the "Installation
for a realtime basestation" section of Readme.md that the script automates.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import dockerutils
import pytest

PILOT_USER = "testpilot"


@pytest.fixture(scope="module")
def installed_container(
    docker_available: None, repo_root: Path
) -> Iterator[dockerutils.Container]:
    """Runs install_basestation.sh once, shared by every test in this module.

    Args:
        docker_available: Ensures Docker is usable before starting.
        repo_root: Host repo path, bind-mounted read-only into the container.

    Yields:
        The container the install script ran against.
    """
    container = dockerutils.prepare_pilot_container(
        "ubuntu:22.04", {str(repo_root): "/src"}, PILOT_USER, read_only=True
    )
    try:
        result = dockerutils.exec_in(
            container.container_id,
            [
                "env",
                f"BASESTATION_SOURCE_DIR={container.repo_mount}",
                "bash",
                f"{container.repo_mount}/install/install_basestation.sh",
                "--pilot-user",
                PILOT_USER,
            ],
        )
        assert result.returncode == 0, result.stdout + result.stderr
        yield container
    finally:
        dockerutils.stop(container.container_id)


def test_install_creates_gliders_group(installed_container: dockerutils.Container) -> None:
    """The gliders group exists after install.

    Args:
        installed_container: Container the install script already ran in.

    Raises:
        AssertionError: If the gliders group is missing.
    """
    result = dockerutils.exec_in(
        installed_container.container_id, ["getent", "group", "gliders"]
    )
    assert result.returncode == 0


def test_install_pilot_user_in_gliders_group(installed_container: dockerutils.Container) -> None:
    """The pilot user was added to the gliders group.

    Args:
        installed_container: Container the install script already ran in.

    Raises:
        AssertionError: If the pilot user isn't in the gliders group.
    """
    result = dockerutils.exec_in(installed_container.container_id, ["id", "-nG", PILOT_USER])
    assert "gliders" in result.stdout.split()


def test_install_directory_ownership(installed_container: dockerutils.Container) -> None:
    """/usr/local/basestation3 is owned by the pilot user and gliders group.

    Args:
        installed_container: Container the install script already ran in.

    Raises:
        AssertionError: If ownership doesn't match pilot_user:gliders.
    """
    result = dockerutils.exec_in(
        installed_container.container_id,
        ["stat", "-c", "%U:%G", "/usr/local/basestation3"],
    )
    assert result.stdout.strip() == f"{PILOT_USER}:gliders"


def test_install_venv_works(installed_container: dockerutils.Container) -> None:
    """The uv-managed venv can run Base.py --help.

    Args:
        installed_container: Container the install script already ran in.

    Raises:
        AssertionError: If the smoke-test command fails.
    """
    result = dockerutils.exec_in(
        installed_container.container_id,
        [
            "sudo",
            "-u",
            PILOT_USER,
            "/opt/basestation/bin/python",
            "/usr/local/basestation3/Base.py",
            "--help",
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_chromium_installed(installed_container: dockerutils.Container) -> None:
    """Chromium (needed by kaleido for static plot image export) was installed.

    Regression guard for the gap this test suite predates: the script used to
    produce a basestation that could run Base.py but couldn't render any plot
    images, since kaleido>=1.0 needs an externally supplied Chromium and
    nothing installed one. The fixture's own smoke_test call already renders a
    plot end-to-end; this asserts the specific artifact (a world-readable
    Chromium binary under /opt/playwright-browsers) that makes that possible.

    Args:
        installed_container: Container the install script already ran in.

    Raises:
        AssertionError: If no executable Chromium binary is found, or it isn't
            world-readable/executable (needed since glider accounts, not just
            the pilot user, run plot generation at logout).
    """
    find_chrome = (
        "find /opt/playwright-browsers -iname chrome -type f -executable | sort | tail -1"
    )
    result = dockerutils.exec_in(
        installed_container.container_id, ["sh", "-c", find_chrome]
    )
    chrome_path = result.stdout.strip()
    assert result.returncode == 0 and chrome_path, result.stdout + result.stderr

    perm_result = dockerutils.exec_in(
        installed_container.container_id, ["stat", "-c", "%A", chrome_path]
    )
    perms = perm_result.stdout.strip()
    assert perms[-3:] in ("r-x", "rwx"), f"{chrome_path} not world-readable/executable: {perms}"


def test_install_login_logout_scripts_copied(installed_container: dockerutils.Container) -> None:
    """glider_login/glider_logout were installed to /usr/local/basestation.

    Args:
        installed_container: Container the install script already ran in.

    Raises:
        AssertionError: If either script is missing.
    """
    for name in ("glider_login", "glider_logout"):
        result = dockerutils.exec_in(
            installed_container.container_id,
            ["test", "-f", f"/usr/local/basestation/{name}"],
        )
        assert result.returncode == 0, f"{name} missing"
