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

"""missions.yml: a stand-alone, permissive checker (warn and proceed) and its CLI.

missions.yml is vis.py's site and mission registry (vis.py buildMissionTable), also
read by ssh/MakeKMLSSHMissions.py and tools/GetActiveMissions.py. Its format is
vis.py's - keys are added there as needed - so this checker only reports: it
never changes what a loader does. Every problem is a warning at file:line; only
a file that can't be read as a yaml mapping is an error.

The key lists below are taken from vis.py; when vis.py starts reading a new key,
add one line to the matching table here.

A top-level key vis.py doesn't read is accepted quietly if it only holds yaml
anchors used elsewhere in the file - e.g.
    colors:
      sams_color: &sams_color "#9332a8"
    assets:
      M3: { ..., color: *sams_color }
- any other is a warning.

Usage:
    MissionsModel.py check FILE [--no-follow] [--path_map FROM=TO ...]
        check FILE and (unless --no-follow) every domains:/includes: file it names;
        --path_map maps a server path prefix to a local one (e.g. on a mirror:
        --path_map /home/jails=/Volumes/WorkFast/seaglider)
    MissionsModel.py dump FILE      the file as loaded (anchors resolved)
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

import plotly.graph_objects
import yaml

import BaseOpts
import BaseOptsType
import YamlValidation
from BaseLog import BaseLogger, log_error, log_info, log_warning

CONFIG_NAME = "missions.yml"

# Top-level keys vis.py buildMissionTable reads: name -> description
TOP_KEYS = {
    "organization": "orgname, orglink, contact, email, text (also mission defaults)",
    "missions": "the list of missions",
    "endpoints": "per-endpoint access (modes, users, groups, level)",
    "controls": "per-control allow/deny lists",
    "defaults": "mission key defaults",
    "missiondefaults": "mission key defaults per mission name",
    "pilotdefaults": "mission key defaults in pilot mode",
    "privatedefaults": "mission key defaults in private mode",
    "publicdefaults": "mission key defaults in public mode",
    "assets": "map assets (fixed points, groups, tilesets, ...)",
    "proxies": "proxied URLs",
    "routes": "extra routes",
    "sa": "top-level situational-awareness entries for the bare map",
    "domain": "this file's domain name",
    "authdomain": "the domain used for authentication",
    "admins": "admin users",
    "admingroups": "admin groups",
    "users": "users",
    "groups": "groups",
    "pilotusers": "pilot users",
    "pilotgroups": "pilot groups",
    "autocomplete": "autocomplete setting",
    "domains": "per-domain missions.yml files (name -> {missions, root, users})",
    "includes": "other missions.yml files to aggregate (name -> {missions, root})",
}

# Keys a mission may set (vis.py missionDictKeys, plus the ones it reads directly)
MISSION_KEYS = {
    "glider": "glider number (required)",
    "path": "mission directory, relative to the file (default: sgNNN)",
    "status": "active (the default), complete, aborted, archived, paused",
    "mission": "mission name",
    "users": "users who may see it",
    "pilotusers": "users who may pilot it",
    "groups": "groups who may see it",
    "pilotgroups": "groups who may pilot it",
    "started": "start date",
    "ended": "end date",
    "planned": "planned end date",
    "orgname": "organization name",
    "orglink": "organization link",
    "contact": "contact name",
    "email": "contact email",
    "color": "track color",
    "project": "project name",
    "link": "project link",
    "comment": "comment",
    "reason": "why it ended",
    "endpoints": "per-endpoint access for this mission",
    "sa": "situational-awareness entries",
    "also": "other gliders, missions or assets shown with it",
    "kml": "kml options",
    "sadata": "situational-awareness data",
    "alert": "alert text",
}

# Keys of a domains:/includes: entry
DOMAIN_KEYS = {
    "missions": "that domain's missions.yml",
    "root": "its missions' root directory",
    "users": "its users file",
}

# Keys of an endpoints: entry (vis.py endpointsDictKeys)
ENDPOINT_KEYS = {"modes": "run modes", "users": "users", "groups": "groups", "level": "access level"}

STATUSES = ("active", "complete", "aborted", "archived", "paused")


def apply_path_map(path: str, path_map: dict[str, str] | None) -> pathlib.Path:
    """A path from a missions.yml, with a server prefix mapped to a local one.

    Args:
        path: The path as written.
        path_map: Server prefix -> local prefix (the longest matching prefix wins).

    Returns:
        The (possibly) mapped path.

    Raises:
        Nothing.
    """
    for prefix in sorted(path_map or {}, key=len, reverse=True):
        bare = prefix.rstrip("/")  # "/home/jails" and "/home/jails/" mean the same prefix
        if path == bare or path.startswith(bare + "/"):
            return pathlib.Path(path_map[prefix].rstrip("/") + path[len(bare) :])  # ty: ignore[non-subscriptable]
    return pathlib.Path(path)


def _nodes(node: yaml.Node, seen: set[int] | None = None) -> set[int]:
    """The ids of a composed node and everything under it (an alias is the same node object as its anchor)."""
    if seen is None:
        seen = set()
    if id(node) in seen:
        return seen
    seen.add(id(node))
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            _nodes(key, seen)
            _nodes(value, seen)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _nodes(item, seen)
    return seen


def _anchor_holders(text: str) -> set[str]:
    """Top-level keys whose contents are aliased from elsewhere in the file (anchor holders like colors:).

    Args:
        text: The file's text.

    Returns:
        Those top-level key names.

    Raises:
        Nothing (a file that doesn't compose has none).
    """
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return set()
    if not isinstance(root, yaml.MappingNode):
        return set()
    holders = set()
    for key, value in root.value:
        mine = _nodes(value) - {id(value)}
        elsewhere: set[int] = set()
        for other_key, other_value in root.value:
            if other_key is not key:
                _nodes(other_value, elsewhere)
        if mine & elsewhere:
            holders.add(key.value)
    return holders


def _is_color(value: Any) -> bool:
    """Whether value is a color a browser knows (a CSS name, #rrggbb, rgb(...), ...)."""
    try:
        plotly.graph_objects.scatter.Marker(color=value)
    except ValueError:
        return False
    return True


def _unknown_key_hint(key: Any, value: Any, known: dict[str, str]) -> str:
    """A hint for an unknown key that looks like a typo of the yaml kind."""
    if isinstance(key, str) and ":" in key and key.split(":", 1)[0] in known:
        name, rest = key.split(":", 1)
        return f" - needs a space after the colon ('{name}: {rest}')"
    if isinstance(key, str) and " " in key and value is None:
        return " - a comma inside a { } value splits it; quote the text (e.g. reason: \"a, b\")"
    return ""


class _Checker:
    """Collects warnings while walking one file."""

    def __init__(self, loaded: YamlValidation.LoadedYaml) -> None:
        self.loaded = loaded
        self.warnings: list[str] = []

    def warn(self, loc: tuple, message: str) -> None:
        dotted = ".".join(str(k) for k in loc)
        self.warnings.append(f"{self.loaded.where(tuple(str(k) if not isinstance(k, int) else k for k in loc))}: {dotted}: {message}")

    def unknown_keys(self, loc: tuple, entry: dict, known: dict[str, str], what: str) -> None:
        for key, value in entry.items():
            if key not in known:
                self.warn((*loc, key), f"not a {what} key - ignored{_unknown_key_hint(key, value, known)}")

    def missions(self, missions: Any) -> None:
        if not isinstance(missions, list):
            self.warn(("missions",), f"should be a list of missions, not {type(missions).__name__}")
            return
        actives: dict[int, int] = {}
        ids: dict[tuple, int] = {}
        for i, mission in enumerate(missions):
            loc = ("missions", i)
            if not isinstance(mission, dict):
                self.warn(loc, f"should be a mapping, not {type(mission).__name__} - skipped by vis")
                continue
            self.unknown_keys(loc, mission, MISSION_KEYS, "mission")
            if "glider" not in mission:
                self.warn(loc, "no glider - skipped by vis")
                continue
            try:
                glider = int(mission["glider"])
            except (TypeError, ValueError):
                self.warn((*loc, "glider"), f"{mission['glider']!r} isn't a glider number - skipped by vis")
                continue
            for key in ("path", "mission"):
                if key in mission and mission[key] is not None and not isinstance(mission[key], str):
                    self.warn((*loc, key), f"should be text, not {type(mission[key]).__name__}")
            status = mission.get("status", "active")
            if status not in STATUSES:
                self.warn((*loc, "status"), f"{status!r} isn't one of {', '.join(STATUSES)}")
            if status == "active":
                if glider in actives:
                    self.warn(loc, f"sg{glider:03d} already has an active mission (entry {actives[glider]}) - vis uses that one")
                else:
                    actives[glider] = i
            ident = (glider, mission.get("mission"))
            if ident in ids:
                self.warn(loc, f"sg{glider:03d} {ident[1]} is listed twice (entry {ids[ident]}) - vis skips this one")
            else:
                ids[ident] = i

    def mapping_of_entries(self, top: str, value: Any, known: dict[str, str] | None, what: str) -> dict:
        if not isinstance(value, dict):
            self.warn((top,), f"should be a mapping, not {type(value).__name__}")
            return {}
        if known is not None:
            for name, entry in value.items():
                if top in ("domains", "includes") and name == "root":
                    continue  # vis reads root on its own (the root domain's name)
                if isinstance(entry, dict):
                    self.unknown_keys((top, name), entry, known, what)
                elif entry is not None:
                    self.warn((top, name), f"should be a mapping, not {type(entry).__name__}")
        return value

    def assets(self, assets: Any) -> None:
        for name, asset in self.mapping_of_entries("assets", assets, None, "asset").items():
            if isinstance(asset, dict) and "color" in asset and not _is_color(asset["color"]):
                self.warn(("assets", name, "color"), f"{asset['color']!r} isn't a color (a name, or #rrggbb)")


def check_file(
    path: pathlib.Path,
    path_map: dict[str, str] | None = None,
    follow: bool = True,
    _visited: set[pathlib.Path] | None = None,
) -> tuple[dict | None, list[str], list[str]]:
    """Checks a missions.yml (and, if follow, the domains:/includes: files it names).

    Args:
        path: The file.
        path_map: Server path prefix -> local prefix, for the paths the file names.
        follow: Also check each domains:/includes: file, recursively.
        _visited: Files already checked (cycle protection).

    Returns:
        (data, warnings, problems): data is the file as loaded (None if it can't be
        used - then problems says why; problems also lists included files that
        can't be used). Each message is "file:line: where: message".

    Raises:
        Nothing.
    """
    visited = _visited if _visited is not None else set()
    visited.add(path.resolve())
    try:
        data, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        return None, [], [YamlValidation.format_yaml_error(path, e)]
    except OSError as e:
        return None, [], [f"{path}: could not read ({e})"]
    if not isinstance(data, dict):
        return None, [], [f"{path}: {CONFIG_NAME} must be a mapping (got {type(data).__name__})"]
    checker = _Checker(YamlValidation.LoadedYaml(path, data, locate))
    holders = _anchor_holders(path.read_text())
    for key in data:
        if key not in TOP_KEYS and key not in holders:
            checker.warn((key,), f"not a {CONFIG_NAME} key - ignored{_unknown_key_hint(key, data[key], TOP_KEYS)}")
    if "missions" in data:
        checker.missions(data["missions"])
    if "endpoints" in data:
        checker.mapping_of_entries("endpoints", data["endpoints"], ENDPOINT_KEYS, "endpoint")
    if "assets" in data:
        checker.assets(data["assets"])
    problems: list[str] = []
    for top in ("domains", "includes"):
        if top not in data:
            continue
        for name, entry in checker.mapping_of_entries(top, data[top], DOMAIN_KEYS, "domain").items():
            if name == "root" or not isinstance(entry, dict):
                continue
            if "missions" not in entry:
                checker.warn((top, name), "no missions file - skipped")
                continue
            if not follow:
                continue
            included = apply_path_map(str(entry["missions"]), path_map)
            if not included.is_absolute():
                included = path.parent / included
            if included.resolve() in visited:
                checker.warn((top, name, "missions"), f"{included} already checked (cyclic {top}?) - skipped")
                continue
            if not included.is_file():
                checker.warn((top, name, "missions"), f"{included} not found - not checked")
                continue
            _, sub_warnings, sub_problems = check_file(included, path_map, follow, visited)
            checker.warnings += sub_warnings
            problems += sub_problems
    return data, checker.warnings, problems


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Checks or dumps a missions.yml.

    Args:
        cmdline_args: Command line arguments.

    Returns:
        0 if there are no warnings or problems, 1 otherwise.

    Raises:
        Nothing expected.
    """
    base_opts = BaseOpts.BaseOptions(
        "Check a missions.yml (vis.py's mission registry) - reports only, changes nothing",
        cmdline_args=cmdline_args,
        calling_module="MissionsModel",
        additional_arguments={
            "action": BaseOptsType.options_t(
                None,
                {"MissionsModel"},
                ("action",),
                str,
                {"help": "check FILE | dump FILE", "choices": ("check", "dump")},
            ),
            "missions_file": BaseOptsType.options_t(
                None, {"MissionsModel"}, ("missions_file",), pathlib.Path, {"help": f"The {CONFIG_NAME} file"}
            ),
            "follow": BaseOptsType.options_t(
                True,
                {"MissionsModel"},
                ("--follow",),
                bool,
                {
                    "help": "Also check the domains:/includes: files (--no-follow: just this one)",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "path_map": BaseOptsType.options_t(
                [],
                {"MissionsModel"},
                ("--path_map",),
                str,
                {"help": "FROM=TO: map a server path prefix to a local one", "nargs": "*"},
            ),
        },
    )
    BaseLogger(base_opts)
    path_map = {}
    for pair in base_opts.path_map or []:
        if "=" not in pair:
            log_error(f"--path_map {pair!r}: expected FROM=TO")
            return 1
        server, local = pair.split("=", 1)
        path_map[server] = local
    path = pathlib.Path(base_opts.missions_file).expanduser()
    data, warnings, problems = check_file(path, path_map, follow=base_opts.follow)
    for warning in warnings:
        log_warning(warning)
    for problem in problems:
        log_error(problem)
    if base_opts.action == "dump":
        if data is None:
            return 1
        # The loaded file is the output - for redirecting
        print(YamlValidation.dump_text(data), end="")
        return 0
    if not (warnings or problems):
        log_info(f"{path}: OK")
    return 1 if (warnings or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
