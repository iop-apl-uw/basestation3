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


"""BaseOptions keeps each call's option changes to itself (add_to_arguments, add_to_required, option groups)."""

import copy
import pathlib
import sys

import pytest

import Base  # noqa: F401 - normal import order
import BaseOpts
import BaseOptsType
import MakePlotTSProfile


def _rejects_mission_dir(tmp_path: pathlib.Path, calling_module: str, capsys: pytest.CaptureFixture[str]) -> bool:
    capsys.readouterr()
    try:
        BaseOpts.BaseOptions("t", cmdline_args=["--mission_dir", str(tmp_path)], calling_module=calling_module)
    except SystemExit as e:
        return e.code == 2 and "unrecognized arguments: --mission_dir" in capsys.readouterr().err
    return False


def test_add_to_arguments_stays_in_its_call(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = copy.deepcopy(BaseOpts.global_options_dict["mission_dir"].group)
    opts = BaseOpts.BaseOptions(
        "t", cmdline_args=["--mission_dir", str(tmp_path)], calling_module="LeakTestX", add_to_arguments=["mission_dir"]
    )
    assert opts.mission_dir == tmp_path.resolve()
    assert _rejects_mission_dir(tmp_path, "LeakTestX", capsys)
    assert BaseOpts.global_options_dict["mission_dir"].group == before


def test_make_plot_ts_profile_main_does_not_leak(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The case from the task: once MakePlotTSProfile.main has run, its options don't stick to the module name."""
    MakePlotTSProfile.main(["--mission_dir", str(tmp_path), str(tmp_path / "p0010001.npro_ct")])
    assert _rejects_mission_dir(tmp_path, "MakePlotTSProfile", capsys)


def test_add_to_required_stays_in_its_call(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = copy.deepcopy(BaseOpts.global_options_dict["mission_dir"].kwargs)
    with pytest.raises(SystemExit):  # required for this call: missing is an error
        BaseOpts.BaseOptions(
            "t", cmdline_args=[], calling_module="LeakTestY", add_to_arguments=["mission_dir"], add_to_required=["mission_dir"]
        )
    capsys.readouterr()
    # The next call adds the option but doesn't require it
    opts = BaseOpts.BaseOptions("t", cmdline_args=[], calling_module="LeakTestY", add_to_arguments=["mission_dir"])
    assert opts.mission_dir is None
    assert BaseOpts.global_options_dict["mission_dir"].kwargs == before


def test_add_option_groups_stays_in_its_call() -> None:
    before = dict(BaseOpts.option_group_description)
    BaseOpts.BaseOptions(
        "t",
        cmdline_args=[],
        calling_module="LeakTestZ",
        add_option_groups={"leaktest": "a group for this call only"},
        additional_arguments={
            "leak_opt": BaseOptsType.options_t(
                None, {"LeakTestZ"}, ("--leak_opt",), str, {"help": "x", "option_group": "leaktest"}
            )
        },
    )
    assert BaseOpts.option_group_description == before


def test_sys_path_does_not_grow(monkeypatch: pytest.MonkeyPatch) -> None:
    """BaseOptions' own sys.path entry isn't added again. (Extensions are left out: adcp's modules append to
    sys.path at import, and BaseOptions re-imports the extensions on every call.)"""
    monkeypatch.setattr(BaseOpts, "find_additional_options", lambda *args: ({}, {}, {}))
    BaseOpts.BaseOptions("t", cmdline_args=[], calling_module="LeakTestW")
    n = len(sys.path)
    for _ in range(3):
        BaseOpts.BaseOptions("t", cmdline_args=[], calling_module="LeakTestW")
    assert len(sys.path) == n
