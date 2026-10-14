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

"""Loading user-supplied yaml files with source line numbers for validation errors.

Shared by the pydantic validators for basestation's yaml inputs (pagers.yml first).
A pydantic error's ``loc`` is a path of keys and indices into the loaded data; this
module maps that path back to the line in the yaml source so an operator can find it.
"""

import pathlib
from collections.abc import Callable
from typing import Any

import yaml
from pydantic import ValidationError

Path_t = tuple[str | int, ...]
Locator = Callable[[Path_t], int | None]


def _line_map(node: yaml.Node | None, path: Path_t = (), lines: dict[Path_t, int] | None = None) -> dict[Path_t, int]:
    """Walks a composed yaml node tree, recording the 1-based line of every key and item.

    Args:
        node: Root (or current) node from yaml.compose.
        path: Key/index path to node.
        lines: Accumulated map, created on the first call.

    Returns:
        Map from key/index path to source line.
    """
    if lines is None:
        lines = {}
    if node is None:
        return lines
    if not path:
        lines[path] = node.start_mark.line + 1
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            key_path = (*path, key_node.value)
            lines[key_path] = key_node.start_mark.line + 1
            _line_map(value_node, key_path, lines)
    elif isinstance(node, yaml.SequenceNode):
        for i, item in enumerate(node.value):
            item_path = (*path, i)
            lines[item_path] = item.start_mark.line + 1
            _line_map(item, item_path, lines)
    return lines


def load_yaml_with_lines(path: pathlib.Path) -> tuple[object, Locator]:
    """Loads a yaml file and returns a way to find the source line of any part of it.

    Args:
        path: The yaml file.

    Returns:
        (data, locate): the loaded data (yaml.safe_load), and a function that maps a
        key/index path - e.g. a pydantic error's loc - to the line of its longest
        prefix found in the source, or None.

    Raises:
        OSError: The file can't be read.
        yaml.YAMLError: The file isn't valid yaml (see format_yaml_error).
    """
    text = path.read_text()
    data = yaml.safe_load(text)
    lines = _line_map(yaml.compose(text))

    def locate(loc: Path_t) -> int | None:
        for n in range(len(loc), -1, -1):
            line = lines.get(tuple(loc[:n]))
            if line is not None:
                return line
        return None

    return data, locate


def format_yaml_error(path: pathlib.Path, err: yaml.YAMLError) -> str:
    """Describes a yaml syntax error as "file:line: problem".

    Args:
        path: The yaml file.
        err: The error from loading it.

    Returns:
        One line naming the file, the line (when yaml reports one) and the problem.

    Raises:
        None.
    """
    mark = getattr(err, "problem_mark", None)
    where = f"{path}:{mark.line + 1}" if mark is not None else f"{path}"
    problem = getattr(err, "problem", None) or str(err).splitlines()[0]
    return f"{where}: {problem}"


def format_validation_errors(
    path: pathlib.Path,
    locate: Locator,
    err: ValidationError,
    prefix: Path_t = (),
    redact: Callable[[Path_t, object], object] | None = None,
) -> list[str]:
    """Describes each pydantic validation error as "file:line: where: message".

    Args:
        path: The yaml file the data came from.
        locate: From load_yaml_with_lines for that file.
        err: The validation error.
        prefix: Path of the validated object within the file (when a part of the file
            was validated on its own, e.g. one user of pagers.yml).
        redact: Called with each error's location and input before the input is
            shown, so secrets (webhook tokens, passwords) never reach a log.

    Returns:
        One string per error.

    Raises:
        None.
    """
    messages = []
    for error in err.errors():
        loc = (*prefix, *error["loc"])
        line = locate(loc)
        where = f"{path}:{line}" if line is not None else f"{path}"
        dotted = ".".join(str(x) for x in loc) or "(top level)"
        shown = redact(loc, error["input"]) if redact else error["input"]
        messages.append(f"{where}: {dotted}: {error['msg']} (input: {shown!r})")
    return messages


class LoadedYaml:
    """A yaml file that loaded and validated, with its line locator.

    Attributes:
        path: The file.
        data: Its contents (plain dicts/lists, as yaml.safe_load gives them).
        locate: Maps a key path to its source line (load_yaml_with_lines).
    """

    def __init__(self, path: pathlib.Path, data: dict, locate: Locator) -> None:
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


def _without_nulls(value: Any) -> Any:
    """A copy of a value with null entries left out (null only means "remove").

    Args:
        value: A loaded yaml value.

    Returns:
        The value, with any null mapping entries dropped, at every level.

    Raises:
        Nothing.
    """
    if isinstance(value, dict):
        return {k: _without_nulls(v) for k, v in value.items() if v is not None}
    return value


def merge_loaded(loaded: list[LoadedYaml]) -> tuple[dict, list[str]]:
    """Merges loaded yaml files in order, from the most general to the most specific.

    Mappings merge key by key. Where a later file sets a value an earlier one set,
    the later value wins (a list counts as one value). A null removes the key.

    Args:
        loaded: The validated files, most general first.

    Returns:
        (merged, changes): changes describes each override and removal,
        "file:line: where: overrides file:line (old -> new)".

    Raises:
        Nothing.
    """
    merged: dict = {}
    origin: dict[tuple, LoadedYaml] = {}
    changes: list[str] = []

    def note_origin(value: Any, path: tuple, src: LoadedYaml) -> None:
        # Everything under a newly added key comes from src
        origin[path] = src
        if isinstance(value, dict):
            for key, sub in value.items():
                note_origin(sub, (*path, key), src)

    def merge(a: dict, b: dict, path: tuple, src: LoadedYaml) -> None:
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


class _BlockDumper(yaml.SafeDumper):
    """Block style, as the yaml inputs are written, but a list of scalars on one line (flag_values: [0, 1, 2])."""


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


_BlockDumper.add_representer(list, _represent_list)


def dump_text(data: dict) -> str:
    """A loaded/merged yaml input as block-style text, lists of scalars on one line.

    Args:
        data: The data.

    Returns:
        The YAML text.

    Raises:
        Nothing.
    """
    return yaml.dump(data, Dumper=_BlockDumper, sort_keys=False, default_flow_style=False, width=float("inf"))
