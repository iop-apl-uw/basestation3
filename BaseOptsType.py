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

"""Definition of the options_t class

Defined here to prevent issues with circular refrences when loading
"""

import argparse
import dataclasses
import typing


@dataclasses.dataclass
class options_t:
    """Data that drives options processing"""

    default_val: typing.Any
    group: set[str] | None
    args: tuple
    var_type: typing.Any
    kwargs: dict

    def __post_init__(self):
        """Type conversions"""
        if not isinstance(self.args, tuple):
            raise ValueError("args is not a tuple")
        if self.group is not None and not isinstance(self.group, set):
            self.group = set(self.group)
        if not isinstance(self.kwargs, dict):
            raise ValueError("kwargs is not a dict")


# Keys in options_t.kwargs that aren't part of an option's definition when comparing
# two of them: BaseOptions updates "required" at run time (add_to_required), and a
# module may restate a core option with its own help (e.g. --force in MakeKMLSSHMissions)
_not_compared_kwargs = ("required", "help")


def same_option(a: options_t, b: options_t) -> bool:
    """Whether two options_t define the same option.

    The group, kwargs "required" and the help are left out: BaseOptions adds the
    calling module to the first two as it runs, and the help doesn't change what the
    option does.

    Args:
        a: first option
        b: second option

    Returns:
        True if both have the same default, arguments, type and other kwargs.

    Raises:
        Nothing.
    """
    if a is b:
        return True

    def kw(o: options_t) -> dict:
        return {k: v for k, v in o.kwargs.items() if k not in _not_compared_kwargs}

    return (
        a.default_val == b.default_val
        and a.args == b.args
        and a.var_type == b.var_type
        and kw(a) == kw(b)
    )


def check_options_dict(options: object, source: str) -> dict[str, options_t]:
    """Checks a dict of additional options is option names mapped to options_t.

    Args:
        options: the additional options, as passed by the caller
        source: where the options came from, for the error message

    Returns:
        options, unchanged

    Raises:
        TypeError: options isn't a dict, or a name isn't a str, or a value isn't an options_t
    """
    if not isinstance(options, dict):
        raise TypeError(
            f"{source}: additional options must be a dict of name to options_t, not {type(options).__name__}"
        )
    for name, opt in options.items():
        if not isinstance(name, str):
            raise TypeError(f"{source}: option name {name!r} is not a str")
        if not isinstance(opt, options_t):
            raise TypeError(
                f"{source}: option {name} is a {type(opt).__name__}, not an options_t"
            )
    return options


def option_conflicts(
    options: dict[str, options_t], name: str, opt: options_t
) -> str | None:
    """Describes how a new option conflicts with the options already defined.

    A conflict is the same name defined differently, or a command line argument
    (e.g. "--foo") already used by an option with another name.

    Args:
        options: the options already defined
        name: the new option's name
        opt: the new option

    Returns:
        None if the option can be added, otherwise what it conflicts with.

    Raises:
        Nothing.
    """
    if name in options:
        if same_option(options[name], opt):
            return None
        return f"option {name} is already defined differently ({options[name].args} vs {opt.args})"
    flags = {a for a in opt.args if isinstance(a, str) and a.startswith("-")}
    for other_name, other in options.items():
        used = flags.intersection(other.args)
        if used:
            return f"option {name} uses {', '.join(sorted(used))}, already used by option {other_name}"
    return None


def merge_options(
    options: dict[str, options_t], new_options: dict[str, options_t], source: str
) -> None:
    """Adds new options to a dict of options, refusing any that conflict.

    An option already present with the same definition is fine (the new copy replaces it).

    Args:
        options: the options already defined - updated in place
        new_options: the options to add
        source: where the new options came from, for the error message

    Returns:
        Nothing.

    Raises:
        TypeError: new_options isn't a dict of name to options_t
        ValueError: a new option conflicts with one already defined
    """
    check_options_dict(new_options, source)
    for name, opt in new_options.items():
        conflict = option_conflicts(options, name, opt)
        if conflict:
            raise ValueError(f"{source}: {conflict}")
    options |= new_options


# Deprecated options to warn and issue alerts on
deprecated_options = {}


class DeprecateAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        deprecated_options[self.option_strings[0]] = self.help
        delattr(namespace, self.dest)
