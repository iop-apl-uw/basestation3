#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025, 2026  University of Washington.
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

"""divescience.yml: pydantic models, validated loading and merging, and a check CLI.

Plotting/DiveScience.py draws one plot per entry in divescience.yml, read from
(in this order, each optional):

    <basestation>/config   shipped with basestation3 - don't edit
    <basestation>/etc      the site
    --group_etc            a group of gliders
    the mission directory  one glider

Each file maps a plot name to:

    instrument:  the instrument name as it appears in the netCDF file
    layout:      {xaxis_title, xaxis2_title, xaxis_type, xaxis2_type}
    vars:        variable -> {xaxis, color_down, color_up, units, hoverfmt, visible}

The files go from the most general to the most specific: a later file adds to
the earlier ones and overrides any value they set, key by key - so it can change
one variable's color, or add a variable, without repeating the plot. A null
removes a key (a variable, or a whole plot). Every problem is reported as
file:line. A plot with a problem in any file is dropped, the other plots are
still drawn; a file that isn't valid yaml, or isn't a mapping, is skipped.

Usage:
    DiveScienceModel.py check FILE                        one file on its own
    DiveScienceModel.py dump FILE > file.yml              one file, as loaded
    DiveScienceModel.py check_merged -m MISSION_DIR       the files the plot reads, merged
    DiveScienceModel.py dump_merged -m MISSION_DIR > merged.yml

The merged actions also use --group_etc (on the command line or from --config).
"""

from __future__ import annotations

import pathlib
import sys
from typing import Annotated, Any, Literal

import plotly.graph_objects
import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
)

import BaseOpts
import BaseOptsType
import YamlValidation
from BaseLog import BaseLogger, log_error, log_info

CONFIG_NAME = "divescience.yml"


def _plotly_color(value: str) -> str:
    """Checks a color is one plotly accepts (a CSS name, #rrggbb, rgb(...), ...).

    Args:
        value: The color.

    Returns:
        The color, unchanged.

    Raises:
        ValueError: Plotly doesn't accept it.
    """
    try:
        plotly.graph_objects.scatter.Marker(color=value)
    except ValueError:
        raise ValueError(f"{value!r} is not a color plotly knows") from None
    return value


Color = Annotated[StrictStr, AfterValidator(_plotly_color)]
XAxis = Literal["x1", "x2"]
AxisType = Literal["linear", "log"]
Visible = Literal["legendonly", True, False]


# Per-file models: every field is optional, as a later file may give only part of a plot


class PlotVarSpec(BaseModel):
    """One variable's traces, as a file gives it."""

    model_config = ConfigDict(extra="forbid")
    xaxis: XAxis | None = None
    color_down: Color | None = None
    color_up: Color | None = None
    units: StrictStr | None = None
    hoverfmt: StrictStr | None = None
    visible: Visible | None = None


class PlotLayoutSpec(BaseModel):
    """A plot's axes, as a file gives them."""

    model_config = ConfigDict(extra="forbid")
    xaxis_title: StrictStr | None = None
    xaxis2_title: StrictStr | None = None
    xaxis_type: AxisType | None = None
    xaxis2_type: AxisType | None = None


class PlotSpec(BaseModel):
    """One plot, as a file gives it."""

    model_config = ConfigDict(extra="forbid")
    instrument: StrictStr | None = None
    layout: PlotLayoutSpec | None = None
    vars: dict[StrictStr, PlotVarSpec | None] | None = None


# Merged models: a complete plot, with the defaults filled in - what Plotting/DiveScience.py uses


class PlotVar(BaseModel):
    """One variable's traces, complete."""

    model_config = ConfigDict(extra="forbid")
    xaxis: XAxis = "x1"
    color_down: Color = "Red"
    color_up: Color = "Magenta"
    units: StrictStr = ""
    hoverfmt: StrictStr = ""
    visible: Visible = True


class PlotLayout(BaseModel):
    """A plot's axes, complete."""

    model_config = ConfigDict(extra="forbid")
    xaxis_title: StrictStr = ""
    xaxis2_title: StrictStr = ""
    xaxis_type: AxisType = "linear"
    xaxis2_type: AxisType = "linear"


