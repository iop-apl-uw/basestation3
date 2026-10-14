#! /usr/bin/env python
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

"""NODC.yml: validated loading and merging of the netCDF global attribute overrides, and a check CLI.

BaseNetCDF.update_globals_from_nodc sets a dive's netCDF global attributes from
(in this order, each optional):

    <basestation_etc>/NODC.yml   the site
    <group_etc>/NODC.yml         a group of gliders (--group_etc)
    <mission_dir>/NODC.yml       one glider

Each file maps a global attribute name to its value (a string, or a number).
A later file overrides an earlier one, and a null removes an override so the
earlier value - or basestation's default - stands. Keys are checked against
BaseNetCDF.nc_global_variables:
    - the attributes meant to be set here (title, summary, institution, creator_*,
      license, keywords, ...) are fine;
    - an attribute basestation sets itself (featureType, nodc_template_version, ...)
      is an error and is ignored - it would replace the computed value;
    - any other name is written as given, with a warning.
Every problem is reported as file:line. A bad key is dropped (the rest of the
file still applies); a file that isn't valid yaml, or isn't a mapping, is skipped.

Usage:
    NODCModel.py check FILE                       one file on its own
    NODCModel.py dump FILE > file.yml             one file, as loaded
    NODCModel.py check_merged -m MISSION_DIR      the files a dive's netCDF reads, merged
    NODCModel.py dump_merged -m MISSION_DIR > merged.yml

The merged actions also use --basestation_etc and --group_etc (on the command line or from --config).
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import yaml

import BaseOpts
import BaseOptsType
import YamlValidation
from BaseLog import BaseLogger, log_error, log_info, log_warning

CONFIG_NAME = "NODC.yml"


def _global_kinds() -> tuple[set[str], set[str]]:
    """The global attributes NODC.yml may set, and the ones basestation sets itself.

    Read from BaseNetCDF.nc_global_variables when needed (BaseNetCDF imports this module).

    Args:
        None

    Returns:
        (overridable, computed) attribute names.

    Raises:
        Nothing.
    """
    import BaseNetCDF  # noqa: PLC0415 - BaseNetCDF imports this module

    overridable = {name for name, (cnf_override, _, _) in BaseNetCDF.nc_global_variables.items() if cnf_override}
    return overridable, set(BaseNetCDF.nc_global_variables) - overridable


def check_file(path: pathlib.Path) -> tuple[YamlValidation.LoadedYaml | None, list[str], list[str], set[str]]:
    """Loads and checks one NODC.yml on its own.

    Args:
        path: The file.

    Returns:
        (loaded, problems, warnings, bad_keys): loaded is None if the file can't be
        used at all (not yaml, or not a mapping); otherwise it holds the whole file
        and bad_keys names the keys to drop. Each problem and warning is
        "file:line: key: message".

    Raises:
        Nothing.
    """
    try:
        data, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        return None, [YamlValidation.format_yaml_error(path, e)], [], set()
    except OSError as e:
        return None, [f"{path}: could not read ({e})"], [], set()
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, [f"{path}: {CONFIG_NAME} must map attribute names to values (got {type(data).__name__})"], [], set()
    loaded = YamlValidation.LoadedYaml(path, data, locate)
    overridable, computed = _global_kinds()
    problems: list[str] = []
    warnings: list[str] = []
    bad: set[str] = set()
    for key, value in data.items():
        where = loaded.where((str(key),))  # the line map holds the key as written
        if not isinstance(key, str):
            problems.append(f"{where}: attribute name {key!r} must be a string - ignored")
            bad.add(str(key))
            continue
        if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
            problems.append(
                f"{where}: {key}: must be a string or a number, not {type(value).__name__} (input: {value!r}) - ignored"
            )
            bad.add(key)
            continue
        if key in computed:
            problems.append(f"{where}: {key}: set by basestation - can't be overridden in {CONFIG_NAME} - ignored")
            bad.add(key)
        elif key not in overridable:
            warnings.append(f"{where}: {key}: not a known netCDF global attribute - written as given")
    return loaded, problems, warnings, bad


class NodcResult:
    """What load_merged found.

    Attributes:
        values: Attribute name -> value, after the merge (nulls removed).
        problems: Each problem, "file:line: key: message" - each costs a key or a file.
        warnings: Unknown attribute names, still written.
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
        self.values: dict[str, Any] = {}
        self.problems: list[str] = []
        self.warnings: list[str] = []
        self.changes: list[str] = []


