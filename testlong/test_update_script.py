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

"""Validates install/update_basestation.sh end-to-end in a fresh container.

Independent of test_install_script.py (its own fresh install + mutate +
update flow, rather than sharing container state across test files) so a
failure in one doesn't obscure a failure in the other.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import dockerutils
import pytest

PILOT_USER = "testpilot"
MARKER_FILE = "TESTLONG_UPDATE_MARKER"


@pytest.fixture(scope="module")
def mutable_source_clone(tmp_path_factory: pytest.TempPathFactory, repo_root: Path) -> Path:
    """Clones repo_root into a scratch directory this test can commit to.

    A plain read-only bind mount of the real working tree can't be used for
    the update flow, since it needs a real `git pull` to fetch a new commit.
    This gives the test its own throwaway git history (repo_root as
    `origin`), safe to mutate without touching the real checkout.

    Args:
        tmp_path_factory: pytest's module-scoped temp directory factory.
        repo_root: The real repository, used as the clone source.

    Returns:
        Path to the cloned, mutable repository.

    Raises:
        subprocess.CalledProcessError: If the clone or branch setup fails.
    """
    clone_dir = tmp_path_factory.mktemp("basestation_source") / "basestation3"
    subprocess.run(["git", "clone", str(repo_root), str(clone_dir)], check=True)

    # A plain clone only creates a local branch for whatever repo_root's
    # checked-out HEAD happens to be (e.g. a feature branch, during
    # development) - `master` is otherwise only reachable as `origin/master`,
    # which does NOT propagate to a further clone, and (pre-merge) doesn't
    # contain install/ at all. update_basestation.sh's checkout_source() runs
    # `git pull origin master` inside the container against a *second* clone
    # of this directory, so force a local `master` branch to point at HEAD's
    # actual content (not origin/master) - this stands in for "master" once
    # the current branch is merged, and keeps install/ present regardless of
    # which branch is under test.
    subprocess.run(["git", "-C", str(clone_dir), "branch", "-f", "master", "HEAD"], check=True)
    return clone_dir


@pytest.fixture(scope="module")
def installed_container(
    docker_available: None, mutable_source_clone: Path
) -> Iterator[dockerutils.Container]:
    """Starts a container and runs install_basestation.sh against the mutable clone.

    Bind-mounted read-write (unlike test_install_script.py's read-only
    mount), so later tests can commit new code to the clone and have
    update_basestation.sh pull it from inside the container.

    Args:
        docker_available: Ensures Docker is usable before starting.
        mutable_source_clone: The scratch git clone to bind-mount read-write.

    Yields:
        The container the install script already ran in.
    """
    container = dockerutils.prepare_pilot_container(
        "ubuntu:22.04", {str(mutable_source_clone): "/src"}, PILOT_USER, read_only=False
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


def test_update_pulls_new_code_and_skips_onetime_steps(
    installed_container: dockerutils.Container, mutable_source_clone: Path
) -> None:
    """A new commit is picked up by update, which skips the one-time setup steps.

    Args:
        installed_container: Container with install_basestation.sh already run.
        mutable_source_clone: The scratch clone bind-mounted into the container.

    Raises:
        AssertionError: If the marker file isn't present after update, or the
            update script doesn't log that it skipped the one-time steps.
    """
    # update_basestation.sh always pulls `origin master` (matching Readme.md's
    # documented update flow), regardless of what branch happens to be
    # checked out in this scratch clone (e.g. a feature branch, during
    # development) - so the marker commit has to land on `master` specifically,
    # not on whatever mutable_source_clone's HEAD currently is.
    subprocess.run(["git", "-C", str(mutable_source_clone), "checkout", "master"], check=True)
    marker = mutable_source_clone / MARKER_FILE
    marker.write_text("update smoke test marker\n")
    subprocess.run(["git", "-C", str(mutable_source_clone), "add", MARKER_FILE], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(mutable_source_clone),
            "-c",
            "user.name=testlong",
            "-c",
            "user.email=testlong@example.com",
            "commit",
            "-m",
            "testlong marker commit",
        ],
        check=True,
    )

    result = dockerutils.exec_in(
        installed_container.container_id,
        [
            "bash",
            f"{installed_container.repo_mount}/install/update_basestation.sh",
            "--pilot-user",
            PILOT_USER,
        ],
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "skipping system package install (update mode)" in output
    assert "skipping gliders group setup (update mode)" in output
    assert "skipping PAM login edit (update mode)" in output

    marker_check = dockerutils.exec_in(
        installed_container.container_id,
        ["test", "-f", f"/usr/local/basestation3/{MARKER_FILE}"],
    )
    assert marker_check.returncode == 0, "new commit was not pulled into /usr/local/basestation3"


def test_update_preserves_hand_edited_login_script(
    installed_container: dockerutils.Container,
) -> None:
    """update_basestation.sh doesn't clobber a hand-edited glider_login.

    Args:
        installed_container: Container with install_basestation.sh already run.

    Raises:
        AssertionError: If the hand-edit is lost after running update.
    """
    edit_marker = "# TESTLONG_HAND_EDIT"
    dockerutils.exec_in(
        installed_container.container_id,
        ["bash", "-c", f"echo '{edit_marker}' >> /usr/local/basestation/glider_login"],
        check=True,
    )

    result = dockerutils.exec_in(
        installed_container.container_id,
        [
            "bash",
            f"{installed_container.repo_mount}/install/update_basestation.sh",
            "--pilot-user",
            PILOT_USER,
        ],
    )
    assert result.returncode == 0, result.stdout + result.stderr

    check = dockerutils.exec_in(
        installed_container.container_id,
        ["grep", "-q", edit_marker, "/usr/local/basestation/glider_login"],
    )
    assert check.returncode == 0, "hand-edited glider_login was overwritten by update"