class Plot(BaseModel):
    """One plot, complete."""

    model_config = ConfigDict(extra="forbid")
    instrument: StrictStr = Field(min_length=1)
    layout: PlotLayout = Field(default_factory=PlotLayout)
    vars: dict[StrictStr, PlotVar] = Field(min_length=1)


def check_file(path: pathlib.Path) -> tuple[YamlValidation.LoadedYaml | None, list[str], set[str]]:
    """Loads and validates one divescience.yml on its own.

    Args:
        path: The file.

    Returns:
        (loaded, problems, bad_plots): loaded is None if the file can't be used at
        all (not yaml, or not a mapping); otherwise it holds the whole file and
        bad_plots names the plots with problems. Each problem is
        "file:line: where: message".

    Raises:
        Nothing.
    """
    try:
        data, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        return None, [YamlValidation.format_yaml_error(path, e)], set()
    except OSError as e:
        return None, [f"{path}: could not read ({e})"], set()
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, [f"{path}: {CONFIG_NAME} must map plot names to plots (got {type(data).__name__})"], set()
    loaded = YamlValidation.LoadedYaml(path, data, locate)
    problems: list[str] = []
    bad: set[str] = set()
    for name, plot in data.items():
        if not isinstance(name, str):
            problems.append(f"{loaded.where((name,))}: plot name {name!r} must be a string")
            bad.add(str(name))
            continue
        if plot is None:
            continue  # removes the plot
        try:
            PlotSpec.model_validate(plot)
        except ValidationError as e:
            problems += YamlValidation.format_validation_errors(path, locate, e, prefix=(name,))
            bad.add(name)
    return loaded, problems, bad


def _where_last(loaded: list[YamlValidation.LoadedYaml], loc: tuple) -> str:
    """file:line in the last file that mentions loc (the most specific one).

    Args:
        loaded: The files, most general first.
        loc: The key path.

    Returns:
        "file:line", or "(no files)".

    Raises:
        Nothing.
    """
    for one in reversed(loaded):
        if isinstance(one.data, dict) and loc[0] in one.data:
            return one.where(loc)
    return "(no files)"


def check_merged_plots(merged: dict, loaded: list[YamlValidation.LoadedYaml]) -> tuple[dict[str, dict], list[str]]:
    """Checks each merged plot is complete, and fills in the defaults.

    Args:
        merged: The merged plots.
        loaded: The files they came from, for locations.

    Returns:
        (plots, problems): plots maps each complete plot's name to its definition,
        defaults filled in; problems describes each plot dropped as incomplete.

    Raises:
        Nothing.
    """
    plots: dict[str, dict] = {}
    problems: list[str] = []
    for name, plot in merged.items():
        try:
            plots[name] = Plot.model_validate(plot).model_dump()
        except ValidationError as e:
            for error in e.errors():
                dotted = ".".join(str(x) for x in (name, *error["loc"]))
                problems.append(f"{_where_last(loaded, (name,))}: {dotted}: {error['msg']} in the merged plot - not plotted")
    return plots, problems


class MergeResult:
    """What load_merged found.

    Attributes:
        plots: Plot name -> complete definition (defaults filled in), for the good plots.
        problems: Each problem, "file:line: where: message" - each costs a plot or a file.
        changes: Each override and removal a later file made (for --verbose / debug).
    """

    def __init__(self) -> None:
        """Args:
            None

        Returns:
            None

        Raises:
            Nothing.
        """
        self.plots: dict[str, dict] = {}
        self.problems: list[str] = []
        self.changes: list[str] = []


