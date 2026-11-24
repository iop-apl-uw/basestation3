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

"""users.yml: a stand-alone checker (it only reports) and its CLI.

users.yml is vis.py's user table (vis.py buildUserTable): user name -> groups and,
optionally, a sha256_crypt password hash (a user without one logs in through
auth.db). A `default:` entry supplies keys a user leaves out. A missions.yml names
a domain's users file under domains: NAME: users:, and MissionsModel.py check
follows it here.

Like MissionsModel.py, this never changes what vis.py loads: every problem is a
warning at file:line, and only a file vis.py can't use at all is an error. When
vis.py starts reading a new user key, add one line to USER_KEYS.

The file holds password hashes. No message includes one, and dump shows
"password: <set>".

Usage:
    UsersModel.py check FILE
    UsersModel.py dump FILE      the file as loaded, passwords hidden
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from passlib.hash import sha256_crypt  # ty: ignore[import-not-found] - lazy members

import BaseOpts
import BaseOptsType
import YamlValidation
from BaseLog import BaseLogger, log_error, log_info, log_warning

CONFIG_NAME = "users.yml"

DEFAULT_ENTRY = "default"

# Keys a user entry may set (vis.py buildUserTable userDictKeys, plus authHandler's): name -> description
USER_KEYS = {
    "groups": "list of groups the user is in",
    "password": "sha256_crypt hash (leave out to log in through auth.db)",
}

PASSWORD_SHOWN_AS = "<set>"


class _Checker:
    """Collects warnings while walking one file.

    Args:
        loaded: The file being checked.
    """

    def __init__(self, loaded: YamlValidation.LoadedYaml) -> None:
        self.loaded = loaded
        self.warnings: list[str] = []

    def warn(self, loc: tuple, message: str) -> None:
        """Records a warning at loc's line.

        Args:
            loc: Key path of the problem.
            message: What's wrong.
        """
        dotted = ".".join(str(k) for k in loc)
        # The line map keys a mapping key by its text (a user name like 1234 too); list indexes stay ints
        where = self.loaded.where((str(loc[0]), *loc[1:]))
        self.warnings.append(f"{where}: {dotted}: {message}")

    def entry(self, name: object, entry: object) -> None:
        """Checks one user (or the default) entry.

        A user without groups is fine - e.g. a shared account that missions give access to by name.

        Args:
            name: The user name (or "default").
            entry: Its value.
        """
        loc = (name,)
        if not isinstance(entry, dict):
            self.warn(
                loc,
                f"should be a mapping (groups:, password:), not {type(entry).__name__} - vis fails to start",
            )
            return
        for key in entry:
            if key not in USER_KEYS:
                self.warn(
                    (name, key),
                    f"not a user key - ignored (known: {', '.join(USER_KEYS)})",
                )
        if "groups" in entry:
            groups = entry["groups"]
            if isinstance(groups, str):
                self.warn(
                    (name, "groups"),
                    f"should be a list (e.g. groups: [{groups}]) - as text, each character counts as a group",
                )
            elif groups is not None and not isinstance(groups, list):
                self.warn(
                    (name, "groups"),
                    f"should be a list of groups, not {type(groups).__name__}",
                )
            elif isinstance(groups, list):
                for i, group in enumerate(groups):
                    if not isinstance(group, str):
                        self.warn(
                            (name, "groups", i),
                            f"should be a group name, not {type(group).__name__}",
                        )
        if "password" in entry:
            password = entry["password"]
            if not isinstance(password, str) or not sha256_crypt.identify(password):
                # Never echo the value - it may be a real password typed in by mistake
                self.warn(
                    (name, "password"),
                    "isn't a sha256_crypt hash ($5$...) - login fails",
                )


def check_file(path: Path) -> tuple[dict | None, list[str], list[str]]:
    """Checks a users.yml.

    Args:
        path: The file.

    Returns:
        (data, warnings, problems): data is the file as loaded (None if vis can't use
        it - then problems says why). Each message is "file:line: where: message".
    """
    try:
        data, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        return None, [], [YamlValidation.format_yaml_error(path, e)]
    except OSError as e:
        return None, [], [f"{path}: could not read ({e})"]
    if not isinstance(data, dict):
        got = "an empty file" if data is None else type(data).__name__
        return (
            None,
            [],
            [
                f"{path}: {CONFIG_NAME} must be a mapping of user names (got {got}) - vis fails to start"
            ],
        )
    checker = _Checker(YamlValidation.LoadedYaml(path, data, locate))
    seen: dict[str, str] = {}
    for name, entry in data.items():
        if not isinstance(name, str):
            checker.warn(
                (name,),
                f"user name should be text, not {type(name).__name__} - every login fails (quote it)",
            )
            continue
        checker.entry(name, entry)
        if name == DEFAULT_ENTRY:
            continue
        if name.lower() in seen:
            checker.warn(
                (name,),
                f"same name as {seen[name.lower()]!r} but for case - vis logs both in as the first",
            )
        else:
            seen[name.lower()] = name
    return data, checker.warnings, []


def hide_passwords(data: dict) -> dict:
    """A copy of a loaded users.yml with every password replaced by PASSWORD_SHOWN_AS.

    Args:
        data: The file as loaded.

    Returns:
        The copy.
    """
    return {
        name: {
            k: (PASSWORD_SHOWN_AS if k == "password" else v) for k, v in entry.items()
        }
        if isinstance(entry, dict)
        else entry
        for name, entry in data.items()
    }


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Checks or dumps a users.yml.

    Args:
        cmdline_args: Command line arguments.

    Returns:
        0 if there are no warnings or problems, 1 otherwise.
    """
    base_opts = BaseOpts.BaseOptions(
        "Check a users.yml (vis.py's user table) - reports only, changes nothing",
        cmdline_args=cmdline_args,
        calling_module="UsersModel",
        additional_arguments={
            "action": BaseOptsType.options_t(
                None,
                {"UsersModel"},
                ("action",),
                str,
                {"help": "check FILE | dump FILE", "choices": ("check", "dump")},
            ),
            "users_file": BaseOptsType.options_t(
                None,
                {"UsersModel"},
                ("users_file",),
                Path,
                {"help": f"The {CONFIG_NAME} file"},
            ),
        },
    )
    BaseLogger(base_opts)
    path = Path(base_opts.users_file).expanduser()
    data, warnings, problems = check_file(path)
    for warning in warnings:
        log_warning(warning)
    for problem in problems:
        log_error(problem)
    if base_opts.action == "dump":
        if data is None:
            return 1
        # The loaded file is the output - for redirecting
        print(YamlValidation.dump_text(hide_passwords(data)), end="")
        return 0
    if not (warnings or problems):
        log_info(f"{path}: OK")
    return 1 if (warnings or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
