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

"""Plotting's registration decorators."""

import ast
import inspect
import logging
import pathlib
import sys
import types

import pytest

import Plotting


@pytest.mark.parametrize("registry", ["dive_plot_funcs", "mission_plot_funcs"])
def test_registered_plots_keep_their_module_names(registry: str) -> None:
    """A decorated plot is reachable under its own name, not just through the registry.

    add_arguments didn't return the function, so e.g. Plotting.DiveCTD.plot_CTD was None
    (BasePlot only uses the registries, so production was unaffected).
    """
    funcs = getattr(Plotting, registry)
    assert funcs
    for name, func in funcs.items():
        assert getattr(sys.modules[func.__module__], name) is func, f"{func.__module__}.{name}"


def _mission_plot(base_opts: object, mission_str: str, dive: int | None = None, generate_plots: bool = True, dbcon: object = None) -> tuple:
    return ([], [])


def test_compare_sigs_ignores_annotations() -> None:
    """A plot whose annotations differ from the reference's still registers (mission_str was list, is str)."""
    assert Plotting.compare_sigs(Plotting.plot_mission_sig, inspect.signature(_mission_plot))


def test_compare_sigs_positional_names_free_keyword_names_fixed() -> None:
    """The first parameters are passed by position (any name); the defaulted ones by keyword (BasePlot)."""

    def renamed_positional(opts, title, dive=None, generate_plots=True, dbcon=None):  # noqa: ANN001, ANN202
        return ([], [])

    def renamed_keyword(base_opts, mission_str, dive_num=None, generate_plots=True, dbcon=None):  # noqa: ANN001, ANN202
        return ([], [])

    def other_default(base_opts, mission_str, dive=None, generate_plots=False, dbcon=None):  # noqa: ANN001, ANN202
        return ([], [])

    def missing_param(base_opts, mission_str, dive=None, generate_plots=True):  # noqa: ANN001, ANN202
        return ([], [])

    ref = Plotting.plot_mission_sig
    assert Plotting.compare_sigs(ref, inspect.signature(renamed_positional))
    assert not Plotting.compare_sigs(ref, inspect.signature(renamed_keyword))
    assert not Plotting.compare_sigs(ref, inspect.signature(other_default))
    assert not Plotting.compare_sigs(ref, inspect.signature(missing_param))


def test_mismatched_plot_is_logged_and_not_registered(caplog: pytest.LogCaptureFixture) -> None:
    """A plot that doesn't match is an error in the log (it was a print), and isn't registered."""

    def bad_mission_plot(base_opts, mission_str):  # noqa: ANN001, ANN202
        return ([], [])

    with caplog.at_level(logging.ERROR):
        assert Plotting.plotmissionsingle(bad_mission_plot) is bad_mission_plot
    assert "bad_mission_plot" not in Plotting.mission_plot_funcs
    assert "bad_mission_plot does not match the plotting signature - not registered" in caplog.text


@pytest.mark.parametrize("registry", ["dive_plot_funcs", "mission_plot_funcs"])
def test_every_plot_registers(registry: str) -> None:
    """Every decorated plot in the package's modules is in its registry."""
    funcs = getattr(Plotting, registry)
    decorator = "plotdivesingle" if registry == "dive_plot_funcs" else "plotmissionsingle"
    for module in Plotting.__dict__.values():
        if not isinstance(module, types.ModuleType) or not module.__name__.startswith("Plotting."):
            continue
        tree = ast.parse(pathlib.Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and any(
                isinstance(d, ast.Name) and d.id == decorator for d in node.decorator_list
            ):
                assert funcs.get(node.name) is getattr(module, node.name), f"{module.__name__}.{node.name}"
