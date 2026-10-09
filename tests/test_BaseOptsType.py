# -*- python-fmt -*-

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

"""Checks on option definitions: types and name/flag conflicts."""

import dataclasses
from pathlib import Path

import pytest

import BaseOpts
import Plotting
from BaseOptsType import (
    check_options_dict,
    merge_options,
    option_conflicts,
    options_t,
    same_option,
)


def make_opt(
    default: object = 1, flag: str = "--test_opt", help_text: str = "a test option"
) -> options_t:
    """An int option with one flag.

    Args:
        default: the default value
        flag: the command line flag
        help_text: the help string

    Returns:
        The option.
    """
    return options_t(default, {"Base"}, (flag,), int, {"help": help_text})


def test_same_option_ignores_group_required_and_help() -> None:
    """Copies of one definition differ only in what BaseOptions changes, or the help."""
    a = make_opt()
    b = dataclasses.replace(
        make_opt(help_text="other help"), group={"Base", "Reprocess"}
    )
    b.kwargs["required"] = {"Reprocess"}
    assert same_option(a, b)


@pytest.mark.parametrize(
    "other",
    [
        make_opt(default=2),
        make_opt(flag="--other"),
        options_t(1, {"Base"}, ("--test_opt",), float, {"help": "a test option"}),
        options_t(
            1, {"Base"}, ("--test_opt",), int, {"help": "x", "action": "store_true"}
        ),
    ],
)
def test_same_option_differs(other: options_t) -> None:
    """Default, flags, type and the other kwargs are part of the definition."""
    assert not same_option(make_opt(), other)


@pytest.mark.parametrize(
    ("options", "match"),
    [
        ([make_opt()], "must be a dict"),
        ({1: make_opt()}, "is not a str"),
        ({"test_opt": {"default": 1}}, "not an options_t"),
    ],
)
def test_check_options_dict_rejects(options: object, match: str) -> None:
    """Anything but a dict of name to options_t is a TypeError naming the source."""
    with pytest.raises(TypeError, match=f"my_source: .*{match}"):
        check_options_dict(options, "my_source")


def test_option_conflicts() -> None:
    """Same name defined differently, or a flag already in use, conflicts."""
    options = {"test_opt": make_opt()}
    assert option_conflicts(options, "test_opt", make_opt()) is None
    assert option_conflicts(options, "other_opt", make_opt(flag="--other")) is None
    assert "already defined differently" in option_conflicts(
        options, "test_opt", make_opt(default=2)
    )
    assert "--test_opt, already used by option test_opt" in option_conflicts(
        options, "other_opt", make_opt()
    )


def test_merge_options_refuses_whole_dict_on_conflict() -> None:
    """A conflict raises before anything is added."""
    options = {"test_opt": make_opt()}
    new = {"new_opt": make_opt(flag="--new"), "test_opt": make_opt(default=2)}
    with pytest.raises(ValueError, match="my_source: option test_opt"):
        merge_options(options, new, "my_source")
    assert list(options) == ["test_opt"]
    merge_options(options, {"new_opt": make_opt(flag="--new")}, "my_source")
    assert list(options) == ["test_opt", "new_opt"]


def test_plot_add_arguments_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plot's options are type checked and can't redefine another plot's."""
    monkeypatch.setattr(
        Plotting, "plotting_additional_arguments", {"test_opt": make_opt()}
    )

    def plot() -> None:
        """Stand-in plot."""

    with pytest.raises(ValueError, match="option test_opt is already defined"):
        Plotting.add_arguments(additional_arguments={"test_opt": make_opt(default=2)})(
            plot
        )
    with pytest.raises(TypeError, match="not an options_t"):
        Plotting.add_arguments(additional_arguments={"x": 1})(plot)
    assert (
        Plotting.add_arguments(additional_arguments={"test_opt": make_opt()})(plot)
        is plot
    )


def test_base_options_caller_conflict() -> None:
    """A module's own option can't redefine a core option."""
    with pytest.raises(ValueError, match="option debug is already defined"):
        BaseOpts.BaseOptions(
            "test",
            cmdline_args=[],
            calling_module="Base",
            additional_arguments={"debug": make_opt(flag="--debug")},
        )


def test_base_options_unknown_add_to_arguments() -> None:
    """add_to_arguments naming an option that doesn't exist says which."""
    with pytest.raises(ValueError, match="unknown option no_such_option"):
        BaseOpts.BaseOptions(
            "test",
            cmdline_args=[],
            calling_module="Base",
            add_to_arguments=["no_such_option"],
        )


def test_base_options_leaves_core_options_alone(tmp_path: Path) -> None:
    """BaseOptions works on a copy - plot options don't leak into the core dict."""
    before = set(BaseOpts.global_options_dict)
    BaseOpts.BaseOptions(
        "test",
        # argparse takes str
        cmdline_args=["--mission_dir", str(tmp_path)],
        calling_module="Base",
    )
    assert set(BaseOpts.global_options_dict) == before
    assert not before & set(Plotting.plotting_additional_arguments)


def test_base_options_bad_extension_options_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A mission extension's bad options are reported and skipped, processing goes on."""
    mission_dir = tmp_path / "mission_dir"
    mission_dir.mkdir()
    (mission_dir / ".extensions").write_text("[postnetcdf]\nOptsTestExt.py\n")
    (mission_dir / "OptsTestExt.py").write_text(
        "from BaseOptsType import options_t\n"
        "def load_additional_arguments():\n"
        "    return (\n"
        "        ['no_such_option', 'opts_test_good'],\n"
        "        {},\n"
        "        {\n"
        "            'debug': options_t(1, None, ('--debug',), int, {}),\n"
        "            'opts_test_bad': 'not an option',\n"
        "            'opts_test_good': options_t(3, {'Base'}, ('--opts_test_good',), int, {}),\n"
        "        },\n"
        "    )\n"
    )
    base_opts = BaseOpts.BaseOptions(
        "test",
        cmdline_args=["--mission_dir", str(mission_dir)],  # argparse takes str
        calling_module="Base",
    )
    err = capsys.readouterr().err
    assert "option debug is already defined differently" in err
    assert "opts_test_bad is a str, not an options_t" in err
    assert "unknown option 'no_such_option'" in err
    assert base_opts.debug is False
    assert base_opts.opts_test_good == 3
