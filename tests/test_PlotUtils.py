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

"""Tests for PlotUtils.add_sample_range_overlay() with bad depth data.

Production case: sg274's lab-test mission (2026-09) - bench data with no
usable depth made the overlay fail with IndexError (negative max depth ->
empty bin grid) or try to allocate 1.33 TiB (a ~1e12 m depth), taking the
whole Legato plot down with it.
"""

import logging
import types

import numpy as np
import plotly.graph_objects as go
import pytest

import PlotUtils

N = 20
MAX_DEPTH_I = 10


def _overlay(
    depth_dive: np.ndarray, depth_climb: np.ndarray, caplog, tmp_path
) -> go.Figure:
    depth = np.concatenate((depth_dive, depth_climb))
    time_var = np.arange(float(N))

    def f_depth(t: np.ndarray) -> np.ndarray:
        return depth[t.astype(int)]

    # The science-grid part after the overlay only needs a mission_dir
    base_opts = types.SimpleNamespace(mission_dir=tmp_path, science_grid=None)
    fig = go.Figure()
    with caplog.at_level(logging.WARNING):
        PlotUtils.add_sample_range_overlay(
            base_opts, "legato", 5, time_var, MAX_DEPTH_I, 0.0, fig, f_depth
        )
    return fig


def _names(fig: go.Figure) -> list[str]:
    """The samples/meter overlay traces added."""
    return [t.name for t in fig.data if t.name and t.name.endswith("samples stats")]


def _depth_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if "implausible max depth" in r.getMessage()
    ]


def test_normal_profile_adds_both_traces(caplog, tmp_path) -> None:
    fig = _overlay(
        np.linspace(0, 100, MAX_DEPTH_I),
        np.linspace(100, 0, N - MAX_DEPTH_I),
        caplog,
        tmp_path,
    )
    assert _names(fig) == ["Dive samples stats", "Climb samples stats"]
    assert not _depth_warnings(caplog)


@pytest.mark.parametrize(
    "bad",
    [
        np.full(
            MAX_DEPTH_I, -3.0
        ),  # bench: below the surface reference -> empty bin grid
        np.full(MAX_DEPTH_I, np.nan),  # no usable depth at all
        np.full(MAX_DEPTH_I, 9.2e11),  # garbage depth -> TiB-sized bin grid
    ],
    ids=["negative", "all-nan", "absurd"],
)
def test_implausible_depth_skips_only_that_half(bad, caplog, tmp_path) -> None:
    fig = _overlay(bad, np.linspace(100, 0, N - MAX_DEPTH_I), caplog, tmp_path)
    assert _names(fig) == ["Climb samples stats"]
    warnings = [r for r in caplog.records if "implausible max depth" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"
    assert "legato dive 5: implausible max depth" in warnings[0].getMessage()
    assert (
        "dive samples - skipping the samples/meter overlay" in warnings[0].getMessage()
    )


def test_implausible_depth_both_halves_adds_nothing(caplog, tmp_path) -> None:
    fig = _overlay(
        np.full(MAX_DEPTH_I, -3.0), np.full(N - MAX_DEPTH_I, np.nan), caplog, tmp_path
    )
    assert _names(fig) == []
    assert len(_depth_warnings(caplog)) == 2


def test_zero_max_depth_is_plotted(caplog, tmp_path) -> None:
    """A surface-only half (max depth exactly 0) is valid, not bad data."""
    fig = _overlay(
        np.zeros(MAX_DEPTH_I), np.linspace(10, 0, N - MAX_DEPTH_I), caplog, tmp_path
    )
    assert _names(fig) == ["Dive samples stats", "Climb samples stats"]
    assert not _depth_warnings(caplog)