def load_merged(paths: list[pathlib.Path]) -> NodcResult:
    """Checks and merges NODC.yml files, most general first.

    Args:
        paths: The files, most general (site) first.

    Returns:
        The merged values, problems, warnings and changes.

    Raises:
        Nothing.
    """
    result = NodcResult()
    kept: list[YamlValidation.LoadedYaml] = []
    for path in paths:
        loaded, problems, warnings, bad = check_file(path)
        result.problems += problems
        result.warnings += warnings
        if loaded is not None:
            kept.append(
                YamlValidation.LoadedYaml(loaded.path, {k: v for k, v in loaded.data.items() if str(k) not in bad}, loaded.locate)
            )
    result.values, result.changes = YamlValidation.merge_loaded(kept)
    return result


def config_files(base_opts: Any) -> list[pathlib.Path]:
    """The NODC.yml files a dive's netCDF globals come from, most general first.

    Args:
        base_opts: Options with basestation_etc, group_etc and mission_dir.

    Returns:
        The files that exist, in merge order.

    Raises:
        Nothing.
    """
    dirs = [
        getattr(base_opts, "basestation_etc", None),
        getattr(base_opts, "group_etc", None),
        getattr(base_opts, "mission_dir", None),
    ]
    return [pathlib.Path(d) / CONFIG_NAME for d in dirs if d and (pathlib.Path(d) / CONFIG_NAME).exists()]


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Checks or dumps NODC.yml files.

    Args:
        cmdline_args: Command line arguments.

    Returns:
        0 if everything checked is valid, 1 if not (or the arguments are wrong).

    Raises:
        Nothing expected.
    """
    base_opts = BaseOpts.BaseOptions(
        "Check NODC.yml files",
        cmdline_args=cmdline_args,
        calling_module="NODCModel",
        add_to_arguments=["mission_dir"],
        additional_arguments={
            "action": BaseOptsType.options_t(
                None,
                {"NODCModel"},
                ("action",),
                str,
                {
                    "help": "check FILE | dump FILE | check_merged -m MISSION_DIR | dump_merged -m MISSION_DIR",
                    "choices": ("check", "dump", "check_merged", "dump_merged"),
                },
            ),
            "yml_file": BaseOptsType.options_t(
                None,
                {"NODCModel"},
                ("yml_file",),
                pathlib.Path,
                {"help": "The NODC.yml file (check and dump only)", "nargs": "?"},
            ),
        },
    )
    BaseLogger(base_opts)

    if base_opts.action in ("check", "dump"):
        if base_opts.yml_file is None:
            log_error(f"{base_opts.action} needs a {CONFIG_NAME} file")
            return 1
        path = pathlib.Path(base_opts.yml_file).expanduser()
        loaded, problems, warnings, _ = check_file(path)
        for warning in warnings:
            log_warning(warning)
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

    # check_merged/dump_merged: the files a dive's netCDF globals come from
    if base_opts.yml_file is not None:
        log_error(f"{base_opts.action} takes no file - it merges the ones a dive reads for --mission_dir")
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
    for warning in result.warnings:
        log_warning(warning)
    for problem in result.problems:
        log_error(problem)
    if base_opts.action == "dump_merged":
        # The merged values are the output - for redirecting
        print(YamlValidation.dump_text(result.values), end="")
    else:
        log_info(f"Merged: {len(result.values)} attribute(s) - {', '.join(result.values) or 'none'}")
    return 1 if result.problems else 0


if __name__ == "__main__":
    sys.exit(main())
