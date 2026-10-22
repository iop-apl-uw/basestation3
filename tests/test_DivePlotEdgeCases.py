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

"""Dive plots on incomplete netCDF data."""

import logging
import types
import typing

import pytest

import BaseOpts
from Plotting import DiveOptode, DivePMAR, DiveSBE43

BASE_OPTS = typing.cast("BaseOpts.BaseOptions", types.SimpleNamespace())


def _ncf(variables: dict) -> typing.Any:  # noqa: ANN401 - a scipy netcdf_file stand-in
    return types.SimpleNamespace(variables=variables, dimensions={}, start_time=0.0)


@pytest.mark.parametrize(
    ("plot", "variable"),
    [(DiveSBE43.plot_sbe43, "sbe43_dissolved_oxygen"), (DiveOptode.plot_optode, "eng_aa4831_O2")],
)
def test_oxygen_load_failure_skips_the_plot(
    plot: typing.Callable, variable: str, caplog: pytest.LogCaptureFixture
) -> None:
    """No "time" variable: a warning and no plot, not an unbound-variable error further on."""
    with caplog.at_level(logging.WARNING):
        assert plot(BASE_OPTS, _ncf({variable: None})) == ([], [])
    assert "Could not load oxygen data - skipping plot" in caplog.text


def test_pmar_unknown_plot_type_names_it(caplog: pytest.LogCaptureFixture) -> None:
    """The warning names the plot_type (the %s was never filled in)."""
    with caplog.at_level(logging.WARNING):
        assert DivePMAR.pmar_create_stats_lines(_ncf({}), "", "bogus") == ("", "", "")
    assert "Unknown plot_type bogus - no stats line being created" in caplog.text
