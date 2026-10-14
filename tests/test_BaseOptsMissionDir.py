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

"""BaseOpts checks --mission_dir once for every module: an existing directory with r and x permission."""

import os
import pathlib

import pytest

import Base  # noqa: F401 - normal import order
import BaseOpts

needs_non_root = pytest.mark.skipif(os.geteuid() == 0, reason="root passes every permission check")


def _options(cmdline_args: list[str], calling_module: str = "Base") -> BaseOpts.BaseOptions:
    return BaseOpts.BaseOptions("test", cmdline_args=cmdline_args, calling_module=calling_module)


def test_mission_dir_problem(tmp_path: pathlib.Path) -> None:
    assert BaseOpts.mission_dir_problem(tmp_path) is None
    assert BaseOpts.mission_dir_problem(tmp_path / "nope") == f"--mission_dir {tmp_path / 'nope'} does not exist"
    a_file = tmp_path / "divescience.yml"
    a_file.write_text("{}\n")
    assert BaseOpts.mission_dir_problem(a_file) == f"--mission_dir {a_file} is not a directory"


@needs_non_root
def test_mission_dir_problem_permissions(tmp_path: pathlib.Path) -> None:
    """r and x are needed; w isn't (checkers and plots run on read-only directories)."""
    read_only = tmp_path / "read_only"
    read_only.mkdir()
    read_only.chmod(0o555)
    no_search = tmp_path / "no_search"
    no_search.mkdir()
    no_search.chmod(0o444)
    try:
        assert BaseOpts.mission_dir_problem(read_only) is None
        assert BaseOpts.mission_dir_problem(no_search) == (
            f"--mission_dir {no_search} is not readable (needs r and x permission)"
        )
    finally:
        read_only.chmod(0o755)
        no_search.chmod(0o755)


@pytest.mark.parametrize("module", ["Base", "Reprocess", "FTPPush"])
def test_bad_mission_dir_is_a_usage_error(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], module: str
) -> None:
    """A bad --mission_dir stops the parse with argparse's usage error (exit 2), for every module."""
    a_file = tmp_path / "not_a_dir"
    a_file.write_text("")
    with pytest.raises(SystemExit) as exc:
        _options(["--mission_dir", str(a_file)], module)
    assert exc.value.code == 2
    assert capsys.readouterr().err.rstrip().endswith(f"error: --mission_dir {a_file} is not a directory")


def test_good_mission_dir(tmp_path: pathlib.Path) -> None:
    assert _options(["--mission_dir", str(tmp_path)]).mission_dir == tmp_path.resolve()


def test_mission_dir_from_config(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A --mission_dir set in the --config file is checked too."""
    missing = tmp_path / "missing_mission"
    conf = tmp_path / "sg123.conf"
    conf.write_text(f"[base]\nmission_dir = {missing}\n")
    with pytest.raises(SystemExit) as exc:
        _options(["--mission_dir", str(tmp_path), "--config", str(conf)])
    assert exc.value.code == 2
    assert f"error: --mission_dir {missing} does not exist" in capsys.readouterr().err
