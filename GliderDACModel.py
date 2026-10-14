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

"""GliderDAC configuration templates: pydantic models, validated loading and a check CLI.

GliderDAC.py builds its output from three YAML templates - base (common to all
Seagliders), project and deployment - merged in that order. Each file carries
a subset of the same structure:

    global_attributes:  name -> value
    variables:          name -> {attributes, dimensions, type, num_digits,
                                 qc_data, qc_missing_data, nc_varname}
    config:             {timeseries_vars: per-dive name -> GliderDAC name}

The templates go from the most general to the most specific: a later file adds
to the earlier ones and overrides any value they set (a null removes the key).
Every problem is reported as file:line. A problem with a file's form, or a
missing _FillValue on platform/instrument_* fails the load: a GliderDAC file submitted with wrong metadata is worse than none. A
variable left incomplete after the merge (no type/dimensions/attributes) is an
error too, but only that variable is dropped.

Usage:
    GliderDACModel.py check FILE                          one template on its own
    GliderDACModel.py dump FILE > file.yml                one template, as loaded
    GliderDACModel.py check_merged --config sgNNN.conf    the templates the .conf names, merged
    GliderDACModel.py dump_merged --config sgNNN.conf > merged.yml

The merged actions read gliderdac_base_config, gliderdac_project_config and
gliderdac_deployment_config from the .conf's [gliderdac] section (or from the
command line options of the same names), as GliderDAC.py does.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Annotated, Any

import numpy as np
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
import QC
import YamlValidation
from BaseLog import BaseLogger, log_error, log_info, log_warning

Scalar = StrictStr | int | float | bool
AttrValue = Scalar | list[Scalar]

# The order the templates are merged in, and the .conf option naming each
TEMPLATE_OPTIONS = ("gliderdac_base_config", "gliderdac_project_config", "gliderdac_deployment_config")
# The option group the template options are listed under
OPTION_GROUP_HELP = "NetCDF file generation for submission to the Glider DAC"
_TEMPLATE_HELP = {
    "gliderdac_base_config": "GliderDAC base configuration YAML file - common for all Seagliders",
    "gliderdac_project_config": "GliderDAC project configuration YAML file - common for single study area",
    "gliderdac_deployment_config": "GliderDAC deployment configuration YAML file - specific to the current glider deployment",
}


def template_options(groups: set[str]) -> dict[str, BaseOptsType.options_t]:
    """The options naming the three templates, for GliderDAC.py and this module.

    Args:
        groups: The modules that use the options.

    Returns:
        Option name -> definition, in merge order.

    Raises:
        Nothing.
    """
    return {
        name: BaseOptsType.options_t(
            None,
            set(groups),
            (f"--{name}",),
            BaseOpts.FullPathlib,
            {
                "help": _TEMPLATE_HELP[name],
                "section": "gliderdac",
                "option_group": "gliderdac",
                "action": BaseOpts.FullPathlibAction,
            },
        )
        for name in TEMPLATE_OPTIONS
    }


def _dtype(value: str) -> str:
    """Checks a variable type is a numpy dtype code (f8, i4, b, c, ...).

    Args:
        value: The type.

    Returns:
        The type, unchanged.

    Raises:
        ValueError: numpy doesn't know it.
    """
    try:
        np.dtype(value)
    except TypeError as e:
        raise ValueError(f"not a numpy type code ({e})") from e
    return value


def _qc_name(value: str) -> str:
    """Checks a QC name (qc_data, qc_missing_data) is one QC.py defines.

    Args:
        value: The name, e.g. QC_GOOD.

    Returns:
        The name, unchanged.

    Raises:
        ValueError: An unknown name.
    """
    if value.strip() not in QC.qc_name_d.values():
        raise ValueError(f"unknown QC name - one of {', '.join(QC.qc_name_d.values())}")
    return value


class VariableSpec(BaseModel):
    """One variable's template entry. Every field is optional in a single file - a
    deployment file may only add attributes - and checked for completeness after the merge."""

    model_config = ConfigDict(extra="forbid")

    attributes: dict[StrictStr, AttrValue | None] | None = None
    dimensions: list[StrictStr] | None = None
    type: Annotated[StrictStr, AfterValidator(_dtype)] | None = None
    num_digits: Annotated[int, Field(ge=0)] | None = None
    qc_data: Annotated[StrictStr, AfterValidator(_qc_name)] | None = None
    qc_missing_data: Annotated[StrictStr, AfterValidator(_qc_name)] | None = None
    nc_varname: StrictStr | None = None


class TemplateConfig(BaseModel):
    """The template's processing options."""

    model_config = ConfigDict(extra="forbid")

    timeseries_vars: dict[StrictStr, StrictStr | None] | None = None