def load_merged(paths: list[pathlib.Path]) -> MergeResult:
    """Validates and merges divescience.yml files, most general first.

    A file that can't be used is skipped. A plot with a problem in any file is
    left out of the merge altogether - drawing it from the other files, without
    the change someone meant to make, would hide the mistake.

    Args:
        paths: The files, most general first.

    Returns:
        The merged plots, problems and changes.

    Raises:
        Nothing.
    """
    result = MergeResult()
    usable: list[YamlValidation.LoadedYaml] = []
    bad: set[str] = set()
    for path in paths:
        loaded, problems, bad_plots = check_file(path)
        result.problems += problems
        bad |= bad_plots
        if loaded is not None:
            usable.append(loaded)
    for name in sorted(bad):
        result.problems.append(f"{_where_last(usable, (name,))}: {name}: has problems (above) - not plotted")
    kept = [
        YamlValidation.LoadedYaml(one.path, {k: v for k, v in one.data.items() if str(k) not in bad}, one.locate)
        for one in usable
    ]
    merged, result.changes = YamlValidation.merge_loaded(kept)
    result.plots, problems = check_merged_plots(merged, kept)
    result.problems += problems
    return result


def config_files(base_opts: Any) -> list[pathlib.Path]:
    """The divescience.yml files Plotting/DiveScience.py reads, most general first.

    Args:
        base_opts: Options with basestation_directory, group_etc and mission_dir.

    Returns:
        The files that exist, in merge order.

    Raises:
        Nothing.
    """
    search_dirs = [
        pathlib.Path(sd)
        for sd in (
            base_opts.basestation_directory / "config",
            base_opts.basestation_directory / "etc",
            getattr(base_opts, "group_etc", None),
            getattr(base_opts, "mission_dir", None),
        )
        if sd
    ]
    return [d / CONFIG_NAME for d in search_dirs if (d / CONFIG_NAME).exists()]


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Checks or dumps divescience.yml files.

    Args:
        cmdline_args: Command line arguments.

    Returns:
        0 if everything checked is valid, 1 if not (or the arguments are wrong).

    Raises:
        Nothing expected.
    """
    base_opts = BaseOpts.BaseOptions(
        "Check divescience.yml files",
        cmdline_args=cmdline_args,
        calling_module="DiveScienceModel",
        add_to_arguments=["mission_dir"],
        additional_arguments={
            "action": BaseOptsType.options_t(
                None,
                {"DiveScienceModel"},
                ("action",),
                str,
                {
                    "help": "check FILE | dump FILE | check_merged -m MISSION_DIR | dump_merged -m MISSION_DIR",
                    "choices": ("check", "dump", "check_merged", "dump_merged"),
                },
            ),
            "yml_file": BaseOptsType.options_t(
                None,
                {"DiveScienceModel"},
                ("yml_file",),
                pathlib.Path,
                {"help": "The divescience.yml file (check and dump only)", "nargs": "?"},
            ),
        },
    )
    BaseLogger(base_opts)

    if base_opts.action in ("check", "dump"):
        if base_opts.yml_file is None:
            log_error(f"{base_opts.action} needs a {CONFIG_NAME} file")
            return 1
        path = pathlib.Path(base_opts.yml_file).expanduser()
        loaded, problems, _ = check_file(path)
        for problem in problems:
            log_error(problem)
        if problems or loaded is None:
            return 1
        if base_opts.action == "dump":
            # The file is the output - for redirecting
            print(YamlValidation.dump_text(loaded.data), end="")
        else:
            log_info(f"{path}: OK")
        return 0

    # check_merged/dump_merged: the files the plot reads for this mission
    if base_opts.yml_file is not None:
        log_error(f"{base_opts.action} takes no file - it merges the ones the plot reads for --mission_dir")
        return 1
    if not base_opts.mission_dir:
        log_error(f"{base_opts.action} needs --mission_dir")
        return 1
    paths = config_files(base_opts)
    for path in paths:
        log_info(f"Reading {path}")
    result = load_merged(paths)
    for change in result.changes:
        log_info(change)
    for problem in result.problems:
        log_error(problem)
    if base_opts.action == "dump_merged":
        # The merged plots are the output - for redirecting
        print(YamlValidation.dump_text(result.plots), end="")
    else:
        log_info(f"Merged: {len(result.plots)} plot(s) - {', '.join(result.plots) or 'none'}")
    return 1 if result.problems else 0


if __name__ == "__main__":
    sys.exit(main())
