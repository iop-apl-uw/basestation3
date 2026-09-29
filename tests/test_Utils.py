# -*- python-fmt -*-

## Copyright (c) 2025, 2026  University of Washington.
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

import logging
import os
import subprocess
import types
import warnings
from pathlib import Path

import numpy as np
import pytest
import testutils

import BaseLog
import Utils


def test_estimate_endurance_handles_all_nan_gauge_column(caplog):
    """A gauge/dive-time column that's entirely NaN over the requested dive
    window (e.g. battery capacity and time_seconds_on_surface both stopped
    being logged partway through a long mission - sg244_AMOS_Jul25 dive 835
    real-world case) must not crash inside time.gmtime() - regression test
    for a bug where MissionEnergy.py's own graceful-degradation path
    (catching datetime.strptime failures) never got a chance to run
    because estimate_endurance() itself raised first.
    """
    base_opts = types.SimpleNamespace(
        mission_energy_dives_back=20,
        mission_energy_reserve_percent=0.2,
    )
    dive_col = np.arange(1, 21, dtype=float)
    gauge_col = np.full(20, np.nan)
    # NaN, matching dive_time = time_seconds_on_surface + time_seconds_diving
    # when time_seconds_on_surface stopped being logged for these dives.
    dive_times = np.full(20, np.nan)
    dive_end = np.arange(1_700_000_000, 1_700_000_000 + 20 * 86400, 86400, dtype=float)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        dives_remaining, days_remaining, end_date = Utils.estimate_endurance(
            base_opts, dive_col, gauge_col, dive_times, dive_end
        )

    assert np.isnan(dives_remaining)
    assert np.isnan(days_remaining)
    # Deliberately unparseable, matching MissionEnergy.py's existing
    # except ValueError handling around datetime.strptime(end_date, ...).
    assert end_date == "unknown"


@pytest.mark.parametrize("test_timeout", (10, None))
def test_run_cmd_shell(caplog, test_timeout):
    ret_code, fo = Utils.run_cmd_shell("tests/echo_err.sh", timeout=test_timeout)
    # Check for known WARNING, ERROR or CRITICAL msgs
    bad_errors = ""
    for record in caplog.records:
        if record.levelname in ["CRITICAL", "ERROR", "WARNING"]:
            bad_errors += f"{record.levelname}:{record.getMessage()}\n"
    if bad_errors:
        pytest.fail(bad_errors)

    assert ret_code is not None
    assert fo is not None

    # No good way to verify output - even with sorting, due to the binary output and
    # buffer sizes, some of the lines are partial.
    # l_lines = fo.readlines()
    # for ii, l_line in enumerate(sorted(l_lines,key=lambda x: int(x.decode.split("")[0]))):
    #    tag = "stderr" if ii % 2 else "stdout"
    #    assert l_line == f"{ii} {tag}\n".encode()


def test_run_cmd_shell_timeout(caplog):
    assert testutils.is_logging_configured()

    ret_code, fo = Utils.run_cmd_shell("tests/loop_infinite.sh", timeout=2)

    # Check for known WARNING, ERROR or CRITICAL msgs
    # Timeout message expected
    required_msgs = {"Timeout running": False}
    bad_errors = ""
    for record in caplog.records:
        for msg in required_msgs:
            if msg in record.msg:
                required_msgs[msg] = True
                break
        else:
            if record.levelname in ["CRITICAL", "ERROR", "WARNING"]:
                bad_errors += f"{record.levelname}:{record.getMessage()}\n"
    if bad_errors:
        pytest.fail(bad_errors)

    for msg, found in required_msgs.items():
        if not found:
            pytest.fail(f"Failed to find required msg {msg}")

    assert ret_code is None
    assert fo is None


SHA = "1917788" + "a" * 33


def _make_git(root: Path, head: str = "ref: refs/heads/master\n") -> Path:
    """Builds a minimal fake .git directory under root."""
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(head)
    return git_dir


def test_get_commit_id_loose_ref(tmp_path: Path) -> None:
    git_dir = _make_git(tmp_path)
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "refs" / "heads" / "master").write_text(SHA + "\n")
    assert Utils.get_commit_id(tmp_path) == ("1917788", None)


def test_get_commit_id_packed_ref(tmp_path: Path) -> None:
    git_dir = _make_git(tmp_path)
    (git_dir / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{'b' * 40} refs/heads/other\n"
        f"{SHA} refs/heads/master\n"
        f"^{'c' * 40}\n"
    )
    assert Utils.get_commit_id(str(tmp_path)) == ("1917788", None)