class TemplateFile(BaseModel):
    """One template file (base, project or deployment)."""

    model_config = ConfigDict(extra="forbid")

    global_attributes: dict[StrictStr, AttrValue | None] | None = None
    variables: dict[StrictStr, VariableSpec | None] | None = None
    config: TemplateConfig | None = None


class LoadedTemplate:
    """A template file that loaded and validated.

    Attributes:
        path: The file.
        data: Its contents (plain dicts/lists, as yaml.safe_load gives them).
        locate: Maps a key path to its source line (YamlValidation.load_yaml_with_lines).
    """

    def __init__(self, path: pathlib.Path, data: dict, locate: YamlValidation.Locator) -> None:
        """Args:
            path: The file.
            data: Its contents.
            locate: Its line locator.

        Returns:
            None

        Raises:
            Nothing.
        """
        self.path = path
        self.data = data
        self.locate = locate

    def where(self, loc: tuple) -> str:
        """file:line for a key path in this file.

        Args:
            loc: The key path.

        Returns:
            "file:line", or "file" if no line is known.

        Raises:
            Nothing.
        """
        line = self.locate(loc)
        return f"{self.path}:{line}" if line is not None else f"{self.path}"


def check_file(path: pathlib.Path) -> tuple[LoadedTemplate | None, list[str]]:
    """Loads and validates one template file on its own.

    Args:
        path: The file.

    Returns:
        (loaded, problems): loaded is None if there were problems. Each problem is
        "file:line: where: message".

    Raises:
        Nothing.
    """
    try:
        data, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        return None, [YamlValidation.format_yaml_error(path, e)]
    except OSError as e:
        return None, [f"{path}: could not read ({e})"]
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, [f"{path}: a GliderDAC template must be a mapping (got {type(data).__name__})"]
    try:
        TemplateFile.model_validate(data)
    except ValidationError as e:
        return None, YamlValidation.format_validation_errors(path, locate, e)
    return LoadedTemplate(path, data, locate), []


def suspect_attributes(template: LoadedTemplate) -> list[str]:
    """Attributes named like a variable field - most likely the field indented under attributes.

    Only an attribute whose value is also valid for the field it's named after counts
    (type: i2, not platform's type: platform). netCDF allows such names, so this is a
    warning, not a problem: valid in one file, but usually a mis-indented block (OSU sg686's
    dissolved_oxygen_n, 2026-10). If no later template supplies the real field the
    merge drops the variable; if one does, the stray attribute is written to the file.

    Args:
        template: A template that loaded.

    Returns:
        One warning per suspect attribute, "file:line: where: message".

    Raises:
        Nothing.
    """
    fields = set(VariableSpec.model_fields) - {"attributes"}
    warnings = []
    for name, spec in (template.data.get("variables") or {}).items():
        attributes = (spec or {}).get("attributes") or {}
        for key, value in attributes.items():
            if key not in fields:
                continue
            # platform/instrument_* carry a real "type" attribute (type: platform) - only
            # warn when the value would also be valid for the field it's named after
            try:
                VariableSpec.model_validate({key: value})
            except ValidationError:
                continue
            loc = ("variables", name, "attributes", key)
            warnings.append(f"{template.where(loc)}: {'.'.join(loc)}: looks like a variable field indented under attributes")
    return warnings


def _without_nulls(value: Any) -> Any:
    """A copy of a template value with null entries left out (null only means "remove").

    Args:
        value: A template value.

    Returns:
        The value, with any null mapping entries dropped, at every level.

    Raises:
        Nothing.
    """
    if isinstance(value, dict):
        return {k: _without_nulls(v) for k, v in value.items() if v is not None}
    return value


def merge_templates(loaded: list[LoadedTemplate]) -> tuple[dict, list[str]]:
    """Merges templates in order, from the most general to the most specific.

    Mappings merge key by key. Where a later file sets a value an earlier one set,
    the later value wins (a list counts as one value). A null removes the key - an
    attribute, a variable, a timeseries_vars entry.

    Args:
        loaded: The validated templates, base first.

    Returns:
        (merged, changes): changes describes each override and removal,
        "file:line: where: overrides file:line (old -> new)".

    Raises:
        Nothing.
    """
    merged: dict = {}
    origin: dict[tuple, LoadedTemplate] = {}
    changes: list[str] = []

    def note_origin(value: Any, path: tuple, src: LoadedTemplate) -> None:
        # Everything under a newly added key comes from src
        origin[path] = src
        if isinstance(value, dict):
            for key, sub in value.items():
                note_origin(sub, (*path, key), src)

    def merge(a: dict, b: dict, path: tuple, src: LoadedTemplate) -> None:
        for key, value in b.items():
            key_path = (*path, key)
            dotted = ".".join(str(k) for k in key_path)
            earlier = origin.get(key_path)
            was = f" {earlier.where(key_path)}" if earlier else ""
            if value is None:
                if key in a:
                    changes.append(f"{src.where(key_path)}: {dotted}: removes it (set at{was})")
                    del a[key]
                continue
            if key not in a:
                a[key] = _without_nulls(value)
                note_origin(a[key], key_path, src)
            elif isinstance(a[key], dict) and isinstance(value, dict):
                merge(a[key], value, key_path, src)
            elif a[key] != value:
                changes.append(f"{src.where(key_path)}: {dotted}: overrides{was} ({a[key]!r} -> {value!r})")
                a[key] = _without_nulls(value)
                note_origin(a[key], key_path, src)

    for template in loaded:
        merge(merged, template.data, (), template)
    return merged, changes


