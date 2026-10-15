#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2026  University of Washington.
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

"""sections.yml: checks (warn and proceed), the shared value lookup, and a check CLI.

A mission's sections.yml drives the mission-profile section plots
(Plotting/MissionProfiles.py; tools/SectionTimes.py reads its sections). It has
three levels, each mapping names to the same set of keys (ENTRY_KEYS):

    defaults:            used when neither level below sets a key
    variables:           per variable (one section plot per variable and section)
        <variable>: {...}
    sections:            per section (a range of dives)
        "<name>": {...}

A key is looked up in the section, then the variable, then defaults, then the
plot's own fallback (get_value). Top-level keys owned by an extension
(EXTENSION_KEYS - adcp's adcp_variables) are left to it; the adcp extension
checks its entries with check_entries.

The check is permissive: a bad key or value is reported at file:line and
ignored - the next level, or the fallback, applies - and the plots are still
drawn. Only a file that can't be used (not yaml, not a mapping, no variables or
no sections) stops them.

To add a key: one line in ENTRY_KEYS.

Usage:
    SectionsModel.py check FILE        report every problem (exit 1 if any)
    SectionsModel.py dump FILE         the file as the plots use it (bad keys/values left out)
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Annotated, Any

import yaml
from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    create_model,
)

import BaseOpts
import BaseOptsType
import YamlValidation
from BaseLog import BaseLogger, log_error, log_info, log_warning

CONFIG_NAME = "sections.yml"

# A strict float accepts ints too (not strings or bools) - one error, "a valid number"; only the
# check uses the model, the file's own values are kept
Number = StrictFloat
NonNegative = Annotated[Number, Field(ge=0)]

# Every key a defaults, variables or sections entry may set: name -> (type, description).
# Add a key here and it is accepted (and checked) at every level, and in adcp_variables.
ENTRY_KEYS: dict[str, tuple[Any, str]] = {
    "start": (StrictInt, "first dive of the section"),
    "stop": (StrictInt, "last dive of the section (-1: the latest)"),
    "step": (Annotated[StrictInt, Field(ge=1)], "every Nth dive"),
    "top": (NonNegative, "shallowest depth plotted (m)"),
    "bottom": (NonNegative, "deepest depth plotted (m)"),
    "bin": (Annotated[Number, Field(gt=0)], "depth bin size (m)"),
    "flip": (StrictBool, "plot dives right to left"),
    "which": (Annotated[StrictInt, Field(ge=1, le=4)], "1 dive only, 2 climb only, 3 both as separate profiles, 4 dive and climb averaged"),
    "colormap": (StrictStr, "cmocean colormap name (see COLORMAPS)"),
    "min": (Number, "colorbar minimum"),
    "max": (Number, "colorbar maximum"),
    "units": (StrictStr, "units shown in the hover text"),
    "fill": (StrictBool, "connect gaps (interpolate)"),
    "decimals": (Annotated[StrictInt, Field(ge=0)], "round values to this many decimal places"),
    "title": (StrictStr, "plot title (default: the variable name)"),
}

# The cmocean colormaps the plots know; any other name is drawn with thermal
COLORMAPS = (
    "thermal", "haline", "solar", "ice", "gray", "oxy", "deep", "dense", "algae",
    "matter", "turbid", "speed", "amp", "tempo", "phase", "balance", "delta", "curl",
)  # fmt: skip

# Top-level keys owned by an extension, which checks them itself - not checked or warned about here
EXTENSION_KEYS = {"adcp_variables": "adcp"}

LEVEL_KEYS = ("defaults", "variables", "sections")

SectionValues = create_model(
    "SectionValues",
    __config__=ConfigDict(extra="forbid"),
    **{name: (kind | None, None) for name, (kind, _) in ENTRY_KEYS.items()},
)

# "max 27.5:" - a key and its value with the colon missing (yaml reads one key with no value)
_MISSING_COLON = re.compile(r"^(?P<key>\w+)\s+(?P<value>\S.*)$")


def _check_entry(
    loaded: YamlValidation.LoadedYaml, loc: tuple, entry: Any
) -> tuple[dict | None, list[str]]:
    """Checks one entry (defaults, or one variable or section), keeping what's good.

    Args:
        loaded: The file.
        loc: The entry's key path, e.g. ("variables", "temperature").
        entry: The entry as loaded.

    Returns:
        (kept, warnings): kept is the entry without the bad keys/values, or None if
        it isn't a mapping at all.

    Raises:
        Nothing.
    """
    dotted = ".".join(str(k) for k in loc)
    if entry is None:
        return {}, []
    if not isinstance(entry, dict):
        return None, [f"{loaded.where(loc)}: {dotted}: should be a mapping of keys to values, not "
                      f"{type(entry).__name__} - ignored"]  # fmt: skip
    warnings: list[str] = []
    bad: set = set()
    try:
        SectionValues.model_validate(entry)
    except ValidationError as e:
        for message, error in zip(
            YamlValidation.format_validation_errors(loaded.path, loaded.locate, e, prefix=loc), e.errors(), strict=True
        ):
            key = error["loc"][0] if error["loc"] else None
            bad.add(key)
            hint = ""
            if error["type"] == "extra_forbidden" and isinstance(key, str):
                match = _MISSING_COLON.match(key)
                if match and match["key"] in ENTRY_KEYS:
                    hint = f" - did you mean '{match['key']}: {match['value']}'?"
            warnings.append(f"{message} - ignored{hint}")
    kept = {k: v for k, v in entry.items() if k not in bad}
    colormap = kept.get("colormap")
    if colormap is not None and colormap not in COLORMAPS:
        warnings.append(
            f"{loaded.where((*loc, 'colormap'))}: {dotted}.colormap: {colormap!r} isn't one of the known "
            f"colormaps ({', '.join(COLORMAPS)}) - thermal is used"
        )
    return kept, warnings


def check_entries(loaded: YamlValidation.LoadedYaml, top_key: str) -> tuple[dict, list[str]]:
    """Checks every entry under a top-level key (variables, sections, or an extension's own key).

    Args:
        loaded: The file.
        top_key: The top-level key, e.g. "variables" or "adcp_variables".

    Returns:
        (cleaned, warnings): cleaned maps each usable entry's name to the entry
        without its bad keys/values.

    Raises:
        Nothing.
    """
    entries = loaded.data.get(top_key)
    if entries is None:
        return {}, []
    if not isinstance(entries, dict):
        return {}, [f"{loaded.where((top_key,))}: {top_key}: should be a mapping of names to entries - ignored"]
    cleaned: dict = {}
    warnings: list[str] = []
    for name, entry in entries.items():
        if not isinstance(name, str):
            warnings.append(
                f"{loaded.where((top_key, str(name)))}: {top_key}.{name}: the name should be quoted "
                f"(\"{name}\") - yaml reads it as {type(name).__name__} {name!r}"
            )
        kept, entry_warnings = _check_entry(loaded, (top_key, name), entry)
        warnings += entry_warnings
        if kept is not None:
            cleaned[name] = kept
    return cleaned, warnings


def get_value(
    sections_d: dict, key: str, section: Any, variable: Any, fallback: Any, variables_key: str = "variables"
) -> Any:
    """A key's value for one section plot: the section's, else the variable's, else the default, else fallback.

    Args:
        sections_d: The checked file (check_file's cleaned result).
        key: The key, e.g. "colormap".
        section: The section name.
        variable: The variable name.
        fallback: The value when no level sets the key.
        variables_key: Where the variables are ("adcp_variables" for the adcp plots).

    Returns:
        The value.

    Raises:
        Nothing.
    """
    for level in (
        (sections_d.get("sections") or {}).get(section) or {},
        (sections_d.get(variables_key) or {}).get(variable) or {},
        sections_d.get("defaults") or {},
    ):
        if key in level:
            return level[key]
    return fallback


def check_ranges(loaded: YamlValidation.LoadedYaml, cleaned: dict, variables_key: str = "variables") -> list[str]:
    """Warns where a section plot's min ends up above its max.

    Args:
        loaded: The file, for locations.
        cleaned: The checked file.
        variables_key: Where the variables are.

    Returns:
        One warning per variable and section with min > max.

    Raises:
        Nothing.
    """
    warnings = []
    for variable in cleaned.get(variables_key) or {}:
        for section in cleaned.get("sections") or {}:
            zmin = get_value(cleaned, "min", section, variable, None, variables_key)
            zmax = get_value(cleaned, "max", section, variable, None, variables_key)
            if zmin is not None and zmax is not None and zmin > zmax:
                warnings.append(
                    f"{loaded.where((variables_key, variable))}: {variables_key}.{variable} in section {section}: "
                    f"min ({zmin}) is above max ({zmax})"
                )
    return warnings


def check_file(path: pathlib.Path) -> tuple[dict | None, list[str], list[str]]:
    """Loads and checks a sections.yml.

    Args:
        path: The file.

    Returns:
        (cleaned, warnings, problems): cleaned is the file as the plots should use
        it - defaults/variables/sections with the bad keys and values left out
        (defaults always present), extension keys as written - or None if the file
        can't be used (then problems says why). Each message is "file:line: where: message".

    Raises:
        Nothing.
    """
    try:
        data, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        return None, [], [YamlValidation.format_yaml_error(path, e)]
    except OSError as e:
        return None, [], [f"{path}: could not read ({e})"]
    if not isinstance(data, dict):
        return None, [], [f"{path}: {CONFIG_NAME} must be a mapping with variables and sections (got {type(data).__name__})"]
    loaded = YamlValidation.LoadedYaml(path, data, locate)
    warnings: list[str] = []
    for key in data:
        if key not in LEVEL_KEYS and key not in EXTENSION_KEYS:
            known = ", ".join((*LEVEL_KEYS, *EXTENSION_KEYS))
            warnings.append(f"{loaded.where((str(key),))}: {key}: not a {CONFIG_NAME} key ({known}) - ignored")
    defaults, defaults_warnings = _check_entry(loaded, ("defaults",), data.get("defaults"))
    warnings += defaults_warnings
    cleaned: dict = {"defaults": defaults or {}}
    for level in ("variables", "sections"):
        cleaned[level], level_warnings = check_entries(loaded, level)
        warnings += level_warnings
    for key in EXTENSION_KEYS:
        if key in data:
            cleaned[key] = data[key]
    problems = [
        f"{path}: no {level} - nothing to plot" for level in ("variables", "sections") if not cleaned[level]
    ]
    if problems:
        return None, warnings, problems
    warnings += check_ranges(loaded, cleaned)
    return cleaned, warnings, []


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Checks or dumps a sections.yml.

    Args:
        cmdline_args: Command line arguments.

    Returns:
        0 if the file has no problems or warnings, 1 otherwise.

    Raises:
        Nothing expected.
    """
    base_opts = BaseOpts.BaseOptions(
        "Check a sections.yml (keys: " + ", ".join(ENTRY_KEYS) + ")",
        cmdline_args=cmdline_args,
        calling_module="SectionsModel",
        additional_arguments={
            "action": BaseOptsType.options_t(
                None,
                {"SectionsModel"},
                ("action",),
                str,
                {"help": "check FILE | dump FILE", "choices": ("check", "dump")},
            ),
            "yml_file": BaseOptsType.options_t(
                None,
                {"SectionsModel"},
                ("yml_file",),
                pathlib.Path,
                {"help": f"The {CONFIG_NAME} file"},
            ),
        },
    )
    BaseLogger(base_opts)
    path = pathlib.Path(base_opts.yml_file).expanduser()
    cleaned, warnings, problems = check_file(path)
    for warning in warnings:
        log_warning(warning)
    for problem in problems:
        log_error(problem)
    if cleaned is None:
        return 1
    if base_opts.action == "dump":
        # The checked file is the output - for redirecting
        print(YamlValidation.dump_text(cleaned), end="")
    elif not warnings:
        log_info(f"{path}: OK - {len(cleaned['variables'])} variable(s), {len(cleaned['sections'])} section(s)")
    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