def test_get_commit_id_detached_head(tmp_path: Path) -> None:
    _make_git(tmp_path, head=SHA + "\n")
    assert Utils.get_commit_id(tmp_path) == ("1917788", None)


def test_get_commit_id_worktree_gitdir_file(tmp_path: Path) -> None:
    """A .git file pointing at a worktree git dir, whose refs live in the common dir."""
    common = tmp_path / "main" / ".git"
    (common / "refs" / "heads").mkdir(parents=True)
    (common / "refs" / "heads" / "feature").write_text(SHA + "\n")
    wt_git = common / "worktrees" / "wt"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/feature\n")
    (wt_git / "commondir").write_text("../..\n")
    checkout = tmp_path / "wt"
    checkout.mkdir()
    (checkout / ".git").write_text(f"gitdir: {wt_git}\n")
    assert Utils.get_commit_id(checkout) == ("1917788", None)


def test_get_commit_id_matches_git(tmp_path: Path) -> None:
    """Agrees with `git rev-parse --short=7 HEAD` on a real repository, loose and packed."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init", "-q", "-b", "master", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "x"],
        check=True,
        env=env,
    )

    def expected() -> str:
        out = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "--short=7", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

    assert Utils.get_commit_id(tmp_path) == (expected(), None)
    subprocess.run(["git", "-C", str(tmp_path), "pack-refs", "--all"], check=True)
    assert not (tmp_path / ".git" / "refs" / "heads" / "master").exists()
    assert Utils.get_commit_id(tmp_path) == (expected(), None)


def test_get_commit_id_no_git(tmp_path: Path) -> None:
    commit, reason = Utils.get_commit_id(tmp_path)
    assert commit is None
    assert reason is not None
    assert "not a git checkout" in reason


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        (
            lambda g: (g / "HEAD").write_text("ref: refs/heads/gone\n"),
            "refs/heads/gone not found",
        ),
        (
            lambda g: (g / "HEAD").write_text("not-a-sha\n"),
            "unexpected commit value 'not-a-sha'",
        ),
        (lambda g: (g / "HEAD").unlink(), "HEAD: No such file or directory"),
    ],
)
def test_get_commit_id_failures(tmp_path: Path, setup, expected: str) -> None:
    setup(_make_git(tmp_path))
    commit, reason = Utils.get_commit_id(tmp_path)
    assert commit is None
    assert reason is not None
    assert expected in reason


def test_get_commit_id_bad_gitdir_file(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("garbage\n")
    commit, reason = Utils.get_commit_id(tmp_path)
    assert commit is None
    assert reason is not None
    assert "not a 'gitdir:' pointer" in reason


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_get_commit_id_unreadable_git(tmp_path: Path) -> None:
    """The seaglider.pub case: .git exists but the running account can't read it."""
    git_dir = _make_git(tmp_path)
    git_dir.chmod(0o000)
    try:
        commit, reason = Utils.get_commit_id(tmp_path)
    finally:
        git_dir.chmod(0o755)
    assert commit is None
    assert reason is not None
    assert "Permission denied" in reason


def test_log_version_banner(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # log_info() is a no-op unless BaseLogger is at INFO (--verbose)
    monkeypatch.setattr(BaseLog.BaseLogger, "log_level", logging.INFO)
    caplog.set_level(logging.INFO)
    base_opts = types.SimpleNamespace(basestation_directory=tmp_path)

    _make_git(tmp_path, head=SHA + "\n")
    Utils.log_version_banner(base_opts)  # ty: ignore[invalid-argument-type]
    msgs = [r.getMessage() for r in caplog.records]
    assert any("Basestation version: " in m and "; QC version: " in m for m in msgs)
    assert any(m.endswith("Commit-ID: 1917788") for m in msgs)
    assert all(r.levelname == "INFO" for r in caplog.records)

    caplog.clear()
    (tmp_path / ".git" / "HEAD").unlink()
    Utils.log_version_banner(base_opts)  # ty: ignore[invalid-argument-type]
    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.endswith("Commit-ID: unknown") for m in msgs)
    assert any("Commit-ID could not be determined: " in m and "HEAD" in m for m in msgs)
    # Never WARNING or above - that would reach pilot notifications on every run.
    assert all(r.levelname == "INFO" for r in caplog.records)