def check_merged_template(merged: dict, loaded: list[LoadedTemplate]) -> tuple[list[str], list[str]]:
    """Checks the merged template is complete enough for GliderDAC.py to use.

    A variable missing type/dimensions/attributes can't be written: it is removed
    from merged (by side effect) and reported, and the rest of the template is
    still usable - writing it later is skipped as for any undefined variable.
    Anything else wrong fails the whole load.

    Args:
        merged: The merged template - incomplete variables are removed from it.
        loaded: The templates it came from, for locations.

    Returns:
        (problems, dropped): problems fail the load; dropped describes each removed
        variable. Each is "file:line: where: message".

    Raises:
        Nothing.
    """

    def where(loc: tuple) -> str:
        # The last file that mentions loc - or failing that, its nearest parent
        for template in reversed(loaded):
            node: Any = template.data
            for key in loc:
                node = node.get(key) if isinstance(node, dict) else None
            if node is not None:
                return template.where(loc)
        return str(loaded[-1].path) if loaded else "(no templates)"

    problems: list[str] = []
    dropped: list[str] = []
    variables = merged.get("variables") or {}
    for name, spec in list(variables.items()):
        missing = [f for f in ("type", "dimensions", "attributes") if f not in spec]
        if missing:
            # e.g. "dimensions:"/"type:" indented under attributes (sg686's dissolved_oxygen_n)
            nested = [f for f in missing if f in (spec.get("attributes") or {})]
            hint = f" ({', '.join(nested)} found under attributes - mis-indented?)" if nested else ""
            dropped.append(
                f"{where(('variables', name))}: variables.{name}: no {', '.join(missing)} in any template{hint} - "
                "dropping this variable"
            )
            del variables[name]
            continue
        if name.endswith("_qc") and "type" in spec and not np.issubdtype(np.dtype(spec["type"]), np.integer):
            problems.append(
                f"{where(('variables', name, 'type'))}: variables.{name}.type: a QC variable must be an integer type"
            )
        if (name == "platform" or name.startswith("instrument_")) and "_FillValue" not in (
            spec.get("attributes") or {}
        ):
            problems.append(f"{where(('variables', name))}: variables.{name}.attributes: no _FillValue")
    # Not checked here: a timeseries_vars target with no variable block. That's a mapping
    # between the per-dive data and the templates, not the templates' form - GliderDAC.py
    # warns and skips that one variable when it writes the file (create_nc_var).
    return problems, dropped


class MergeResult:
    """What load_merged found.

    Attributes:
        template: The merged template, or None if a problem fails the load.
        problems: Problems that fail the load.
        dropped: Incomplete variables left out of template (errors, but the rest is used).
        changes: Overrides and removals by the more specific templates (not problems).
        warnings: Suspect attributes (see suspect_attributes) - not problems.
    """

    def __init__(self) -> None:
        """Returns:
            None

        Raises:
            Nothing.
        """
        self.template: dict | None = None
        self.problems: list[str] = []
        self.dropped: list[str] = []
        self.changes: list[str] = []
        self.warnings: list[str] = []


def load_merged(paths: list[pathlib.Path]) -> MergeResult:
    """Loads, validates and merges template files, as GliderDAC.py uses them.

    Args:
        paths: The template files, most general (base) first. Ones that don't exist
            are skipped by the caller.

    Returns:
        The merged template and what was found on the way.

    Raises:
        Nothing.
    """
    result = MergeResult()
    loaded = []
    for path in paths:
        template, file_problems = check_file(path)
        result.problems += file_problems
        if template is not None:
            loaded.append(template)
            result.warnings += suspect_attributes(template)
    if result.problems:
        return result
    merged, result.changes = merge_templates(loaded)
    result.problems, result.dropped = check_merged_template(merged, loaded)
    if not result.problems:
        result.template = merged
    return result


