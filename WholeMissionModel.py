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

"""The whole-mission config (--whole_mission_config): a permissive checker and its CLI.

The file changes what goes into the whole-mission netCDF files (MakeMissionProfile,
MakeMissionTimeSeries, BaseParquet; see docs/whole_mission.yml). Two optional
sections, `profile` and `timeseries`, each map a netCDF variable name to True
(include it), False (leave it out) or a netCDF type code (include it as that type).

It's read in the processing pipeline, so a problem never stops processing: the
entry (or section) is warned about at file:line and left out, and the rest is used.
A file that can't be read or isn't a mapping is an error, and none of it is used.

Usage:
    WholeMissionModel.py check FILE --mission_dir DIR
        check FILE; variable names are checked against the basestation's variables plus
        those the sensor and basestation extensions add (DIR's .extensions included)
    WholeMissionModel.py dump FILE --mission_dir DIR
        the settings that would be used, after the check
"""

from __future__ import annotations

import sys
from collections.abc import Collection
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import AfterValidator, StrictBool, StrictStr, TypeAdapter, ValidationError

import BaseDotFiles
import BaseNetCDF
import BaseOpts
import BaseOptsType
import Sensors
import Utils
import YamlValidation
from BaseLog import BaseLogger, log_error, log_info, log_warning

CONFIG_NAME = "whole-mission config"

# The alert tag for the pipeline's messages (Utils.whole_mission_cfg; html/AlertsReferenceManual.html)
ALERT = "WHOLE_MISSION_CONFIG"

# The CLI's options are parsed as this module's (see main)
CLI_AS = "MakeMissionTimeSeries"

# The sections, in the order Utils.whole_mission_cfg returns them
SECTIONS = ("profile", "timeseries")

Setting = str | bool


def _nc_type(value: str) -> str:
    """A netCDF type code a whole-mission variable can be written as.

    Args:
        value: The code.

    Returns:
        The code.

    Raises:
        ValueError: It isn't one of Utils.netcdf4_datatypes_nonchar.
    """
    if value not in Utils.netcdf4_datatypes_nonchar:
        raise ValueError(value)
    return value


# True, False, or a (non-char) netCDF type code
_SETTING = TypeAdapter(StrictBool | Annotated[StrictStr, AfterValidator(_nc_type)])


def check_file(
    path: Path, known: Collection[str]
) -> tuple[dict[str, dict[str, Setting]] | None, list[str], list[str]]:
    """Checks a whole-mission config.

    Args:
        path: The file.
        known: The netCDF variable names that may be set (BaseNetCDF.nc_var_metadata, once the
            sensor extensions are loaded).

    Returns:
        (settings, warnings, problems): settings is section -> variable -> setting for every section
        (empty where the file has none), with every entry warned about left out; None if the file
        can't be used at all (then problems says why). Each message is "file:line: where: message".
    """
    try:
        data, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        return None, [], [YamlValidation.format_yaml_error(path, e)]
    except OSError as e:
        return None, [], [f"{path}: could not read ({e})"]
    settings: dict[str, dict[str, Setting]] = {section: {} for section in SECTIONS}
    if data is None:
        return settings, [f"{path}: empty - no whole-mission changes"], []
    if not isinstance(data, dict):
        return (
            None,
            [],
            [
                f"{path}: a {CONFIG_NAME} must be a mapping (profile:, timeseries:), not {type(data).__name__}"
            ],
        )
    loaded = YamlValidation.LoadedYaml(path, data, locate)
    warnings: list[str] = []

    def warn(loc: tuple, message: str) -> None:
        dotted = ".".join(str(k) for k in loc)
        warnings.append(
            f"{loaded.where(tuple(str(k) for k in loc))}: {dotted}: {message}"
        )

    for key in data:
        if key not in SECTIONS:
            warn((key,), f"not a section ({', '.join(SECTIONS)}) - ignored")
    nc_types = ", ".join(Utils.netcdf4_datatypes_nonchar)
    for section in SECTIONS:
        if section not in data:
            continue
        entries = data[section]
        if not isinstance(entries, dict):
            warn(
                (section,),
                f"should be a mapping of variable: setting, not {type(entries).__name__} - ignored",
            )
            continue
        for name, value in entries.items():
            if not isinstance(name, str):
                warn(
                    (section, name),
                    f"a variable name should be text, not {type(name).__name__} - skipped",
                )
                continue
            if name not in known:
                warn((section, name), "not a known variable - skipped")
                continue
            try:
                settings[section][name] = _SETTING.validate_python(value)
            except ValidationError:
                warn(
                    (section, name),
                    f"{value!r} should be True, False or a netCDF type ({nc_types}) - skipped",
                )
    return settings, warnings, []


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Checks or dumps a whole-mission config.

    Args:
        cmdline_args: Command line arguments.

    Returns:
        0 if there are no warnings or problems, 1 otherwise.
    """
    # Parsed as MakeMissionTimeSeries, where the config is used: the extensions' own options
    # (which name the modules they apply to) are then there for their init_extension calls,
    # and --mission_dir is required, as the extensions need it
    base_opts = BaseOpts.BaseOptions(
        f"Check a {CONFIG_NAME} (--whole_mission_config)",
        cmdline_args=cmdline_args,
        calling_module=CLI_AS,
        additional_arguments={
            "action": BaseOptsType.options_t(
                None,
                {CLI_AS},
                ("action",),
                str,
                {"help": "check FILE | dump FILE", "choices": ("check", "dump")},
            ),
            "config_file": BaseOptsType.options_t(
                None,
                {CLI_AS},
                ("config_file",),
                Path,
                {"help": f"The {CONFIG_NAME} file"},
            ),
        },
    )
    BaseLogger(base_opts)
    # The variables the config may name, set up as MakeMissionTimeSeries does: the sensor and
    # basestation extensions add theirs to BaseNetCDF.nc_var_metadata
    init_dict, init_ret_val = Sensors.init_extensions(base_opts)
    if init_ret_val > 0 or init_dict is None:
        log_error("Sensor initialization failed - can't tell which variables are known")
        return 1
    BaseDotFiles.process_extensions(("init_extension",), base_opts, init_dict=init_dict)
    BaseNetCDF.init_tables(init_dict)
    path = Path(base_opts.config_file).expanduser()
    settings, warnings, problems = check_file(path, BaseNetCDF.nc_var_metadata)
    for warning in warnings:
        log_warning(warning)
    for problem in problems:
        log_error(problem)
    if base_opts.action == "dump":
        if settings is None:
            return 1
        # The settings are the output - for redirecting
        print(YamlValidation.dump_text(settings), end="")
        return 0
    if not (warnings or problems):
        log_info(f"{path}: OK")
    return 1 if (warnings or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