def templates_from_opts(base_opts: Any) -> list[pathlib.Path] | None:
    """The template files to merge, from the gliderdac_*_config options.

    As GliderDAC.py has always done: all three options must be set, and a file
    that doesn't exist is skipped.

    Args:
        base_opts: Options with gliderdac_base_config, gliderdac_project_config
            and gliderdac_deployment_config.

    Returns:
        The existing files in merge order, or None (logged) if an option isn't set.

    Raises:
        Nothing.
    """
    for name in TEMPLATE_OPTIONS:
        if not getattr(base_opts, name, None):
            log_error(f"{name} file not specified")
            return None
    files = []
    for name in TEMPLATE_OPTIONS:
        path = pathlib.Path(getattr(base_opts, name))
        if not path.exists():
            log_info(f"{path} does not exist - skipping")
            continue
        files.append(path)
    return files


class _TemplateDumper(yaml.SafeDumper):
    """Block style, as the templates are written, but a list of scalars on one line (flag_values: [0, 1, 2])."""


def _represent_list(dumper: yaml.SafeDumper, data: list) -> yaml.Node:
    """Represents a list in flow style if it holds only scalars, else in block style.

    Args:
        dumper: The dumper.
        data: The list.

    Returns:
        The YAML node.

    Raises:
        Nothing.
    """
    flow = all(not isinstance(item, (dict, list)) for item in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_TemplateDumper.add_representer(list, _represent_list)


def _dump(data: dict) -> None:
    """Writes a template as YAML to stdout - the output of the dump actions, for redirecting.

    Args:
        data: The template.

    Returns:
        None

    Raises:
        Nothing.
    """
    text = yaml.dump(data, Dumper=_TemplateDumper, sort_keys=False, default_flow_style=False, width=float("inf"))
    print(text, end="")


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Checks or dumps GliderDAC template files.

    Args:
        cmdline_args: Command line arguments.

    Returns:
        0 if everything checked is valid, 1 if not (or the arguments are wrong).

    Raises:
        Nothing expected.
    """
    base_opts = BaseOpts.BaseOptions(
        "Check GliderDAC configuration templates",
        cmdline_args=cmdline_args,
        calling_module="GliderDACModel",
        additional_arguments={
            "action": BaseOptsType.options_t(
                None,
                {"GliderDACModel"},
                ("action",),
                str,
                {
                    "help": "check FILE | dump FILE | check_merged --config CONF | dump_merged --config CONF",
                    "choices": ("check", "dump", "check_merged", "dump_merged"),
                },
            ),
            "template": BaseOptsType.options_t(
                None,
                {"GliderDACModel"},
                ("template",),
                pathlib.Path,
                {"help": "The template file (check and dump only)", "nargs": "?"},
            ),
            **template_options({"GliderDACModel"}),
        },
        add_option_groups={"gliderdac": OPTION_GROUP_HELP},
    )
    BaseLogger(base_opts)

    if base_opts.action in ("check", "dump"):
        if base_opts.template is None:
            log_error(f"{base_opts.action} needs a template file")
            return 1
        path = pathlib.Path(base_opts.template).expanduser()
        loaded, problems = check_file(path)
        for problem in problems:
            log_error(problem)
        if problems or loaded is None:
            return 1
        for warning in suspect_attributes(loaded):
            log_warning(warning)
        if base_opts.action == "dump":
            _dump(loaded.data)
        else:
            log_info(f"{path}: OK")
        return 0

    # check_merged/dump_merged: the templates a mission .conf names
    if base_opts.template is not None:
        log_error(f"{base_opts.action} takes no template file - it merges the ones --config names")
        return 1
    if base_opts.config_file_name is None:
        log_error(f"{base_opts.action} needs --config (a mission .conf naming the gliderdac_*_config templates)")
        return 1
    if getattr(base_opts, "config_file_not_found", False):
        log_error(f"{base_opts.config_file_name} does not exist")
        return 1
    templates = templates_from_opts(base_opts)
    if templates is None:
        return 1
    # GliderDAC.py skips a missing template quietly; here it is what's being checked
    for name in TEMPLATE_OPTIONS:
        path = pathlib.Path(getattr(base_opts, name))
        if path not in templates:
            log_warning(f"{name} {path} does not exist - not checked")
    if not templates:
        log_error(f"None of the templates {base_opts.config_file_name} names exist - nothing to check")
        return 1
    result = load_merged(templates)
    for change in result.changes:
        log_info(change)
    for warning in result.warnings:
        log_warning(warning)
    for problem in result.problems + result.dropped:
        log_error(problem)
    merged = result.template
    if merged is None or result.dropped:
        return 1
    if base_opts.action == "dump_merged":
        _dump(merged)
    else:
        n_vars = len(merged.get("variables") or {})
        n_attrs = len(merged.get("global_attributes") or {})
        n_ts = len((merged.get("config") or {}).get("timeseries_vars") or {})
        log_info(f"Merged OK: {n_attrs} global attributes, {n_vars} variables, {n_ts} timeseries_vars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
